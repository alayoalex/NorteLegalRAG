"""Ruta de preguntas."""

from fastapi import APIRouter

from norte_legal.adapters.factory import get_embedding_provider, get_llm_provider
from norte_legal.api.dependencies import DbSession, TenantId
from norte_legal.api.schemas import QueryIn, QueryOut
from norte_legal.config import get_settings
from norte_legal.observability.telemetry import current_trace_id
from norte_legal.services.query import answer_question

router = APIRouter(prefix="/api/v1", tags=["query"])


@router.post("/query", response_model=QueryOut)
def query(body: QueryIn, tenant_id: TenantId, session: DbSession) -> QueryOut:
    """Responde con citas verificadas, declara que no hay contexto o, si el LLM falla,
    devuelve los fragmentos recuperados (`degraded`). Los tres casos son 200."""
    settings = get_settings()
    result = answer_question(
        session,
        tenant_id=tenant_id,
        question=body.question.strip(),
        embedder=get_embedding_provider(),
        llm=get_llm_provider(),
        min_similarity=settings.retrieval_min_similarity,
        llm_timeout_s=settings.llm_timeout_s,
    )
    return QueryOut.build(result, current_trace_id())
