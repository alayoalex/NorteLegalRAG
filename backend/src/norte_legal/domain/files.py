"""Validación de archivos subidos: tipo real por magic bytes, nombre y archivos comprimidos.

No se confía en la extensión ni en el `Content-Type` del cliente: el tipo sale del contenido.
Un DOCX es un ZIP, así que antes de abrirlo se inspecciona su directorio central para rechazar
bombas de descompresión sin descomprimir nada.
"""

import io
import unicodedata
import zipfile
from enum import StrEnum
from pathlib import PurePosixPath

from norte_legal.domain.errors import InvalidDocumentError

MAX_NAME_LENGTH = 255
# El encabezado de un PDF puede ir precedido de basura; los lectores lo buscan en el primer KiB.
PDF_HEADER_WINDOW = 1024
ZIP_MAX_ENTRIES = 2_000
ZIP_MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
ZIP_MAX_RATIO = 100
# Los archivos pequeños comprimen muy bien sin ser peligrosos: la ratio solo se mira por encima.
ZIP_RATIO_MIN_BYTES = 1024 * 1024
DOCX_REQUIRED_ENTRIES = frozenset({"[Content_Types].xml", "word/document.xml"})


class MediaType(StrEnum):
    PDF = "application/pdf"
    DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    TXT = "text/plain"


def sanitize_name(raw: str | None) -> str:
    """Nombre lógico del documento: sin ruta, normalizado y sin caracteres de control."""
    name = PurePosixPath((raw or "").replace("\\", "/")).name
    name = unicodedata.normalize("NFC", name).strip()
    if not name or len(name) > MAX_NAME_LENGTH:
        raise InvalidDocumentError("invalid_file_name", "file name is empty or too long")
    if any(unicodedata.category(char).startswith("C") for char in name):
        raise InvalidDocumentError("invalid_file_name", "file name contains control characters")
    return name


def detect_media_type(content: bytes) -> MediaType:
    if not content:
        raise InvalidDocumentError("empty_file", "file is empty")
    if b"%PDF-" in content[:PDF_HEADER_WINDOW]:
        return MediaType.PDF
    if content.startswith(b"PK\x03\x04"):
        inspect_docx_archive(content)
        return MediaType.DOCX
    decode_text(content)
    return MediaType.TXT


def inspect_docx_archive(content: bytes) -> None:
    """Rechaza ZIP que no son DOCX o cuya descompresión sería desproporcionada."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
    except zipfile.BadZipFile as error:
        raise InvalidDocumentError("corrupt_file", "archive cannot be read") from error

    if len(entries) > ZIP_MAX_ENTRIES:
        raise InvalidDocumentError("archive_too_complex", "archive has too many entries")
    if not {entry.filename for entry in entries} >= DOCX_REQUIRED_ENTRIES:
        raise InvalidDocumentError("unsupported_media_type", "archive is not a DOCX document")

    total = 0
    for entry in entries:
        if entry.flag_bits & 0x1:
            raise InvalidDocumentError("encrypted_file", "archive is encrypted")
        total += entry.file_size
        ratio = entry.file_size / max(entry.compress_size, 1)
        if entry.file_size > ZIP_RATIO_MIN_BYTES and ratio > ZIP_MAX_RATIO:
            raise InvalidDocumentError("archive_too_large", "suspicious compression ratio")
    if total > ZIP_MAX_UNCOMPRESSED_BYTES:
        raise InvalidDocumentError("archive_too_large", "uncompressed size exceeds the limit")


def decode_text(content: bytes) -> str:
    """UTF-8 (con o sin BOM) y, si falla, Windows-1252, habitual en textos legales antiguos."""
    if b"\x00" in content:
        raise InvalidDocumentError("unsupported_media_type", "binary content is not supported")
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        return content.decode("cp1252")
    except UnicodeDecodeError as error:
        raise InvalidDocumentError("unsupported_encoding", "text encoding not supported") from error
