"""Lógica pura de la recuperación híbrida: consulta léxica y fusión por rangos (RRF)."""

import re
import unicodedata
from dataclasses import dataclass

RRF_K = 60
VECTOR_CANDIDATES = 30
LEXICAL_CANDIDATES = 30
MAX_SOURCES = 8
MIN_TERM_CHARS = 3
MAX_TERMS = 32

# Con la configuración 'simple' de PostgreSQL no hay lista de palabras vacías. Estas, que pasan el
# filtro de longitud, coincidirían con casi cualquier fragmento.
_STOPWORDS = frozenset(
    # Una cadena partida se lee mejor que ochenta líneas de lista.
    """
    que qué los las del por para con una uno unos unas como cómo cuál cuáles cuando cuándo donde
    dónde este esta estos estas ese esa esos esas hay ser son está están puede pueden debe deben
    sobre entre sin más muy sus nos the and for are was were with that this these those what which
    who when where how can does did has have had from into any all not but its
    """.split()  # noqa: SIM905
)
_WORD = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class RankedCandidate:
    chunk_id: str
    vector_rank: int | None
    lexical_rank: int | None
    similarity: float | None

    @property
    def score(self) -> float:
        return sum(1 / (RRF_K + rank) for rank in (self.vector_rank, self.lexical_rank) if rank)


def lexical_query(question: str) -> str | None:
    """`tsquery` en OR con los términos útiles de la pregunta. Solo contiene caracteres `\\w`,
    así que no puede romper la sintaxis de `to_tsquery`."""
    terms: list[str] = []
    for word in _WORD.findall(unicodedata.normalize("NFC", question).casefold()):
        if len(word) >= MIN_TERM_CHARS and word not in _STOPWORDS and word not in terms:
            terms.append(word)
    return " | ".join(terms[:MAX_TERMS]) or None


def fuse(
    vector: list[tuple[str, float]], lexical: list[str], min_similarity: float
) -> list[RankedCandidate]:
    """Reciprocal Rank Fusion. `vector` llega ordenado por similitud y `lexical` por relevancia.

    Un candidato que solo aparece por similitud y no llega a `min_similarity` se descarta: es la
    primera compuerta contra respuestas sin respaldo. Una coincidencia léxica siempre cuenta.
    """
    candidates: dict[str, RankedCandidate] = {}
    for rank, (chunk_id, similarity) in enumerate(vector, start=1):
        candidates[chunk_id] = RankedCandidate(chunk_id, rank, None, similarity)
    for rank, chunk_id in enumerate(lexical, start=1):
        previous = candidates.get(chunk_id)
        candidates[chunk_id] = RankedCandidate(
            chunk_id,
            previous.vector_rank if previous else None,
            rank,
            previous.similarity if previous else None,
        )
    kept = [
        candidate
        for candidate in candidates.values()
        if candidate.lexical_rank is not None or (candidate.similarity or 0.0) >= min_similarity
    ]
    return sorted(kept, key=lambda candidate: candidate.score, reverse=True)[:MAX_SOURCES]
