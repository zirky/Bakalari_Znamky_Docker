from datetime import datetime
from sqlalchemy.orm import Session as DbSession
from sqlalchemy import func
import logging

from ..models import AppSetting, Payout, PayoutAudit, Reward, SyncState
from ..services.lnbits import LnbitsService, LnbitsPaymentError, LnAddressResolutionError
from ..services.rates import RateService


logger = logging.getLogger(__name__)


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


def check_and_run_payout(db: DbSession, state: SyncState) -> bool:
    """
    Zkontroluje podmínky a spustí payout hned po synchronizaci.
    
    Podmínky:
    - payout_mode == 'scheduler' (explicitně nastaveno uživatelem)
    - balance >= threshold
    - LN adresa je nastavena
    - Neexistuje duplicitní payout
    
    Vrací True, pokud se payout spustil.
    """
    payout_mode = _get_setting(db, 'payout_mode', 'disabled')
    
    # BEZPEČNOSTNÍ KONTROLA 1: Explicitní režim
    if payout_mode != 'scheduler':
        logger.debug(
            'Payout scheduler je vypnutý (mode=%r), přeskakuji',
            payout_mode,
        )
        return False
    
    # Kontrola thresholdu
    threshold = int(_get_setting(db, 'payout_threshold_czk', '100'))
    balance = _get_pending_balance(db)
    
    if balance <= 0:
        logger.debug('Žádné pending odměny k výplatě')
        return False
    
    if balance < threshold:
        logger.debug(
            'Balance %d CZK < threshold %d CZK, přeskakuji payout',
            balance,
            threshold,
        )
        return False
    
    # Kontrola LN adresy
    ln_address = _get_setting(db, 'ln_address', '').strip()
    if not ln_address or '@' not in ln_address:
        logger.warning(
            'LN adresa "%s" je neplatná, přeskakuji payout',
            ln_address[:10] + '...' if len(ln_address) > 10 else ln_address,
        )
        return False
    
    # BEZPEČNOSTNÍ KONTROLA 2: Zabránění duplicitám
    existing = db.query(Payout).filter(
        Payout.status.in_(['pending', 'paid']),
        Payout.amount_czk == balance,
        Payout.ln_address == ln_address,
    ).first()
    
    if existing:
        logger.warning(
            'Duplicitní payout již existuje (id=%d, status=%s), přeskakuji',
            existing.id,
            existing.status,
        )
        return False
    
    logger.info(
        'Spouštím automatický payout: %d CZK na %s',
        balance,
        ln_address,
    )
    
    # Spustit payout
    try:
        # Převod CZK → sats
        czk_per_btc = RateService().get_czk_per_btc()
        amount_sats = RateService().czk_to_sats(balance, czk_per_btc)
        
        # Vytvořit payout
        payout = Payout(
            ln_address=ln_address,
            amount_czk=balance,
            amount_sats=amount_sats,
            idempotency_key=datetime.utcnow().isoformat(),
            status='pending',
        )
        db.add(payout)
        db.flush()
        
        # Audit
        db.add(
            PayoutAudit(
                payout_id=payout.id,
                event='payment_started',
                details=f'{{"amount_czk": {balance}, "amount_sats": {amount_sats}, "ln_address": "{ln_address}"}}',
            )
        )
        
        # Odeslat platbu
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
        state.last_payout_at = datetime.utcnow()
        state.running_balance_czk = 0
        
        db.commit()
        
        logger.info(
            'Payout úspěšně dokončen: %d CZK (%d sats), hash: %s',
            balance,
            amount_sats,
            result.get('payment_hash', 'N/A')[:16] + '...',
        )
        return True
        
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
        return False
