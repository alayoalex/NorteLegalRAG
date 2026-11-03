from hypothesis import given, settings
from hypothesis import strategies as st

from norte_legal.domain.chunking import (
    OVERLAP_CHARS,
    TARGET_CHARS,
    chunk_text,
    pipeline_fingerprint,
    section_at,
)

# Texto con estructura: palabras, signos, saltos de línea y encabezados al inicio de línea.
_pieces = st.one_of(
    st.text(alphabet=st.characters(codec="utf-8", exclude_categories=["Cs"]), max_size=40),
    st.sampled_from(["\n", "\n\n", ". ", " ", "\nSection 4.2 Term\n", "\nCLÁUSULA TERCERA\n"]),
    st.just("x" * 2_500),
)
_documents = st.lists(_pieces, max_size=80).map("".join)


@settings(max_examples=300, deadline=None)
@given(text=_documents, target=st.integers(50, 2_000), overlap_ratio=st.floats(0, 0.5))
def test_offsets_slice_the_extracted_text_exactly(
    text: str, target: int, overlap_ratio: float
) -> None:
    overlap = int(target * overlap_ratio)
    chunks = chunk_text(text, target=target, overlap=overlap)

    for ordinal, chunk in enumerate(chunks):
        assert chunk.ordinal == ordinal
        assert text[chunk.char_start : chunk.char_end] == chunk.text
        assert chunk.char_end > chunk.char_start
        assert len(chunk.text) <= target + overlap
        assert chunk.text == chunk.text.strip()

    # Ningún carácter visible se pierde y el orden se respeta.
    covered = set()
    for chunk in chunks:
        covered.update(range(chunk.char_start, chunk.char_end))
    assert all(i in covered for i, char in enumerate(text) if not char.isspace())
    assert [c.char_end for c in chunks] == sorted(c.char_end for c in chunks)


def test_prefers_clause_headings_as_boundaries() -> None:
    clause = "The supplier shall deliver the goods on time and in good condition. " * 15
    text = f"Section 1. Delivery\n{clause}\n\nSection 2. Payment\n{clause}"
    chunks = chunk_text(text)

    assert [chunk.section for chunk in chunks] == ["Section 1. Delivery", "Section 2. Payment"]
    # Un fragmento que abre cláusula no arrastra el final de la anterior.
    assert chunks[1].text.startswith("Section 2. Payment")


def test_consecutive_chunks_overlap_within_a_long_clause() -> None:
    text = " ".join(f"Sentence number {i} of a long clause." for i in range(400))
    first, second, *_ = chunk_text(text)

    assert first.char_end - TARGET_CHARS <= first.char_start
    assert 0 < first.char_end - second.char_start <= OVERLAP_CHARS
    assert text[second.char_start - 1] == " "


def test_maps_offsets_to_pages() -> None:
    page_one, page_two = "First page text. " * 150, "Second page text. " * 150
    text = f"{page_one}\n\n{page_two}"
    chunks = chunk_text(text, page_starts=[0, len(page_one) + 2])

    assert chunks[0].page_start == 1
    assert chunks[-1].page_end == 2
    second_page = len(page_one) + 2
    for chunk in chunks:
        assert chunk.page_start == (1 if chunk.char_start < second_page else 2)
        assert chunk.page_end == (1 if chunk.char_end <= second_page else 2)


def test_formats_without_pages_have_no_page_numbers() -> None:
    (chunk,) = chunk_text("Short policy text.")
    assert chunk.page_start is None
    assert chunk.page_end is None


def test_fingerprint_changes_with_the_embedding_model() -> None:
    assert pipeline_fingerprint("extract-v1", "a") != pipeline_fingerprint("extract-v1", "b")


def test_section_at_returns_the_heading_that_precedes_an_offset() -> None:
    text = "Section 1. Term\nTwo years.\n\nSection 2. Rent\nMonthly."
    assert section_at(text, text.index("Monthly")) == "Section 2. Rent"
    assert section_at(text, text.index("Two")) == "Section 1. Term"
    assert section_at("No headings here.", 5) is None
