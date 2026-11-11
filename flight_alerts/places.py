"""Airport → city grouping and human-readable names.

Grouping by city lets us combine e.g. TBS→BGY with MXP→KUT (both Milan).
"""
from __future__ import annotations

import logging
import math

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


FALLBACK_COORDS = {
    "TBS": (41.669, 44.955), "KUT": (42.176, 42.483), "BUS": (41.610, 41.600),
    "BUD": (47.437, 19.256), "VIE": (48.110, 16.570), "WAW": (52.166, 20.967), "KTW": (50.474, 19.080),
    "KRK": (50.078, 19.785), "BER": (52.367, 13.503), "DTM": (51.518, 7.612), "MUC": (48.354, 11.786),
    "FMM": (47.989, 10.240), "BGY": (45.674, 9.704), "MXP": (45.630, 8.723), "FCO": (41.800, 12.239),
    "CIA": (41.799, 12.595), "NAP": (40.886, 14.291), "ATH": (37.936, 23.947), "LCA": (34.875, 33.625),
    "PFO": (34.718, 32.486), "SOF": (42.695, 23.406), "OTP": (44.571, 26.085), "VNO": (54.634, 25.286),
    "RIX": (56.924, 23.971), "PRG": (50.101, 14.260), "IST": (41.262, 28.742), "SAW": (40.899, 29.309),
    "AYT": (36.899, 30.800), "DXB": (25.253, 55.364), "SHJ": (25.329, 55.517), "AUH": (24.433, 54.651),
    "TLV": (32.011, 34.887), "LTN": (51.875, -0.368), "STN": (51.885, 0.235), "LGW": (51.148, -0.190),
    "BCN": (41.297, 2.078), "MAD": (40.472, -3.561), "AMS": (52.309, 4.764), "EIN": (51.450, 5.375),
    "CGN": (50.866, 7.143), "VCE": (45.505, 12.352), "BLQ": (44.535, 11.289), "MLA": (35.858, 14.477),
    "LIS": (38.774, -9.134), "CDG": (49.010, 2.548), "BVA": (49.454, 2.113), "NUE": (49.499, 11.078),
}


class Places:
    def __init__(self, airport_city: dict[str, str] | None = None, city_names: dict[str, str] | None = None,
                 airport_tz: dict[str, str] | None = None, country: dict[str, str] | None = None):
        self.airport_city = dict(FALLBACK_AIRPORT_CITY)
        self.city_names = dict(FALLBACK_CITY_NAMES)
        self.airport_tz = {"TBS": "Asia/Tbilisi", "KUT": "Asia/Tbilisi", "BUS": "Asia/Tbilisi"}
        self.country = {"TBS": "GE", "KUT": "GE", "BUS": "GE"}
        self.coords: dict[str, tuple[float, float]] = dict(FALLBACK_COORDS)
        if airport_city:
            self.airport_city.update(airport_city)
        if city_names:
            self.city_names.update(city_names)
        if airport_tz:
            self.airport_tz.update(airport_tz)
        if country:
            self.country.update(country)

    @classmethod
    def load(cls, session: requests.Session) -> "Places":
        airport_city: dict[str, str] = {}
        city_names: dict[str, str] = {}
        airport_tz: dict[str, str] = {}
        country: dict[str, str] = {}
        coords: dict[str, tuple[float, float]] = {}
        try:
            for a in session.get(AIRPORTS_URL, timeout=60).json():
                if a.get("code") and a.get("city_code"):
                    airport_city[a["code"]] = a["city_code"]
                if a.get("code") and a.get("time_zone"):
                    airport_tz[a["code"]] = a["time_zone"]
                if a.get("code") and a.get("country_code"):
                    country[a["code"]] = a["country_code"]
                c = a.get("coordinates") or {}
                if a.get("code") and c.get("lat") is not None and c.get("lon") is not None:
                    coords[a["code"]] = (float(c["lat"]), float(c["lon"]))
            for c in session.get(CITIES_URL, timeout=60).json():
                if c.get("code") and c.get("name"):
                    city_names[c["code"]] = c["name"]
            log.info("Loaded %d airports, %d cities", len(airport_city), len(city_names))
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not load airport data, using built-in table: %s", exc)
        places = cls(airport_city, city_names, airport_tz, country)
        places.coords.update(coords)
        return places

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

    def estimate_minutes(self, a: str, b: str) -> int | None:
        """Rough nonstop flight time from great-circle distance (cruise ~780 km/h + 35 min)."""
        if a not in self.coords or b not in self.coords:
            return None
        (la1, lo1), (la2, lo2) = self.coords[a], self.coords[b]
        p1, p2 = math.radians(la1), math.radians(la2)
        dp, dl = p2 - p1, math.radians(lo2 - lo1)
        h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        km = 2 * 6371 * math.asin(math.sqrt(h))
        return int(round((km / 780 * 60 + 35) / 5) * 5)

    def is_domestic(self, code: str) -> bool:
        return code in DOMESTIC or self.city(code) in DOMESTIC


def airline_name(code: str) -> str:
    return AIRLINES.get(code, code) if code else "?"
