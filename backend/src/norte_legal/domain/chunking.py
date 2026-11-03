"""Fragmentador recursivo consciente de la estructura legal.

Corta por el límite más fuerte disponible: encabezado de cláusula, párrafo, línea, frase,
espacio y, en último caso, a ciegas. Después fusiona piezas contiguas hasta el tamaño objetivo y
añade solapamiento con el fragmento anterior.

Todo se calcula como offsets sobre el texto extraído y el texto del fragmento es siempre
`text[char_start:char_end]`. Ese invariante lo comprueba una prueba de propiedades.
"""

import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from itertools import pairwise

CHUNKER_VERSION = "chunk-v1"
TARGET_CHARS = 1_800
OVERLAP_CHARS = 200
MAX_SECTION_CHARS = 200

# Línea corta que parece un encabezado: "Section 4.2", "ARTICLE V", "Cláusula Tercera", "12.1 Pago".
_HEADING = re.compile(
    r"^[ ]*(?:"
    r"(?:section|secci[oó]n|article|art[ií]culo|clause|cl[aá]usula|chapter|cap[ií]tulo"
    r"|exhibit|schedule|anexo|appendix|ap[eé]ndice)\b"
    r"|(?:\d+(?:\.\d+)*\.?|[IVXLC]+\.)[ ]"
    r")[^\n]{0,120}$",
    re.IGNORECASE | re.MULTILINE,
)
# De más fuerte a más débil. Cada posición es un punto de corte: el inicio de la pieza siguiente.
_BOUNDARIES = (
    _HEADING,
    re.compile(r"\n[ ]*\n\s*"),
    re.compile(r"\n"),
    re.compile(r"(?<=[.!?;:])\s+"),
    re.compile(r"\s+"),
)


@dataclass(frozen=True)
class TextChunk:
    ordinal: int
    text: str
    char_start: int
    char_end: int
    page_start: int | None
    page_end: int | None
    section: str | None


def pipeline_fingerprint(extractor_version: str, embedding_model: str) -> str:
    """Si cambia cualquier pieza, el mismo archivo produce una versión nueva."""
    return f"{extractor_version}|{CHUNKER_VERSION}:{TARGET_CHARS}/{OVERLAP_CHARS}|{embedding_model}"


def chunk_text(
    text: str,
    page_starts: list[int] | None = None,
    target: int = TARGET_CHARS,
    overlap: int = OVERLAP_CHARS,
) -> list[TextChunk]:
    if overlap >= target:
        raise ValueError("overlap must be smaller than target")
    headings = [match.group().strip()[:MAX_SECTION_CHARS] for match in _HEADING.finditer(text)]
    heading_starts = [match.start() for match in _HEADING.finditer(text)]
    # Un fragmento que abre una cláusula no arrastra el final de la anterior.
    opens_heading = {_strip(text, start, len(text))[0] for start in heading_starts}
    boundaries = [heading_starts] + [
        [match.end() for match in pattern.finditer(text)] for pattern in _BOUNDARIES[1:]
    ]

    spans = [_strip(text, s, e) for s, e in _split(boundaries, 0, len(text), 0, target)]
    cores = [(s, e) for s, e in spans if e > s]

    chunks: list[TextChunk] = []
    previous_core_start = 0
    for ordinal, (core_start, end) in enumerate(cores):
        start = core_start
        if ordinal > 0 and core_start not in opens_heading:
            start = _overlap_start(text, max(previous_core_start, core_start - overlap), core_start)
        previous_core_start = core_start
        chunks.append(
            TextChunk(
                ordinal=ordinal,
                text=text[start:end],
                char_start=start,
                char_end=end,
                page_start=_page(page_starts, start),
                page_end=_page(page_starts, end - 1),
                section=_section(heading_starts, headings, core_start),
            )
        )
    return chunks


def section_at(text: str, offset: int) -> str | None:
    """Último encabezado de `text` que empieza antes de `offset`, si lo hay."""
    section = None
    for match in _HEADING.finditer(text, 0, offset):
        section = match.group().strip()[:MAX_SECTION_CHARS]
    return section


def _split(
    boundaries: list[list[int]], start: int, end: int, level: int, target: int
) -> list[tuple[int, int]]:
    if end - start <= target:
        return [(start, end)]
    if level == len(boundaries):
        return [(i, min(i + target, end)) for i in range(start, end, target)]

    positions = boundaries[level]
    cuts = positions[bisect_right(positions, start) : bisect_left(positions, end)]
    if not cuts:
        return _split(boundaries, start, end, level + 1, target)

    pieces: list[tuple[int, int]] = []
    for piece_start, piece_end in pairwise([start, *cuts, end]):
        pieces.extend(_split(boundaries, piece_start, piece_end, level + 1, target))
    return _merge(pieces, target)


def _merge(pieces: list[tuple[int, int]], target: int) -> list[tuple[int, int]]:
    """Las piezas son contiguas: fusionar es extender el final de la actual."""
    merged = [pieces[0]]
    for start, end in pieces[1:]:
        current_start, _ = merged[-1]
        if end - current_start <= target:
            merged[-1] = (current_start, end)
        else:
            merged.append((start, end))
    return merged


def _strip(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _overlap_start(text: str, start: int, core_start: int) -> int:
    """Empieza el solapamiento en un inicio de palabra para no cortar a mitad."""
    if start > 0 and not text[start - 1].isspace():
        space = next((i for i in range(start, core_start) if text[i].isspace()), core_start)
        start = space
    while start < core_start and text[start].isspace():
        start += 1
    return start


def _page(page_starts: list[int] | None, offset: int) -> int | None:
    if not page_starts:
        return None
    return max(bisect_right(page_starts, offset), 1)


def _section(heading_starts: list[int], headings: list[str], offset: int) -> str | None:
    """Último encabezado que empieza antes del fragmento (o en su inicio)."""
    index = bisect_right(heading_starts, offset) - 1
    return headings[index] if index >= 0 else None
