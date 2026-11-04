"""Acceso a datos del lado de la API. Cada consulta filtra por el tenant con el que se construye."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from norte_legal.db.models import Chunk, Document, DocumentVersion


@dataclass(frozen=True)
class DocumentView:
    document: Document
    latest: DocumentVersion
    current: DocumentVersion | None


@dataclass(frozen=True)
class ChunkView:
    chunk: Chunk
    document: Document
    version: DocumentVersion


class DocumentRepository:
    def __init__(self, session: Session, tenant_id: str) -> None:
        self._session = session
        self._tenant_id = tenant_id

    def lock_or_create_document(self, name: str) -> uuid.UUID:
        """Devuelve el documento con su fila bloqueada hasta el final de la transacción.

        El bloqueo serializa las subidas concurrentes del mismo documento: el cálculo de
        `version_no` y la comprobación de idempotencia no compiten entre sí. Subir de nuevo un
        documento borrado lo restaura.
        """
        statement = insert(Document).values(id=uuid.uuid4(), tenant_id=self._tenant_id, name=name)
        statement = statement.on_conflict_do_update(
            constraint="uq_documents_tenant_name",
            set_={"name": statement.excluded.name, "deleted_at": None},
        )
        return self._session.execute(statement.returning(Document.id)).scalar_one()

    def current_version_id(self, document_id: uuid.UUID) -> uuid.UUID | None:
        return self._session.scalar(
            select(Document.current_version_id).where(
                Document.tenant_id == self._tenant_id, Document.id == document_id
            )
        )

    def find_version(
        self, document_id: uuid.UUID, content_sha256: str, fingerprint: str
    ) -> DocumentVersion | None:
        return self._session.scalars(
            select(DocumentVersion).where(
                DocumentVersion.tenant_id == self._tenant_id,
                DocumentVersion.document_id == document_id,
                DocumentVersion.content_sha256 == content_sha256,
                DocumentVersion.pipeline_fingerprint == fingerprint,
            )
        ).one_or_none()

    def add_version(
        self,
        *,
        document_id: uuid.UUID,
        content_sha256: str,
        fingerprint: str,
        media_type: str,
        size_bytes: int,
        storage_key: str,
        trace_id: str | None,
        deadline: datetime,
        attempt_limit: int,
    ) -> DocumentVersion:
        version_no = self._session.execute(
            select(func.coalesce(func.max(DocumentVersion.version_no), 0) + 1).where(
                DocumentVersion.tenant_id == self._tenant_id,
                DocumentVersion.document_id == document_id,
            )
        ).scalar_one()
        version = DocumentVersion(
            tenant_id=self._tenant_id,
            document_id=document_id,
            version_no=version_no,
            content_sha256=content_sha256,
            pipeline_fingerprint=fingerprint,
            media_type=media_type,
            size_bytes=size_bytes,
            storage_key=storage_key,
            status="queued",
            attempt=0,
            attempt_limit=attempt_limit,
            lease_expires_at=deadline,
            trace_id=trace_id,
        )
        self._session.add(version)
        self._session.flush()
        self._session.refresh(version)
        return version

    def make_current(self, document_id: uuid.UUID, version_id: uuid.UUID) -> None:
        """Vuelve a hacer vigente una versión lista. Solo para un documento sin versión vigente."""
        self._session.execute(
            update(Chunk)
            .where(Chunk.tenant_id == self._tenant_id, Chunk.version_id == version_id)
            .values(is_current=True)
        )
        self._session.execute(
            update(Document)
            .where(Document.tenant_id == self._tenant_id, Document.id == document_id)
            .values(current_version_id=version_id)
        )

    def soft_delete(self, document: Document, deleted_at: datetime) -> None:
        """Saca el documento de la lista y de la búsqueda. Versiones y fragmentos se conservan."""
        self._session.execute(
            update(Chunk)
            .where(Chunk.tenant_id == self._tenant_id, Chunk.document_id == document.id)
            .values(is_current=False)
        )
        document.current_version_id = None
        document.deleted_at = deleted_at

    def has_pending_versions(self, document_id: uuid.UUID, pending: tuple[str, ...]) -> bool:
        return bool(
            self._session.scalar(
                select(
                    select(DocumentVersion.id)
                    .where(
                        DocumentVersion.tenant_id == self._tenant_id,
                        DocumentVersion.document_id == document_id,
                        DocumentVersion.status.in_(pending),
                    )
                    .exists()
                )
            )
        )

    def list_documents(self, limit: int) -> list[DocumentView]:
        documents = self._session.scalars(
            select(Document)
            .where(Document.tenant_id == self._tenant_id, Document.deleted_at.is_(None))
            .order_by(Document.created_at.desc(), Document.id)
            .limit(limit)
        ).all()
        versions = self._versions_by_document([document.id for document in documents])
        return [
            _view(document, versions[document.id])
            for document in documents
            if versions.get(document.id)
        ]

    def get_document(
        self, document_id: uuid.UUID, *, lock: bool = False
    ) -> tuple[DocumentView, list[DocumentVersion]]:
        """Documento no borrado con sus versiones. `lock` bloquea su fila hasta el final de la
        transacción, como `lock_or_create_document`, para serializar borrado, reintento y subida.
        """
        statement = select(Document).where(
            Document.tenant_id == self._tenant_id,
            Document.id == document_id,
            Document.deleted_at.is_(None),
        )
        if lock:
            statement = statement.with_for_update()
        document = self._session.scalars(statement).one_or_none()
        versions = self._versions_by_document([document_id]).get(document_id) if document else None
        if document is None or not versions:
            raise LookupError(document_id)
        return _view(document, versions), versions

    def requeue_failed(
        self, document_id: uuid.UUID, deadline: datetime, extra_attempts: int
    ) -> DocumentVersion | None:
        """Vuelve a encolar la última versión si falló. `None` si no hay nada que reintentar."""
        latest = (
            select(DocumentVersion.id)
            .where(
                DocumentVersion.tenant_id == self._tenant_id,
                DocumentVersion.document_id == document_id,
            )
            .order_by(DocumentVersion.version_no.desc())
            .limit(1)
            .scalar_subquery()
        )
        return self._session.scalars(
            update(DocumentVersion)
            .where(
                DocumentVersion.tenant_id == self._tenant_id,
                DocumentVersion.id == latest,
                DocumentVersion.status == "failed",
            )
            .values(
                status="queued",
                error_code=None,
                error_message=None,
                finished_at=None,
                lease_expires_at=deadline,
                attempt_limit=DocumentVersion.attempt + extra_attempts,
            )
            .returning(DocumentVersion)
        ).one_or_none()

    def get_chunk(self, chunk_id: uuid.UUID) -> ChunkView | None:
        row = self._session.execute(
            select(Chunk, Document, DocumentVersion)
            .join(Document, Document.id == Chunk.document_id)
            .join(DocumentVersion, DocumentVersion.id == Chunk.version_id)
            .where(Chunk.tenant_id == self._tenant_id, Chunk.id == chunk_id)
        ).one_or_none()
        return ChunkView(row.Chunk, row.Document, row.DocumentVersion) if row else None

    def _versions_by_document(
        self, document_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[DocumentVersion]]:
        grouped: dict[uuid.UUID, list[DocumentVersion]] = {}
        if not document_ids:
            return grouped
        versions = self._session.scalars(
            select(DocumentVersion)
            .where(
                DocumentVersion.tenant_id == self._tenant_id,
                DocumentVersion.document_id.in_(document_ids),
            )
            .order_by(DocumentVersion.version_no.desc())
        )
        for version in versions:
            grouped.setdefault(version.document_id, []).append(version)
        return grouped


def _view(document: Document, versions: list[DocumentVersion]) -> DocumentView:
    """`versions` viene ordenada de la más reciente a la más antigua."""
    current = next((v for v in versions if v.id == document.current_version_id), None)
    return DocumentView(document=document, latest=versions[0], current=current)
