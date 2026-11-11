"""Airport → city grouping and human-readable names.

Grouping by city lets us combine e.g. TBS→BGY with MXP→KUT (both Milan).
"""
from __future__ import annotations

import logging

import requests

log = logging.getLogger(__name__)

AIRPORTS_URL = "https://api.travelpayouts.com/data/en/airports.json"
CITIES_URL = "https://api.travelpayouts.com/data/en/cities.json"

GEORGIAN_CITIES = {"TBS": "თბილისი", "KUT": "ქუთაისი", "BUS": "ბათუმი"}
DOMESTIC = {"TBS", "KUT", "BUS"}

# Used when the public data files can't be downloaded.
FALLBACK_AIRPORT_CITY = {
    "IST": "IST", "SAW": "IST",
    "LHR": "LON", "LGW": "LON", "STN": "LON", "LTN": "LON", "LCY": "LON", "SEN": "LON",
    "MXP": "MIL", "BGY": "MIL", "LIN": "MIL",
    "FCO": "ROM", "CIA": "ROM",
    "CDG": "PAR", "ORY": "PAR", "BVA": "PAR",
    "WAW": "WAW", "WMI": "WAW",
    "BER": "BER", "SXF": "BER",
    "DXB": "DXB", "DWC": "DXB",
    "VKO": "MOW", "SVO": "MOW", "DME": "MOW",
    "TLV": "TLV", "ETM": "ETH",
    "BUD": "BUD", "VIE": "VIE", "PRG": "PRG", "ATH": "ATH",
    "LCA": "LCA", "PFO": "PFO", "KRK": "KRK", "KTW": "KTW",
    "DTM": "DTM", "CGN": "CGN", "MUC": "MUC", "FMM": "FMM", "NUE": "NUE",
    "OTP": "BUH", "BBU": "BUH", "SOF": "SOF", "VNO": "VNO", "RIX": "RIX",
    "AYT": "AYT", "ESB": "ANK", "SHJ": "SHJ", "AUH": "AUH",
    "BCN": "BCN", "MAD": "MAD", "AMS": "AMS", "EIN": "EIN", "NAP": "NAP",
    "VCE": "VCE", "TSF": "VCE", "BLQ": "BLQ", "MLA": "MLA", "LIS": "LIS",
}

FALLBACK_CITY_NAMES = {
    "IST": "Istanbul", "LON": "London", "MIL": "Milan", "ROM": "Rome", "PAR": "Paris",
    "WAW": "Warsaw", "BER": "Berlin", "DXB": "Dubai", "MOW": "Moscow", "TLV": "Tel Aviv",
    "BUD": "Budapest", "VIE": "Vienna", "PRG": "Prague", "ATH": "Athens", "LCA": "Larnaca",
    "KRK": "Krakow", "KTW": "Katowice", "DTM": "Dortmund", "CGN": "Cologne", "MUC": "Munich",
    "FMM": "Memmingen", "BUH": "Bucharest", "SOF": "Sofia", "VNO": "Vilnius", "RIX": "Riga",
    "AYT": "Antalya", "ANK": "Ankara", "SHJ": "Sharjah", "AUH": "Abu Dhabi", "BCN": "Barcelona",
    "MAD": "Madrid", "AMS": "Amsterdam", "EIN": "Eindhoven", "NAP": "Naples", "VCE": "Venice",
    "BLQ": "Bologna", "MLA": "Malta", "LIS": "Lisbon", "NUE": "Nuremberg", "PFO": "Paphos",
    "ETH": "Eilat",
}

AIRLINES = {
    "W6": "Wizz Air", "W4": "Wizz Air Malta", "W9": "Wizz Air UK", "5W": "Wizz Air Abu Dhabi",
    "PC": "Pegasus", "TK": "Turkish Airlines", "VF": "AJet", "QR": "Qatar Airways",
    "FZ": "flydubai", "G9": "Air Arabia", "3L": "Air Arabia Abu Dhabi", "A9": "Georgian Airways",
    "LO": "LOT", "A3": "Aegean", "LH": "Lufthansa", "OS": "Austrian", "J2": "AZAL",
    "BT": "airBaltic", "6H": "Israir", "IZ": "Arkia", "LY": "El Al", "KC": "Air Astana",
    "HY": "Uzbekistan Airways", "EK": "Emirates", "EY": "Etihad", "MS": "EgyptAir",
    "RJ": "Royal Jordanian", "FR": "Ryanair", "U2": "easyJet", "XQ": "SunExpress",
    "B2": "Belavia", "SZ": "Somon Air", "ZF": "Azur Air", "H9": "Himalaya Airlines",
    "OV": "SalamAir", "WY": "Oman Air", "J9": "Jazeera Airways", "KU": "Kuwait Airways",
    "GF": "Gulf Air", "SV": "Saudia", "XY": "flynas", "F3": "flyadeal", "LS": "Jet2",
    "PS": "UIA", "AZ": "ITA Airways", "AF": "Air France", "KL": "KLM", "LX": "Swiss",
}


class Places:
    def __init__(self, airport_city: dict[str, str] | None = None, city_names: dict[str, str] | None = None):
        self.airport_city = dict(FALLBACK_AIRPORT_CITY)
        self.city_names = dict(FALLBACK_CITY_NAMES)
        if airport_city:
            self.airport_city.update(airport_city)
        if city_names:
            self.city_names.update(city_names)

    @classmethod
    def load(cls, session: requests.Session) -> "Places":
        airport_city: dict[str, str] = {}
        city_names: dict[str, str] = {}
        try:
            for a in session.get(AIRPORTS_URL, timeout=60).json():
                if a.get("code") and a.get("city_code"):
                    airport_city[a["code"]] = a["city_code"]
            for c in session.get(CITIES_URL, timeout=60).json():
                if c.get("code") and c.get("name"):
                    city_names[c["code"]] = c["name"]
            log.info("Loaded %d airports, %d cities", len(airport_city), len(city_names))
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not load airport data, using built-in table: %s", exc)
        return cls(airport_city, city_names)

    def city(self, code: str) -> str:
        """City code for an airport (or the code itself if unknown / already a city)."""
        return self.airport_city.get(code, code)

    def name(self, code: str) -> str:
        if code in GEORGIAN_CITIES:
            return GEORGIAN_CITIES[code]
        city = self.city(code)
        if city in GEORGIAN_CITIES:
            return GEORGIAN_CITIES[city]
        return self.city_names.get(city) or self.city_names.get(code) or code

    def is_domestic(self, code: str) -> bool:
        return code in DOMESTIC or self.city(code) in DOMESTIC


def airline_name(code: str) -> str:
    return AIRLINES.get(code, code) if code else "?"
