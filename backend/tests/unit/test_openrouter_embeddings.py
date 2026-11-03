"""Embeddings de OpenRouter contra un transporte HTTP simulado: sin red ni claves."""

import json
from collections.abc import Callable

import httpx2
import openai
import pytest

from norte_legal.adapters.openrouter import (
    OPENROUTER_BASE_URL,
    DataPolicy,
    OpenRouterEmbeddingProvider,
)
from norte_legal.domain import errors
from norte_legal.domain.ports import EMBEDDING_DIMENSION

VECTOR = [0.1] * EMBEDDING_DIMENSION


def _provider(
    handler: Callable[[httpx2.Request], httpx2.Response], policy: DataPolicy = "zdr"
) -> OpenRouterEmbeddingProvider:
    client = openai.OpenAI(
        api_key="test",
        base_url=OPENROUTER_BASE_URL,
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    )
    return OpenRouterEmbeddingProvider("test", "baai/bge-m3", 5.0, policy, client=client)


def _body(*vectors: tuple[int, list[float]]) -> dict:  # type: ignore[type-arg]
    data = [{"object": "embedding", "index": i, "embedding": v} for i, v in vectors]
    usage = {"prompt_tokens": 1, "total_tokens": 1}
    return {"object": "list", "data": data, "model": "baai/bge-m3", "usage": usage}


def test_sends_dimensions_input_type_and_privacy_and_restores_the_order() -> None:
    sent: list[dict] = []  # type: ignore[type-arg]
    second = [0.2] * EMBEDDING_DIMENSION

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content))
        return httpx2.Response(200, json=_body((1, second), (0, VECTOR)))

    assert _provider(handler).embed_documents(["a", "b"]) == [VECTOR, second]
    body = sent[0]
    assert (body["model"], body["dimensions"], body["encoding_format"]) == (
        "baai/bge-m3",
        1024,
        "float",
    )
    assert body["input_type"] == "document"
    assert body["provider"] == {"data_collection": "deny", "zdr": True}


def test_queries_use_the_query_input_type_and_free_models_need_allow() -> None:
    sent: list[dict] = []  # type: ignore[type-arg]

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content))
        return httpx2.Response(200, json=_body((0, VECTOR)))

    _provider(handler, "allow").embed_query("¿plazo?")
    assert sent[0]["input_type"] == "query"
    assert sent[0]["provider"] == {"data_collection": "allow"}


def test_a_model_that_ignores_the_dimension_is_a_permanent_error() -> None:
    wrong = _body((0, [0.1] * 2048))
    with pytest.raises(errors.ProviderPermanentError):
        _provider(lambda _: httpx2.Response(200, json=wrong)).embed_query("x")


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (429, errors.ProviderRateLimitedError),
        (503, errors.ProviderUnavailableError),
        (408, errors.ProviderTimeoutError),
        (402, errors.ProviderPermanentError),
        (404, errors.ProviderPermanentError),
    ],
)
def test_translates_http_errors(status: int, expected: type[errors.ProviderError]) -> None:
    with pytest.raises(expected):
        _provider(lambda _: httpx2.Response(status, json={"error": {}})).embed_query("x")


def test_translates_timeouts() -> None:
    def timeout(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectTimeout("slow", request=request)

    with pytest.raises(errors.ProviderTimeoutError):
        _provider(timeout).embed_query("x")
