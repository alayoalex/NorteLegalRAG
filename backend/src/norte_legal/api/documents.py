"""Rutas de documentos: subida, estado, reintento, borrado y resolución de fragmentos."""

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Query, Response, UploadFile, status

from norte_legal.adapters.factory import get_embedding_provider
from norte_legal.api.dependencies import BlobStore, DbSession, TenantId
from norte_legal.api.problems import ProblemError
from norte_legal.api.schemas import (
    ChunkOut,
    DocumentDetailOut,
    DocumentListOut,
    DocumentOut,
    UploadOut,
    VersionOut,
)
from norte_legal.config import get_settings
from norte_legal.db.repository import DocumentRepository
from norte_legal.observability.telemetry import current_trace_id
from norte_legal.services import ingestion
from norte_legal.worker.tasks import enqueue_ingestion

router = APIRouter(prefix="/api/v1", tags=["documents"])


@router.post(
    "/documents",
    response_model=UploadOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={200: {"description": "Mismo contenido ya subido: versión existente"}},
)
def upload_document(
    response: Response,
    tenant_id: TenantId,
    session: DbSession,
    blobs: BlobStore,
    file: Annotated[UploadFile, File()],
) -> UploadOut:
    """Acepta el archivo y encola su ingesta. El resultado se consulta con `GET /documents`."""
    settings = get_settings()
    content = file.file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise ProblemError(
            status.HTTP_413_CONTENT_TOO_LARGE,
            "file_too_large",
            "File too large",
            f"maximum size is {settings.max_upload_bytes} bytes",
        )
    result = ingestion.register_upload(
        session,
        tenant_id=tenant_id,
        file_name=file.filename,
        content=content,
        blobs=blobs,
        embedding_model=get_embedding_provider().model,
        trace_id=current_trace_id(),
    )
    version = result.version
    enqueued = result.created and enqueue_ingestion(version.id)
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return UploadOut(
        document_id=version.document_id,
        version=VersionOut.build(version, result.current_version_id),
        created=result.created,
        enqueued=enqueued,
    )


@router.get("/documents", response_model=DocumentListOut)
def list_documents(
    tenant_id: TenantId,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> DocumentListOut:
    views = DocumentRepository(session, tenant_id).list_documents(limit)
    return DocumentListOut(items=[DocumentOut.build(view) for view in views])


@router.get("/documents/{document_id}", response_model=DocumentDetailOut)
def get_document(
    document_id: uuid.UUID, tenant_id: TenantId, session: DbSession
) -> DocumentDetailOut:
    try:
        view, versions = DocumentRepository(session, tenant_id).get_document(document_id)
    except LookupError as error:
        raise _document_not_found() from error
    current_id = view.document.current_version_id
    return DocumentDetailOut(
        **DocumentOut.build(view).model_dump(),
        versions=[VersionOut.build(version, current_id) for version in versions],
    )


@router.post(
    "/documents/{document_id}/retry",
    response_model=VersionOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_document(document_id: uuid.UUID, tenant_id: TenantId, session: DbSession) -> VersionOut:
    """Vuelve a encolar la última versión si está en `failed`."""
    try:
        version = ingestion.retry_failed(session, tenant_id=tenant_id, document_id=document_id)
    except LookupError as error:
        raise _document_not_found() from error
    except ValueError as error:
        raise ProblemError(
            status.HTTP_409_CONFLICT,
            "not_retryable",
            "Nothing to retry",
            "the latest version is not in failed state",
        ) from error
    enqueue_ingestion(version.id)
    return VersionOut.build(version, current_version_id=None)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: uuid.UUID, tenant_id: TenantId, session: DbSession) -> None:
    """Borrado lógico: el documento deja de listarse y de buscarse, pero sus citas siguen
    resolviéndose con `GET /chunks/{id}` (`document_deleted: true`)."""
    try:
        ingestion.delete_document(session, tenant_id=tenant_id, document_id=document_id)
    except LookupError as error:
        raise _document_not_found() from error
    except ValueError as error:
        raise ProblemError(
            status.HTTP_409_CONFLICT,
            "document_processing",
            "Document is being processed",
            "wait until processing finishes before deleting",
        ) from error


@router.get("/chunks/{chunk_id}", response_model=ChunkOut)
def get_chunk(chunk_id: uuid.UUID, tenant_id: TenantId, session: DbSession) -> ChunkOut:
    """Resuelve una cita, también si su versión ya no es la vigente (`is_current = false`)."""
    view = DocumentRepository(session, tenant_id).get_chunk(chunk_id)
    if view is None:
        raise ProblemError(status.HTTP_404_NOT_FOUND, "chunk_not_found", "Chunk not found")
    return ChunkOut.build(view)


def _document_not_found() -> ProblemError:
    return ProblemError(status.HTTP_404_NOT_FOUND, "document_not_found", "Document not found")
