"""Configuración de OpenTelemetry por proceso.

Debe ejecutarse después del fork: `BatchSpanProcessor` usa un hilo, y los hilos no sobreviven al
fork de un worker prefork de Celery. Por eso el worker la llama desde `worker_process_init`.
"""

import os
import socket

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider, _Gauge
from opentelemetry.sdk.metrics.export import AggregationTemporality, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from norte_legal.config import Settings

_configured = False


def configure_telemetry(service_name: str, settings: Settings) -> None:
    global _configured
    if _configured or not settings.otel_enabled:
        return
    _configured = True

    resource = telemetry_resource(service_name)
    endpoint = settings.otel_exporter_otlp_endpoint.rstrip("/")

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
    )
    trace.set_tracer_provider(tracer_provider)

    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(
            endpoint=f"{endpoint}/v1/metrics",
            # Un gauge acumulado se reexporta siempre con su último valor. `ingestion.backlog`
            # lo fija el reconciliador en el hijo del worker que toque: los demás seguirían
            # publicando un valor viejo. En delta se envía una vez por pasada y el colector
            # caduca la serie (90 s).
            preferred_temporality={_Gauge: AggregationTemporality.DELTA},
        ),
        export_interval_millis=15_000,
    )
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[metric_reader]))


def telemetry_resource(service_name: str) -> Resource:
    """Identifica el proceso, no solo el servicio.

    Los hijos prefork del worker exportan cada uno sus contadores acumulados. Sin
    `service.instance.id` (etiqueta `instance` en Prometheus) compartirían serie y se pisarían.
    Se llama después del fork, así que el pid es el del hijo.
    """
    return Resource.create(
        {
            "service.name": service_name,
            "service.instance.id": f"{socket.gethostname()}-{os.getpid()}",
        }
    )


def flush_telemetry() -> None:
    """Vacía los buffers. Sin esto, los spans de un proceso hijo se pierden al terminar."""
    tracer_provider = trace.get_tracer_provider()
    if isinstance(tracer_provider, TracerProvider):
        tracer_provider.force_flush()
    meter_provider = metrics.get_meter_provider()
    if isinstance(meter_provider, MeterProvider):
        meter_provider.force_flush()


def current_trace_id() -> str | None:
    """`trace_id` activo en hexadecimal. Es también el identificador de correlación."""
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, "032x") if context.is_valid else None
