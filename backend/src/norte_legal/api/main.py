"""Punto de entrada de la API."""

from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response, status
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

from norte_legal.adapters import traced
from norte_legal.api import auth, documents, query
from norte_legal.api.problems import install_problem_handlers, problem_response
from norte_legal.api.routes import router
from norte_legal.config import get_settings
from norte_legal.db.session import get_engine
from norte_legal.observability.logging import configure_logging
from norte_legal.observability.telemetry import configure_telemetry, current_trace_id
from norte_legal.services.query import initialize_metrics as initialize_query_metrics

SERVICE_NAME = "norte-legal-api"
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


async def _correlation_header(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    response = await call_next(request)
    correlation_id = current_trace_id()
    if correlation_id:
        response.headers["X-Correlation-ID"] = correlation_id
    return response


async def _same_origin(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Protección CSRF. La cookie es `SameSite=Lax`, pero los subdominios de mizpa.io son el mismo
    *site*: otra aplicación del servidor podría enviar un POST con la cookie. Los navegadores
    siempre mandan `Origin` en un POST o DELETE de `fetch`; sin `Origin` es un cliente que no es
    un navegador (curl, eval/) y no tiene cookies ajenas que aprovechar."""
    origin = request.headers.get("origin")
    if (
        request.method in _UNSAFE_METHODS
        and origin is not None
        and urlsplit(origin).netloc != request.headers.get("host")
    ):
        return problem_response(
            status.HTTP_403_FORBIDDEN, "cross_origin_request", "Cross-origin request"
        )
    return await call_next(request)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(SERVICE_NAME, settings.log_level)
    configure_telemetry(SERVICE_NAME, settings)
    initialize_query_metrics()
    traced.initialize_metrics()

    app = FastAPI(title="NorteLegal RAG API", version="0.1.0")
    app.middleware("http")(_correlation_header)
    app.middleware("http")(_same_origin)
    install_problem_handlers(app)
    app.include_router(router)
    app.include_router(auth.router)
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
