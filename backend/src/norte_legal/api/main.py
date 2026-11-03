"""Punto de entrada de la API."""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

from norte_legal.api import documents, query
from norte_legal.api.problems import install_problem_handlers
from norte_legal.api.routes import router
from norte_legal.config import get_settings
from norte_legal.db.session import get_engine
from norte_legal.observability.logging import configure_logging
from norte_legal.observability.telemetry import configure_telemetry, current_trace_id

SERVICE_NAME = "norte-legal-api"


async def _correlation_header(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    response = await call_next(request)
    correlation_id = current_trace_id()
    if correlation_id:
        response.headers["X-Correlation-ID"] = correlation_id
    return response


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(SERVICE_NAME, settings.log_level)
    configure_telemetry(SERVICE_NAME, settings)

    app = FastAPI(title="NorteLegal RAG API", version="0.1.0")
    app.middleware("http")(_correlation_header)
    install_problem_handlers(app)
    app.include_router(router)
    app.include_router(documents.router)
    app.include_router(query.router)

    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz")
    # La API también publica: sin esto no se inyecta la traza en las cabeceras de la tarea.
    instrumentor = CeleryInstrumentor()  # type: ignore[no-untyped-call]
    if not instrumentor.is_instrumented_by_opentelemetry:
        instrumentor.instrument()
    sql_instrumentor = SQLAlchemyInstrumentor()
    if not sql_instrumentor.is_instrumented_by_opentelemetry:
        sql_instrumentor.instrument(engine=get_engine())
    return app
