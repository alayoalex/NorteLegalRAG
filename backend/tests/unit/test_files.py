import pytest

from factories import make_docx, make_pdf, make_zip
from norte_legal.domain import files
from norte_legal.domain.errors import InvalidDocumentError
from norte_legal.domain.files import MediaType, decode_text, detect_media_type, sanitize_name


def _code(call: object, *args: object) -> str:
    with pytest.raises(InvalidDocumentError) as caught:
        call(*args)  # type: ignore[operator]
    return caught.value.code


class TestDetectMediaType:
    def test_detects_by_content_not_by_name(self) -> None:
        assert detect_media_type(make_pdf(["Hello"])) is MediaType.PDF
        assert detect_media_type(make_docx(["Hello"])) is MediaType.DOCX
        assert detect_media_type(b"Contrato de arrendamiento") is MediaType.TXT

    def test_rejects_empty_and_binary_content(self) -> None:
        assert _code(detect_media_type, b"") == "empty_file"
        assert _code(detect_media_type, b"\x89PNG\r\n\x1a\n\x00\x00") == "unsupported_media_type"

    def test_rejects_zip_files_that_are_not_docx(self) -> None:
        archive = make_zip({"notes.txt": b"hello"})
        assert _code(detect_media_type, archive) == "unsupported_media_type"

    def test_rejects_corrupt_zip(self) -> None:
        assert _code(detect_media_type, b"PK\x03\x04garbage") == "corrupt_file"


class TestZipBomb:
    def test_rejects_suspicious_compression_ratio(self) -> None:
        bomb = make_zip(
            {
                "[Content_Types].xml": b"<Types/>",
                "word/document.xml": b"0" * (5 * 1024 * 1024),
            }
        )
        assert len(bomb) < 100_000
        assert _code(files.inspect_docx_archive, bomb) == "archive_too_large"

    def test_rejects_total_uncompressed_size(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(files, "ZIP_MAX_UNCOMPRESSED_BYTES", 1_000)
        assert _code(files.inspect_docx_archive, make_docx(["Hello"])) == "archive_too_large"

    def test_rejects_too_many_entries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(files, "ZIP_MAX_ENTRIES", 2)
        assert _code(files.inspect_docx_archive, make_docx(["Hello"])) == "archive_too_complex"

    def test_accepts_a_regular_docx(self) -> None:
        files.inspect_docx_archive(make_docx(["Hello"] * 100))


class TestDecodeText:
    def test_accepts_utf8_with_bom_and_windows_1252(self) -> None:
        assert decode_text("\ufeffCláusula".encode()) == "Cláusula"
        assert decode_text("Cláusula".encode("cp1252")) == "Cláusula"

    def test_rejects_bytes_undefined_in_windows_1252(self) -> None:
        assert _code(decode_text, b"\x81\x8d\x8f") == "unsupported_encoding"


class TestSanitizeName:
    def test_strips_paths_from_both_separators(self) -> None:
        assert sanitize_name("../../etc/contrato.pdf") == "contrato.pdf"
        assert sanitize_name("C:\\Users\\ana\\politica.docx") == "politica.docx"

    @pytest.mark.parametrize("name", [None, "", "   ", "a\x00b.txt", "x" * 300])
    def test_rejects_invalid_names(self, name: str | None) -> None:
        assert _code(sanitize_name, name) == "invalid_file_name"
