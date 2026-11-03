"""El riesgo arquitectónico principal: una sola traza desde HTTP hasta la llamada al LLM."""

import time
from collections.abc import Iterator

import pytest
from celery.contrib.testing.worker import start_worker
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

pytestmark = pytest.mark.integration

SPAN_TIMEOUT_S = 15


@pytest.fixture(scope="module")
def exporter() -> InMemorySpanExporter:
    span_exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    trace.set_tracer_provider(provider)
    return span_exporter


@pytest.fixture(scope="module")
def app(migrated_settings: None, exporter: InMemorySpanExporter) -> FastAPI:
    from norte_legal.api.main import create_app

    return create_app()


@pytest.fixture(scope="module")
def running_worker(app: FastAPI) -> Iterator[None]:
    from norte_legal.worker.celery_app import celery_app

    celery_app.conf.update(
        broker_url=_broker_url(),
        task_default_queue="ingestion",
    )
    with start_worker(
        celery_app, pool="solo", perform_ping_check=False, queues=["ingestion"], loglevel="WARNING"
    ):
        yield
    CeleryInstrumentor().uninstrument()


def _broker_url() -> str:
    from norte_legal.config import get_settings

    return get_settings().redis_url


def _wait_for_span(exporter: InMemorySpanExporter, name: str) -> ReadableSpan:
    deadline = time.monotonic() + SPAN_TIMEOUT_S
    while time.monotonic() < deadline:
        for span in exporter.get_finished_spans():
            if span.name == name:
                return span
        time.sleep(0.1)
    names = [span.name for span in exporter.get_finished_spans()]
    raise AssertionError(f"Span {name!r} not found. Spans: {names}")


def test_http_request_task_and_llm_call_share_one_trace(
    app: FastAPI, running_worker: None, exporter: InMemorySpanExporter
) -> None:
    response = TestClient(app).post("/api/v1/system/ping")
    assert response.status_code == 202
    correlation_id = response.headers["X-Correlation-ID"]
    assert response.json()["correlation_id"] == correlation_id

    llm_span = _wait_for_span(exporter, "llm.generate_answer")
    worker_span = _wait_for_span(exporter, "run/system.ping")

    assert format(llm_span.context.trace_id, "032x") == correlation_id
    assert format(worker_span.context.trace_id, "032x") == correlation_id
    assert llm_span.attributes["gen_ai.request.model"] == "fake-extractive-1"


def test_readiness_reports_real_dependencies(app: FastAPI) -> None:
    response = TestClient(app).get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"database": True, "redis": True}


def test_liveness_does_not_depend_on_infrastructure(app: FastAPI) -> None:
    assert TestClient(app).get("/healthz").json() == {"status": "ok"}


def test_database_queries_appear_in_the_request_trace(
    app: FastAPI, exporter: InMemorySpanExporter
) -> None:
    """Si la instrumentación de SQLAlchemy se desactiva (versión no soportada), esto falla."""
    exporter.clear()
    response = TestClient(app).get("/api/v1/documents")
    correlation_id = response.headers["X-Correlation-ID"]

    sql_spans = [
        span
        for span in exporter.get_finished_spans()
        if span.attributes and span.attributes.get("db.system") == "postgresql"
    ]
    assert sql_spans
    assert all(format(span.context.trace_id, "032x") == correlation_id for span in sql_spans)
