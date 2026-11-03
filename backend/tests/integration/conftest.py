"""Infraestructura real con testcontainers: el mismo camino en local y en CI."""

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from norte_legal.config import get_settings
from norte_legal.db.session import get_engine

PGVECTOR_IMAGE = "pgvector/pgvector:0.8.1-pg17"
REDIS_IMAGE = "redis:7.4-alpine"


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    with PostgresContainer(PGVECTOR_IMAGE, driver="psycopg") as container:
        yield container.get_connection_url()


@pytest.fixture(scope="session")
def redis_url() -> Iterator[str]:
    with RedisContainer(REDIS_IMAGE) as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(6379)
        yield f"redis://{host}:{port}/0"


@pytest.fixture(scope="session")
def alembic_config(database_url: str) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["configure_logging"] = False
    return config


@pytest.fixture(scope="session")
def migrated_settings(database_url: str, redis_url: str, alembic_config: Config) -> Iterator[None]:
    """Apunta la aplicación a los contenedores, con el esquema migrado."""
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("REDIS_URL", redis_url)
    monkeypatch.setenv("OTEL_ENABLED", "false")
    get_settings.cache_clear()
    get_engine.cache_clear()
    command.upgrade(alembic_config, "head")
    yield
    monkeypatch.undo()
    get_settings.cache_clear()
    get_engine.cache_clear()
