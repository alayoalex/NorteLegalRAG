"""Único punto donde se decide qué proveedor concreto se usa. Todos salen instrumentados."""

from functools import lru_cache

from norte_legal.adapters.fake import FakeEmbeddingProvider, FakeLLMProvider
from norte_legal.adapters.openrouter import OpenRouterLLMProvider
from norte_legal.adapters.traced import TracedEmbeddingProvider, TracedLLMProvider
from norte_legal.adapters.voyage import VoyageEmbeddingProvider
from norte_legal.config import Settings, get_settings
from norte_legal.domain.ports import EmbeddingProvider, LLMProvider


def build_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "openrouter" and settings.openrouter_api_key is not None:
        return TracedLLMProvider(
            OpenRouterLLMProvider(
                api_key=settings.openrouter_api_key.get_secret_value(),
                model=settings.llm_model,
                reasoning_effort=settings.llm_reasoning_effort,
                timeout_s=settings.llm_timeout_s,
            )
        )
    return TracedLLMProvider(FakeLLMProvider(settings.fake_llm_failure_mode))


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider == "voyage" and settings.voyage_api_key is not None:
        return TracedEmbeddingProvider(
            VoyageEmbeddingProvider(
                api_key=settings.voyage_api_key.get_secret_value(),
                model=settings.embedding_model,
                timeout_s=settings.embedding_timeout_s,
            )
        )
    return TracedEmbeddingProvider(FakeEmbeddingProvider())


# Una instancia por proceso: reutiliza las conexiones HTTP de los clientes.
@lru_cache
def get_llm_provider() -> LLMProvider:
    return build_llm_provider(get_settings())


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    return build_embedding_provider(get_settings())
