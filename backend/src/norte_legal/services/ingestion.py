"""Servicio de ingesta: registro de subidas, procesamiento de una versión y reconciliación.

Reglas (CLAUDE.md, invariantes 1-3):

- PostgreSQL decide qué está pendiente. Todo estado no terminal tiene un plazo en
  `lease_expires_at`. Si vence, el reconciliador vuelve a encolar.
- El worker toma una versión con un `UPDATE` condicional que incrementa `attempt`. Cada escritura
  posterior exige `attempt` y `status = 'processing'`: un worker que perdió el lease no escribe.
- Ninguna transacción queda abierta mientras se llama al proveedor de embeddings.
- Los fragmentos y el cambio de versión vigente se escriben en una sola transacción.
"""

import hashlib
import random
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import batched
from typing import Literal

import structlog
from opentelemetry import metrics, trace
from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import Session

from norte_legal.adapters.blob_store import LocalBlobStore
from norte_legal.db.models import Chunk, Document, DocumentVersion
from norte_legal.db.repository import DocumentRepository
from norte_legal.db.session import new_session
from norte_legal.domain.chunking import TextChunk, chunk_text, pipeline_fingerprint
from norte_legal.domain.errors import (
    InvalidDocumentError,
    ProviderError,
    ProviderPermanentError,
    ProviderRateLimitedError,
)
from norte_legal.domain.extraction import EXTRACTOR_VERSION, extract_text
from norte_legal.domain.files import detect_media_type, sanitize_name
from norte_legal.domain.ports import EMBEDDING_DIMENSION, EmbeddingProvider

logger = structlog.get_logger(__name__)
_meter = metrics.get_meter("norte_legal.ingestion")
_duration = _meter.create_histogram(
    "ingestion.duration", unit="s", description="Duración de un intento de ingesta, por resultado"
)
_chunks = _meter.create_histogram("ingestion.chunks", description="Fragmentos por versión lista")
# Lo actualiza el reconciliador en cada pasada: la cola real está en PostgreSQL, no en Redis.
_backlog = _meter.create_gauge(
    "ingestion.backlog", description="Versiones pendientes, por estado (todos los tenants)"
)

MAX_ATTEMPTS = 5
# Se renueva tras extraer y tras cada lote de embeddings: solo vence si el worker muere o se cuelga.
LEASE = timedelta(minutes=5)
# Plazo para que un worker tome una versión encolada antes de que el reconciliador la reencole.
QUEUED_GRACE = timedelta(minutes=10)
EMBEDDING_BATCH_SIZE = 64
BACKOFF_BASE_S = 5.0
BACKOFF_CAP_S = 300.0
RECONCILE_BATCH_SIZE = 100
_PENDING = ("queued", "processing", "retrying")

Outcome = Literal["ready", "failed", "retrying", "skipped", "lease_lost"]


class LeaseLostError(Exception):
    """Otro intento tomó la versión. Este worker abandona sin escribir."""


@dataclass(frozen=True)
class UploadResult:
    version: DocumentVersion
    created: bool
    current_version_id: uuid.UUID | None = None


@dataclass(frozen=True)
class Claim:
    version_id: uuid.UUID
    tenant_id: str
    document_id: uuid.UUID
    attempt: int
    attempt_limit: int
    storage_key: str
    media_type: str


@dataclass(frozen=True)
class ProcessResult:
    outcome: Outcome
    retry_in_s: float | None = None


def register_upload(
    session: Session,
    *,
    tenant_id: str,
    file_name: str | None,
    content: bytes,
    blobs: LocalBlobStore,
    embedding_model: str,
    trace_id: str | None,
) -> UploadResult:
    """Valida, guarda los bytes y crea la versión. Idempotente por contenido y pipeline.

    Los bytes se guardan antes de la transacción: si esta falla, queda un blob huérfano e
    inofensivo (la clave es su hash), nunca una fila que apunte a bytes inexistentes.
    """
    name = sanitize_name(file_name)
    media_type = detect_media_type(content)
    sha256 = hashlib.sha256(content).hexdigest()
    fingerprint = pipeline_fingerprint(EXTRACTOR_VERSION, embedding_model)
    storage_key = blobs.put(sha256, content)

    with session.begin():
        repository = DocumentRepository(session, tenant_id)
        document_id = repository.lock_or_create_document(name)
        existing = repository.find_version(document_id, sha256, fingerprint)
        if existing is not None:
            current_version_id = repository.current_version_id(document_id)
            # Una versión lista sin vigente solo ocurre si el documento se borró: se restaura.
            if current_version_id is None and existing.status == "ready":
                repository.make_current(document_id, existing.id)
                current_version_id = existing.id
            return UploadResult(existing, created=False, current_version_id=current_version_id)
        version = repository.add_version(
            document_id=document_id,
            content_sha256=sha256,
            fingerprint=fingerprint,
            media_type=media_type,
            size_bytes=len(content),
            storage_key=storage_key,
            trace_id=trace_id,
            deadline=_now() + QUEUED_GRACE,
            attempt_limit=MAX_ATTEMPTS,
        )
    logger.info(
        "upload_registered",
        version_id=str(version.id),
        version_no=version.version_no,
        media_type=media_type,
        size_bytes=len(content),
    )
    return UploadResult(version, created=True)


def retry_failed(session: Session, *, tenant_id: str, document_id: uuid.UUID) -> DocumentVersion:
    """Reintento manual. Lanza `LookupError` si el documento no existe y `ValueError` si su
    última versión no está en `failed`."""
    with session.begin():
        repository = DocumentRepository(session, tenant_id)
        repository.get_document(document_id, lock=True)
        version = repository.requeue_failed(document_id, _now() + QUEUED_GRACE, MAX_ATTEMPTS)
    if version is None:
        raise ValueError(document_id)
    logger.info("retry_requested", version_id=str(version.id), attempt=version.attempt)
    return version


def delete_document(session: Session, *, tenant_id: str, document_id: uuid.UUID) -> None:
    """Borrado lógico. Lanza `LookupError` si no existe y `ValueError` si una versión se está
    procesando: así ningún worker puede hacer vigente una versión de un documento borrado.

    La fila del documento queda bloqueada: una subida o un reintento simultáneos esperan.
    """
    with session.begin():
        repository = DocumentRepository(session, tenant_id)
        view, _ = repository.get_document(document_id, lock=True)
        if repository.has_pending_versions(document_id, _PENDING):
            raise ValueError(document_id)
        repository.soft_delete(view.document, _now())
    logger.info("document_deleted", document_id=str(document_id))


def process_version(
    version_id: uuid.UUID,
    *,
    blobs: LocalBlobStore,
    embedder: EmbeddingProvider,
    session_factory: Callable[[], Session] = new_session,
) -> ProcessResult:
    started = time.perf_counter()
    with session_factory() as session, session.begin():
        claim = _claim(session, version_id)
    if claim is None:
        # Entrega duplicada, versión ya terminada o sin intentos: no hay nada que hacer.
        logger.info("ingest_claim_skipped", version_id=str(version_id))
        return ProcessResult("skipped")

    log = logger.bind(version_id=str(version_id), attempt=claim.attempt)
    span = trace.get_current_span()
    span.set_attribute("ingestion.version_id", str(version_id))
    span.set_attribute("ingestion.attempt", claim.attempt)
    log.info("ingest_started", media_type=claim.media_type)

    result = _run(claim, blobs, embedder, session_factory, log)
    elapsed = time.perf_counter() - started
    _duration.record(elapsed, {"status": result.outcome})
    span.set_attribute("ingestion.outcome", result.outcome)
    log.info("ingest_finished", outcome=result.outcome, duration_s=round(elapsed, 3))
    return result


def _run(
    claim: Claim,
    blobs: LocalBlobStore,
    embedder: EmbeddingProvider,
    session_factory: Callable[[], Session],
    log: structlog.stdlib.BoundLogger,
) -> ProcessResult:
    try:
        extracted = extract_text(blobs.get(claim.storage_key), claim.media_type)
        chunks = chunk_text(extracted.text, extracted.page_starts)
        log.info("text_extracted", chars=len(extracted.text), chunk_count=len(chunks))
        _renew_lease(session_factory, claim)

        embeddings: list[list[float]] = []
        for batch in batched(chunks, EMBEDDING_BATCH_SIZE):
            embeddings.extend(embedder.embed_documents([chunk.text for chunk in batch]))
            _renew_lease(session_factory, claim)
        _check_embeddings(embeddings, len(chunks))

        with session_factory() as session, session.begin():
            _complete(session, claim, chunks, embeddings, embedder.model)
        _chunks.record(len(chunks))
        return ProcessResult("ready")
    except LeaseLostError:
        log.warning("ingest_lease_lost")
        return ProcessResult("lease_lost")
    except FileNotFoundError:
        return _fail(session_factory, claim, "blob_missing", "stored file not found", log)
    except InvalidDocumentError as error:
        return _fail(session_factory, claim, error.code, error.message, log)
    except ProviderError as error:
        if not error.retryable or claim.attempt >= claim.attempt_limit:
            return _fail(session_factory, claim, error.code, str(error), log)
        retry_after = error.retry_after_s if isinstance(error, ProviderRateLimitedError) else None
        delay = backoff_delay(claim.attempt, retry_after)
        with session_factory() as session, session.begin():
            _write_state(
                session,
                claim,
                status="retrying",
                error_code=error.code,
                error_message=str(error),
                # Si el mensaje de reintento se pierde, el reconciliador lo detecta al vencer.
                lease_expires_at=_now() + timedelta(seconds=delay) + QUEUED_GRACE,
            )
        log.warning("ingest_retry_scheduled", error_code=error.code, retry_in_s=round(delay, 1))
        return ProcessResult("retrying", retry_in_s=delay)


def backoff_delay(attempt: int, retry_after_s: float | None = None) -> float:
    """Exponencial con *equal jitter*: nunca menos de la mitad del escalón ni de `Retry-After`."""
    step = min(BACKOFF_CAP_S, BACKOFF_BASE_S * 2.0 ** max(attempt - 1, 0))
    # No es criptografía: solo dispersa los reintentos de varios workers.
    delay = step / 2 + random.uniform(0, step / 2)  # noqa: S311
    return max(delay, retry_after_s or 0.0)


def reconcile(session: Session) -> list[uuid.UUID]:
    """Recupera versiones cuyo plazo venció. Devuelve las que hay que volver a publicar.

    Atiende a todos los tenants: es un proceso de sistema que solo toca el estado de ingesta.
    `SKIP LOCKED` permite ejecutarlo en paralelo sin que dos instancias tomen la misma fila.
    """
    now = _now()
    expired = (
        select(DocumentVersion.id)
        .where(DocumentVersion.status.in_(_PENDING), DocumentVersion.lease_expires_at < now)
        .order_by(DocumentVersion.lease_expires_at)
        .limit(RECONCILE_BATCH_SIZE)
        .with_for_update(skip_locked=True)
    )
    with session.begin():
        exhausted = session.scalars(
            update(DocumentVersion)
            .where(
                DocumentVersion.id.in_(expired),
                DocumentVersion.attempt >= DocumentVersion.attempt_limit,
            )
            .values(
                status="failed",
                error_code="attempts_exhausted",
                error_message="no attempts left",
                lease_expires_at=None,
                finished_at=func.now(),
            )
            .returning(DocumentVersion.id)
        ).all()
        # Volver a `queued` también invalida al worker que tenía el lease: sus escrituras
        # exigen `status = 'processing'`.
        requeued = session.scalars(
            update(DocumentVersion)
            .where(DocumentVersion.id.in_(expired))
            .values(status="queued", lease_expires_at=now + QUEUED_GRACE)
            .returning(DocumentVersion.id)
        ).all()
        rows = session.execute(
            select(DocumentVersion.status, func.count())
            .where(DocumentVersion.status.in_(_PENDING))
            .group_by(DocumentVersion.status)
        ).all()
        counts = {status: count for status, count in rows}
    for status in _PENDING:
        _backlog.set(counts.get(status, 0), {"status": status})
    if exhausted or requeued:
        logger.info("reconcile_finished", requeued=len(requeued), exhausted=len(exhausted))
    return list(requeued)


def _claim(session: Session, version_id: uuid.UUID) -> Claim | None:
    row = session.execute(
        update(DocumentVersion)
        .where(
            DocumentVersion.id == version_id,
            DocumentVersion.status.in_(("queued", "retrying")),
            DocumentVersion.attempt < DocumentVersion.attempt_limit,
        )
        .values(
            status="processing",
            attempt=DocumentVersion.attempt + 1,
            lease_expires_at=func.now() + LEASE,
        )
        .returning(
            DocumentVersion.tenant_id,
            DocumentVersion.document_id,
            DocumentVersion.attempt,
            DocumentVersion.attempt_limit,
            DocumentVersion.storage_key,
            DocumentVersion.media_type,
        )
    ).one_or_none()
    if row is None:
        return None
    return Claim(
        version_id=version_id,
        tenant_id=row.tenant_id,
        document_id=row.document_id,
        attempt=row.attempt,
        attempt_limit=row.attempt_limit,
        storage_key=row.storage_key,
        media_type=row.media_type,
    )


def _write_state(session: Session, claim: Claim, **values: object) -> None:
    """Escritura protegida por el token: sin el `attempt` vigente no se escribe nada."""
    updated = session.execute(
        update(DocumentVersion)
        .where(
            DocumentVersion.id == claim.version_id,
            DocumentVersion.tenant_id == claim.tenant_id,
            DocumentVersion.attempt == claim.attempt,
            DocumentVersion.status == "processing",
        )
        .values(**values)
        .returning(DocumentVersion.id)
    ).one_or_none()
    if updated is None:
        raise LeaseLostError


def _renew_lease(session_factory: Callable[[], Session], claim: Claim) -> None:
    with session_factory() as session, session.begin():
        _write_state(session, claim, lease_expires_at=func.now() + LEASE)


def _fail(
    session_factory: Callable[[], Session],
    claim: Claim,
    code: str,
    message: str,
    log: structlog.stdlib.BoundLogger,
) -> ProcessResult:
    try:
        with session_factory() as session, session.begin():
            _write_state(
                session,
                claim,
                status="failed",
                error_code=code,
                error_message=message,
                lease_expires_at=None,
                finished_at=func.now(),
            )
    except LeaseLostError:
        log.warning("ingest_lease_lost")
        return ProcessResult("lease_lost")
    log.warning("ingest_failed", error_code=code)
    return ProcessResult("failed")


def _check_embeddings(embeddings: list[list[float]], expected: int) -> None:
    if len(embeddings) != expected or any(len(v) != EMBEDDING_DIMENSION for v in embeddings):
        raise ProviderPermanentError("provider returned unexpected vectors")


def _complete(
    session: Session,
    claim: Claim,
    chunks: list[TextChunk],
    embeddings: list[list[float]],
    embedding_model: str,
) -> None:
    version = session.scalars(
        select(DocumentVersion)
        .where(
            DocumentVersion.id == claim.version_id,
            DocumentVersion.tenant_id == claim.tenant_id,
            DocumentVersion.attempt == claim.attempt,
            DocumentVersion.status == "processing",
        )
        .with_for_update()
    ).one_or_none()
    if version is None:
        raise LeaseLostError
    document = session.scalars(
        select(Document)
        .where(Document.id == claim.document_id, Document.tenant_id == claim.tenant_id)
        .with_for_update()
    ).one()

    # Si una versión anterior termina después que una posterior, no le quita la vigencia.
    current_no = None
    if document.current_version_id is not None:
        current_no = session.scalar(
            select(DocumentVersion.version_no).where(
                DocumentVersion.id == document.current_version_id
            )
        )
    becomes_current = current_no is None or version.version_no > current_no

    if becomes_current and document.current_version_id is not None:
        session.execute(
            update(Chunk)
            .where(
                Chunk.tenant_id == claim.tenant_id,
                Chunk.version_id == document.current_version_id,
            )
            .values(is_current=False)
        )
    session.execute(
        insert(Chunk),
        [
            {
                "id": uuid.uuid4(),
                "tenant_id": claim.tenant_id,
                "document_id": claim.document_id,
                "version_id": claim.version_id,
                "ordinal": chunk.ordinal,
                "text": chunk.text,
                "char_start": chunk.char_start,
                "char_end": chunk.char_end,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "section": chunk.section,
                "embedding": embedding,
                "embedding_model": embedding_model,
                "is_current": becomes_current,
            }
            for chunk, embedding in zip(chunks, embeddings, strict=True)
        ],
    )
    if becomes_current:
        document.current_version_id = version.id
    version.status = "ready"
    version.chunk_count = len(chunks)
    version.error_code = None
    version.error_message = None
    version.lease_expires_at = None
    version.finished_at = _now()


def _now() -> datetime:
    return datetime.now(UTC)
