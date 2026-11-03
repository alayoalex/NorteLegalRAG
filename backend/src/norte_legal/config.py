"""Configuración de la aplicación. Todo sale de variables de entorno."""

from functools import lru_cache
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

    otel_enabled: bool = True
    otel_exporter_otlp_endpoint: str = "http://localhost:4318"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
