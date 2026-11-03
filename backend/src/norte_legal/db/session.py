"""Acceso síncrono a la base de datos, compartido por la API y el worker."""

from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from norte_legal.config import get_settings


@lru_cache
def get_engine() -> Engine:
    # `hide_parameters`: los errores de SQL no incluyen valores, que pueden ser texto de documentos.
    return create_engine(get_settings().database_url, pool_pre_ping=True, hide_parameters=True)


def new_session() -> Session:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)()
