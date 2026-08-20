from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session as DbSession

from ..config import get_settings
from ..database import SessionLocal
from ..models import AppSetting, SyncState


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
            'Nalezen neúplný synchronizační běh bez času zahájení.'
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
        'Synchronizace byla označena jako neúspěšná po překročení '
        f'timeoutu {timeout_minutes} minut.'
    )
    state.sync_started_at = None
    state.consecutive_failures = int(
        state.consecutive_failures or 0
    ) + 1

    return True


def check_sync_scheduler() -> None:
    """
    První infrastrukturní verze scheduleru.

    Worker pouze ověřuje uložený stav a případně označí zaseknutý běh
    synchronizace jako failed. Záměrně nespouští Bakaláři synchronizaci,
    payout ani žádnou LNbits operaci.
    """
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
                'Neplatný sync_interval %r; automatická synchronizace '
                'zůstává vypnutá.',
                interval,
            )

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
        10,
    )

    logger.info(
        'Worker synchronizace byl spuštěn; kontrolní interval: %s s.',
        poll_seconds,
    )

    try:
        while True:
            check_sync_scheduler()
            await asyncio.sleep(poll_seconds)
    except asyncio.CancelledError:
        logger.info('Worker synchronizace byl ukončen.')
        raise
