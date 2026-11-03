import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text

from norte_legal.db.models import Base

pytestmark = pytest.mark.integration


def test_migrations_match_the_orm_and_are_reversible(
    database_url: str, alembic_config: Config
) -> None:
    command.upgrade(alembic_config, "head")
    engine = create_engine(database_url)
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == []

    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")


def test_vector_index_is_partial_hnsw_with_cosine_distance(
    database_url: str, alembic_config: Config
) -> None:
    command.upgrade(alembic_config, "head")
    with create_engine(database_url).connect() as connection:
        definition = connection.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_chunks_embedding_hnsw'")
        ).scalar_one()
    assert "USING hnsw" in definition
    assert "vector_cosine_ops" in definition
    assert "WHERE is_current" in definition
