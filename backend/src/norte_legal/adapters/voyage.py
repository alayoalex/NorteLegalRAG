"""Embeddings de Voyage AI por su API REST.

No se usa el SDK `voyageai`: su versión 0.5 arrastra unas 35 dependencias (langchain-core,
huggingface-hub, tokenizers, numpy, aiohttp...) para una sola llamada HTTP. Ver DECISIONS.md.
Sin reintentos aquí: los decide quien llama (Celery en el worker, el servicio en la API).
"""

from typing import Literal

import httpx2
from pydantic import BaseModel, ValidationError

from norte_legal.domain.errors import (
    ProviderPermanentError,
    ProviderRateLimitedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from norte_legal.domain.ports import EMBEDDING_DIMENSION

VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"


class _Embedding(BaseModel):
    index: int
    embedding: list[float]


class _EmbeddingResponse(BaseModel):
    data: list[_Embedding]


class VoyageEmbeddingProvider:
    def __init__(
        self, api_key: str, model: str, timeout_s: float, client: httpx2.Client | None = None
    ) -> None:
        self._model = model
        self._client = client or httpx2.Client(timeout=timeout_s)
        self._headers = {"Authorization": f"Bearer {api_key}"}

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
        payload = {
            "input": texts,
            "model": self._model,
            "input_type": input_type,
            "output_dimension": EMBEDDING_DIMENSION,
            # Un fragmento demasiado largo es un fallo del fragmentador: no se recorta en silencio.
            "truncation": False,
        }
        try:
            response = self._client.post(VOYAGE_URL, json=payload, headers=self._headers)
        except httpx2.TimeoutException as error:
            raise ProviderTimeoutError("voyage request timed out") from error
        except httpx2.TransportError as error:
            raise ProviderUnavailableError("voyage connection failed") from error

        _raise_for_status(response)
        try:
            body = _EmbeddingResponse.model_validate_json(response.content)
        except ValidationError as error:
            raise ProviderPermanentError("voyage returned an unexpected body") from error
        # La API devuelve `index`: no se asume que el orden de la respuesta sea el de la entrada.
        return [item.embedding for item in sorted(body.data, key=lambda item: item.index)]


def _raise_for_status(response: httpx2.Response) -> None:
    status = response.status_code
    if status < 400:
        return
    message = f"voyage returned HTTP {status}"
    if status == 429:
        raise ProviderRateLimitedError(message, retry_after_s=_retry_after(response))
    if status in (408, 504):
        raise ProviderTimeoutError(message)
    if status >= 500:
        raise ProviderUnavailableError(message)
    raise ProviderPermanentError(message)


def _retry_after(response: httpx2.Response) -> float | None:
    try:
        return float(response.headers["retry-after"])
    except (KeyError, ValueError):
        return None
