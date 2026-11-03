"""Acceso síncrono a la base de datos, compartido por la API y el worker."""

from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from norte_legal.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


def new_session() -> Session:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)()
