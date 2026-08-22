from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session, declarative_base
from datetime import datetime
from typing import Generator

DATABASE_URL = "sqlite:////app.db"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}, echo=False
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

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
            day_of_week INTEGER NOT NULL,
            lesson_number INTEGER NOT NULL,
            subject TEXT NOT NULL,
            room TEXT,
            teacher TEXT,
            note TEXT,
            valid_from DATE,
            valid_to DATE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """))
        conn.commit()
