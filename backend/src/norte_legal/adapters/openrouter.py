"""LLM a través de OpenRouter, con el SDK oficial de `openai` (API compatible). Ver DECISIONS.md §8.

- Salida estructurada con `response_format` `json_schema` estricto. `require_parameters` impide
  que OpenRouter enrute a un proveedor que ignore el esquema; aun así se valida con Pydantic.
- `data_collection: deny` y `zdr`: solo proveedores que no retienen ni entrenan con los datos.
- Se comprueban `finish_reason` y `refusal` antes de leer el contenido.
- `max_retries=0`: los reintentos los decide el servicio de consulta, no el SDK.
"""

from typing import Any

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
from norte_legal.domain.ports import DraftAnswer, RagPrompt
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


class OpenRouterLLMProvider:
    def __init__(
        self,
        api_key: str,
        model: str,
        reasoning_effort: str,
        timeout_s: float,
        client: openai.OpenAI | None = None,
    ) -> None:
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._client = client or openai.OpenAI(
            api_key=api_key, base_url=OPENROUTER_BASE_URL, timeout=timeout_s, max_retries=0
        )

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
                    "provider": {
                        "require_parameters": True,
                        "data_collection": "deny",
                        "zdr": True,
                    },
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
