from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from norte_legal.config import get_settings
from norte_legal.db.models import Base

config = context.config
if config.config_file_name and config.attributes.get("configure_logging", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_online() -> None:
    url = config.get_main_option("sqlalchemy.url") or get_settings().database_url
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
