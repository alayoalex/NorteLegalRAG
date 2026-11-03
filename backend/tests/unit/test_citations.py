from norte_legal.domain.citations import locate_quote, validate_answer
from norte_legal.domain.ports import DraftAnswer, DraftCitation

# Apóstrofo tipográfico (\u2019), como suele salir de un PDF.
SENTENCE = "Either party may terminate this Agreement with 30 days\u2019 notice"
CHUNK = f"Section 8.2 Termination.\n{SENTENCE}."


def test_locates_the_quote_in_the_original_text() -> None:
    span = locate_quote("may terminate this Agreement", CHUNK)
    assert span is not None
    assert CHUNK[span[0] : span[1]] == "may terminate this Agreement"


def test_tolerates_case_whitespace_quotes_and_surrounding_punctuation() -> None:
    span = locate_quote(
        '"either party  MAY terminate\nthis agreement with 30 days\' notice…"', CHUNK
    )
    assert span is not None
    assert CHUNK[span[0] : span[1]] == SENTENCE


def test_rejects_paraphrases_and_trivial_quotes() -> None:
    assert locate_quote("Any party can end the contract", CHUNK) is None
    assert locate_quote("party", CHUNK) is None


def test_drops_citations_to_unknown_refs_and_duplicates() -> None:
    draft = DraftAnswer(
        insufficient_context=False,
        answer="  Se puede terminar con preaviso.  ",
        citations=[
            DraftCitation(ref="S1", quote="may terminate this Agreement"),
            DraftCitation(ref="S1", quote="May terminate this agreement"),
            DraftCitation(ref="S9", quote="may terminate this Agreement"),
            DraftCitation(ref="S1", quote="invented sentence that is not there"),
        ],
    )
    validated = validate_answer(draft, {"S1": CHUNK})

    assert validated.answer == "Se puede terminar con preaviso."
    assert [(c.ref, c.quote) for c in validated.citations] == [
        ("S1", "may terminate this Agreement")
    ]
    assert validated.dropped == 3
