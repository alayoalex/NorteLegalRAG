"""Esquemas de entrada y salida de la API."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from norte_legal.db.models import DocumentVersion
from norte_legal.db.repository import ChunkView, DocumentView

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
            ordinal=chunk.ordinal,
            text=chunk.text,
            char_start=chunk.char_start,
            char_end=chunk.char_end,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            section=chunk.section,
        )
