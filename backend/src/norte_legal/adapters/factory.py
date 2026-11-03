"""Único punto donde se decide qué proveedor concreto se usa."""

from norte_legal.adapters.fake import FakeEmbeddingProvider, FakeLLMProvider
from norte_legal.adapters.traced import TracedLLMProvider
from norte_legal.config import Settings
from norte_legal.domain.ports import EmbeddingProvider, LLMProvider


def build_llm_provider(settings: Settings) -> LLMProvider:
    return TracedLLMProvider(FakeLLMProvider(settings.fake_llm_failure_mode))


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    return FakeEmbeddingProvider()
