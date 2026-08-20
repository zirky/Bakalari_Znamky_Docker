from __future__ import annotations

from calendar import monthrange
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


PRAGUE_TIMEZONE = ZoneInfo('Europe/Prague')
SCHEDULE_TIME = time(hour=20, minute=0)


def local_now() -> datetime:
    return datetime.now(PRAGUE_TIMEZONE)


def to_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError(
            'Čas pro plánování musí obsahovat časové pásmo'
        )

    return value.astimezone(
        ZoneInfo('UTC')
    ).replace(tzinfo=None)


def from_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is not None:
        raise ValueError(
            'Čas uložený v databázi musí být UTC bez časového pásma'
        )

    return value.replace(
        tzinfo=ZoneInfo('UTC')
    ).astimezone(PRAGUE_TIMEZONE)


def next_weekly_sync(
    now: datetime | None = None,
) -> datetime:
    current = now or local_now()

    if current.tzinfo is None:
        raise ValueError(
            'Čas pro plánování musí obsahovat časové pásmo'
        )

    local = current.astimezone(PRAGUE_TIMEZONE)
    days_until_sunday = (6 - local.weekday()) % 7
    candidate_date = local.date() + timedelta(
        days=days_until_sunday
    )
    candidate = datetime.combine(
        candidate_date,
        SCHEDULE_TIME,
        tzinfo=PRAGUE_TIMEZONE,
    )

    if candidate <= local:
        candidate += timedelta(days=7)

    return to_utc_naive(candidate)


def next_monthly_sync(
    now: datetime | None = None,
) -> datetime:
    current = now or local_now()

    if current.tzinfo is None:
        raise ValueError(
            'Čas pro plánování musí obsahovat časové pásmo'
        )

    local = current.astimezone(PRAGUE_TIMEZONE)
    last_day = monthrange(
        local.year,
        local.month,
    )[1]
    candidate = datetime(
        local.year,
        local.month,
        last_day,
        SCHEDULE_TIME.hour,
        SCHEDULE_TIME.minute,
        tzinfo=PRAGUE_TIMEZONE,
    )

    if candidate <= local:
        if local.month == 12:
            year = local.year + 1
            month = 1
        else:
            year = local.year
            month = local.month + 1

        last_day = monthrange(year, month)[1]
        candidate = datetime(
            year,
            month,
            last_day,
            SCHEDULE_TIME.hour,
            SCHEDULE_TIME.minute,
            tzinfo=PRAGUE_TIMEZONE,
        )

    return to_utc_naive(candidate)


def next_sync_at(
    interval: str,
    now: datetime | None = None,
) -> datetime | None:
    if interval == 'weekly':
        return next_weekly_sync(now)

    if interval == 'monthly':
        return next_monthly_sync(now)

    if interval == 'manual':
        return None

    raise ValueError(
        f'Neplatný interval synchronizace: {interval}'
    )
