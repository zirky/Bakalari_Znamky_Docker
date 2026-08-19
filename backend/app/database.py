from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _migrate_existing_schema() -> None:
    inspector = inspect(engine)
    table_names = inspector.get_table_names()

    if 'grades' in table_names:
        columns = {column['name'] for column in inspector.get_columns('grades')}
        if 'active_in_sync' not in columns:
            with engine.begin() as connection:
                connection.execute(text(
                    'ALTER TABLE grades '
                    'ADD COLUMN active_in_sync BOOLEAN NOT NULL DEFAULT 1'
                ))


def init_db() -> None:
    from . import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _migrate_existing_schema()
