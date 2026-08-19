"""LNbits Lightning Address payout service."""
import secrets
import httpx

from ..config import get_settings


class LnAddressResolutionError(RuntimeError):
    pass


class LnbitsPaymentError(RuntimeError):
    pass


class LnbitsService:
    """Resolves LN addresses via LNURL-pay and pays invoices through LNbits.

    Only the invoice/withdraw scoped API key is required for this flow;
    no admin key is used to keep the blast radius of a leaked key small.
    """

    def __init__(self, timeout: float = 10.0):
        self.settings = get_settings()
        self.timeout = timeout

    def _headers(self) -> dict:
        return {'X-Api-Key': self.settings.lnbits_api_key}

    def resolve_ln_address(self, ln_address: str, amount_sats: int) -> str:
        """Resolve a Lightning Address (user@domain) to a BOLT11 invoice."""
        if '@' not in ln_address:
            raise LnAddressResolutionError('Neplatná Lightning adresa')

        name, domain = ln_address.split('@', 1)
        lnurlp_url = f'https://{domain}/.well-known/lnurlp/{name}'

        try:
            meta_response = httpx.get(lnurlp_url, timeout=self.timeout)
            meta_response.raise_for_status()
            meta = meta_response.json()

            callback = meta['callback']
            amount_msat = amount_sats * 1000

            if amount_msat < meta.get('minSendable', 0) or amount_msat > meta.get('maxSendable', amount_msat):
                raise LnAddressResolutionError('Částka je mimo povolený rozsah pro tuto LN adresu')

            invoice_response = httpx.get(callback, params={'amount': amount_msat}, timeout=self.timeout)
            invoice_response.raise_for_status()
            invoice_data = invoice_response.json()

            if 'pr' not in invoice_data:
                raise LnAddressResolutionError('LN adresa nevrátila platnou faktu')

            return invoice_data['pr']
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise LnAddressResolutionError(f'Nepodařilo se rozeznat LN adresu: {exc}') from exc

    def pay_invoice(self, invoice: str) -> dict:
        """Submit a BOLT11 invoice for payment through LNbits."""
        try:
            response = httpx.post(
                f'{self.settings.lnbits_host}/api/v1/payments',
                headers=self._headers(),
                json={'out': True, 'bolt11': invoice},
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            raise LnbitsPaymentError(f'Platba přes LNbits selhala: {exc}') from exc

    def get_payment_status(self, payment_hash: str) -> dict:
        try:
            response = httpx.get(
                f'{self.settings.lnbits_host}/api/v1/payments/{payment_hash}',
                headers=self._headers(),
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            raise LnbitsPaymentError(f'Nepodařilo se zjistit stav platby: {exc}') from exc


def new_idempotency_key() -> str:
    return secrets.token_hex(16)
