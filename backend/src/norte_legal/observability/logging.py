"""Logs JSON a stdout con `correlation_id` (el `trace_id` de OpenTelemetry)."""

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog
from opentelemetry import trace


def _add_trace_context(
    _logger: Any, _method: str, event: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    context = trace.get_current_span().get_span_context()
    if context.is_valid:
        event["correlation_id"] = format(context.trace_id, "032x")
        event["span_id"] = format(context.span_id, "016x")
    return event


def configure_logging(service_name: str, level: str = "INFO") -> None:
    def add_service(
        _logger: Any, _method: str, event: MutableMapping[str, Any]
    ) -> MutableMapping[str, Any]:
        event["service"] = service_name
        return event

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        add_service,
        _add_trace_context,
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Los logs de librerías (uvicorn, celery) pasan por el mismo formato.
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(ensure_ascii=False),
            ],
        )
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
