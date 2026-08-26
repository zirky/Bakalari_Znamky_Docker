from datetime import date

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args = (
    {'check_same_thread': False}
    if settings.database_url.startswith('sqlite')
    else {}
)
engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
)
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)


def _table_columns(table_name: str) -> set[str]:
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return set()
    return {column['name'] for column in inspector.get_columns(table_name)}


def _add_missing_columns(
    table_name: str,
    additions: tuple[tuple[str, str], ...],
) -> None:
    columns = _table_columns(table_name)
    if not columns:
        return

    with engine.begin() as connection:
        for column_name, sql_type in additions:
            if column_name not in columns:
                connection.execute(
                    text(
                        f'ALTER TABLE {table_name} '
                        f'ADD COLUMN {column_name} {sql_type}'
                    )
                )


def _migrate_existing_schema() -> None:
    inspector = inspect(engine)
    table_names = inspector.get_table_names()

    if 'grades' not in table_names:
        return

    columns = {
        column['name']
        for column in inspector.get_columns('grades')
    }

    with engine.begin() as connection:
        if 'active_in_sync' not in columns:
            connection.execute(
                text(
                    'ALTER TABLE grades '
                    'ADD COLUMN active_in_sync '
                    'BOOLEAN NOT NULL DEFAULT 1'
                )
            )

        if 'school_year' not in columns:
            connection.execute(
                text(
                    'ALTER TABLE grades '
                    'ADD COLUMN school_year VARCHAR(9)'
                )
            )

    from .school_year import school_year_for_date

    with engine.begin() as connection:
        rows = connection.execute(
            text(
                'SELECT id, grade_date FROM grades '
                'WHERE school_year IS NULL '
                'AND grade_date IS NOT NULL'
            )
        ).mappings()

        for row in rows:
            grade_date = row['grade_date']

            if isinstance(grade_date, str):
                grade_date = date.fromisoformat(grade_date)

            connection.execute(
                text(
                    'UPDATE grades '
                    'SET school_year = :school_year '
                    'WHERE id = :id'
                ),
                {
                    'school_year': school_year_for_date(grade_date),
                    'id': row['id'],
                },
            )


def _migrate_sync_state_schema() -> None:
    additions = (
        ('next_sync_at', 'DATETIME'),
        ('sync_started_at', 'DATETIME'),
        ('last_sync_error', 'TEXT'),
        ('consecutive_failures', 'INTEGER NOT NULL DEFAULT 0'),
    )
    _add_missing_columns('sync_state', additions)


def _migrate_auth_schema() -> None:
    _add_missing_columns(
        'auth_users',
        (
            ('created_at', 'DATETIME'),
            ('last_login_at', 'DATETIME'),
        ),
    )
    _add_missing_columns(
        'sessions',
        (
            ('last_activity_at', 'DATETIME'),
        ),
    )

    with engine.begin() as connection:
        auth_columns = _table_columns('auth_users')
        if 'created_at' in auth_columns:
            connection.execute(
                text(
                    'UPDATE auth_users SET created_at = CURRENT_TIMESTAMP '
                    'WHERE created_at IS NULL'
                )
            )

        session_columns = _table_columns('sessions')
        if 'last_activity_at' in session_columns:
            connection.execute(
                text(
                    'UPDATE sessions SET last_activity_at = CURRENT_TIMESTAMP '
                    'WHERE last_activity_at IS NULL'
                )
            )


def _migrate_payout_schema() -> None:
    _add_missing_columns(
        'payouts',
        (
            ('exchange_rate_id', 'INTEGER'),
        ),
    )
    _add_missing_columns(
        'reward_rules',
        (
            ('updated_at', 'DATETIME'),
        ),
    )

    with engine.begin() as connection:
        columns = _table_columns('reward_rules')
        if 'updated_at' in columns:
            connection.execute(
                text(
                    'UPDATE reward_rules SET updated_at = CURRENT_TIMESTAMP '
                    'WHERE updated_at IS NULL'
                )
            )


def _migrate_scheduler_state_schema() -> None:
    """Přidá auto_payout_confirmed do scheduler_state, pokud chybí."""
    _add_missing_columns(
        'scheduler_state',
        (
            ('auto_payout_confirmed', 'BOOLEAN NOT NULL DEFAULT 0'),
        ),
    )


def init_db() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _migrate_existing_schema()
    _migrate_sync_state_schema()
    _migrate_auth_schema()
    _migrate_payout_schema()
    _migrate_scheduler_state_schema()  # ← Nová migrace


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
