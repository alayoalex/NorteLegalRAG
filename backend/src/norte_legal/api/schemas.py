"""Esquemas de entrada y salida de la API."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from norte_legal.db.models import DocumentVersion
from norte_legal.db.repository import ChunkView, DocumentView
from norte_legal.db.retrieval import RetrievedChunk
from norte_legal.services.query import QueryResult

VersionStatus = Literal["queued", "processing", "retrying", "ready", "failed"]


class VersionOut(BaseModel):
    id: uuid.UUID
    version_no: int
    status: VersionStatus
    is_current: bool
    media_type: str
    size_bytes: int
    attempt: int
    error_code: str | None
    error_message: str | None
    chunk_count: int | None
    created_at: datetime
    finished_at: datetime | None

    @classmethod
    def build(cls, version: DocumentVersion, current_version_id: uuid.UUID | None) -> "VersionOut":
        return cls(
            id=version.id,
            version_no=version.version_no,
            status=version.status,
            is_current=version.id == current_version_id,
            media_type=version.media_type,
            size_bytes=version.size_bytes,
            attempt=version.attempt,
            error_code=version.error_code,
            error_message=version.error_message,
            chunk_count=version.chunk_count,
            created_at=version.created_at,
            finished_at=version.finished_at,
        )


class DocumentOut(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    # La última subida, que es la que interesa seguir mientras se procesa.
    latest_version: VersionOut
    # La que usan las consultas. Puede ser anterior a `latest_version` o no existir todavía.
    current_version: VersionOut | None

    @classmethod
    def build(cls, view: DocumentView) -> "DocumentOut":
        current_id = view.document.current_version_id
        return cls(
            id=view.document.id,
            name=view.document.name,
            created_at=view.document.created_at,
            latest_version=VersionOut.build(view.latest, current_id),
            current_version=VersionOut.build(view.current, current_id) if view.current else None,
        )


class DocumentDetailOut(DocumentOut):
    versions: list[VersionOut]


class DocumentListOut(BaseModel):
    items: list[DocumentOut]


class UploadOut(BaseModel):
    document_id: uuid.UUID
    version: VersionOut
    # `false` cuando el mismo contenido ya estaba subido: se devuelve la versión existente.
    created: bool
    enqueued: bool


class ChunkOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    version_id: uuid.UUID
    version_no: int
    is_current: bool
    # El documento se borró después de citarse: la cita se resuelve, pero ya no se consulta.
    document_deleted: bool
    ordinal: int
    text: str
    char_start: int
    char_end: int
    page_start: int | None
    page_end: int | None
    section: str | None

    @classmethod
    def build(cls, view: ChunkView) -> "ChunkOut":
        chunk, document = view.chunk, view.document
        return cls(
            id=chunk.id,
            document_id=document.id,
            document_name=document.name,
            version_id=view.version.id,
            version_no=view.version.version_no,
            is_current=chunk.is_current,
            document_deleted=document.deleted_at is not None,
            ordinal=chunk.ordinal,
            text=chunk.text,
            char_start=chunk.char_start,
            char_end=chunk.char_end,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            section=chunk.section,
        )


class QueryIn(BaseModel):
    question: str = Field(min_length=3, max_length=2_000)


class SourceOut(BaseModel):
    """Fragmento recuperado. En `degraded` es lo único que se muestra."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    version_id: uuid.UUID
    version_no: int
    is_current: bool
    section: str | None
    page_start: int | None
    page_end: int | None
    char_start: int
    char_end: int
    text: str

    @classmethod
    def build(cls, source: RetrievedChunk) -> "SourceOut":
        return cls(
            chunk_id=source.chunk_id,
            document_id=source.document_id,
            document_name=source.document_name,
            version_id=source.version_id,
            version_no=source.version_no,
            is_current=source.is_current,
            section=source.section,
            page_start=source.page_start,
            page_end=source.page_end,
            char_start=source.char_start,
            char_end=source.char_end,
            text=source.text,
        )


class CitationOut(BaseModel):
    """Todo sale de la base de datos salvo `ref`, y `quote` está verificada contra el fragmento."""

    ref: str
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    version_id: uuid.UUID
    version_no: int
    is_current: bool
    section: str | None
    page_start: int | None
    page_end: int | None
    quote: str
    # Posición de la cita en el texto extraído del documento.
    char_start: int
    char_end: int


class QueryOut(BaseModel):
    status: Literal["answered", "no_context", "degraded"]
    reason: str | None
    retrieval_mode: Literal["hybrid", "lexical"]
    answer: str | None
    citations: list[CitationOut]
    sources: list[SourceOut]
    correlation_id: str | None

    @classmethod
    def build(cls, result: QueryResult, correlation_id: str | None) -> "QueryOut":
        return cls(
            status=result.status,
            reason=result.reason,
            retrieval_mode=result.retrieval_mode,
            answer=result.answer,
            citations=[
                CitationOut(
                    ref=citation.ref,
                    chunk_id=citation.source.chunk_id,
                    document_id=citation.source.document_id,
                    document_name=citation.source.document_name,
                    version_id=citation.source.version_id,
                    version_no=citation.source.version_no,
                    is_current=citation.source.is_current,
                    section=citation.section,
                    page_start=citation.source.page_start,
                    page_end=citation.source.page_end,
                    quote=citation.quote,
                    char_start=citation.char_start,
                    char_end=citation.char_end,
                )
                for citation in result.citations
            ],
            sources=[SourceOut.build(source) for source in result.sources],
            correlation_id=correlation_id,
        )
