"""Configuración de la aplicación. Todo sale de variables de entorno."""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://norte:norte_dev@localhost:5432/norte_legal"
    redis_url: str = "redis://localhost:6379/0"

    # Sin claves, todo funciona con los proveedores simulados.
    llm_provider: Literal["fake", "openrouter"] = "fake"
    embedding_provider: Literal["fake", "openrouter"] = "fake"
    fake_llm_failure_mode: Literal["none", "timeout", "rate_limit", "unavailable"] = "none"

    # Una sola clave para el LLM y los embeddings.
    openrouter_api_key: SecretStr | None = None
    # zdr | deny | allow. `allow` es necesario para los modelos gratuitos (entrenan con los datos):
    # solo con documentos públicos, como los de eval/. Ver DECISIONS.md.
    openrouter_data_policy: Literal["zdr", "deny", "allow"] = "zdr"
    llm_model: str = "anthropic/claude-opus-5.5"
    # En Opus 5.5 el razonamiento no se desactiva: solo se elige su profundidad.
    llm_reasoning_effort: Literal["low", "medium", "high"] = "medium"
    # Por intento. El presupuesto total de la consulta está en services/query.py.
    llm_timeout_s: float = 40.0

    # Identificador de OpenRouter. Debe admitir 1024 dimensiones. Elegido con eval/ (DECISIONS.md).
    embedding_model: str = "baai/bge-m3"
    embedding_timeout_s: float = 20.0

    # Por debajo, un fragmento recuperado solo por similitud no llega al LLM. Calibrar con eval/.
    retrieval_min_similarity: float = 0.25

    # Volumen compartido entre la API y el worker.
    blob_dir: Path = Path("/data/blobs")
    # Por debajo del `client_max_body_size` de nginx (26 MiB), para que el error lo dé la API.
    max_upload_bytes: int = 25 * 1024 * 1024

    # Duración fija: no se renueva con el uso. Al caducar, se vuelve a iniciar sesión.
    session_ttl_hours: int = 12
    # Solo `false` en desarrollo sobre HTTP. En producción Caddy termina TLS.
    session_cookie_secure: bool = True

    otel_enabled: bool = True
    otel_exporter_otlp_endpoint: str = "http://localhost:4318"
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _require_keys(self) -> Self:
        """Falla al arrancar, no en la primera petición, si falta la clave del proveedor elegido."""
        uses_openrouter = "openrouter" in (self.llm_provider, self.embedding_provider)
        if uses_openrouter and self.openrouter_api_key is None:
            raise ValueError("an openrouter provider requires OPENROUTER_API_KEY")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
