from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy.orm import Session as DbSession
from sqlalchemy import func
import logging

from ..models import AppSetting, Payout, PayoutAudit, Reward, SyncState
from ..services.lnbits import LnbitsService, LnbitsPaymentError, LnAddressResolutionError
from ..services.rates import RateService


logger = logging.getLogger(__name__)


class PayoutMode(str, Enum):
    DISABLED = "disabled"
    MANUAL = "manual"
    DRAFT = "draft"
    SCHEDULER = "scheduler"


def _get_setting(db: DbSession, key: str, default: str = '') -> str:
    item = db.query(AppSetting).filter_by(key=key).first()
    return item.value if item and item.value is not None else default


def _get_pending_balance(db: DbSession) -> int:
    """Získá součet všech pending odměn."""
    balance = db.query(
        func.coalesce(func.sum(Reward.amount_czk), 0)
    ).filter(
        Reward.status == 'pending'
    ).scalar() or 0
    return int(balance)


def execute_payout(
    db: DbSession,
    state: SyncState,
    mode: str,
    *,
    amount_czk: int | None = None,
    ln_address: str | None = None,
    sync_id: int | None = None,
) -> dict[str, Any]:
    """
    Společná logika pro ruční i automatický payout.
    
    Podporované režimy:
    - 'disabled' / 'manual': okamžitý návrat {"status": "skipped", "reason": "wrong_mode"}
    - 'draft': vytvoří záznam v payouts s status='draft', bez platby
    - 'scheduler': provede reálnou platbu přes LNbits
    
    Parametry:
    - mode: aktuální payout_mode z nastavení
    - amount_czk: explicitní částka (pokud None, použije se pending balance)
    - ln_address: explicitní adresa (pokud None, načte se z nastavení)
    - sync_id: ID SyncRun pro idempotenci (volitelné)
    
    Vrací dict s výsledkem: {"status": "...", ...}
    """
    # 1. Režimová kontrola
    if mode not in (PayoutMode.DRAFT.value, PayoutMode.SCHEDULER.value):
        logger.debug('Payout přerušen: režim %r není draft/scheduler', mode)
        return {"status": "skipped", "reason": "wrong_mode"}

    # 2. Načtení výchozích hodnot
    if amount_czk is None:
        amount_czk = _get_pending_balance(db)
    if amount_czk <= 0:
        logger.debug('Žádné pending odměny k výplatě')
        return {"status": "skipped", "reason": "no_balance"}

    if ln_address is None:
        ln_address = _get_setting(db, 'ln_address', '').strip()
    if not ln_address or '@' not in ln_address:
        logger.warning('LN adresa "%s" je neplatná', ln_address[:10] + '...' if len(ln_address) > 10 else ln_address)
        return {"status": "error", "reason": "invalid_ln_address"}

    # 3. Kontrola thresholdu pouze pro scheduler (draft může být i pod thresholdem)
    if mode == PayoutMode.SCHEDULER.value:
        threshold = int(_get_setting(db, 'payout_threshold_czk', '100'))
        if amount_czk < threshold:
            logger.debug('Balance %d CZK < threshold %d CZK, přeskakuji payout', amount_czk, threshold)
            return {"status": "skipped", "reason": "below_threshold"}

    # 4. Idempotence – zabránění duplicitám
    existing = db.query(Payout).filter(
        Payout.status.in_(['pending', 'paid', 'draft']),
        Payout.amount_czk == amount_czk,
        Payout.ln_address == ln_address,
    ).first()

    if existing:
        logger.warning(
            'Duplicitní payout již existuje (id=%d, status=%s), přeskakuji',
            existing.id,
            existing.status,
        )
        return {"status": "skipped", "reason": "duplicate", "payout_id": existing.id}

    logger.info(
        'Payout mode=%s: %d CZK na %s',
        mode,
        amount_czk,
        ln_address,
    )

    # 5. Vytvoření záznamu payoutu
    try:
        czk_per_btc = RateService().get_czk_per_btc()
        amount_sats = RateService().czk_to_sats(amount_czk, czk_per_btc)
    except Exception as exc:
        logger.error('Selhal převod CZK → sats: %s', str(exc))
        return {"status": "error", "reason": "rate_conversion_failed", "error": str(exc)}

    # Idempotency key podle sync_id nebo času
    idempotency_key = (
        f"sync_{sync_id}_{amount_czk}_{ln_address}" if sync_id is not None
        else datetime.utcnow().isoformat()
    )

    payout = Payout(
        ln_address=ln_address,
        amount_czk=amount_czk,
        amount_sats=amount_sats,
        idempotency_key=idempotency_key,
        status='draft' if mode == PayoutMode.DRAFT.value else 'pending',
    )
    db.add(payout)
    db.flush()

    # Audit začátku
    db.add(
        PayoutAudit(
            payout_id=payout.id,
            event='payment_started',
            details=f'{{"amount_czk": {amount_czk}, "amount_sats": {amount_sats}, "ln_address": "{ln_address}", "mode": "{mode}"}}',
        )
    )
    db.flush()

    # 6. Pro DRAFT: jen záznam, bez platby
    if mode == PayoutMode.DRAFT.value:
        db.commit()
        logger.info('Vytvořen DRAFT payout: %d CZK (%d sats)', amount_czk, amount_sats)
        return {
            "status": "draft_created",
            "payout_id": payout.id,
            "amount_czk": amount_czk,
            "amount_sats": amount_sats,
        }

    # 7. Pro SCHEDULER: reálná platba přes LNbits
    try:
        service = LnbitsService()
        invoice = service.resolve_ln_address(ln_address, amount_sats)
        result = service.pay_invoice(invoice)

        payout.invoice = invoice
        payout.payment_hash = result.get('payment_hash')
        payout.status = 'paid'
        payout.completed_at = datetime.utcnow()

        # Označit odměny jako paid
        db.query(Reward).filter(
            Reward.status == 'pending'
        ).update({'status': 'paid'})

        # Audit úspěchu
        db.add(
            PayoutAudit(
                payout_id=payout.id,
                event='payment_succeeded',
                details=f'{{"payment_hash": "{result.get("payment_hash")}"}}',
            )
        )

        # Aktualizovat stav
        state.running_balance_czk = 0

        db.commit()

        logger.info(
            'Payout úspěšně dokončen: %d CZK (%d sats), hash: %s',
            amount_czk,
            amount_sats,
            result.get('payment_hash', 'N/A')[:16] + '...',
        )
        return {
            "status": "paid",
            "payout_id": payout.id,
            "amount_czk": amount_czk,
            "amount_sats": amount_sats,
            "payment_hash": result.get('payment_hash'),
        }

    except (LnAddressResolutionError, LnbitsPaymentError, RuntimeError) as exc:
        payout.status = 'failed'
        payout.error_message = str(exc)
        payout.completed_at = datetime.utcnow()

        db.add(
            PayoutAudit(
                payout_id=payout.id,
                event='payment_failed',
                details=f'{{"error": "{str(exc)}"}}',
            )
        )

        db.commit()

        logger.error('Payout selhal: %s', str(exc))
        return {"status": "failed", "error": str(exc)}


def check_and_run_payout(db: DbSession, state: SyncState) -> bool:
    """
    Zkontroluje podmínky a spustí payout hned po synchronizaci.
    
    Volá execute_payout s mode='scheduler'.
    Vrací True, pokud se payout spustil.
    """
    payout_mode = _get_setting(db, 'payout_mode', 'disabled')

    result = execute_payout(
        db=db,
        state=state,
        mode=payout_mode,
    )

    return result.get("status") in ("paid", "draft_created")
