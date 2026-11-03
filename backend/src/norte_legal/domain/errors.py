"""Taxonomía de errores del dominio.

La distinción clave es `retryable`: decide si la tarea de Celery reintenta con backoff o si el
documento pasa directamente a `failed`. Ningún adaptador deja escapar excepciones de un SDK.
"""


class ProviderError(Exception):
    """Fallo al hablar con un proveedor externo de LLM o embeddings."""

    code = "provider_error"
    retryable = False


class ProviderTimeoutError(ProviderError):
    code = "provider_timeout"
    retryable = True


class ProviderRateLimitedError(ProviderError):
    code = "provider_rate_limited"
    retryable = True

    def __init__(self, message: str = "rate limited", retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class ProviderUnavailableError(ProviderError):
    code = "provider_unavailable"
    retryable = True


class ProviderPermanentError(ProviderError):
    """Credenciales inválidas, petición rechazada, rechazo del modelo: reintentar no ayuda."""

    code = "provider_permanent"
    retryable = False
