"""Configuración de la aplicación. Todo sale de variables de entorno."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://norte:norte_dev@localhost:5432/norte_legal"
    redis_url: str = "redis://localhost:6379/0"

    # Los proveedores reales se añaden en el hito M3: el tipo se amplía junto con el adaptador.
    llm_provider: Literal["fake"] = "fake"
    embedding_provider: Literal["fake"] = "fake"
    fake_llm_failure_mode: Literal["none", "timeout", "rate_limit", "unavailable"] = "none"

    # Volumen compartido entre la API y el worker.
    blob_dir: Path = Path("/data/blobs")
    # Por debajo del `client_max_body_size` de nginx (26 MiB), para que el error lo dé la API.
    max_upload_bytes: int = 25 * 1024 * 1024

    otel_enabled: bool = True
    otel_exporter_otlp_endpoint: str = "http://localhost:4318"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
