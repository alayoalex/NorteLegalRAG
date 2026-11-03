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
    embedding_provider: Literal["fake", "voyage"] = "fake"
    fake_llm_failure_mode: Literal["none", "timeout", "rate_limit", "unavailable"] = "none"

    openrouter_api_key: SecretStr | None = None
    llm_model: str = "anthropic/claude-opus-5.5"
    # En Opus 5.5 el razonamiento no se desactiva: solo se elige su profundidad.
    llm_reasoning_effort: Literal["low", "medium", "high"] = "medium"
    # Por intento. El presupuesto total de la consulta está en services/query.py.
    llm_timeout_s: float = 40.0

    voyage_api_key: SecretStr | None = None
    # voyage-4 (multilingüe) frente a voyage-law-2 (legal): se decide con eval/ (M5).
    embedding_model: str = "voyage-4"
    embedding_timeout_s: float = 20.0

    # Por debajo, un fragmento recuperado solo por similitud no llega al LLM. Calibrar con eval/.
    retrieval_min_similarity: float = 0.25

    # Volumen compartido entre la API y el worker.
    blob_dir: Path = Path("/data/blobs")
    # Por debajo del `client_max_body_size` de nginx (26 MiB), para que el error lo dé la API.
    max_upload_bytes: int = 25 * 1024 * 1024

    otel_enabled: bool = True
    otel_exporter_otlp_endpoint: str = "http://localhost:4318"
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _require_keys(self) -> Self:
        """Falla al arrancar, no en la primera petición, si falta la clave del proveedor elegido."""
        if self.llm_provider == "openrouter" and self.openrouter_api_key is None:
            raise ValueError("LLM_PROVIDER=openrouter requires OPENROUTER_API_KEY")
        if self.embedding_provider == "voyage" and self.voyage_api_key is None:
            raise ValueError("EMBEDDING_PROVIDER=voyage requires VOYAGE_API_KEY")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
