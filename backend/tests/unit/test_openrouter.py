"""Adaptador de OpenRouter contra un transporte HTTP simulado: sin red ni claves."""

import json
from collections.abc import Callable

import httpx2
import openai
import pytest

from norte_legal.adapters.openrouter import OPENROUTER_BASE_URL, OpenRouterLLMProvider
from norte_legal.domain import errors
from norte_legal.domain.ports import PromptSource, RagPrompt

PROMPT = RagPrompt(system="sys", question="¿Plazo?", sources=[PromptSource(ref="S1", text="t")])
ANSWER = {
    "insufficient_context": False,
    "answer": "Dos años.",
    "citations": [{"ref": "S1", "quote": "t"}],
}


def _completion(
    content: str | None, finish_reason: str = "stop", refusal: str | None = None
) -> dict:  # type: ignore[type-arg]
    return {
        "id": "gen-1",
        "object": "chat.completion",
        "created": 0,
        "model": "anthropic/claude-opus-5.5",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {"role": "assistant", "content": content, "refusal": refusal},
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def _provider(handler: Callable[[httpx2.Request], httpx2.Response]) -> OpenRouterLLMProvider:
    client = openai.OpenAI(
        api_key="test",
        base_url=OPENROUTER_BASE_URL,
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    )
    return OpenRouterLLMProvider("test", "anthropic/claude-opus-5.5", "medium", 5.0, client=client)


def test_sends_strict_schema_reasoning_and_privacy_settings() -> None:
    sent: list[dict] = []  # type: ignore[type-arg]

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content))
        return httpx2.Response(200, json=_completion(json.dumps(ANSWER)))

    answer = _provider(handler).generate_answer(PROMPT)

    assert answer.answer == "Dos años." and answer.citations[0].ref == "S1"
    body = sent[0]
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["reasoning"] == {"effort": "medium"}
    assert body["provider"] == {"require_parameters": True, "data_collection": "deny", "zdr": True}
    assert body["messages"][0] == {"role": "system", "content": "sys"}
    assert '<source ref="S1"' in body["messages"][1]["content"]


@pytest.mark.parametrize(
    ("completion", "expected"),
    [
        (_completion(None, refusal="no"), errors.ProviderPermanentError),
        (_completion("{}", finish_reason="length"), errors.ProviderPermanentError),
        (_completion("{}", finish_reason="error"), errors.ProviderUnavailableError),
        (_completion("not json"), errors.ProviderPermanentError),
        (_completion('{"answer": "sin el campo obligatorio"}'), errors.ProviderPermanentError),
    ],
)
def test_checks_finish_reason_refusal_and_schema(completion: dict, expected: type) -> None:  # type: ignore[type-arg]
    provider = _provider(lambda _: httpx2.Response(200, json=completion))
    with pytest.raises(expected):
        provider.generate_answer(PROMPT)


@pytest.mark.parametrize(
    ("status", "expected", "retryable"),
    [
        (429, errors.ProviderRateLimitedError, True),
        (502, errors.ProviderUnavailableError, True),
        (408, errors.ProviderTimeoutError, True),
        (401, errors.ProviderPermanentError, False),
        (402, errors.ProviderPermanentError, False),
    ],
)
def test_translates_http_errors_to_the_domain_taxonomy(
    status: int, expected: type[errors.ProviderError], retryable: bool
) -> None:
    provider = _provider(
        lambda _: httpx2.Response(
            status, json={"error": {"message": "x"}}, headers={"retry-after": "7"}
        )
    )
    with pytest.raises(expected) as caught:
        provider.generate_answer(PROMPT)
    assert caught.value.retryable is retryable
    if status == 429:
        assert caught.value.retry_after_s == 7.0  # type: ignore[attr-defined]


def test_translates_timeouts() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    with pytest.raises(errors.ProviderTimeoutError):
        _provider(handler).generate_answer(PROMPT)
