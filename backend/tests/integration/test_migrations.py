import uuid

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

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


def test_existing_tenants_become_organizations(database_url: str, alembic_config: Config) -> None:
    command.downgrade(alembic_config, "0003")
    engine = create_engine(database_url)
    tenant = f"legacy-{uuid.uuid4().hex[:8]}"
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO documents (id, tenant_id, name) VALUES (:id, :tenant, 'a.txt')"),
            {"id": uuid.uuid4(), "tenant": tenant},
        )
    command.upgrade(alembic_config, "head")
    with engine.connect() as connection:
        name = connection.execute(
            text("SELECT name FROM organizations WHERE id = :tenant"), {"tenant": tenant}
        ).scalar_one()
    assert name == tenant


def test_removing_a_member_ends_their_sessions(database_url: str, alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")
    organization, user = f"org-{uuid.uuid4().hex[:8]}", uuid.uuid4()
    with create_engine(database_url).begin() as connection:
        connection.execute(
            text("INSERT INTO organizations (id, name) VALUES (:org, 'Org')"), {"org": organization}
        )
        connection.execute(
            text("INSERT INTO users (id, email, password_hash) VALUES (:id, :email, 'x')"),
            {"id": user, "email": f"{user.hex}@example.com"},
        )
        connection.execute(
            text(
                "INSERT INTO memberships (user_id, organization_id, role)"
                " VALUES (:user, :org, 'member')"
            ),
            {"user": user, "org": organization},
        )
        connection.execute(
            text(
                "INSERT INTO sessions (id, token_sha256, user_id, organization_id, expires_at)"
                " VALUES (:id, :token, :user, :org, now() + interval '1 hour')"
            ),
            {"id": uuid.uuid4(), "token": "0" * 64, "user": user, "org": organization},
        )
        connection.execute(text("DELETE FROM memberships WHERE user_id = :user"), {"user": user})
        remaining = connection.execute(
            text("SELECT count(*) FROM sessions WHERE user_id = :user"), {"user": user}
        ).scalar_one()
    assert remaining == 0


def test_emails_are_unique_regardless_of_case(database_url: str, alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")
    with create_engine(database_url).connect() as connection, pytest.raises(IntegrityError):
        connection.execute(
            text(
                "INSERT INTO users (id, email, password_hash) VALUES (:id, 'Ana@Example.com', 'x')"
            ),
            {"id": uuid.uuid4()},
        )
