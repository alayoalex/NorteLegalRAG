import pytest

from factories import make_docx, make_pdf
from norte_legal.domain.errors import InvalidDocumentError
from norte_legal.domain.extraction import extract_text, normalize
from norte_legal.domain.files import MediaType


def test_pdf_keeps_page_boundaries() -> None:
    extracted = extract_text(make_pdf(["Term clause.", "Payment clause."]), MediaType.PDF)

    assert extracted.text == "Term clause.\n\nPayment clause."
    assert extracted.page_starts == [0, len("Term clause.\n\n")]


def test_docx_keeps_paragraph_and_table_order() -> None:
    content = make_docx(["Cláusula Primera", "Objeto del contrato."], [["Parte", "Rol"]])
    assert extract_text(content, MediaType.DOCX).text == (
        "Cláusula Primera\n\nObjeto del contrato.\n\nParte | Rol"
    )


def test_txt_is_normalized() -> None:
    raw = "Línea uno\r\n\r\n\r\n\r\nLínea\t\tdos   \r\n".encode()
    assert extract_text(raw, MediaType.TXT).text == "Línea uno\n\nLínea dos"


def test_normalize_composes_accents() -> None:
    assert normalize("Cla\u0301usula") == "Cláusula"


@pytest.mark.parametrize(
    ("content", "media_type", "code"),
    [
        (make_pdf([""]), MediaType.PDF, "no_text_extracted"),
        (b"%PDF-1.4 not really a pdf", MediaType.PDF, "corrupt_file"),
        (b"   \n\n  ", MediaType.TXT, "no_text_extracted"),
        (b"hello", "image/png", "unsupported_media_type"),
    ],
)
def test_unprocessable_documents_fail_with_a_stable_code(
    content: bytes, media_type: str, code: str
) -> None:
    with pytest.raises(InvalidDocumentError) as caught:
        extract_text(content, media_type)
    assert caught.value.code == code
