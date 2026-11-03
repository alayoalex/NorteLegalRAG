"""Tareas de Celery."""

import structlog

from norte_legal.adapters.factory import build_llm_provider
from norte_legal.config import get_settings
from norte_legal.domain.ports import PromptSource, RagPrompt
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
