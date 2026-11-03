"""Adaptador de Voyage contra un transporte HTTP simulado: sin red ni claves."""

import json
from collections.abc import Callable

import httpx2
import pytest

from norte_legal.adapters.voyage import VoyageEmbeddingProvider
from norte_legal.domain import errors


def _provider(handler: Callable[[httpx2.Request], httpx2.Response]) -> VoyageEmbeddingProvider:
    client = httpx2.Client(transport=httpx2.MockTransport(handler))
    return VoyageEmbeddingProvider("key", "voyage-4", 5.0, client=client)


def test_sends_input_type_and_restores_the_input_order() -> None:
    sent: list[dict] = []  # type: ignore[type-arg]

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer key"
        data = [{"index": 1, "embedding": [2.0]}, {"index": 0, "embedding": [1.0]}]
        return httpx2.Response(200, json={"data": data, "model": "voyage-4"})

    assert _provider(handler).embed_documents(["a", "b"]) == [[1.0], [2.0]]
    assert sent[0]["input_type"] == "document"
    assert sent[0]["output_dimension"] == 1024
    assert sent[0]["truncation"] is False


def test_queries_use_the_query_input_type() -> None:
    sent: list[dict] = []  # type: ignore[type-arg]

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content))
        return httpx2.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}]})

    _provider(handler).embed_query("¿plazo?")
    assert sent[0]["input_type"] == "query"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (429, errors.ProviderRateLimitedError),
        (503, errors.ProviderUnavailableError),
        (504, errors.ProviderTimeoutError),
        (400, errors.ProviderPermanentError),
        (401, errors.ProviderPermanentError),
    ],
)
def test_translates_http_errors(status: int, expected: type[errors.ProviderError]) -> None:
    with pytest.raises(expected):
        _provider(lambda _: httpx2.Response(status)).embed_query("x")


def test_translates_timeouts_and_connection_errors() -> None:
    def timeout(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectTimeout("slow", request=request)

    def refused(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    with pytest.raises(errors.ProviderTimeoutError):
        _provider(timeout).embed_query("x")
    with pytest.raises(errors.ProviderUnavailableError):
        _provider(refused).embed_query("x")


def test_unexpected_bodies_are_permanent_errors() -> None:
    with pytest.raises(errors.ProviderPermanentError):
        _provider(lambda _: httpx2.Response(200, json={"oops": True})).embed_query("x")
