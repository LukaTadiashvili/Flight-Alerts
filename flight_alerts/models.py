from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Flight:
    """One-way flight (one leg) with a price already converted to GEL."""

    origin: str          # departure airport IATA
    destination: str     # arrival airport IATA
    depart: date
    price_gel: float
    airline: str = ""    # IATA airline code (e.g. W6)
    transfers: int = 0
    link: str = ""
    source: str = ""


@dataclass
class Deal:
    """A full trip: there and back, total price in GEL."""

    origin: str          # where you fly out from (TBS / KUT)
    destination: str     # destination airport
    return_from: str     # airport you fly back from
    return_to: str       # where you land back (TBS / KUT)
    depart: date
    ret: date
    price_gel: float
    out_leg: Flight | None = None    # None when this is a single round-trip fare
    back_leg: Flight | None = None
    airlines: tuple[str, ...] = ()
    transfers: int = 0               # max transfers on either leg
    link: str = ""
    source: str = ""
    extra_links: list[tuple[str, str]] = field(default_factory=list)  # (label, url)

    @property
    def nights(self) -> int:
        return (self.ret - self.depart).days
