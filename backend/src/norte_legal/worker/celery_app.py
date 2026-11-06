"""Aplicación Celery. El estado de cada tarea vive en PostgreSQL, no en un result backend."""

from typing import Any

from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

from norte_legal.adapters import traced
from norte_legal.config import get_settings
from norte_legal.db.session import get_engine
from norte_legal.observability.logging import configure_logging
from norte_legal.observability.telemetry import configure_telemetry, flush_telemetry

SERVICE_NAME = "norte-legal-worker"
TASK_TIME_LIMIT_S = 900
RECONCILE_INTERVAL_S = 60
# Debe superar el límite de tiempo: si no, Redis reentrega tareas que siguen en ejecución.
VISIBILITY_TIMEOUT_S = 3_600

settings = get_settings()

celery_app = Celery("norte_legal", broker=settings.redis_url, include=["norte_legal.worker.tasks"])
celery_app.conf.update(
    # Entrega "al menos una vez": confirma al terminar y reencola si muere el proceso.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_ignore_result=True,
    task_time_limit=TASK_TIME_LIMIT_S,
    task_soft_time_limit=TASK_TIME_LIMIT_S - 60,
    broker_transport_options={
        "visibility_timeout": VISIBILITY_TIMEOUT_S,
        "socket_connect_timeout": 3,
    },
    broker_connection_retry_on_startup=True,
    # Publicar no debe bloquear una petición HTTP si Redis está caído.
    task_publish_retry_policy={"max_retries": 2, "interval_start": 0, "interval_step": 0.2},
    # JSON evita la ejecución de código que permite pickle.
    task_serializer="json",
    accept_content=["json"],
    task_default_queue="ingestion",
    worker_hijack_root_logger=False,
    # Celery sustituye sys.stdout en los procesos hijo por un proxy hacia su logger: el handler
    # de structlog escribiría en ese proxy y los logs de las tareas se perderían.
    worker_redirect_stdouts=False,
    # Lo ejecuta el beat embebido en el worker (`--beat`). Con varios workers, beat iría aparte.
    beat_schedule={
        "reconcile-ingestion": {"task": "ingestion.reconcile", "schedule": RECONCILE_INTERVAL_S}
    },
)


@worker_process_init.connect
def _init_worker_process(**_: Any) -> None:
    configure_logging(SERVICE_NAME, settings.log_level)
    configure_telemetry(SERVICE_NAME, settings)
    traced.initialize_metrics()  # Errores de embeddings de la ingesta
    CeleryInstrumentor().instrument()  # type: ignore[no-untyped-call]
    # El pool del padre no puede compartirse con el hijo tras el fork.
    get_engine().dispose(close=False)
    SQLAlchemyInstrumentor().instrument(engine=get_engine())


@worker_process_shutdown.connect
def _shutdown_worker_process(**_: Any) -> None:
    flush_telemetry()
