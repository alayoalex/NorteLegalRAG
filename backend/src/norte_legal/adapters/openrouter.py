"""LLM y embeddings a través de OpenRouter, con el SDK oficial de `openai` (API compatible).
Ver DECISIONS.md §8.

- Salida estructurada con `response_format` `json_schema` estricto. `require_parameters` impide
  que OpenRouter enrute a un proveedor que ignore el esquema; aun así se valida con Pydantic.
- Privacidad según `OPENROUTER_DATA_POLICY` (por defecto `zdr`: solo proveedores que no retienen
  ni entrenan con los datos). Los modelos gratuitos exigen `allow`: solo para datos públicos.
- Se comprueban `finish_reason` y `refusal` antes de leer el contenido.
- `max_retries=0`: los reintentos los deciden el worker y el servicio de consulta, no el SDK.
- Plazo total por intento (`_DeadlineTransport`): OpenRouter responde 200 en seguida y mantiene viva
  la conexión con espacios mientras el modelo genera, así que el `timeout` de httpx, que mide el
  tiempo entre bytes, no salta nunca.
"""

import time
from collections.abc import Iterator
from typing import Any, Literal

import httpx2
import openai
import structlog
from pydantic import ValidationError

from norte_legal.domain.errors import (
    ProviderError,
    ProviderPermanentError,
    ProviderRateLimitedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from norte_legal.domain.ports import EMBEDDING_DIMENSION, DraftAnswer, RagPrompt
from norte_legal.domain.prompts import render_user_message

logger = structlog.get_logger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# Incluye el razonamiento, que en este modelo no se puede desactivar.
MAX_TOKENS = 8_000

# Esquema escrito a mano: el modo estricto exige todos los campos y `additionalProperties: false`,
# y así el contrato con el modelo se lee en un solo sitio.
DRAFT_ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["insufficient_context", "answer", "citations"],
    "properties": {
        "insufficient_context": {
            "type": "boolean",
            "description": "true si los fragmentos no permiten responder la pregunta",
        },
        "answer": {"type": "string", "description": "Respuesta. Vacía si insufficient_context"},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["ref", "quote"],
                "properties": {
                    "ref": {"type": "string", "description": "Referencia del fragmento, p. ej. S2"},
                    "quote": {
                        "type": "string",
                        "description": "Frase copiada literalmente del fragmento citado",
                    },
                },
            },
        },
    },
}


DataPolicy = Literal["zdr", "deny", "allow"]


def provider_preferences(policy: DataPolicy) -> dict[str, Any]:
    """`zdr`: retención cero. `deny`: sin entrenamiento, pero el proveedor puede retener.
    `allow`: cualquier proveedor, también los modelos gratuitos, que entrenan con lo recibido."""
    match policy:
        case "zdr":
            return {"data_collection": "deny", "zdr": True}
        case "deny":
            return {"data_collection": "deny"}
        case "allow":
            return {"data_collection": "allow"}


class _DeadlineStream(httpx2.SyncByteStream):
    def __init__(self, inner: httpx2.SyncByteStream, deadline: float, request: httpx2.Request):
        self._inner = inner
        self._deadline = deadline
        self._request = request

    def __iter__(self) -> Iterator[bytes]:
        for chunk in self._inner:
            if time.monotonic() > self._deadline:
                # El SDK lo traduce a APITimeoutError y el adaptador a ProviderTimeoutError.
                raise httpx2.ReadTimeout("total request time exceeded", request=self._request)
            yield chunk

    def close(self) -> None:
        self._inner.close()


class _DeadlineTransport(httpx2.BaseTransport):
    """Limita la duración total de cada petición, cabeceras y cuerpo incluidos."""

    def __init__(self, timeout_s: float, inner: httpx2.BaseTransport | None = None) -> None:
        self._timeout_s = timeout_s
        self._inner = inner or httpx2.HTTPTransport()

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        deadline = time.monotonic() + self._timeout_s
        response = self._inner.handle_request(request)
        # Un transporte síncrono siempre devuelve un SyncByteStream; si no, no se envuelve.
        if isinstance(response.stream, httpx2.SyncByteStream):
            response.stream = _DeadlineStream(response.stream, deadline, request)
        return response

    def close(self) -> None:
        self._inner.close()


def _client(api_key: str, timeout_s: float) -> openai.OpenAI:
    http_client = httpx2.Client(transport=_DeadlineTransport(timeout_s), timeout=timeout_s)
    return openai.OpenAI(
        api_key=api_key,
        base_url=OPENROUTER_BASE_URL,
        timeout=timeout_s,
        max_retries=0,
        http_client=http_client,
    )


class OpenRouterLLMProvider:
    def __init__(
        self,
        api_key: str,
        model: str,
        reasoning_effort: str,
        timeout_s: float,
        data_policy: DataPolicy = "zdr",
        client: openai.OpenAI | None = None,
    ) -> None:
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._provider = {"require_parameters": True, **provider_preferences(data_policy)}
        self._client = client or _client(api_key, timeout_s)

    @property
    def model(self) -> str:
        return self._model

    def generate_answer(self, prompt: RagPrompt) -> DraftAnswer:
        try:
            completion = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": prompt.system},
                    {"role": "user", "content": render_user_message(prompt)},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "draft_answer",
                        "strict": True,
                        "schema": DRAFT_ANSWER_SCHEMA,
                    },
                },
                max_tokens=MAX_TOKENS,
                extra_body={
                    "reasoning": {"effort": self._reasoning_effort},
                    "provider": self._provider,
                },
            )
        except openai.OpenAIError as error:
            raise translate_error(error) from error

        if not completion.choices:
            raise ProviderUnavailableError("openrouter returned no choices")
        choice = completion.choices[0]
        usage = completion.usage
        logger.info(
            "llm_completion",
            model=self._model,
            finish_reason=choice.finish_reason,
            input_tokens=usage.prompt_tokens if usage else None,
            output_tokens=usage.completion_tokens if usage else None,
        )
        # OpenRouter normaliza `finish_reason` y puede devolver "error" si el proveedor falló.
        match choice.finish_reason:
            case "stop":
                pass
            case "error":
                raise ProviderUnavailableError("upstream provider failed")
            case "length":
                raise ProviderPermanentError("answer truncated by max_tokens")
            case other:
                raise ProviderPermanentError(f"unexpected finish_reason: {other}")
        if choice.message.refusal:
            raise ProviderPermanentError("model refused to answer")
        if not choice.message.content:
            raise ProviderPermanentError("empty answer")
        try:
            return DraftAnswer.model_validate_json(choice.message.content)
        except ValidationError as error:
            raise ProviderPermanentError("answer does not match the schema") from error


class OpenRouterEmbeddingProvider:
    """Embeddings por `POST /embeddings`. `input_type` distingue documento y consulta en los
    modelos que lo admiten (Voyage, Nemotron) y el resto lo ignora."""

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_s: float,
        data_policy: DataPolicy = "zdr",
        client: openai.OpenAI | None = None,
    ) -> None:
        self._model = model
        self._provider = provider_preferences(data_policy)
        self._client = client or _client(api_key, timeout_s)

    @property
    def model(self) -> str:
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, "document")

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "query")[0]

    def _embed(
        self, texts: list[str], input_type: Literal["document", "query"]
    ) -> list[list[float]]:
        try:
            response = self._client.embeddings.create(
                model=self._model,
                input=texts,
                dimensions=EMBEDDING_DIMENSION,
                # Sin esto el SDK pide base64, que no todos los proveedores de OpenRouter devuelven.
                encoding_format="float",
                extra_body={"input_type": input_type, "provider": self._provider},
            )
        except openai.OpenAIError as error:
            raise translate_error(error) from error
        # No se asume que el orden de la respuesta sea el de la entrada.
        vectors = [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
        # Un modelo que ignora `dimensions` no cabe en `vector(1024)`: mejor fallar aquí.
        if len(vectors) != len(texts) or any(len(v) != EMBEDDING_DIMENSION for v in vectors):
            raise ProviderPermanentError("openrouter returned embeddings of an unexpected shape")
        return vectors


def translate_error(error: openai.OpenAIError) -> ProviderError:
    """Taxonomía del dominio a partir de las excepciones del SDK (invariante 10)."""
    if isinstance(error, openai.APITimeoutError):
        return ProviderTimeoutError("openrouter request timed out")
    if isinstance(error, openai.APIConnectionError):
        return ProviderUnavailableError("openrouter connection failed")
    if isinstance(error, openai.RateLimitError):
        return ProviderRateLimitedError(
            "openrouter rate limited", retry_after_s=_retry_after(error.response.headers)
        )
    if isinstance(error, openai.APIStatusError):
        if error.status_code == 408:
            return ProviderTimeoutError("openrouter returned HTTP 408")
        if error.status_code >= 500:
            return ProviderUnavailableError(f"openrouter returned HTTP {error.status_code}")
        # 400 petición inválida, 401 clave, 402 sin crédito, 403 moderación: reintentar no ayuda.
        return ProviderPermanentError(f"openrouter returned HTTP {error.status_code}")
    return ProviderPermanentError(type(error).__name__)


def _retry_after(headers: Any) -> float | None:
    try:
        return float(headers["retry-after"])
    except (KeyError, TypeError, ValueError):
        return None
