"""Tareas de Celery. Solo traducen mensajes a llamadas del servicio de ingesta."""

import uuid

import structlog
from celery import Task
from kombu.exceptions import OperationalError

from norte_legal.adapters.blob_store import LocalBlobStore
from norte_legal.adapters.factory import build_embedding_provider, build_llm_provider
from norte_legal.config import get_settings
from norte_legal.db.session import new_session
from norte_legal.domain.ports import PromptSource, RagPrompt
from norte_legal.services import ingestion
from norte_legal.worker.celery_app import celery_app

logger = structlog.get_logger(__name__)


@celery_app.task(name="system.ping")
def ping() -> None:
    """Prueba de humo del recorrido HTTP -> cola -> worker -> LLM. No toca datos."""
    answer = build_llm_provider(get_settings()).generate_answer(
        RagPrompt(
            system="diagnostic",
            question="diagnostic ping request",
            sources=[PromptSource(ref="diagnostic", text="Diagnostic ping request received.")],
        )
    )
    logger.info("system_ping_completed", insufficient_context=answer.insufficient_context)


# Claim check: el mensaje solo lleva el identificador. El presupuesto de reintentos vive en
# PostgreSQL (`attempt_limit`), no en Celery, para que sobreviva a una cola perdida.
@celery_app.task(name="ingestion.ingest_version", bind=True, max_retries=None)
def ingest_version(self: Task, version_id: str) -> None:
    settings = get_settings()
    result = ingestion.process_version(
        uuid.UUID(version_id),
        blobs=LocalBlobStore(settings.blob_dir),
        embedder=build_embedding_provider(settings),
    )
    if result.retry_in_s is not None:
        raise self.retry(countdown=result.retry_in_s)


@celery_app.task(name="ingestion.reconcile")
def reconcile() -> None:
    with new_session() as session:
        version_ids = ingestion.reconcile(session)
    for version_id in version_ids:
        enqueue_ingestion(version_id)


def enqueue_ingestion(version_id: uuid.UUID) -> bool:
    """Publica la tarea. Si Redis no responde, la versión sigue en PostgreSQL y el reconciliador
    la publicará cuando venza su plazo: el fallo no se propaga a quien sube el archivo."""
    try:
        ingest_version.delay(str(version_id))
    except OperationalError as error:
        logger.warning("enqueue_failed", version_id=str(version_id), error=str(error))
        return False
    return True
