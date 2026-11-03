import math

import pytest

from norte_legal.adapters.fake import FakeEmbeddingProvider, FakeLLMProvider
from norte_legal.domain.errors import (
    ProviderRateLimitedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from norte_legal.domain.ports import EMBEDDING_DIMENSION, PromptSource, RagPrompt


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _prompt(question: str, *texts: str) -> RagPrompt:
    sources = [PromptSource(ref=f"S{i}", text=text) for i, text in enumerate(texts, start=1)]
    return RagPrompt(system="sys", question=question, sources=sources)


class TestFakeEmbedding:
    def test_is_deterministic_with_unit_norm_and_expected_dimension(self) -> None:
        provider = FakeEmbeddingProvider()
        first, second = provider.embed_documents(["Cláusula de terminación"] * 2)
        assert first == second
        assert len(first) == EMBEDDING_DIMENSION
        assert math.isclose(sum(v * v for v in first), 1.0, rel_tol=1e-9)

    def test_shared_terms_score_higher_than_unrelated_text(self) -> None:
        provider = FakeEmbeddingProvider()
        query = provider.embed_query("termination clause notice period")
        related, unrelated = provider.embed_documents(
            ["The termination clause requires a notice period.", "Payment is due in euros."]
        )
        assert _cosine(query, related) > _cosine(query, unrelated)

    def test_ignores_case_and_accents(self) -> None:
        provider = FakeEmbeddingProvider()
        assert provider.embed_query("CLÁUSULA") == provider.embed_query("clausula")

    def test_text_without_tokens_avoids_the_zero_vector(self) -> None:
        assert any(FakeEmbeddingProvider().embed_query("  ...  "))


class TestFakeLLM:
    def test_quotes_a_literal_substring_of_the_best_source(self) -> None:
        source = "Payment is due in euros. Either party may terminate with notice in writing."
        answer = FakeLLMProvider().generate_answer(
            _prompt("Can a party terminate with written notice?", "Unrelated text here.", source)
        )
        assert not answer.insufficient_context
        assert answer.citations[0].ref == "S2"
        assert answer.citations[0].quote in source

    def test_abstains_without_sources(self) -> None:
        assert (
            FakeLLMProvider().generate_answer(_prompt("Any question at all?")).insufficient_context
        )

    def test_abstains_when_sources_do_not_match(self) -> None:
        answer = FakeLLMProvider().generate_answer(
            _prompt("What is the governing law?", "Payment is due in euros.")
        )
        assert answer.insufficient_context
        assert answer.citations == []

    @pytest.mark.parametrize(
        ("mode", "expected"),
        [
            ("timeout", ProviderTimeoutError),
            ("rate_limit", ProviderRateLimitedError),
            ("unavailable", ProviderUnavailableError),
        ],
    )
    def test_injects_retryable_failures(self, mode: str, expected: type[Exception]) -> None:
        with pytest.raises(expected) as caught:
            FakeLLMProvider(mode).generate_answer(_prompt("q"))  # type: ignore[arg-type]
        assert caught.value.retryable  # type: ignore[attr-defined]


def test_numbers_and_clause_numbers_do_not_split_sentences() -> None:
    source = "Section 4.2 Rent. The tenant pays a monthly rent of 1.200 euros."
    answer = FakeLLMProvider().generate_answer(
        _prompt("What monthly rent does the tenant pay?", source)
    )
    assert answer.citations[0].quote == "The tenant pays a monthly rent of 1.200 euros."
