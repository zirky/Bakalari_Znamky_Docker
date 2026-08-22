from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings
from .models import Base, Grade, SyncState, TimetableEntry


engine = create_engine(
    get_settings().database_url,
    connect_args={'check_same_thread': False},
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)

    # Vytvoř výchozí·°SyncState, pokud neexistuje
    db = SessionLocal()
    try:
        if not db.query(SyncState).filter_by(id=1).first():
            db.add(
                SyncState(
                    id=1,
                    sync_status='never',
                    running_balance_czk=0,
                )
            )
            db.commit()
    finally:
        db.close()

    # Zajisti, že tabulka timetable_entries existuje
    TimetableEntry.__table__.create(bind=engine, checkfirst=True)

    # Zajisti, že tabulka grades existuje
    Grade.__table__.create(bind=engine, checkfirst=True)
