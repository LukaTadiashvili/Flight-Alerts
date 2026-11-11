"""Exchange rates to GEL from the National Bank of Georgia, with fallbacks."""
from __future__ import annotations

import logging

import requests

log = logging.getLogger(__name__)

NBG_URL = "https://nbg.gov.ge/gw/api/ct/monetarypolicy/currencies/en/json/"


def fetch_nbg_rates(session: requests.Session) -> dict[str, float]:
    resp = session.get(NBG_URL, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    block = payload[0] if isinstance(payload, list) else payload
    rates: dict[str, float] = {}
    for c in block.get("currencies", []):
        code = str(c.get("code", "")).upper()
        qty = float(c.get("quantity") or 1)
        rate = c.get("rate")
        if code and rate:
            rates[code] = float(rate) / qty
    if not rates:
        raise ValueError("NBG response had no currencies")
    return rates


class Converter:
    def __init__(self, rates: dict[str, float]):
        self.rates = {k.upper(): float(v) for k, v in rates.items()}
        self.rates["GEL"] = 1.0

    def to_gel(self, amount: float, currency: str) -> float | None:
        rate = self.rates.get((currency or "").upper())
        if rate is None:
            return None
        return float(amount) * rate

    def from_gel(self, amount_gel: float, currency: str) -> float | None:
        rate = self.rates.get(currency.upper())
        return None if not rate else amount_gel / rate


def load_converter(session: requests.Session, state: dict, fallback: dict[str, float]) -> Converter:
    rates = dict(fallback)
    rates.update(state.get("rates", {}))  # last known good
    try:
        fresh = fetch_nbg_rates(session)
        rates.update(fresh)
        state["rates"] = fresh
        log.info("Loaded %d NBG rates (EUR=%.4f)", len(fresh), fresh.get("EUR", 0))
    except Exception as exc:  # noqa: BLE001
        log.warning("NBG rates unavailable, using cached/fallback: %s", exc)
    return Converter(rates)
