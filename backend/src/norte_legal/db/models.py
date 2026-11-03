"""Modelos ORM. Reflejan migrations/versions; la prueba de deriva verifica que coincidan."""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from norte_legal.domain.ports import EMBEDDING_DIMENSION


class Base(DeclarativeBase):
    pass


class Document(Base):
    """Identidad lógica: un mismo nombre dentro de un tenant es el mismo documento."""

    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_documents_tenant_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "document_versions.id",
            name="fk_documents_current_version",
            ondelete="SET NULL",
            use_alter=True,
        ),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DocumentVersion(Base):
    """Versión inmutable de un documento y estado de su ingesta."""

    __tablename__ = "document_versions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'processing', 'retrying', 'ready', 'failed')",
            name="ck_document_versions_status",
        ),
        UniqueConstraint("document_id", "version_no", name="uq_versions_document_version_no"),
        UniqueConstraint(
            "document_id",
            "content_sha256",
            "pipeline_fingerprint",
            name="uq_versions_idempotency",
        ),
        Index(
            "ix_versions_reaper",
            "status",
            "lease_expires_at",
            postgresql_where=text("status IN ('queued', 'processing', 'retrying')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(Text)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE")
    )
    version_no: Mapped[int] = mapped_column(Integer)
    content_sha256: Mapped[str] = mapped_column(String(64))
    pipeline_fingerprint: Mapped[str] = mapped_column(Text)
    media_type: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    storage_key: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="queued")
    # Token de exclusión: un worker con un intento antiguo no puede escribir resultados.
    attempt: Mapped[int] = mapped_column(Integer, server_default="0")
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    chunk_count: Mapped[int | None] = mapped_column(Integer)
    trace_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Chunk(Base):
    """Fragmento inmutable. `text == texto_extraído[char_start:char_end]` es un invariante."""

    __tablename__ = "chunks"
    __table_args__ = (
        CheckConstraint("char_end > char_start", name="ck_chunks_char_range"),
        UniqueConstraint("version_id", "ordinal", name="uq_chunks_version_ordinal"),
        Index("ix_chunks_tenant_document", "tenant_id", "document_id"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 128},
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_where=text("is_current"),
        ),
        Index(
            "ix_chunks_text_tsv_gin",
            "text_tsv",
            postgresql_using="gin",
            postgresql_where=text("is_current"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(Text)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE")
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="CASCADE")
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSION))
    embedding_model: Mapped[str] = mapped_column(Text)
    is_current: Mapped[bool] = mapped_column(Boolean, server_default=false())
    text_tsv: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple', text)", persisted=True)
    )
