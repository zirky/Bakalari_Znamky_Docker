"""CoinGecko exchange rate service."""
import httpx

COINGECKO_URL = 'https://api.coingecko.com/api/v3/simple/price'


class RateService:
    def __init__(self, timeout: float = 5.0):
        self.timeout = timeout

    def get_czk_per_btc(self) -> float:
        """Fetch current CZK price of 1 BTC from CoinGecko.

        Raises RuntimeError on network or API failure so callers can
        decide how to handle a missing rate (e.g. skip payout run).
        """
        try:
            response = httpx.get(
                COINGECKO_URL,
                params={'ids': 'bitcoin', 'vs_currencies': 'czk'},
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            return float(data['bitcoin']['czk'])
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise RuntimeError(f'Nepodařilo se získat kurz CZK/BTC: {exc}') from exc

    def czk_to_sats(self, amount_czk: int, czk_per_btc: float) -> int:
        if czk_per_btc <= 0:
            raise ValueError('Neplatný kurz CZK/BTC')
        btc = amount_czk / czk_per_btc
        return round(btc * 100_000_000)
