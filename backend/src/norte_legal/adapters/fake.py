"""Proveedores simulados y deterministas, para pruebas y para ejecutar sin claves.

El embedding usa feature hashing, así que la similitud refleja solapamiento léxico: la demo
funciona de forma razonable, pero no mide calidad semántica. Las métricas de recuperación que
se publiquen deben indicar qué proveedor se usó.
"""

import hashlib
import math
import re
import unicodedata
from typing import Literal

from norte_legal.domain.errors import (
    ProviderRateLimitedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from norte_legal.domain.ports import (
    EMBEDDING_DIMENSION,
    DraftAnswer,
    DraftCitation,
    RagPrompt,
)

FailureMode = Literal["none", "timeout", "rate_limit", "unavailable"]

_TOKEN = re.compile(r"\w+", re.UNICODE)
_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")
_MIN_TOKEN_LENGTH = 4
_MIN_OVERLAP = 2


def _tokens(text: str) -> list[str]:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _TOKEN.findall(plain)


def _content_tokens(text: str) -> set[str]:
    return {token for token in _tokens(text) if len(token) >= _MIN_TOKEN_LENGTH}


class FakeEmbeddingProvider:
    @property
    def model(self) -> str:
        return f"fake-hash-{EMBEDDING_DIMENSION}"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    @staticmethod
    def _embed(text: str) -> list[float]:
        vector = [0.0] * EMBEDDING_DIMENSION
        for token in _tokens(text):
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % EMBEDDING_DIMENSION
            vector[index] += 1.0 if digest[4] % 2 == 0 else -1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            # La distancia coseno no está definida para el vector cero.
            vector[0] = 1.0
            return vector
        return [value / norm for value in vector]


class FakeLLMProvider:
    """Extractivo: cita la frase del fragmento con mayor solapamiento léxico con la pregunta."""

    def __init__(self, failure_mode: FailureMode = "none") -> None:
        self._failure_mode = failure_mode

    @property
    def model(self) -> str:
        return "fake-extractive-1"

    def generate_answer(self, prompt: RagPrompt) -> DraftAnswer:
        self._maybe_fail()
        question_tokens = _content_tokens(prompt.question)

        best: tuple[int, str, str] | None = None
        for source in prompt.sources:
            for match in _SENTENCE.finditer(source.text):
                sentence = match.group().strip()
                overlap = len(question_tokens & _content_tokens(sentence))
                if sentence and (best is None or overlap > best[0]):
                    best = (overlap, source.ref, sentence)

        if best is None or best[0] < _MIN_OVERLAP:
            return DraftAnswer(insufficient_context=True)

        _, ref, sentence = best
        return DraftAnswer(
            insufficient_context=False,
            answer=sentence,
            citations=[DraftCitation(ref=ref, quote=sentence)],
        )

    def _maybe_fail(self) -> None:
        match self._failure_mode:
            case "timeout":
                raise ProviderTimeoutError("simulated timeout")
            case "rate_limit":
                raise ProviderRateLimitedError("simulated rate limit", retry_after_s=1.0)
            case "unavailable":
                raise ProviderUnavailableError("simulated outage")
            case "none":
                return
