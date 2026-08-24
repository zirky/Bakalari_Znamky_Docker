"""
Background worker that periodically syncs grades and timetable
from Bakaláře for all configured parents.

- Grades: synced according to settings (disabled/manual/weekly/monthly)
- Timetable: synced independently every 24 hours
"""

import logging
import time
from datetime import datetime, timedelta, date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import engine
from ..models import Parent, Settings, Grade, Child, TimetableEntry
from .bakalari import BakalariService

logger = logging.getLogger("uvicorn")


class SyncScheduler:
    """
    Periodically synchronizes grades and timetable for all parents
    that have Bakaláře credentials configured.
    
    - Grades: synced according to settings (disabled/manual/weekly/monthly)
    - Timetable: synced independently every 24 hours
    """

    def __init__(self, sync_interval_seconds: int = 600):
        self.sync_interval_seconds = sync_interval_seconds
        self.bakalari = BakalariService()
        self.last_timetable_sync: dict[int, datetime] = {}  # parent_id -> last sync time

    def run_once(self) -> None:
        """Run one synchronization cycle for all parents."""
        with Session(engine) as session:
            parents = session.execute(select(Parent)).scalars().all()

        for parent in parents:
            if not parent.bakalari_username or not parent.bakalari_password:
                continue

            try:
                self._sync_parent(parent)
            except Exception as e:
                logger.error(f"Error syncing parent {parent.id}: {e}")

    def _sync_parent(self, parent: Parent) -> None:
        """Synchronize grades and timetable for a single parent."""
        with Session(engine) as session:
            # Load settings
            settings = session.execute(
                select(Settings).where(Settings.parent_id == parent.id)
            ).scalars().first()

            if not settings:
                logger.warning(f"No settings for parent {parent.id}")
                return

            # Determine sync_from date
            sync_from = settings.sync_from_date
            if not sync_from:
                # Default to start of current school year (September 1st)
                now = datetime.now()
                sync_from = date(now.year - 1, 9, 1) if now.month < 9 else date(now.year, 9, 1)
                settings.sync_from_date = sync_from
                session.add(settings)
                session.commit()

            # Sync grades according to settings
            self._sync_grades_if_needed(session, parent, settings, sync_from)

            # Sync timetable independently (every 24 hours)
            self._sync_timetable_if_needed(session, parent)

    def _sync_grades_if_needed(self, session: Session, parent: Parent, settings: Settings, sync_from: date) -> None:
        """Synchronize grades if interval has passed."""
        # Check if sync is enabled
        if settings.sync_interval == "manual":
            return  # Manual sync only
        
        if settings.sync_interval == "disabled":
            return  # Sync disabled

        # Check if enough time has passed
        now = datetime.now()
        last_sync = settings.last_sync_at
        
        interval_map = {
            "weekly": timedelta(days=7),
            "monthly": timedelta(days=30),
        }
        
        required_interval = interval_map.get(settings.sync_interval, timedelta(days=7))
        
        if last_sync and (now - last_sync) < required_interval:
            return  # Not time yet

        # Perform sync
        self._sync_grades(session, parent, sync_from)
        
        # Update last sync time
        settings.last_sync_at = now
        session.add(settings)
        session.commit()

    def _sync_grades(self, session: Session, parent: Parent, sync_from: date) -> None:
        """Synchronize grades for a single parent."""
        try:
            subjects = self.bakalari.login_and_fetch_subjects(
                parent.bakalari_username,
                parent.bakalari_password,
            )
        except Exception as e:
            logger.error(f"Bakaláře login failed for {parent.id}: {e}")
            return

        for subject in subjects:
            for grade in subject['grades']:
                if grade['date'] < sync_from:
                    continue

                # Check if grade already exists
                exists = session.execute(
                    select(Grade).where(
                        Grade.parent_id == parent.id,
                        Grade.grade_date == grade['date'],
                        Grade.subject == grade['subject'],
                        Grade.grade_value == grade['grade'],
                    )
                ).scalars().first()

                if exists:
                    continue

                # Create new grade
                new_grade = Grade(
                    parent_id=parent.id,
                    grade_date=grade['date'],
                    subject=grade['subject'],
                    grade_value=grade['grade'],
                    description=grade.get('description', ''),
                )
                session.add(new_grade)

            session.commit()

    def _sync_timetable_if_needed(self, session: Session, parent: Parent) -> None:
        """Synchronize timetable if 24 hours have passed."""
        now = datetime.now()
        last_sync = self.last_timetable_sync.get(parent.id)
        
        # Sync every 24 hours
        if last_sync and (now - last_sync) < timedelta(hours=24):
            return  # Not time yet

        # Perform sync
        self._sync_timetable(session, parent)
        
        # Update last sync time
        self.last_timetable_sync[parent.id] = now

    def _sync_timetable(self, session: Session, parent: Parent) -> None:
        """Synchronize timetable for a single parent."""
        try:
            timetable = self.bakalari.get_timetable(
                parent.bakalari_username,
                parent.bakalari_password,
            )
        except Exception as e:
            logger.error(f"Bakaláře timetable fetch failed for {parent.id}: {e}")
            return

        if not timetable:
            logger.info(f"No timetable for parent {parent.id}")
            return

        # Smazat staré¿° rozvrh
        session.execute(
            TimetableEntry.__table__.delete()
        )

        # P?idat nový rozvrh
        for lesson in timetable:
            entry = TimetableEntry(
                day_of_week=lesson['day'],
                lesson_number=lesson['hour'],
                subject=lesson['subject'],
                room=lesson.get('room'),
                teacher=lesson.get('teacher'),
                note=lesson.get('note'),
            )
            session.add(entry)

        session.commit()
        logger.info(f"Timetable synced for parent {parent.id}: {len(timetable)} lessons")

    def start(self) -> None:
        """Start the background scheduler."""
        logger.info(f"Starting sync scheduler (interval: {self.sync_interval_seconds}s)")
        while True:
            self.run_once()
            time.sleep(self.sync_interval_seconds)
