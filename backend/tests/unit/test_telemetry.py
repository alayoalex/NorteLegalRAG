"""Las métricas que lee Grafana deben poder agregarse sin mentir."""

import os

import pytest
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    HistogramDataPoint,
    InMemoryMetricReader,
    NumberDataPoint,
)

from norte_legal.adapters import traced
from norte_legal.observability.telemetry import telemetry_resource
from norte_legal.services import ingestion, query


@pytest.fixture(scope="module")
def reader() -> InMemoryMetricReader:
    # El proveedor global solo se fija una vez por proceso. Los instrumentos de módulo son
    # proxies y se enlazan a él al fijarlo, igual que en producción.
    metric_reader = InMemoryMetricReader()
    metrics.set_meter_provider(MeterProvider(metric_readers=[metric_reader]))
    return metric_reader


def _bounds(reader: InMemoryMetricReader, name: str) -> tuple[float, ...]:
    data = reader.get_metrics_data()
    assert data is not None
    for resource_metrics in data.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                if metric.name == name:
                    point = metric.data.data_points[0]
                    assert isinstance(point, HistogramDataPoint)
                    return tuple(point.explicit_bounds)
    raise AssertionError(f"metric {name} not exported")


def test_each_process_has_its_own_instance_id() -> None:
    attributes = telemetry_resource("worker").attributes
    assert attributes["service.name"] == "worker"
    assert str(attributes["service.instance.id"]).endswith(f"-{os.getpid()}")


def test_histograms_use_buckets_that_fit_their_values(reader: InMemoryMetricReader) -> None:
    traced._duration.record(3.0)
    traced._embedding_duration.record(0.3)
    ingestion._duration.record(12.0)
    ingestion._chunks.record(40)
    query._retrieval_duration.record(0.02)
    query._top_similarity.record(0.42)

    # El presupuesto de la consulta debe ser un límite exacto para ver cuánto margen queda.
    assert query.QUERY_BUDGET_S in _bounds(reader, "llm.request.duration")
    # Una recuperación típica (milisegundos) no puede caer en el primer bucket.
    assert _bounds(reader, "retrieval.duration")[0] < 0.01
    assert _bounds(reader, "embeddings.request.duration")[0] < 0.1
    assert _bounds(reader, "ingestion.duration")[0] < 1
    assert _bounds(reader, "ingestion.chunks")[0] == 1
    similarity = _bounds(reader, "retrieval.top_similarity")
    assert similarity[0] == 0.05
    assert similarity[-1] == 0.95
    assert len(similarity) == 19


def _points(reader: InMemoryMetricReader, name: str) -> dict[tuple[str, ...], float]:
    data = reader.get_metrics_data()
    assert data is not None
    for resource_metrics in data.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                if metric.name == name:
                    points: dict[tuple[str, ...], float] = {}
                    for point in metric.data.data_points:
                        assert isinstance(point, NumberDataPoint)
                        key = tuple(str(v) for v in (point.attributes or {}).values())
                        points[key] = point.value
                    return points
    raise AssertionError(f"metric {name} not exported")


def test_counters_start_at_zero_so_the_first_increment_is_seen(
    reader: InMemoryMetricReader,
) -> None:
    query.initialize_metrics()
    traced.initialize_metrics()

    answers = _points(reader, "rag.answers")
    assert answers[("answered", "none")] == 0
    assert answers[("degraded", "llm_unavailable")] == 0
    assert len(answers) == 7
    assert _points(reader, "rag.prompt_leaks") == {(): 0}
    assert _points(reader, "rag.citations.dropped") == {(): 0}
    assert _points(reader, "llm.request.errors")[("provider_rate_limited",)] == 0
    assert len(_points(reader, "embeddings.request.errors")) == 5
