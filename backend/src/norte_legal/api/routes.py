"""Rutas de sistema."""

import structlog
from fastapi import APIRouter, Response, status
from kombu.exceptions import OperationalError
from pydantic import BaseModel
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from norte_legal.api.problems import ProblemError
from norte_legal.config import get_settings
from norte_legal.db.session import new_session
from norte_legal.observability.telemetry import current_trace_id
from norte_legal.worker.tasks import ping

logger = structlog.get_logger(__name__)
router = APIRouter()


class HealthOut(BaseModel):
    status: str


class ReadinessOut(BaseModel):
    database: bool
    redis: bool


class PingOut(BaseModel):
    task_id: str
    correlation_id: str | None


@router.get("/healthz", response_model=HealthOut, tags=["system"])
def healthz() -> HealthOut:
    """Liveness: el proceso responde. No comprueba dependencias."""
    return HealthOut(status="ok")


@router.get("/readyz", response_model=ReadinessOut, tags=["system"])
def readyz(response: Response) -> ReadinessOut:
    """Readiness: el proceso puede atender peticiones porque sus dependencias responden."""
    result = ReadinessOut(database=_database_ok(), redis=_redis_ok())
    if not (result.database and result.redis):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result


@router.post(
    "/api/v1/system/ping",
    response_model=PingOut,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["system"],
)
def system_ping() -> PingOut:
    """Encola una tarea de diagnóstico para verificar la traza de extremo a extremo."""
    try:
        task = ping.delay()
    except OperationalError as error:
        logger.warning("broker_unavailable", error=str(error))
        raise ProblemError(
            status.HTTP_503_SERVICE_UNAVAILABLE, "broker_unavailable", "Broker unavailable"
        ) from error
    return PingOut(task_id=task.id, correlation_id=current_trace_id())


def _database_ok() -> bool:
    try:
        with new_session() as session:
            session.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        logger.warning("database_unavailable", error=str(error))
        return False
    return True


def _redis_ok() -> bool:
    client = Redis.from_url(get_settings().redis_url, socket_connect_timeout=2)
    try:
        return bool(client.ping())
    except RedisError as error:
        logger.warning("redis_unavailable", error=str(error))
        return False
    finally:
        client.close()
