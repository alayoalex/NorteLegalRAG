"""Servicio de consulta: recuperación híbrida, generación y validación de la respuesta.

Tres compuertas antes de mostrar una respuesta (invariante 6):
1. Sin fragmentos que superen la recuperación, no se llama al LLM (`no_context`).
2. El LLM puede declarar `insufficient_context`.
3. Sin al menos una cita verificada contra su fragmento, no hay respuesta.

Degradación: si fallan los embeddings, la búsqueda sigue solo con texto completo. Si falla el
LLM, se devuelven los fragmentos recuperados sin respuesta generada (`degraded`).
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

import structlog
from opentelemetry import metrics, trace
from sqlalchemy.orm import Session

from norte_legal.db.retrieval import RetrievalRepository, RetrievedChunk
from norte_legal.domain.chunking import section_at
from norte_legal.domain.citations import validate_answer
from norte_legal.domain.errors import ProviderError, ProviderRateLimitedError
from norte_legal.domain.ports import (
    DraftAnswer,
    EmbeddingProvider,
    LLMProvider,
    PromptSource,
    RagPrompt,
)
from norte_legal.domain.prompts import build_prompt, leaks_canary, new_canary
from norte_legal.domain.retrieval import (
    LEXICAL_CANDIDATES,
    VECTOR_CANDIDATES,
    fuse,
    lexical_query,
)

logger = structlog.get_logger(__name__)
_tracer = trace.get_tracer("norte_legal.query")
_meter = metrics.get_meter("norte_legal.query")
_retrieval_duration = _meter.create_histogram(
    "retrieval.duration",
    unit="s",
    description="Duración de la recuperación, por modo",
    explicit_bucket_boundaries_advisory=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5],
)
_answers = _meter.create_counter("rag.answers", description="Respuestas, por estado y motivo")
_top_similarity = _meter.create_histogram(
    "retrieval.top_similarity",
    description="Similitud coseno del mejor candidato vectorial. Sirve para calibrar el umbral",
    # Pasos de 0.05: la resolución con la que se ajusta RETRIEVAL_MIN_SIMILARITY.
    explicit_bucket_boundaries_advisory=[round(0.05 * i, 2) for i in range(1, 20)],
)
_citations_dropped = _meter.create_counter(
    "rag.citations.dropped", description="Citas del LLM descartadas por no verificarse"
)
_prompt_leaks = _meter.create_counter(
    "rag.prompt_leaks", description="Respuestas descartadas porque contenían el canario"
)

# Presupuesto de toda la consulta: por debajo del `proxy_read_timeout` de nginx (60 s).
QUERY_BUDGET_S = 55.0

Status = Literal["answered", "no_context", "degraded"]
Reason = Literal[
    "no_sources",
    "model_insufficient_context",
    "unverified_citations",
    "llm_unavailable",
    "llm_error",
    "prompt_leak",
]
RetrievalMode = Literal["hybrid", "lexical"]

# Combinaciones que emite answer_question. Una serie que nace con valor 1 no tiene muestra previa
# en Prometheus e `increase()` no ve ese primer incremento: por eso se publican en 0 al arrancar.
_ANSWER_SERIES: tuple[tuple[Status, Reason | Literal["none"]], ...] = (
    ("answered", "none"),
    ("no_context", "no_sources"),
    ("no_context", "model_insufficient_context"),
    ("no_context", "unverified_citations"),
    ("no_context", "prompt_leak"),
    ("degraded", "llm_unavailable"),
    ("degraded", "llm_error"),
)


def initialize_metrics() -> None:
    """Publica los contadores de la consulta en 0. Va después de `configure_telemetry`: antes,
    los instrumentos son proxies sin proveedor y el `add(0)` se pierde."""
    for status, reason in _ANSWER_SERIES:
        _answers.add(0, {"status": status, "reason": reason})
    _citations_dropped.add(0)
    _prompt_leaks.add(0)


@dataclass(frozen=True)
class Citation:
    ref: str
    source: RetrievedChunk
    section: str | None
    quote: str
    # Posición de la cita en el texto extraído del documento, no en el fragmento.
    char_start: int
    char_end: int


@dataclass(frozen=True)
class QueryResult:
    status: Status
    retrieval_mode: RetrievalMode
    reason: Reason | None = None
    answer: str | None = None
    citations: list[Citation] = field(default_factory=list)
    sources: list[RetrievedChunk] = field(default_factory=list)


def answer_question(
    session: Session,
    *,
    tenant_id: str,
    question: str,
    embedder: EmbeddingProvider,
    llm: LLMProvider,
    min_similarity: float,
    llm_timeout_s: float,
    clock: Callable[[], float] = time.monotonic,
) -> QueryResult:
    started = clock()
    sources, mode = _retrieve(session, tenant_id, question, embedder, min_similarity)
    if not sources:
        return _finish(QueryResult("no_context", mode, "no_sources"))

    refs = {f"S{index}": source for index, source in enumerate(sources, start=1)}
    canary = new_canary()
    prompt = build_prompt(
        question,
        [PromptSource(ref=ref, text=src.text, label=_label(src)) for ref, src in refs.items()],
        canary,
    )
    try:
        draft = _generate_within_budget(llm, prompt, started, llm_timeout_s, clock)
    except ProviderError as error:
        reason: Reason = "llm_unavailable" if error.retryable else "llm_error"
        logger.warning("llm_degraded", error_code=error.code)
        return _finish(QueryResult("degraded", mode, reason, sources=sources))

    if leaks_canary(canary, draft.answer, *(citation.quote for citation in draft.citations)):
        _prompt_leaks.add(1)
        logger.warning("prompt_canary_leaked", source_count=len(sources))
        return _finish(QueryResult("no_context", mode, "prompt_leak", sources=sources))

    if draft.insufficient_context:
        return _finish(
            QueryResult("no_context", mode, "model_insufficient_context", sources=sources)
        )

    validated = validate_answer(draft, {ref: source.text for ref, source in refs.items()})
    if validated.dropped:
        _citations_dropped.add(validated.dropped)
        logger.warning("citations_dropped", dropped=validated.dropped)
    if not validated.citations or not validated.answer:
        return _finish(QueryResult("no_context", mode, "unverified_citations", sources=sources))

    citations = [
        Citation(
            ref=citation.ref,
            source=refs[citation.ref],
            # Un fragmento puede abarcar varias cláusulas: vale la que precede a la cita.
            section=section_at(refs[citation.ref].text, citation.start)
            or refs[citation.ref].section,
            quote=citation.quote,
            char_start=refs[citation.ref].char_start + citation.start,
            char_end=refs[citation.ref].char_start + citation.end,
        )
        for citation in validated.citations
    ]
    return _finish(
        QueryResult("answered", mode, answer=validated.answer, citations=citations, sources=sources)
    )


def _retrieve(
    session: Session,
    tenant_id: str,
    question: str,
    embedder: EmbeddingProvider,
    min_similarity: float,
) -> tuple[list[RetrievedChunk], RetrievalMode]:
    started = time.perf_counter()
    mode: RetrievalMode = "hybrid"
    with _tracer.start_as_current_span("retrieval.hybrid") as span:
        # Fuera de la transacción: no se retiene una conexión mientras responde el proveedor.
        query_embedding: list[float] | None = None
        try:
            query_embedding = embedder.embed_query(question)
        except ProviderError as error:
            mode = "lexical"
            logger.warning("embedding_degraded", error_code=error.code)

        tsquery = lexical_query(question)
        with session.begin():
            repository = RetrievalRepository(session, tenant_id)
            vector = (
                repository.vector_search(query_embedding, embedder.model, VECTOR_CANDIDATES)
                if query_embedding is not None
                else []
            )
            lexical = repository.lexical_search(tsquery, LEXICAL_CANDIDATES) if tsquery else []
            ranked = fuse(vector, lexical, min_similarity)
            loaded = repository.load([candidate.chunk_id for candidate in ranked])
        sources = [loaded[c.chunk_id] for c in ranked if c.chunk_id in loaded]

        if vector:
            _top_similarity.record(vector[0][1], {"embedding_model": embedder.model})
            span.set_attribute("retrieval.top_similarity", vector[0][1])
        span.set_attribute("retrieval.mode", mode)
        span.set_attribute("retrieval.vector_candidates", len(vector))
        span.set_attribute("retrieval.lexical_candidates", len(lexical))
        span.set_attribute("retrieval.sources", len(sources))
    _retrieval_duration.record(time.perf_counter() - started, {"mode": mode})
    logger.info(
        "retrieval_finished",
        mode=mode,
        question_chars=len(question),
        vector_candidates=len(vector),
        lexical_candidates=len(lexical),
        sources=len(sources),
    )
    return sources, mode


def _generate_within_budget(
    llm: LLMProvider,
    prompt: RagPrompt,
    started: float,
    timeout_s: float,
    clock: Callable[[], float],
) -> DraftAnswer:
    """Un único reintento, y solo si cabe entero en el presupuesto de la consulta."""
    try:
        return llm.generate_answer(prompt)
    except ProviderError as error:
        wait_s = 0.0
        if isinstance(error, ProviderRateLimitedError):
            wait_s = error.retry_after_s or 0.0
        remaining = QUERY_BUDGET_S - (clock() - started)
        if not error.retryable or wait_s + timeout_s > remaining:
            raise
        logger.warning("llm_retry", error_code=error.code, wait_s=wait_s)
        time.sleep(wait_s)
        return llm.generate_answer(prompt)


def _label(source: RetrievedChunk) -> str:
    parts = [source.document_name]
    if source.section:
        parts.append(source.section)
    if source.page_start is not None:
        pages = (
            f"{source.page_start}"
            if source.page_start == source.page_end
            else (f"{source.page_start}-{source.page_end}")
        )
        parts.append(f"pág. {pages}")
    return " · ".join(parts)


def _finish(result: QueryResult) -> QueryResult:
    _answers.add(1, {"status": result.status, "reason": result.reason or "none"})
    logger.info(
        "query_finished",
        status=result.status,
        reason=result.reason,
        retrieval_mode=result.retrieval_mode,
        citations=len(result.citations),
    )
    return result
