from datetime import date, datetime
import json
from uuid import uuid4

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session as DbSession

from .auth import COOKIE_NAME, current_parent, delete_session, get_db
from .models import (
    AppSetting,
    Grade,
    Payout,
    PayoutAudit,
    Reward,
    RewardRule,
    SyncRun,
    SyncState,
    TimetableEntry,
    Child,
)
from .school_year import school_year_for_date
from .services.bakalari import BakalariService
from .services.lnbits import (
    LnAddressResolutionError,
    LnbitsPaymentError,
    LnbitsService,
)
from .services.rates import RateService
from .services.sync_schedule import next_sync_at


router = APIRouter(prefix='/api')


class RuleIn(BaseModel):
    grade_value: str
    reward_czk: int
    active: bool = True


class SyncIn(BaseModel):
    from_date: date | None = None
    mode: str = 'normal'


class SettingsIn(BaseModel):
    start_date: str = '2026-01-01'
    sync_interval: str = 'manual'
    payout_threshold_czk: int = 100
    ln_address: str = ''
    payout_mode: str = 'disabled'


class PayoutDraftIn(BaseModel):
    pass


def _get_setting(
    db: DbSession,
    key: str,
    default: str = '',
) -> str:
    item = db.query(AppSetting).filter_by(key=key).first()
    return item.value if item and item.value is not None else default


def _set_setting(
    db: DbSession,
    key: str,
    value: str,
) -> None:
    item = db.query(AppSetting).filter_by(key=key).first()

    if item:
        item.value = value
    else:
        db.add(AppSetting(key=key, value=value))


def _configured_start_date(db: DbSession) -> date:
    value = _get_setting(
        db,
        'start_date',
        '2026-01-01',
    )

    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            422,
            'Neplatné počáteční datum synchronizace',
        ) from exc


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


def _active_reward_query(db: DbSession):
    return db.query(Reward).join(
        Grade,
        Reward.grade_id == Grade.id,
    ).filter(
        Reward.status == 'pending',
        Grade.active_in_sync.is_(True),
    )


def _refresh_running_balance(
    db: DbSession,
    state: SyncState,
) -> int:
    balance = (
        _active_reward_query(db)
        .with_entities(
            func.coalesce(func.sum(Reward.amount_czk), 0)
        )
        .scalar()
        or 0
    )

    state.running_balance_czk = int(balance)
    return state.running_balance_czk


def _datetime_payload(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _sync_state_payload(state: SyncState) -> dict:
    balance = int(state.running_balance_czk or 0)

    return {
        'last_sync_at': _datetime_payload(
            state.last_sync_at
        ),
        'next_sync_at': _datetime_payload(
            state.next_sync_at
        ),
        'sync_started_at': _datetime_payload(
            state.sync_started_at
        ),
        'sync_from_date': (
            state.sync_from_date.isoformat()
            if state.sync_from_date
            else None
        ),
        'sync_status': state.sync_status,
        'last_sync_error': state.last_sync_error,
        'consecutive_failures': int(
            state.consecutive_failures or 0
        ),
        'running_balance_czk': balance,
        'payout_eligible_czk': max(balance, 0),
    }


def _audit(
    db: DbSession,
    payout_id: int,
    event: str,
    details: dict,
) -> None:
    db.add(
        PayoutAudit(
            payout_id=payout_id,
            event=event,
            details=json.dumps(
                details,
                ensure_ascii=False,
            ),
        )
    )


@router.post('/auth/parent/logout')
def logout(
    response: Response,
    session_token: str | None = Cookie(
        default=None,
        alias=COOKIE_NAME,
    ),
    db: DbSession = Depends(get_db),
):
    delete_session(response, session_token, db)
    return {'authenticated': False}


@router.get('/parent/dashboard')
def parent_dashboard(
    _: object = Depends(current_parent),
    db: DbSession = Depends(get_db),
):
    total = (
        _active_reward_query(db)
        .with_entities(
            func.coalesce(func.sum(Reward.amount_czk), 0)
        )
        .scalar()
        or 0
    )

    return {
        'pending_reward_czk': total,
        'grades_count': db.query(
            func.count(Grade.id)
        ).scalar() or 0,
        'pending_rewards_count': _active_reward_query(db).count(),
    }


@router.get('/parent/grades')
def parent_grades(
    _: object = Depends(current_parent),
    db: DbSession = Depends(get_db),
):
    grades = db.query(Grade).order_by(
        Grade.grade_date.desc()
    ).all()

    return [
        {
            'id': grade.id,
            'subject': grade.subject,
            'grade_value': grade.grade_value,
            'grade_date': grade.grade_date.isoformat(),
            'description': grade.description,
        }
        for grade in grades
    ]


@router.get('/parent/reward-rules')
def get_rules(
    _: object = Depends(current_parent),
    db: DbSession = Depends(get_db),
):
    rules = db.query(RewardRule).order_by(
        RewardRule.grade_value
    ).all()

    return [
        {
            'id': rule.id,
            'grade_value': rule.grade_value,
            'reward_czk': rule.reward_czk,
            'active': rule.active,
        }
        for rule in rules
    ]


@router.post('/parent/reward-rules')
def add_rule(
    payload: RuleIn,
    _: object = Depends(current_parent),
    db: DbSession = Depends(get_db),
):
    if db.query(RewardRule).filter_by(
        grade_value=payload.grade_value
    ).first():
        raise HTTPException(
            409,
            'Pravidlo již existuje',
        )

    rule = RewardRule(**payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)

    return {
        'id': rule.id,
        'grade_value': rule.grade_value,
        'reward_czk': rule.reward_czk,
        'active': rule.active,
    }


@router.put('/parent/reward-rules/{rule_id}')
def update_rule(
    rule_id: int,
    payload: RuleIn,
    _: object = Depends(current_parent),
    db: DbSession = Depends(get_db),
):
    rule = db.get(RewardRule, rule_id)

    if not rule:
        raise HTTPException(
            404,
            'Pravidlo nebylo nalezeno',
        )

    duplicate = db.query(RewardRule).filter(
        RewardRule.grade_value == payload.grade_value,
        RewardRule.id != rule_id,
    ).first()

    if duplicate:
        raise HTTPException(
            409,
            'Pravidlo pro tuto známku již existuje',
        )

    rule.grade_value = payload.grade_value
    rule.reward_czk = payload.reward_czk
    rule.active = payload.active
    db.commit()

    return {
        'id': rule.id,
        'grade_value': rule.grade_value,
        'reward_czk': rule.reward_czk,
        'active': rule.active,
    }


@router.delete('/parent/reward-rules/{rule_id}')
def delete_rule(
    rule_id: int,
    _: object = Depends(current_parent),
    db: DbSession = Depends(get_db),
):
    rule = db.get(RewardRule, rule_id)

    if not rule:
        raise HTTPException(
            404,
            'Pravidlo nebylo nalezeno',
        )

    db.delete(rule)
    db.commit()

    return {
        'deleted': True,
        'id': rule_id,
    }


@router.get('/parent/settings')
def get_settings(
    _: object = Depends(current_parent),
    db: DbSession = Depends(get_db),
):
    values = {
        item.key: item.value
        for item in db.query(AppSetting).all()
    }

    return {
        'start_date': values.get(
            'start_date',
            '2026-01-01',
        ),
        'sync_interval': values.get(
            'sync_interval',
            'manual',
        ),
        'payout_threshold_czk': int(
            values.get(
                'payout_threshold_czk',
                '100',
            )
        ),
        'ln_address': values.get(
            'ln_address',
            '',
        ),
        'payout_mode': values.get(
            'payout_mode',
            'disabled',
        ),
    }


@router.put('/parent/settings')
def save_settings(
    payload: SettingsIn,
    _: object = Depends(current_parent),
    db: DbSession = Depends(get_db),
):
    if payload.payout_mode not in {
        'disabled',
        'draft',
        'manual',
        'scheduler',
    }:
        raise HTTPException(
            422,
            'Neplatný režim výplaty',
        )

    if payload.sync_interval not in {
        'manual',
        'weekly',
        'monthly',
    }:
        raise HTTPException(
            422,
            'Neplatný interval synchronizace',
        )

    try:
        date.fromisoformat(payload.start_date)
    except ValueError as exc:
        raise HTTPException(
            422,
            'Neplatné počáteční datum synchronizace',
        ) from exc

    previous_interval = _get_setting(
        db,
        'sync_interval',
        'manual',
    )

    for key, value in payload.model_dump().items():
        _set_setting(db, key, str(value))

    state = _get_sync_state(db)

    if payload.sync_interval == 'manual':
        state.next_sync_at = None

        if state.sync_status != 'running':
            state.sync_status = 'manual'
            state.sync_started_at = None

    elif previous_interval != payload.sync_interval:
        state.next_sync_at = datetime.utcnow()
        state.sync_status = 'scheduled'
        state.sync_started_at = None
        state.last_sync_error = None
        state.consecutive_failures = 0

    elif state.next_sync_at is None:
        state.next_sync_at = datetime.utcnow()
        state.sync_status = 'scheduled'
        state.sync_started_at = None

    db.commit()

    result = payload.model_dump()
    result.update({
        'next_sync_at': _datetime_payload(
            state.next_sync_at
        ),
        'sync_status': state.sync_status,
    })

    return result


@router.get('/parent/sync/status')
def sync_status(
    _: object = Depends(current_parent),
    db: DbSession = Depends(get_db),
):
    state = _get_sync_state(db)
    _refresh_running_balance(db, state)

    positive = (
        _active_reward_query(db)
        .filter(Reward.amount_czk > 0)
        .with_entities(
            func.coalesce(func.sum(Reward.amount_czk), 0)
        )
        .scalar()
        or 0
    )

    negative = (
        _active_reward_query(db)
        .filter(Reward.amount_czk < 0)
        .with_entities(
            func.coalesce(func.sum(Reward.amount_czk), 0)
        )
        .scalar()
        or 0
    )

    db.commit()

    payload = _sync_state_payload(state)
    payload.update({
        'positive_pending_czk': int(positive),
        'negative_pending_czk': int(negative),
    })

    return payload


@router.post('/parent/sync')
def sync(
    payload: SyncIn,
    _: object = Depends(current_parent),
    db: DbSession = Depends(get_db),
):
    if payload.mode not in {'normal', 'backtest'}:
        raise HTTPException(
            422,
            'Neplatný režim synchronizace',
        )

    state = _get_sync_state(db)

    if state.sync_status == 'running':
        raise HTTPException(
            409,
            'Synchronizace již probíhá',
        )

    requested_from_date = (
        payload.from_date
        or _configured_start_date(db)
    )

    run = SyncRun(
        mode=payload.mode,
        from_date=requested_from_date,
        status='running',
    )

    state.sync_status = 'running'
    state.sync_started_at = datetime.utcnow()
    state.sync_from_date = requested_from_date
    state.last_sync_error = None

    db.add(run)
    db.commit()

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
                    reward.calculation_type = payload.mode
            elif reward is None:
                db.add(
                    Reward(
                        grade_id=grade.id,
                        amount_czk=rule.reward_czk,
                        calculation_type=payload.mode,
                    )
                )
            elif reward.status == 'pending':
                reward.amount_czk = rule.reward_czk
                reward.calculation_type = payload.mode

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
        state.last_sync_error = None
        state.consecutive_failures = 0

        _refresh_running_balance(db, state)
        db.commit()

        return {
            'status': 'success',
            'mode': payload.mode,
            'grades_found': run.grades_found,
            'grades_new': run.grades_new,
            'running_balance_czk': state.running_balance_czk,
            'next_sync_at': _datetime_payload(
                state.next_sync_at
            ),
            'payout': None,
        }

    except NotImplementedError as exc:
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

        raise HTTPException(501, str(exc))

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

        raise HTTPException(
            502,
            'Synchronizace selhala',
        ) from exc


@router.get('/parent/payout/preview')
def payout_preview(
    _: object = Depends(current_parent),
    db: DbSession = Depends(get_db),
):
    state = _get_sync_state(db)
    _refresh_running_balance(db, state)
    db.commit()

    balance = int(state.running_balance_czk or 0)
    pending_count = _active_reward_query(db).count()
    threshold = int(
        _get_setting(
            db,
            'payout_threshold_czk',
            '100',
        ) or '100'
    )
    ln_address = _get_setting(
        db,
        'ln_address',
    ).strip()

    eligible = max(balance, 0)
    estimated_sats = None
    rate_available = False

    if eligible > 0:
        try:
            czk_per_btc = RateService().get_czk_per_btc()
            estimated_sats = RateService().czk_to_sats(
                eligible,
                czk_per_btc,
            )
            rate_available = True
        except (RuntimeError, ValueError):
            pass

    return {
        'pending_reward_czk': balance,
        'payout_eligible_czk': eligible,
        'pending_rewards_count': pending_count,
        'payout_threshold_czk': threshold,
        'threshold_reached': eligible >= threshold,
        'ln_address_configured': bool(
            ln_address and '@' in ln_address
        ),
        'estimated_sats': estimated_sats,
        'rate_available': rate_available,
        'payment_will_be_sent': False,
    }


@router.post('/parent/payout/draft')
def create_payout_draft(
    _: PayoutDraftIn,
    __: object = Depends(current_parent),
    db: DbSession = Depends(get_db),
):
    if _get_setting(
        db,
        'payout_mode',
        'disabled',
    ) != 'draft':
        raise HTTPException(
            409,
            'Draft payout není povolený',
        )

    state = _get_sync_state(db)
    _refresh_running_balance(db, state)

    balance = int(state.running_balance_czk or 0)
    eligible = max(balance, 0)
    threshold = int(
        _get_setting(
            db,
            'payout_threshold_czk',
            '100',
        ) or '100'
    )
    ln_address = _get_setting(
        db,
        'ln_address',
    ).strip()

    if eligible <= 0:
        raise HTTPException(
            409,
            'Kladný zůstatek k výplatě není k dispozici',
        )

    if eligible < threshold:
        raise HTTPException(
            409,
            'Zůstatek nedosahuje limitu výplaty',
        )

    if not ln_address or '@' not in ln_address:
        raise HTTPException(
            409,
            'Lightning adresa není nastavena',
        )

    try:
        czk_per_btc = RateService().get_czk_per_btc()
        amount_sats = RateService().czk_to_sats(
            eligible,
            czk_per_btc,
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(
            503,
            'Kurz pro přepočet není dostupný',
        ) from exc

    active_draft = db.query(Payout).filter(
        Payout.status == 'draft'
    ).first()

    if active_draft:
        return {
            'status': active_draft.status,
            'payout_id': active_draft.id,
            'amount_czk': active_draft.amount_czk,
            'amount_sats': active_draft.amount_sats,
            'ln_address': active_draft.ln_address,
            'payment_will_be_sent': False,
        }

    payout = Payout(
        ln_address=ln_address,
        amount_czk=eligible,
        amount_sats=amount_sats,
        idempotency_key=uuid4().hex,
        status='draft',
    )

    db.add(payout)
    db.flush()

    _audit(
        db,
        payout.id,
        'draft_created',
        {
            'amount_czk': eligible,
            'amount_sats': amount_sats,
            'balance_czk': balance,
            'ln_address_configured': True,
        },
    )

    db.commit()
    db.refresh(payout)

    return {
        'status': payout.status,
        'payout_id': payout.id,
        'amount_czk': payout.amount_czk,
        'amount_sats': payout.amount_sats,
        'ln_address': payout.ln_address,
        'idempotency_key': payout.idempotency_key,
        'payment_will_be_sent': False,
    }


@router.post('/parent/payout/{payout_id}/simulate-confirm')
def simulate_confirm_payout(
    payout_id: int,
    _: object = Depends(current_parent),
    db: DbSession = Depends(get_db),
):
    payout = db.get(Payout, payout_id)

    if payout is None:
        raise HTTPException(
            404,
            'Payout draft nebyl nalezen',
        )

    if payout.status == 'simulated':
        return {
            'status': 'simulated',
            'payout_id': payout.id,
            'payment_will_be_sent': False,
        }

    if payout.status != 'draft':
        raise HTTPException(
            409,
            f'Payout má stav {payout.status} a nelze ho simulovat',
        )

    state = _get_sync_state(db)
    _refresh_running_balance(db, state)
    current_balance = int(state.running_balance_czk or 0)

    if current_balance != payout.amount_czk:
        payout.status = 'stale'
        payout.error_message = (
            'Stav účtu se od vytvoření draftu změnil.'
        )

        _audit(
            db,
            payout.id,
            'draft_stale',
            {
                'draft_amount_czk': payout.amount_czk,
                'current_balance_czk': current_balance,
            },
        )

        db.commit()

        raise HTTPException(
            409,
            'Stav účtu se změnil; vytvoř nový draft',
        )

    payout.status = 'simulated'
    payout.completed_at = datetime.utcnow()

    _audit(
        db,
        payout.id,
        'simulated_confirmation',
        {
            'amount_czk': payout.amount_czk,
            'amount_sats': payout.amount_sats,
            'payment_will_be_sent': False,
        },
    )

    db.commit()

    return {
        'status': 'simulated',
        'payout_id': payout.id,
        'amount_czk': payout.amount_czk,
        'amount_sats': payout.amount_sats,
        'payment_will_be_sent': False,
    }


@router.get('/parent/payouts')
def list_payouts(
    _: object = Depends(current_parent),
    db: DbSession = Depends(get_db),
):
    payouts = db.query(Payout).order_by(
        Payout.created_at.desc()
    ).all()

    return [
        {
            'id': payout.id,
            'ln_address': payout.ln_address,
            'amount_czk': payout.amount_czk,
            'amount_sats': payout.amount_sats,
            'status': payout.status,
            'idempotency_key': payout.idempotency_key,
            'error_message': payout.error_message,
            'created_at': payout.created_at.isoformat(),
            'completed_at': (
                payout.completed_at.isoformat()
                if payout.completed_at
                else None
            ),
        }
        for payout in payouts
    ]


@router.post('/parent/payout')
def manual_payout(
    _: object = Depends(current_parent),
    db: DbSession = Depends(get_db),
):
    if _get_setting(
        db,
        'payout_mode',
        'disabled',
    ) != 'manual':
        raise HTTPException(
            409,
            'Ruční payout není povolený',
        )

    state = _get_sync_state(db)
    _refresh_running_balance(db, state)

    balance = int(state.running_balance_czk or 0)
    eligible = max(balance, 0)
    threshold = int(
        _get_setting(
            db,
            'payout_threshold_czk',
            '100',
        ) or '100'
    )
    ln_address = _get_setting(
        db,
        'ln_address',
    ).strip()

    if eligible <= 0:
        raise HTTPException(
            409,
            'Kladný zůstatek k výplatě není k dispozici',
        )

    if eligible < threshold:
        raise HTTPException(
            409,
            'Zůstatek nedosahuje limitu výplaty',
        )

    if not ln_address or '@' not in ln_address:
        raise HTTPException(
            409,
            'Lightning adresa není nastavena',
        )

    existing = db.query(Payout).filter(
        Payout.status.in_(['pending', 'paid']),
        Payout.amount_czk == eligible,
        Payout.ln_address == ln_address,
    ).first()

    if existing:
        return {
            'status': existing.status,
            'payout_id': existing.id,
            'amount_czk': existing.amount_czk,
            'amount_sats': existing.amount_sats,
            'payment_hash': existing.payment_hash,
        }

    try:
        czk_per_btc = RateService().get_czk_per_btc()
        amount_sats = RateService().czk_to_sats(
            eligible,
            czk_per_btc,
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(
            503,
            'Kurz pro přepočet není dostupný',
        ) from exc

    payout = Payout(
        ln_address=ln_address,
        amount_czk=eligible,
        amount_sats=amount_sats,
        idempotency_key=uuid4().hex,
        status='pending',
    )

    db.add(payout)
    db.flush()

    _audit(
        db,
        payout.id,
        'payment_started',
        {
            'amount_czk': eligible,
            'amount_sats': amount_sats,
            'ln_address': ln_address,
        },
    )

    try:
        service = LnbitsService()
        invoice = service.resolve_ln_address(
            ln_address,
            amount_sats,
        )
        result = service.pay_invoice(invoice)

        payout.invoice = invoice
        payout.payment_hash = result.get('payment_hash')
        payout.status = 'paid'
        payout.completed_at = datetime.utcnow()

        db.query(Reward).filter(
            Reward.status == 'pending'
        ).update({
            'status': 'paid',
        })

        _audit(
            db,
            payout.id,
            'payment_succeeded',
            {
                'amount_czk': eligible,
                'amount_sats': amount_sats,
                'payment_hash': payout.payment_hash,
            },
        )

        db.commit()

        return {
            'status': 'paid',
            'payout_id': payout.id,
            'amount_czk': eligible,
            'amount_sats': amount_sats,
            'payment_hash': payout.payment_hash,
        }

    except (
        LnAddressResolutionError,
        LnbitsPaymentError,
        RuntimeError,
    ) as exc:
        payout.status = 'failed'
        payout.error_message = str(exc)
        payout.completed_at = datetime.utcnow()

        _audit(
            db,
            payout.id,
            'payment_failed',
            {
                'error': str(exc),
            },
        )

        db.commit()

        raise HTTPException(
            502,
            'Platbu se nepodařilo odeslat',
        ) from exc


def _current_school_year() -> str:
    return school_year_for_date(date.today())


def _available_school_years(db: DbSession) -> list[str]:
    years = [
        school_year
        for (school_year,) in db.query(Grade.school_year)
        .filter(Grade.school_year.is_not(None))
        .distinct()
        .order_by(Grade.school_year.desc())
        .all()
    ]
    active_school_year = _current_school_year()

    if active_school_year not in years:
        years.insert(0, active_school_year)

    return years


def _validate_school_year(value: str) -> str:
    if len(value) != 9 or value[4] != '/':
        raise HTTPException(422, 'Neplatný školní rok')

    try:
        start_year = int(value[:4])
        end_year = int(value[5:])
    except ValueError as exc:
        raise HTTPException(422, 'Neplatný školní rok') from exc

    if end_year != start_year + 1:
        raise HTTPException(422, 'Neplatný školní rok')

    return value


@router.get('/school-years')
def school_years(
    db: DbSession = Depends(get_db),
):
    active_school_year = _current_school_year()

    return {
        'active_school_year': active_school_year,
        'available_school_years': _available_school_years(db),
    }


@router.get('/child/overview')
def child_overview(
    school_year: str | None = None,
    db: DbSession = Depends(get_db),
):
    active_school_year = _current_school_year()
    selected_school_year = (
        _validate_school_year(school_year)
        if school_year
        else active_school_year
    )

    grades = db.query(Grade).filter(
        Grade.school_year == selected_school_year,
    ).order_by(
        Grade.grade_date.desc(),
        Grade.id.desc(),
    ).all()

    subject_values: dict[str, list[int]] = {}
    grade_items = []

    for grade in grades:
        grade_items.append({
            'id': grade.id,
            'subject': grade.subject,
            'grade_value': grade.grade_value,
            'grade_date': grade.grade_date.isoformat(),
            'description': grade.description,
        })

        if grade.grade_value in {'1', '2', '3', '4', '5'}:
            subject_values.setdefault(
                grade.subject,
                [],
            ).append(int(grade.grade_value))

    subjects = [
        {
            'subject': subject,
            'grades_count': len(values),
            'average': round(
                sum(values) / len(values),
                2,
            ),
            'average_grades_count': len(values),
        }
        for subject, values in sorted(subject_values.items())
    ]

    paid_czk = db.query(
        func.coalesce(func.sum(Payout.amount_czk), 0)
    ).filter(
        Payout.status == 'paid'
    ).scalar() or 0

    paid_payout_count = db.query(Payout).filter(
        Payout.status == 'paid'
    ).count()

    return {
        'school_year': selected_school_year,
        'selected_school_year': selected_school_year,
        'active_school_year': active_school_year,
        'available_school_years': _available_school_years(db),
        'grades': grade_items,
        'subjects': subjects,
        'reward_summary': {
            'paid_czk': int(paid_czk),
            'paid_payout_count': paid_payout_count,
        },
    }


@router.get('/child/summary')
def child_summary(
    db: DbSession = Depends(get_db),
):
    total = db.query(
        func.coalesce(func.sum(Reward.amount_czk), 0)
    ).scalar() or 0

    subjects = db.query(
        Grade.subject,
        func.count(Grade.id).label('count'),
    ).group_by(
        Grade.subject
    ).all()

    return {
        'reward_czk': total,
        'subjects': [
            {
                'subject': subject,
                'grades_count': count,
            }
            for subject, count in subjects
        ],
    }


@router.get('/child/timetable')
async def get_child_timetable(
    child_id: int,
    db: DbSession = Depends(get_db),
    current_user: object = Depends(current_parent),
):
    """
    Získá rozvrh hodin pro dané dítě.
    """
    child = db.query(Child).filter(
        Child.id == child_id,
        Child.parent_user_id == current_user.id
    ).first()
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")

    entries = db.query(TimetableEntry).filter(
        TimetableEntry.child_id == child_id
    ).order_by(
        TimetableEntry.day_of_week,
        TimetableEntry.lesson_number
    ).all()

    return [
        {
            'id': e.id,
            'day_of_week': e.day_of_week,
            'lesson_number': e.lesson_number,
            'subject': e.subject,
            'room': e.room,
            'teacher': e.teacher,
            'note': e.note,
            'valid_from': e.valid_from.isoformat() if e.valid_from else None,
            'valid_to': e.valid_to.isoformat() if e.valid_to else None,
        }
        for e in entries
    ]


@router.post('/child/timetable/sync')
async def sync_child_timetable(
    payload: dict,
    db: DbSession = Depends(get_db),
    current_user: object = Depends(current_parent),
):
    """
    Synchronizuje rozvrh hodin pro dané dítě.
    payload: {"child_id": int, "entries": [...]}
    """
    child_id = payload["child_id"]
    new_entries = payload["entries"]

    child = db.query(Child).filter(
        Child.id == child_id,
        Child.parent_user_id == current_user.id
    ).first()
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")

    db.query(TimetableEntry).filter(
        TimetableEntry.child_id == child_id
    ).delete()

    for e in new_entries:
        entry = TimetableEntry(
            child_id=child_id,
            day_of_week=e["day_of_week"],
            lesson_number=e["lesson_number"],
            subject=e["subject"],
            room=e.get("room"),
            teacher=e.get("teacher"),
            note=e.get("note"),
            valid_from=date.fromisoformat(e["valid_from"]) if e.get("valid_from") else None,
            valid_to=date.fromisoformat(e["valid_to"]) if e.get("valid_to") else None,
        )
        db.add(entry)

    db.commit()
    return {"status": "ok", "count": len(new_entries)}
