"""Data files for the web app: current prices (flights.json) and price history (history.json)."""
from __future__ import annotations

import json
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .models import Deal, Flight
from .places import AIRLINES, Places

LEG_FIELDS = ["o", "x", "d", "t", "arr", "dur", "est", "p", "al", "fn", "tr", "src"]
RT_FIELDS = ["o", "x", "d", "t", "r", "rt", "dto", "dback", "p", "al", "fn", "tr"]
MAX_LEG_PRICE = 1500       # GEL, one-way legs above this are not exported
MAX_RT_PRICE = 3000        # GEL, round-trip fares above this are not exported
HISTORY_LEG_PRICE = 800    # GEL, only legs below this get a price history
HISTORY_MAX_TRANSFERS = 1


def _tz(name: str | None) -> ZoneInfo | None:
    try:
        return ZoneInfo(name) if name else None
    except Exception:  # noqa: BLE001
        return None


def arrival(places: Places, o: str, x: str, d: date, t: str, dur: int | None) -> str:
    """Local arrival time at the destination, e.g. "2026-12-05T09:40"."""
    tz_o, tz_x = _tz(places.airport_tz.get(o)), _tz(places.airport_tz.get(x))
    if not (t and dur and tz_o and tz_x):
        return ""
    try:
        hh, mm = map(int, t.split(":"))
    except ValueError:
        return ""
    dep = datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz_o)
    return (dep + timedelta(minutes=dur)).astimezone(tz_x).strftime("%Y-%m-%dT%H:%M")


def typical_durations(flights: list[Flight]) -> dict[tuple[str, str], int]:
    """Median nonstop duration per route (used to fill in Wizz Air legs, whose
    timetable has no duration)."""
    acc: dict[tuple[str, str], list[int]] = {}
    for f in flights:
        if f.transfers == 0 and f.duration_min:
            acc.setdefault((f.origin, f.destination), []).append(f.duration_min)
    return {k: int(statistics.median(v)) for k, v in acc.items()}


def export_legs(flights: list[Flight], places: Places) -> list[list]:
    typical = typical_durations(flights)
    best: dict[tuple, Flight] = {}
    for f in flights:
        if f.price_gel > MAX_LEG_PRICE or f.transfers > 2:
            continue
        k = (f.origin, f.destination, f.depart, f.airline, f.transfers)
        if k not in best or f.price_gel < best[k].price_gel:
            best[k] = f
    rows = []
    for f in sorted(best.values(), key=lambda f: (f.depart, f.price_gel)):
        dur, est = f.duration_min, 0
        if not dur and f.transfers == 0:
            dur = typical.get((f.origin, f.destination)) or places.estimate_minutes(f.origin, f.destination)
            est = 1 if dur else 0
        rows.append([f.origin, f.destination, f.depart.isoformat(), f.dep_time,
                     arrival(places, f.origin, f.destination, f.depart, f.dep_time, dur),
                     dur, est, round(f.price_gel), f.airline, f.flight_number, f.transfers, f.source])
    return rows


def export_round_trips(deals: list[Deal]) -> list[list]:
    best: dict[tuple, Deal] = {}
    for d in deals:
        if d.price_gel > MAX_RT_PRICE or d.transfers > 2:
            continue
        k = (d.origin, d.destination, d.depart, d.ret, d.airlines)
        if k not in best or d.price_gel < best[k].price_gel:
            best[k] = d
    return [[d.origin, d.destination, d.depart.isoformat(), d.dep_time, d.ret.isoformat(), d.ret_time,
             d.duration_to, d.duration_back, round(d.price_gel), d.airlines[0] if d.airlines else "",
             d.flight_number, d.transfers]
            for d in sorted(best.values(), key=lambda d: (d.depart, d.price_gel))]


def _record(series: list, day: str, price: int) -> None:
    """Append today's price; keep the day's minimum; store only changes."""
    if series and series[-1][0] == day:
        series[-1][1] = min(series[-1][1], price)
        if len(series) >= 2 and series[-2][1] == series[-1][1]:
            series.pop()
    elif not series or series[-1][1] != price:
        series.append([day, price])


def update_history(history: dict, flights: list[Flight], round_trips: list[Deal], best_trips: list[Deal],
                   places: Places, today: date) -> dict:
    day = today.isoformat()
    legs: dict = history.setdefault("legs", {})
    cheapest: dict[str, int] = {}
    for f in flights:
        if f.transfers <= HISTORY_MAX_TRANSFERS and f.price_gel <= HISTORY_LEG_PRICE:
            k = f"{f.origin}|{f.destination}|{f.depart.isoformat()}"
            cheapest[k] = min(cheapest.get(k, 10**9), round(f.price_gel))
    for k, p in cheapest.items():
        _record(legs.setdefault(k, []), day, p)

    rts: dict = history.setdefault("roundtrips", {})
    rt_cheapest: dict[str, int] = {}
    for d in round_trips:
        if d.transfers <= HISTORY_MAX_TRANSFERS and d.price_gel <= 2 * HISTORY_LEG_PRICE:
            k = f"{d.origin}|{d.destination}|{d.depart.isoformat()}|{d.ret.isoformat()}"
            rt_cheapest[k] = min(rt_cheapest.get(k, 10**9), round(d.price_gel))
    for k, p in rt_cheapest.items():
        _record(rts.setdefault(k, []), day, p)

    # cheapest trip (with the user's current nights/transfer settings) per destination city
    routes: dict = history.setdefault("routes", {})
    city_best: dict[str, int] = {}
    for d in best_trips:
        c = places.city(d.destination)
        city_best[c] = min(city_best.get(c, 10**9), round(d.price_gel))
    for c, p in city_best.items():
        _record(routes.setdefault(c, []), day, p)

    # forget flights that already departed, and routes not seen for 120 days
    for store in (legs, rts):
        for k in [k for k in store if k.split("|")[2] < day]:
            del store[k]
    cutoff = (today - timedelta(days=120)).isoformat()
    for c in [c for c, s in routes.items() if not s or s[-1][0] < cutoff]:
        del routes[c]
    history["updated"] = day
    return history


def best_trips_any_price(deals: list[Deal], places: Places) -> list[Deal]:
    best: dict[str, Deal] = {}
    for d in deals:
        c = places.city(d.destination)
        if c not in best or d.price_gel < best[c].price_gel:
            best[c] = d
    return list(best.values())


def place_table(codes: set[str], places: Places) -> dict:
    out = {}
    for c in sorted(codes):
        city = places.city(c)
        out[c] = {"city": city, "name": places.name(c), "country": places.country.get(c, "")}
    return out


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def export_all(data_dir: Path, flights: list[Flight], round_trips: list[Deal], deals: list[Deal],
               places: Places, settings: dict, rates: dict, origins: list[str], now: datetime,
               errors: dict[str, str]) -> dict:
    legs = export_legs(flights, places)
    rts = export_round_trips(round_trips)
    codes = {r[0] for r in legs} | {r[1] for r in legs} | {r[0] for r in rts} | {r[1] for r in rts}
    airlines = {r[8] for r in legs} | {r[9] for r in rts}
    payload = {
        "generated": now.isoformat(timespec="minutes"),
        "origins": origins,
        "settings": settings,
        "rates": {k: rates[k] for k in ("EUR", "USD") if k in rates},
        "errors": errors,
        "places": place_table(codes, places),
        "cities": {},  # filled below (city code → name, incl. cities that only appear in history)
        "airlines": {a: AIRLINES.get(a, a) for a in sorted(a for a in airlines if a)},
        "leg_fields": LEG_FIELDS, "legs": legs,
        "rt_fields": RT_FIELDS, "roundtrips": rts,
    }

    hist_path = data_dir / "history.json"
    try:
        history = json.loads(hist_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        history = {}
    history = update_history(history, flights, round_trips, best_trips_any_price(deals, places), places,
                             now.date())
    write_json(hist_path, history)
    cities = {places.city(c) for c in codes} | set(history.get("routes", {}))
    payload["cities"] = {c: places.name(c) for c in sorted(cities)}
    write_json(data_dir / "flights.json", payload)
    return {"legs": len(legs), "roundtrips": len(rts), "history_legs": len(history.get("legs", {}))}
