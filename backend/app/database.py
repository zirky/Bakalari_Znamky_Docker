from datetime import date

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

    if 'grades' not in table_names:
        return

    columns = {column['name'] for column in inspector.get_columns('grades')}
    with engine.begin() as connection:
        if 'active_in_sync' not in columns:
            connection.execute(text(
                'ALTER TABLE grades '
                'ADD COLUMN active_in_sync BOOLEAN NOT NULL DEFAULT 1'
            ))
        if 'school_year' not in columns:
            connection.execute(text(
                'ALTER TABLE grades '
                'ADD COLUMN school_year VARCHAR(9)'
            ))

    from .school_year import school_year_for_date

    with engine.begin() as connection:
        rows = connection.execute(text(
            'SELECT id, grade_date FROM grades '
            'WHERE school_year IS NULL AND grade_date IS NOT NULL'
        )).mappings()
        for row in rows:
            grade_date = row['grade_date']
            if isinstance(grade_date, str):
                grade_date = date.fromisoformat(grade_date)
            connection.execute(
                text('UPDATE grades SET school_year = :school_year WHERE id = :id'),
                {'school_year': school_year_for_date(grade_date), 'id': row['id']},
            )


def init_db() -> None:
    from . import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _migrate_existing_schema()
