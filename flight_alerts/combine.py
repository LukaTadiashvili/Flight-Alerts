"""Build round trips out of one-way flights and pick the best deals."""
from __future__ import annotations

from datetime import timedelta
from typing import Callable, Iterable

from .models import Deal, Flight
from .places import Places
from .sources.wizzair import booking_link as wizz_link


def skyscanner_link(o: str, x: str, d1, d2=None) -> str:
    ret = f"{d2:%y%m%d}/" if d2 else ""
    return f"https://www.skyscanner.net/transport/flights/{o.lower()}/{x.lower()}/{d1:%y%m%d}/{ret}?adultsv2=1"


def _cheapest_by(flights: Iterable[Flight], key: Callable[[Flight], tuple]) -> dict[tuple, Flight]:
    best: dict[tuple, Flight] = {}
    for f in flights:
        k = key(f)
        if k not in best or f.price_gel < best[k].price_gel:
            best[k] = f
    return best


def combine_one_ways(flights: list[Flight], origins: list[str], places: Places,
                     min_nights: int, max_nights: int, max_transfers: int) -> list[Deal]:
    """Pair every outbound leg (TBS/KUT → X) with the cheapest return leg
    (X' → TBS/KUT, X' in the same city as X) 3..7 days later.
    Departure and return Georgian airport may differ (TBS→X→KUT)."""
    origin_set = set(origins)
    usable = [f for f in flights if f.transfers <= max_transfers and f.price_gel > 0]
    outs = [f for f in usable if f.origin in origin_set and not places.is_domestic(f.destination)]
    backs = [f for f in usable if f.destination in origin_set and not places.is_domestic(f.origin)]

    # Cheapest outbound per (origin, destination, day) and inbound per (city, day).
    outs_best = _cheapest_by(outs, lambda f: (f.origin, f.destination, f.depart))
    back_best = _cheapest_by(backs, lambda f: (places.city(f.origin), f.depart))

    deals: list[Deal] = []
    for out in outs_best.values():
        city = places.city(out.destination)
        for n in range(min_nights, max_nights + 1):
            back = back_best.get((city, out.depart + timedelta(days=n)))
            if back is None:
                continue
            deals.append(make_deal(out, back))
    return deals


def make_deal(out: Flight, back: Flight) -> Deal:
    deal = Deal(
        origin=out.origin, destination=out.destination,
        return_from=back.origin, return_to=back.destination,
        depart=out.depart, ret=back.depart,
        price_gel=out.price_gel + back.price_gel,
        out_leg=out, back_leg=back,
        airlines=(out.airline, back.airline),
        transfers=max(out.transfers, back.transfers),
        source=out.source if out.source == back.source else f"{out.source}+{back.source}",
    )
    simple_return = out.destination == back.origin and out.origin == back.destination
    if out.source == back.source == "wizzair" and simple_return:
        deal.link = wizz_link(out.origin, out.destination, out.depart, back.depart)
    else:
        deal.link = out.link or skyscanner_link(out.origin, out.destination, out.depart)
        deal.extra_links.append(("↩️ დაბრუნება", back.link or skyscanner_link(back.origin, back.destination, back.depart)))
    if simple_return:
        deal.extra_links.append(("🔎 Skyscanner", skyscanner_link(out.origin, out.destination, out.depart, back.depart)))
    return deal


def filter_round_trips(deals: list[Deal], places: Places, min_nights: int, max_nights: int,
                       max_transfers: int) -> list[Deal]:
    good = []
    for d in deals:
        if min_nights <= d.nights <= max_nights and d.transfers <= max_transfers \
                and not places.is_domestic(d.destination) and d.price_gel > 0:
            if not d.link:
                d.link = skyscanner_link(d.origin, d.destination, d.depart, d.ret)
            good.append(d)
    return good


def best_per_destination(deals: list[Deal], places: Places, max_price: float) -> list[Deal]:
    """Cheapest qualifying trip per destination city, sorted by price."""
    best: dict[str, Deal] = {}
    for d in deals:
        if d.price_gel > max_price:
            continue
        city = places.city(d.destination)
        if city not in best or d.price_gel < best[city].price_gel:
            best[city] = d
    return sorted(best.values(), key=lambda d: d.price_gel)
