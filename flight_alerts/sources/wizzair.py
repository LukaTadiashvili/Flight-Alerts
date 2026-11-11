"""Wizz Air — the (unofficial) API that wizzair.com itself uses.

It is not a public API: the version number changes every few weeks and the
site sometimes blocks automated traffic. Everything here is defensive — on any
block we stop politely and the run continues with other sources.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime, timedelta

import requests

from ..currency import Converter
from ..models import Flight

log = logging.getLogger(__name__)

BUILD_URL = "https://wizzair.com/buildnumber"
API = "https://be.wizzair.com/{ver}/Api"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-GB,en;q=0.9",
    "Origin": "https://wizzair.com",
    "Referer": "https://wizzair.com/",
}


class Blocked(RuntimeError):
    pass


def booking_link(origin: str, dest: str, d1: date, d2: date | None = None) -> str:
    ret = d2.isoformat() if d2 else "null"
    return f"https://wizzair.com/en-gb/booking/select-flight/{origin}/{dest}/{d1.isoformat()}/{ret}/1/0/0/null"


def parse_version(text: str) -> str | None:
    m = re.search(r"be\.wizzair\.com/([\d.]+)", text) or re.search(r"\b(\d+\.\d+\.\d+)\b", text)
    return m.group(1) if m else None


def parse_timetable(body: dict, conv: Converter) -> list[Flight]:
    flights: list[Flight] = []
    for key in ("outboundFlights", "returnFlights"):
        for f in body.get(key) or []:
            if f.get("priceType") in ("soldOut", "checkPrice"):
                continue
            price = f.get("price") or {}
            amount, cur = price.get("amount"), price.get("currencyCode")
            if not amount or not cur:
                continue
            gel = conv.to_gel(float(amount), cur)
            if gel is None:
                log.debug("Unknown currency %s", cur)
                continue
            raw = f.get("departureDate") or ""
            try:
                d = datetime.fromisoformat(raw[:19]).date()
            except ValueError:
                continue
            o, x = f.get("departureStation", ""), f.get("arrivalStation", "")
            times = [t for t in (f.get("departureDates") or []) if isinstance(t, str) and len(t) >= 16]
            flights.append(Flight(
                origin=o, destination=x, depart=d, price_gel=gel, airline="W6",
                transfers=0, link=booking_link(o, x, d), source="wizzair",
                dep_time=times[0][11:16] if times else "",
            ))
    return flights


class WizzAir:
    name = "wizzair"

    def __init__(self, session: requests.Session, converter: Converter, window_days: int = 42,
                 delay: float = 1.0, fallback_version: str = ""):
        self.session = session
        self.conv = converter
        self.window_days = window_days
        self.delay = delay
        self.fallback_version = fallback_version
        self.version: str | None = None
        self.requests_made = 0
        self.busy = 0

    def _req(self, method: str, url: str, **kw) -> requests.Response:
        if self.requests_made:
            time.sleep(self.delay)
        self.requests_made += 1
        resp = self.session.request(method, url, headers=HEADERS, timeout=45, **kw)
        if resp.status_code in (403, 429):
            raise Blocked(f"Wizz Air answered {resp.status_code} — probably anti-bot protection")
        # 503 = "slow down": after a few in a row, stop for this run instead of insisting
        self.busy = self.busy + 1 if resp.status_code == 503 else 0
        if self.busy >= 3:
            raise Blocked("Wizz Air is answering 503 (busy) — stopped for this run")
        return resp

    def _api(self) -> str:
        if not self.version:
            # the version is in /buildnumber and also embedded in the home page
            for url in (BUILD_URL, "https://wizzair.com/en-gb"):
                try:
                    resp = self._req("GET", url)
                    self.version = parse_version(resp.text)
                    if self.version:
                        break
                    snippet = " ".join(resp.text[:300].split())
                    log.warning("No Wizz version in %s (HTTP %s): %r", url, resp.status_code, snippet)
                except Blocked:
                    raise
                except Exception as exc:  # noqa: BLE001
                    log.warning("Wizz %s failed: %s", url, exc)
            self.version = self.version or self.fallback_version
            if not self.version:
                raise RuntimeError("Could not determine Wizz Air API version (site probably served a bot check)")
            log.info("Wizz Air API version %s", self.version)
        return API.format(ver=self.version)

    def routes(self, origins: list[str]) -> list[tuple[str, str]]:
        resp = self._req("GET", f"{self._api()}/asset/map", params={"languageCode": "en-gb"})
        resp.raise_for_status()
        pairs = []
        for city in resp.json().get("cities", []):
            if city.get("iata") in origins:
                for c in city.get("connections", []):
                    if c.get("iata"):
                        pairs.append((city["iata"], c["iata"]))
        return pairs

    def timetable(self, origin: str, dest: str, start: date, end: date, back_end: date) -> list[Flight]:
        body = {
            "flightList": [
                {"departureStation": origin, "arrivalStation": dest,
                 "from": start.isoformat(), "to": end.isoformat()},
                {"departureStation": dest, "arrivalStation": origin,
                 "from": start.isoformat(), "to": back_end.isoformat()},
            ],
            "priceType": "regular",
            "adultCount": 1, "childCount": 0, "infantCount": 0,
        }
        resp = self._req("POST", f"{self._api()}/search/timetable", json=body)
        if resp.status_code == 404:  # route has no flights in this window
            return []
        resp.raise_for_status()
        return parse_timetable(resp.json(), self.conv)

    def collect(self, origins: list[str], first: date, last: date, max_nights: int) -> list[Flight]:
        pairs = self.routes(origins)
        log.info("Wizz Air: %d routes from %s", len(pairs), "/".join(origins))
        flights: list[Flight] = []
        for origin, dest in pairs:
            start = first
            while start <= last:
                end = min(start + timedelta(days=self.window_days - 1), last)
                back_end = end + timedelta(days=max_nights)
                try:
                    flights.extend(self.timetable(origin, dest, start, end, back_end))
                except Blocked:
                    raise
                except Exception as exc:  # noqa: BLE001
                    log.warning("Wizz %s-%s %s: %s", origin, dest, start, exc)
                start = end + timedelta(days=1)
        return flights
