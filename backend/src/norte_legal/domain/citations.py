"""Validación de la salida del LLM antes de mostrarla (invariantes 4 y 6).

Una cita solo sobrevive si su `ref` está entre los fragmentos recuperados y su texto aparece de
verdad en ese fragmento. La comparación tolera diferencias de mayúsculas, espacios, comillas y
acentos compuestos, y devuelve la posición exacta de la cita en el texto original del fragmento.
"""

import unicodedata
from dataclasses import dataclass

from norte_legal.domain.ports import DraftAnswer

MIN_QUOTE_CHARS = 8
# Comillas tipográficas, angulares y apóstrofos se comparan como comillas rectas.
_QUOTES = str.maketrans(
    dict.fromkeys("\u201c\u201d\u00ab\u00bb", '"') | dict.fromkeys("\u2018\u2019\u00b4", "'")
)
# Lo que el modelo suele añadir alrededor de una cita: comillas, puntos suspensivos y guiones.
_TRIM = " \t\n\"'.,;:\u2026-\u2013\u2014"


@dataclass(frozen=True)
class VerifiedCitation:
    ref: str
    quote: str
    # Posición de la cita dentro del texto del fragmento.
    start: int
    end: int


@dataclass(frozen=True)
class ValidatedAnswer:
    answer: str
    citations: list[VerifiedCitation]
    dropped: int


def validate_answer(draft: DraftAnswer, sources: dict[str, str]) -> ValidatedAnswer:
    """`sources` asocia cada `ref` recuperada con el texto de su fragmento."""
    verified: list[VerifiedCitation] = []
    seen: set[tuple[str, int, int]] = set()
    for citation in draft.citations:
        text = sources.get(citation.ref)
        if text is None:
            continue
        span = locate_quote(citation.quote, text)
        if span is None or (citation.ref, *span) in seen:
            continue
        seen.add((citation.ref, *span))
        start, end = span
        verified.append(VerifiedCitation(citation.ref, text[start:end], start, end))
    return ValidatedAnswer(draft.answer.strip(), verified, len(draft.citations) - len(verified))


def locate_quote(quote: str, text: str) -> tuple[int, int] | None:
    """`text` es un fragmento, ya en NFC por la extracción: las posiciones valen sobre él."""
    needle, _ = _normalize(unicodedata.normalize("NFC", quote).strip(_TRIM))
    if len(needle) < MIN_QUOTE_CHARS:
        return None
    haystack, positions = _normalize(text)
    index = haystack.find(needle)
    if index < 0:
        return None
    return positions[index], positions[index + len(needle) - 1] + 1


def _normalize(text: str) -> tuple[str, list[int]]:
    """Texto comparable y, para cada carácter, su offset en el original."""
    chars: list[str] = []
    positions: list[int] = []
    previous_space = True
    for offset, char in enumerate(text):
        for piece in unicodedata.normalize("NFKC", char.translate(_QUOTES)).casefold():
            if piece.isspace():
                if previous_space:
                    continue
                piece, previous_space = " ", True
            else:
                previous_space = False
            chars.append(piece)
            positions.append(offset)
    return "".join(chars), positions
