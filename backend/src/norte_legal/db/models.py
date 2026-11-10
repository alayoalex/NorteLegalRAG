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
    ForeignKeyConstraint,
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
    # Versiones y fragmentos heredan el tenant de su documento: basta con esta clave foránea.
    tenant_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organizations.id", name="fk_documents_organization")
    )
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
    # Borrado lógico: deja de listarse y de buscarse, pero sus citas siguen resolviéndose.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
    # Tope de `attempt`. El reintento manual lo sube: `attempt` es el token y nunca retrocede.
    attempt_limit: Mapped[int] = mapped_column(Integer, server_default="5")
    # Plazo del estado actual. Vencido en un estado no terminal, el reconciliador reencola.
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


class Organization(Base):
    """El tenant. Su `id` es el `tenant_id` de documentos, versiones y fragmentos."""

    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint("id ~ '^[a-z0-9][a-z0-9_-]{0,63}$'", name="ck_organizations_id_format"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("email = lower(email)", name="ck_users_email_lowercase"),
        UniqueConstraint("email", name="uq_users_email"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(Text)
    password_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Intentos fallidos seguidos. Al llegar al tope se bloquea el inicio de sesión un rato.
    failed_logins: Mapped[int] = mapped_column(Integer, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Membership(Base):
    """Pertenencia de un usuario a una organización. Los miembros comparten sus documentos."""

    __tablename__ = "memberships"
    __table_args__ = (
        CheckConstraint("role IN ('owner', 'member')", name="ck_memberships_role"),
        Index("ix_memberships_organization", "organization_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    organization_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuthSession(Base):
    """Sesión iniciada en una organización. Se guarda el hash del token, nunca el token."""

    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("token_sha256", name="uq_sessions_token_sha256"),
        # Expulsar a un miembro borra sus sesiones en esa organización.
        ForeignKeyConstraint(
            ["user_id", "organization_id"],
            ["memberships.user_id", "memberships.organization_id"],
            name="fk_sessions_membership",
            ondelete="CASCADE",
        ),
        Index("ix_sessions_membership", "user_id", "organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token_sha256: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    organization_id: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
