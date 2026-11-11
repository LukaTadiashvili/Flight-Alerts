"""Travelpayouts (Aviasales) Data API — cached cheapest fares for all airlines.

Docs: https://support.travelpayouts.com/hc/en-us/articles/203956163
Endpoint: GET https://api.travelpayouts.com/aviasales/v3/prices_for_dates
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime

import requests

from ..currency import Converter
from ..models import Deal, Flight

log = logging.getLogger(__name__)

URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
ROUTES_URL = "https://api.travelpayouts.com/data/routes.json"  # public list of all airline routes
SITE = "https://www.aviasales.com"


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None


def _time(value: str | None) -> str:
    """Local "HH:MM" from an ISO timestamp with offset (the offset is the airport's local one)."""
    if value and len(value) >= 16 and value[10] == "T":
        return value[11:16]
    return ""


def _int(value) -> int | None:
    try:
        v = int(value)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _link(item: dict) -> str:
    link = item.get("link") or ""
    if link.startswith("/"):
        return SITE + link
    return link


class Travelpayouts:
    name = "travelpayouts"

    def __init__(self, session: requests.Session, token: str, converter: Converter, currency: str = "eur"):
        self.session = session
        self.token = token
        self.conv = converter
        self.currency = currency.lower()
        self.requests_made = 0

    def _get(self, max_pages: int = 3, **params) -> list[dict]:
        params = {k: v for k, v in params.items() if v is not None}
        params.update(currency=self.currency, sorting="price", limit=1000, unique="false")
        all_items: list[dict] = []
        for page in range(1, max_pages + 1):  # up to 1000 rows per page
            params["page"] = page
            for attempt in range(4):
                resp = self.session.get(URL, params=params, headers={"X-Access-Token": self.token}, timeout=45)
                self.requests_made += 1
                if resp.status_code != 429:
                    break
                time.sleep(5 * (attempt + 1))  # API rate limit — wait and retry
            if resp.status_code == 401:
                raise RuntimeError("Travelpayouts token is invalid (401)")
            resp.raise_for_status()
            body = resp.json()
            if body.get("success") is False:
                raise RuntimeError(f"Travelpayouts error: {body.get('error')}")
            items = body.get("data") or []
            all_items.extend(items)
            if len(items) < 1000:
                break
        return all_items

    def _price_gel(self, item: dict) -> float | None:
        price = item.get("price") or item.get("value")
        if price is None:
            return None
        return self.conv.to_gel(float(price), self.currency)

    def _flight(self, item: dict) -> Flight | None:
        d = _parse_date(item.get("departure_at"))
        gel = self._price_gel(item)
        if d is None or gel is None:
            return None
        return Flight(
            origin=item.get("origin_airport") or item.get("origin", ""),
            destination=item.get("destination_airport") or item.get("destination", ""),
            depart=d,
            price_gel=gel,
            airline=item.get("airline", ""),
            transfers=int(item.get("transfers") or 0),
            link=_link(item),
            source=self.name,
            dep_time=_time(item.get("departure_at")),
            duration_min=_int(item.get("duration_to") or item.get("duration")),
            flight_number=str(item.get("flight_number") or ""),
        )

    def outbound(self, origin: str, month: str) -> list[Flight]:
        """Cheapest one-way flights from `origin` to anywhere in a given month (YYYY-MM)."""
        items = self._get(origin=origin, departure_at=month, one_way="true")
        return [f for f in map(self._flight, items) if f]

    def inbound(self, destination: str, month: str) -> list[Flight]:
        """Cheapest one-way flights from anywhere to `destination` in a given month."""
        items = self._get(destination=destination, departure_at=month, one_way="true")
        return [f for f in map(self._flight, items) if f]

    def route_pairs(self, origins: list[str]) -> set[tuple[str, str]]:
        """Every (origin, destination) airport pair any airline flies nonstop from our airports."""
        pairs: set[tuple[str, str]] = set()
        resp = self.session.get(ROUTES_URL, timeout=90)
        resp.raise_for_status()
        for r in resp.json():
            o, x = r.get("departure_airport_iata"), r.get("arrival_airport_iata")
            if o in origins and x and x not in origins and not r.get("codeshare"):
                pairs.add((o, x))
        return pairs

    def route(self, origin: str, destination: str) -> list[Flight]:
        """All cached one-way prices on one route, any date (cheapest first)."""
        items = self._get(max_pages=1, origin=origin, destination=destination, one_way="true")
        return [f for f in map(self._flight, items) if f]

    def round_trips(self, origin: str, month: str) -> list[Deal]:
        """Return-fare tickets (sometimes cheaper than two one-ways on legacy airlines)."""
        items = self._get(origin=origin, departure_at=month, one_way="false")
        deals: list[Deal] = []
        for it in items:
            d1, d2 = _parse_date(it.get("departure_at")), _parse_date(it.get("return_at"))
            gel = self._price_gel(it)
            if not (d1 and d2 and gel):
                continue
            o = it.get("origin_airport") or it.get("origin", origin)
            x = it.get("destination_airport") or it.get("destination", "")
            deals.append(Deal(
                origin=o, destination=x, return_from=x, return_to=o,
                depart=d1, ret=d2, price_gel=gel,
                airlines=(it.get("airline", ""),),
                transfers=max(int(it.get("transfers") or 0), int(it.get("return_transfers") or 0)),
                link=_link(it), source=self.name,
                dep_time=_time(it.get("departure_at")), ret_time=_time(it.get("return_at")),
                duration_to=_int(it.get("duration_to")), duration_back=_int(it.get("duration_back")),
                flight_number=str(it.get("flight_number") or ""),
            ))
        return deals
