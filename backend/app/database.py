from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from datetime import datetime
from typing import Generator

from .models import Base


DATABASE_URL = "sqlite:///./bakalari.db"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}, echo=False
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    migrate_sync_state(engine)
    migrate_timetable_entries(engine)


def migrate_sync_state(engine) -> None:
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE sync_state ADD COLUMN next_sync_at DATETIME"))
        except:
            pass
        try:
            conn.execute(text("ALTER TABLE sync_state ADD COLUMN sync_started_at DATETIME"))
        except:
            pass
        try:
            conn.execute(text("ALTER TABLE sync_state ADD COLUMN last_sync_error TEXT"))
        except:
            pass
        try:
            conn.execute(text("ALTER TABLE sync_state ADD COLUMN consecutive_failures INTEGER DEFAULT 0"))
        except:
            pass
        conn.commit()


def migrate_timetable_entries(engine) -> None:
    with engine.connect() as conn:
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS timetable_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            child_id INTEGER NOT NULL,
            day_of_week INTEGER NOT NULL,
            lesson_number INTEGER NOT NULL,
            subject TEXT NOT NULL,
            room TEXT,
            teacher TEXT,
            note TEXT,
            valid_from DATE,
            valid_to DATE,
            FOREIGN KEY (child_id) REFERENCES children(id) ON DELETE CASCADE
        )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_timetable_child ON timetable_entries(child_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_timetable_day ON timetable_entries(day_of_week, lesson_number)"))
        conn.commit()
