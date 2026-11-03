"""Consultas de recuperación. Filtran siempre por tenant y por versión vigente (`is_current`)."""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from norte_legal.db.models import Chunk, Document, DocumentVersion


@dataclass(frozen=True)
class RetrievedChunk:
    """Copia sin ORM: sigue siendo válida después de cerrar la transacción de recuperación."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    version_id: uuid.UUID
    version_no: int
    is_current: bool
    text: str
    char_start: int
    char_end: int
    page_start: int | None
    page_end: int | None
    section: str | None


class RetrievalRepository:
    def __init__(self, session: Session, tenant_id: str) -> None:
        self._session = session
        self._tenant_id = tenant_id

    def vector_search(
        self, embedding: list[float], embedding_model: str, limit: int
    ) -> list[tuple[str, float]]:
        """`(chunk_id, similitud coseno)` de más a menos similar.

        `ef_search = 100` (DECISIONS.md §6): más candidatos explorados en el grafo HNSW.

        El filtro por tenant y modelo se aplica después de recorrer el índice. El escaneo
        iterativo de pgvector 0.8 sigue buscando hasta reunir `limit` filas que lo cumplan, en
        lugar de devolver menos resultados cuando el tenant es pequeño.
        """
        # Valor fijo en el texto: SET no admite parámetros y aquí no se interpola nada.
        self._session.execute(text("SET LOCAL hnsw.ef_search = 100"))
        self._session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
        distance = Chunk.embedding.cosine_distance(embedding)
        rows = self._session.execute(
            select(Chunk.id, distance.label("distance"))
            .where(
                Chunk.tenant_id == self._tenant_id,
                Chunk.is_current,
                Chunk.embedding_model == embedding_model,
            )
            .order_by(distance)
            .limit(limit)
        ).all()
        return [(str(row.id), 1.0 - float(row.distance)) for row in rows]

    def lexical_search(self, tsquery: str, limit: int) -> list[str]:
        query = func.to_tsquery("simple", tsquery)
        rank = func.ts_rank_cd(Chunk.text_tsv, query)
        rows = self._session.execute(
            select(Chunk.id)
            .where(
                Chunk.tenant_id == self._tenant_id,
                Chunk.is_current,
                Chunk.text_tsv.op("@@")(query),
            )
            .order_by(rank.desc(), Chunk.id)
            .limit(limit)
        ).all()
        return [str(row.id) for row in rows]

    def load(self, chunk_ids: list[str]) -> dict[str, RetrievedChunk]:
        if not chunk_ids:
            return {}
        rows = self._session.execute(
            select(Chunk, Document.name, DocumentVersion.version_no)
            .join(Document, Document.id == Chunk.document_id)
            .join(DocumentVersion, DocumentVersion.id == Chunk.version_id)
            .where(
                Chunk.tenant_id == self._tenant_id,
                Chunk.id.in_([uuid.UUID(chunk_id) for chunk_id in chunk_ids]),
            )
        ).all()
        return {
            str(row.Chunk.id): RetrievedChunk(
                chunk_id=row.Chunk.id,
                document_id=row.Chunk.document_id,
                document_name=row.name,
                version_id=row.Chunk.version_id,
                version_no=row.version_no,
                is_current=row.Chunk.is_current,
                text=row.Chunk.text,
                char_start=row.Chunk.char_start,
                char_end=row.Chunk.char_end,
                page_start=row.Chunk.page_start,
                page_end=row.Chunk.page_end,
                section=row.Chunk.section,
            )
            for row in rows
        }
