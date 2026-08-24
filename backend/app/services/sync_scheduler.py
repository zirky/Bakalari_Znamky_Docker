from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, date

from sqlalchemy.orm import Session as DbSession

from ..config import get_settings
from ..database import SessionLocal
from ..models import AppSetting, Grade, Reward, RewardRule, SyncRun, SyncState, TimetableEntry
from ..school_year import school_year_for_date
from ..services.bakalari import BakalariService
from ..services.sync_schedule import next_sync_at


logger = logging.getLogger(__name__)


def _get_setting(
    db: DbSession,
    key: str,
    default: str = '',
) -> str:
    item = db.query(AppSetting).filter_by(key=key).first()

    if item is None or item.value is None:
        return default

    return item.value


def _get_sync_state(db: DbSession) -> SyncState:
    state = db.get(SyncState, 1)

    if state is None:
        state = SyncState(
            id=1,
            sync_status='never',
            running_balance_czk=0,
        )
        db.add(state)
        db.flush()

    return state


def _recover_stale_run(
    state: SyncState,
    now: datetime,
) -> bool:
    timeout_minutes = get_settings().sync_run_timeout_minutes

    if state.sync_status != 'running':
        return False

    if state.sync_started_at is None:
        state.sync_status = 'failed'
        state.last_sync_error = (
            'Nalezen ne�pln� synchroniza�n� b�h bez �asu zah�jen�.'
        )
        state.consecutive_failures = int(
            state.consecutive_failures or 0
        ) + 1
        return True

    timeout_at = state.sync_started_at + timedelta(
        minutes=timeout_minutes
    )

    if timeout_at > now:
        return False

    state.sync_status = 'failed'
    state.last_sync_error = (
        'Synchronizace byla ozna�ena jako ne�sp�šn� po p�ekro�en� '
        f'timeoutu {timeout_minutes} minut.'
    )
    state.sync_started_at = None
    state.consecutive_failures = int(
        state.consecutive_failures or 0
    ) + 1

    return True


def _run_bakalari_sync(db: DbSession, state: SyncState) -> None:
    """
    Spust� synchronizaci s Bakal��i.
    Stejn� k�d jako v endpointu POST /api/parent/sync.
    """
    requested_from_date = state.sync_from_date

    run = SyncRun(
        mode='normal',
        from_date=requested_from_date,
        status='running',
    )

    state.sync_status = 'running'
    state.sync_started_at = datetime.utcnow()
    state.last_sync_error = None

    db.add(run)
    db.flush()

    try:
        fetched = BakalariService().fetch_grades()
        run.grades_found = len(fetched)
        fetched_ids = set()

        for item in fetched:
            external_id = str(item['external_id'])
            fetched_ids.add(external_id)
            in_range = item['grade_date'] >= requested_from_date

            grade = db.query(Grade).filter_by(
                external_id=external_id
            ).first()

            if grade is None:
                grade = Grade(
                    **item,
                    school_year=school_year_for_date(
                        item['grade_date']
                    ),
                    active_in_sync=in_range,
                )
                db.add(grade)
                db.flush()
                run.grades_new += 1
            else:
                grade.subject = item['subject']
                grade.grade_value = item['grade_value']
                grade.grade_date = item['grade_date']
                grade.school_year = school_year_for_date(
                    grade.grade_date
                )
                grade.description = item.get('description')
                grade.source = item.get(
                    'source',
                    grade.source,
                )
                grade.active_in_sync = in_range

            reward = db.query(Reward).filter_by(
                grade_id=grade.id
            ).first()

            rule = db.query(RewardRule).filter_by(
                grade_value=grade.grade_value,
                active=True,
            ).first()

            if not in_range:
                if (
                    reward is not None
                    and reward.status == 'pending'
                ):
                    reward.status = 'superseded'
                continue

            if (
                reward is not None
                and reward.status == 'superseded'
            ):
                reward.status = 'pending'

            if rule is None:
                if (
                    reward is not None
                    and reward.status == 'pending'
                ):
                    reward.amount_czk = 0
                    reward.calculation_type = 'normal'
            elif reward is None:
                db.add(
                    Reward(
                        grade_id=grade.id,
                        amount_czk=rule.reward_czk,
                        calculation_type='normal',
                    )
                )
            elif reward.status == 'pending':
                reward.amount_czk = rule.reward_czk
                reward.calculation_type = 'normal'

        for grade in db.query(Grade).filter(
            Grade.source == 'bakalari'
        ).all():
            if grade.external_id not in fetched_ids:
                grade.active_in_sync = False

                reward = db.query(Reward).filter_by(
                    grade_id=grade.id
                ).first()

                if (
                    reward is not None
                    and reward.status == 'pending'
                ):
                    reward.status = 'superseded'

        completed_at = datetime.utcnow()
        sync_interval = _get_setting(
            db,
            'sync_interval',
            'manual',
        )

        run.status = 'success'
        run.finished_at = completed_at

        state.sync_status = 'success'
        state.last_sync_at = completed_at
        state.next_sync_at = next_sync_at(
            sync_interval,
            now=completed_at.replace(
                tzinfo=datetime.now().astimezone().tzinfo
            ),
        )
        state.sync_started_at = None
        state.consecutive_failures = 0

        db.commit()

        logger.info(
            'Synchronizace �sp�šn� dokon�ena; nalezeno %d zn�mek, '
            'nov�ch %d; dalš� sync napl�nov�n na %s',
            run.grades_found,
            run.grades_new,
            state.next_sync_at.isoformat() if state.next_sync_at else 'N/A',
        )

    except Exception as exc:
        run.status = 'failed'
        run.error_message = str(exc)
        run.finished_at = datetime.utcnow()

        state.sync_status = 'failed'
        state.sync_started_at = None
        state.last_sync_error = str(exc)
        state.consecutive_failures = int(
            state.consecutive_failures or 0
        ) + 1

        db.commit()

        logger.exception(
            'Synchronizace selhala: %s',
            str(exc),
        )
        raise


def _sync_timetable(db: DbSession) -> None:
    """
    Synchronizuje rozvrh hodin z Bakal��.
    Spoušt� se nevisle na synchronizaci zn�mek (každ�ch 24 hodin).
    """
    try:
        # Z�skat rozvrh z Bakal��
        bakalari = BakalariService()
        timetable = bakalari.get_timetable()

        if not timetable:
            logger.info('Rozvrh nen� k dispozici.')
            return

        # Smazat star� rozvrh
        db.query(TimetableEntry).delete()

        # P�idat nov� rozvrh
        for lesson in timetable:
            entry = TimetableEntry(
                day_of_week=lesson['day'],
                lesson_number=lesson['hour'],
                subject=lesson['subject'],
                room=lesson.get('room'),
                teacher=lesson.get('teacher'),
                note=lesson.get('note'),
            )
            db.add(entry)

        db.commit()
        logger.info(f'Rozvrh synchronizov�n: {len(timetable)} hodin.')

    except Exception as exc:
        db.rollback()
        logger.exception(f'Synchronizace rozvrhu selhala: {exc}')


# Track last timetable sync per session (in-memory)
_last_timetable_sync: datetime | None = None


def check_sync_scheduler() -> None:
    """
    Kontrola scheduleru synchronizace.

    - Ozna�� zaseknut� b�h jako failed.
    - Pokud je next_sync_at v minulosti a interval nen� 'manual',
      spust� synchronizaci s Bakal��i.
    - Rozvrh synchronizuje nevisle (každ�ch 24 hodin).
    """
    global _last_timetable_sync

    db = SessionLocal()

    try:
        state = _get_sync_state(db)
        interval = _get_setting(
            db,
            'sync_interval',
            'manual',
        )
        now = datetime.utcnow()

        state_changed = _recover_stale_run(
            state,
            now,
        )

        if interval not in {'manual', 'weekly', 'monthly'}:
            logger.warning(
                'Neplatn� sync_interval %r; automatick� synchronizace '
                'z�st�v� vypnut�.',
                interval,
            )

        # Zkontroluj, zda je �as spustit synchronizaci
        if (
            interval in {'weekly', 'monthly'}
            and state.next_sync_at is not None
            and state.next_sync_at <= now
            and state.sync_status != 'running'
        ):
            logger.info(
                'Synchronizace je napl�novan� na %s; spoušt�m...',
                state.next_sync_at.isoformat(),
            )
            _run_bakalari_sync(db, state)
            state_changed = True

        # Synchronizuj rozvrh (každ�ch 24 hodin)
        if (
            _last_timetable_sync is None
            or (now - _last_timetable_sync) >= timedelta(hours=24)
        ):
            logger.info('Synchronizuji rozvrh hodin...')
            _sync_timetable(db)
            _last_timetable_sync = now

        if state_changed:
            db.commit()

    except Exception:
        db.rollback()
        logger.exception(
            'Kontrola scheduleru synchronizace selhala.'
        )

    finally:
        db.close()


async def run_sync_scheduler() -> None:
    settings = get_settings()
    poll_seconds = max(
        int(settings.sync_worker_poll_seconds),
        600,  # 10 minut
    )

    logger.info(
        'Worker synchronizace byl spuštěn; kontroln� interval: %s s.',
        poll_seconds,
    )

    try:
        while True:
            check_sync_scheduler()
            await asyncio.sleep(poll_seconds)
    except asyncio.CancelledError:
        logger.info('Worker synchronizace byl ukon�en.')
        raise
