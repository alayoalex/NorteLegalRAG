"""Esquema inicial: documentos, versiones inmutables y fragmentos con embeddings.

El índice HNSW y el GIN son parciales (`WHERE is_current`): las versiones antiguas se conservan
para resolver citas ya mostradas, pero no ocupan el índice ni contaminan la recuperación.
Parámetros del índice justificados en DECISIONS.md.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "name", name="uq_documents_tenant_name"),
    )

    op.create_table(
        "document_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("pipeline_fingerprint", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="queued", nullable=False),
        sa.Column("attempt", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=True),
        sa.Column("trace_id", sa.String(32), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'retrying', 'ready', 'failed')",
            name="ck_document_versions_status",
        ),
        sa.UniqueConstraint("document_id", "version_no", name="uq_versions_document_version_no"),
        sa.UniqueConstraint(
            "document_id",
            "content_sha256",
            "pipeline_fingerprint",
            name="uq_versions_idempotency",
        ),
    )
    op.create_index(
        "ix_versions_reaper",
        "document_versions",
        ["status", "lease_expires_at"],
        postgresql_where=sa.text("status IN ('queued', 'processing', 'retrying')"),
    )

    # La FK circular se añade después de crear ambas tablas.
    op.create_foreign_key(
        "fk_documents_current_version",
        "documents",
        "document_versions",
        ["current_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("section", sa.Text(), nullable=True),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.Column("embedding_model", sa.Text(), nullable=False),
        sa.Column("is_current", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "text_tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', text)", persisted=True),
            nullable=False,
        ),
        sa.CheckConstraint("char_end > char_start", name="ck_chunks_char_range"),
        sa.UniqueConstraint("version_id", "ordinal", name="uq_chunks_version_ordinal"),
    )
    op.create_index("ix_chunks_tenant_document", "chunks", ["tenant_id", "document_id"])
    op.execute(
        """
        CREATE INDEX ix_chunks_embedding_hnsw ON chunks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 128)
        WHERE is_current
        """
    )
    op.execute(
        "CREATE INDEX ix_chunks_text_tsv_gin ON chunks USING gin (text_tsv) WHERE is_current"
    )


def downgrade() -> None:
    op.drop_table("chunks")
    op.drop_constraint("fk_documents_current_version", "documents", type_="foreignkey")
    op.drop_table("document_versions")
    op.drop_table("documents")
    op.execute("DROP EXTENSION IF EXISTS vector")
