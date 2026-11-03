"""Extracción de texto de PDF, DOCX y TXT.

El texto que devuelve es la referencia de todos los offsets: `chunk.text` es siempre un corte de
`ExtractedText.text`. La extracción es determinista para un mismo archivo y una misma
`EXTRACTOR_VERSION`, que forma parte de la huella del pipeline.
"""

import io
import re
import unicodedata
from dataclasses import dataclass, field

import docx
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader

from norte_legal.domain.errors import InvalidDocumentError
from norte_legal.domain.files import MediaType, decode_text, inspect_docx_archive

EXTRACTOR_VERSION = "extract-v1"
MAX_PDF_PAGES = 1_000
# Acota la memoria del worker y el coste de embeddings de un único documento.
MAX_EXTRACTED_CHARS = 3_000_000
PAGE_SEPARATOR = "\n\n"

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_HORIZONTAL_SPACE = re.compile(r"[ \t\u00a0]+")
_TRAILING_SPACE = re.compile(r" +\n")
_BLANK_LINES = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class ExtractedText:
    text: str
    # Offset en `text` donde empieza cada página. Vacío si el formato no tiene páginas.
    page_starts: list[int] = field(default_factory=list)


def extract_text(content: bytes, media_type: str) -> ExtractedText:
    match media_type:
        case MediaType.PDF:
            extracted = _extract_pdf(content)
        case MediaType.DOCX:
            extracted = _extract_docx(content)
        case MediaType.TXT:
            extracted = ExtractedText(normalize(decode_text(content)))
        case _:
            raise InvalidDocumentError("unsupported_media_type", "media type not supported")

    if not extracted.text.strip():
        # Típico de un PDF escaneado: el OCR queda fuera del alcance (DECISIONS.md).
        raise InvalidDocumentError("no_text_extracted", "document contains no extractable text")
    if len(extracted.text) > MAX_EXTRACTED_CHARS:
        raise InvalidDocumentError("document_too_long", "extracted text exceeds the limit")
    return extracted


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL.sub("", text.replace("\f", "\n"))
    text = _HORIZONTAL_SPACE.sub(" ", text)
    text = _TRAILING_SPACE.sub("\n", text)
    return _BLANK_LINES.sub("\n\n", text).strip()


def _extract_pdf(content: bytes) -> ExtractedText:
    # pypdf puede lanzar casi cualquier excepción ante un PDF malformado: entrada no confiable.
    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted and not reader.decrypt(""):
            raise InvalidDocumentError("encrypted_file", "PDF requires a password")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise InvalidDocumentError("document_too_long", "PDF has too many pages")
        pages = [normalize(page.extract_text() or "") for page in reader.pages]
    except InvalidDocumentError:
        raise
    except Exception as error:
        raise InvalidDocumentError("corrupt_file", "PDF cannot be parsed") from error

    parts: list[str] = []
    page_starts: list[int] = []
    offset = 0
    for page in pages:
        if parts:
            parts.append(PAGE_SEPARATOR)
            offset += len(PAGE_SEPARATOR)
        page_starts.append(offset)
        parts.append(page)
        offset += len(page)
    return ExtractedText("".join(parts), page_starts)


def _extract_docx(content: bytes) -> ExtractedText:
    inspect_docx_archive(content)
    try:
        document = docx.Document(io.BytesIO(content))
        blocks = [_docx_block_text(block) for block in document.iter_inner_content()]
    except Exception as error:
        raise InvalidDocumentError("corrupt_file", "DOCX cannot be parsed") from error
    return ExtractedText(normalize("\n\n".join(block for block in blocks if block.strip())))


def _docx_block_text(block: Paragraph | Table) -> str:
    if isinstance(block, Paragraph):
        return block.text
    rows = []
    for row in block.rows:
        rows.append(" | ".join(cell.text.strip() for cell in row.cells))
    return "\n".join(rows)
