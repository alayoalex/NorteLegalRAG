"""Decoradores que añaden trazas y métricas a cualquier proveedor de LLM o de embeddings.

Vive fuera de los adaptadores para que toda implementación quede instrumentada igual. Sigue las
convenciones `gen_ai.*`. No registra prompts ni respuestas: pueden contener datos confidenciales.
"""

import time
from collections.abc import Callable

from opentelemetry import metrics, trace
from opentelemetry.trace import Status, StatusCode

from norte_legal.domain.errors import (
    ProviderError,
    ProviderPermanentError,
    ProviderRateLimitedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from norte_legal.domain.ports import DraftAnswer, EmbeddingProvider, LLMProvider, RagPrompt

_tracer = trace.get_tracer("norte_legal.llm")
_meter = metrics.get_meter("norte_legal.llm")
# Buckets explícitos: los del SDK (0, 5, 10, 25...) meten casi todo en el primero.
# 55 s es QUERY_BUDGET_S: el último límite útil antes del timeout de nginx.
_duration = _meter.create_histogram(
    "llm.request.duration",
    unit="s",
    description="Duración de las llamadas al LLM",
    explicit_bucket_boundaries_advisory=[0.5, 1, 2, 5, 10, 15, 20, 30, 45, 55, 60],
)
_errors = _meter.create_counter(
    "llm.request.errors", description="Fallos de llamadas al LLM, por tipo"
)
_embedding_duration = _meter.create_histogram(
    "embeddings.request.duration",
    unit="s",
    description="Duración de las llamadas de embeddings",
    explicit_bucket_boundaries_advisory=[0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60],
)
_embedding_errors = _meter.create_counter(
    "embeddings.request.errors", description="Fallos de llamadas de embeddings, por tipo"
)

_ERROR_TYPES = tuple(
    error.code
    for error in (
        ProviderError,
        ProviderTimeoutError,
        ProviderRateLimitedError,
        ProviderUnavailableError,
        ProviderPermanentError,
    )
)


def initialize_metrics() -> None:
    """Publica los contadores de errores en 0 para que Prometheus vea el primer fallo.

    Mismo motivo y misma condición que `services.query.initialize_metrics`.
    """
    for error_type in _ERROR_TYPES:
        _errors.add(0, {"error.type": error_type})
        _embedding_errors.add(0, {"error.type": error_type})


class TracedLLMProvider:
    def __init__(self, inner: LLMProvider) -> None:
        self._inner = inner

    @property
    def model(self) -> str:
        return self._inner.model

    def generate_answer(self, prompt: RagPrompt) -> DraftAnswer:
        attributes = {"gen_ai.operation.name": "chat", "gen_ai.request.model": self.model}
        started = time.perf_counter()
        with _tracer.start_as_current_span("llm.generate_answer", attributes=attributes) as span:
            span.set_attribute("rag.source_count", len(prompt.sources))
            try:
                answer = self._inner.generate_answer(prompt)
            except ProviderError as error:
                span.record_exception(error)
                span.set_status(Status(StatusCode.ERROR, error.code))
                span.set_attribute("error.type", error.code)
                _errors.add(1, {"error.type": error.code})
                raise
            finally:
                _duration.record(
                    time.perf_counter() - started, {"gen_ai.request.model": self.model}
                )
            span.set_attribute("rag.insufficient_context", answer.insufficient_context)
            return answer


class TracedEmbeddingProvider:
    def __init__(self, inner: EmbeddingProvider) -> None:
        self._inner = inner

    @property
    def model(self) -> str:
        return self._inner.model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._traced("embeddings.embed_documents", texts, self._inner.embed_documents)

    def embed_query(self, text: str) -> list[float]:
        return self._traced(
            "embeddings.embed_query", [text], lambda t: [self._inner.embed_query(t[0])]
        )[0]

    def _traced(
        self,
        name: str,
        texts: list[str],
        call: Callable[[list[str]], list[list[float]]],
    ) -> list[list[float]]:
        attributes = {"gen_ai.operation.name": "embeddings", "gen_ai.request.model": self.model}
        started = time.perf_counter()
        with _tracer.start_as_current_span(name, attributes=attributes) as span:
            span.set_attribute("embeddings.input_count", len(texts))
            span.set_attribute("embeddings.input_chars", sum(len(text) for text in texts))
            try:
                return call(texts)
            except ProviderError as error:
                span.record_exception(error)
                span.set_status(Status(StatusCode.ERROR, error.code))
                span.set_attribute("error.type", error.code)
                _embedding_errors.add(1, {"error.type": error.code})
                raise
            finally:
                _embedding_duration.record(
                    time.perf_counter() - started, {"gen_ai.request.model": self.model}
                )
