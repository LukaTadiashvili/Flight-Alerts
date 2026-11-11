from datetime import date, datetime, timedelta

from flight_alerts.combine import best_per_destination, combine_one_ways, filter_round_trips
from flight_alerts.currency import Converter
from flight_alerts.main import month_list, should_notify
from flight_alerts.models import Deal, Flight
from flight_alerts.places import Places
from flight_alerts.settings import Settings, apply_command
from flight_alerts.sources.travelpayouts import Travelpayouts
from flight_alerts.sources.wizzair import parse_timetable, parse_version

P = Places()
D0 = date(2026, 12, 5)


def f(o, x, day, price, src="test", tr=0, al="W6"):
    return Flight(o, x, D0 + timedelta(days=day), price, al, tr, f"http://{o}{x}{day}", src)


def test_open_jaw_and_nights_window():
    flights = [
        f("TBS", "BER", 0, 80),
        f("BER", "KUT", 2, 30),   # 2 nights — too short
        f("BER", "KUT", 4, 70),   # 4 nights — ok
        f("BER", "TBS", 4, 90),   # same day, more expensive
        f("BER", "TBS", 9, 10),   # 9 nights — too long
    ]
    deals = combine_one_ways(flights, ["TBS", "KUT"], P, 3, 7, 1)
    assert len(deals) == 1
    d = deals[0]
    assert (d.origin, d.return_to, d.nights, d.price_gel) == ("TBS", "KUT", 4, 150)
    assert any("დაბრუნება" in label for label, _ in d.extra_links)


def test_city_grouping_milan():
    flights = [f("KUT", "BGY", 0, 60), f("MXP", "KUT", 5, 60, al="PC")]
    deals = combine_one_ways(flights, ["TBS", "KUT"], P, 3, 7, 1)
    assert len(deals) == 1 and deals[0].return_from == "MXP"


def test_transfers_and_domestic_filtered():
    flights = [f("TBS", "BUS", 0, 10), f("BUS", "TBS", 3, 10),
               f("TBS", "IST", 0, 50, tr=2), f("IST", "TBS", 3, 50)]
    assert combine_one_ways(flights, ["TBS", "KUT"], P, 3, 7, 1) == []


def test_best_per_destination_and_limit():
    flights = [f("TBS", "BER", 0, 80), f("BER", "TBS", 3, 80), f("BER", "TBS", 5, 60),
               f("KUT", "BUD", 0, 150), f("BUD", "KUT", 3, 150)]
    deals = combine_one_ways(flights, ["TBS", "KUT"], P, 3, 7, 1)
    best = best_per_destination(deals, P, 220)
    assert [(d.destination, d.price_gel) for d in best] == [("BER", 140)]


def test_round_trip_filter():
    rt = [Deal("TBS", "IST", "IST", "TBS", D0, D0 + timedelta(days=d), 200, airlines=("PC",)) for d in (2, 3, 7, 8)]
    assert [d.nights for d in filter_round_trips(rt, P, 3, 7, 1)] == [3, 7]


def test_settings_commands():
    s = Settings()
    assert apply_command(s, "200")[0] and s.max_price_gel == 200
    assert apply_command(s, "ზღვარი 150₾")[0] and s.max_price_gel == 150
    assert apply_command(s, "Max: 300 GEL")[0] and s.max_price_gel == 300
    assert apply_command(s, "ღამე 2-6")[0] and (s.min_nights, s.max_nights) == (2, 6)
    assert apply_command(s, "პირდაპირი")[0] and s.max_transfers == 0
    assert apply_command(s, "პაუზა")[0] and s.paused
    assert apply_command(s, "ჩართვა")[0] and not s.paused
    assert not apply_command(s, "გამარჯობა")[0]
    assert not apply_command(s, "5")[0]


def test_settings_from_state_overrides_defaults():
    s = Settings.from_state({"max_price_gel": 220, "min_nights": 3}, {"max_price_gel": 180})
    assert s.max_price_gel == 180 and s.min_nights == 3


def test_wizz_parsing():
    assert parse_version('<html>SSR https://be.wizzair.com/27.6.0 </html>') == "27.6.0"
    body = {
        "outboundFlights": [
            {"departureStation": "KUT", "arrivalStation": "BUD", "departureDate": "2026-12-05T00:00:00",
             "price": {"amount": 99.0, "currencyCode": "GEL"}, "priceType": "price"},
            {"departureStation": "KUT", "arrivalStation": "BUD", "departureDate": "2026-12-06T00:00:00",
             "price": {"amount": 0, "currencyCode": "GEL"}, "priceType": "soldOut"},
        ],
        "returnFlights": [
            {"departureStation": "BUD", "arrivalStation": "KUT", "departureDate": "2026-12-09T00:00:00",
             "price": {"amount": 20.0, "currencyCode": "EUR"}, "priceType": "price"},
        ],
    }
    fl = parse_timetable(body, Converter({"EUR": 3.0}))
    assert [(x.origin, x.depart.day, x.price_gel) for x in fl] == [("KUT", 5, 99.0), ("BUD", 9, 60.0)]
    deals = combine_one_ways(fl, ["TBS", "KUT"], P, 3, 7, 1)
    assert deals[0].link.endswith("/KUT/BUD/2026-12-05/2026-12-09/1/0/0/null")


class FakeResp:
    def __init__(self, data, status=200):
        self._d, self.status_code = data, status

    def json(self):
        return self._d

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self, data):
        self.data, self.calls = data, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(params)
        return FakeResp(self.data)


def test_travelpayouts_parsing():
    data = {"success": True, "currency": "eur", "data": [
        {"origin": "TBS", "destination": "BER", "origin_airport": "TBS", "destination_airport": "BER",
         "price": 40, "airline": "W6", "departure_at": "2026-12-05T06:00:00+04:00", "transfers": 0,
         "link": "/search/TBS0512BER1"},
        {"origin": "TBS", "destination": "IST", "origin_airport": "TBS", "destination_airport": "SAW",
         "price": 60, "airline": "PC", "departure_at": "2026-12-05T06:00:00+04:00",
         "return_at": "2026-12-10T10:00:00+03:00", "transfers": 0, "return_transfers": 1, "link": "/x"},
    ]}
    tp = Travelpayouts(FakeSession(data), "t", Converter({"EUR": 3.0}))
    out = tp.outbound("TBS", "2026-12")
    assert out[0].price_gel == 120 and out[0].link == "https://www.aviasales.com/search/TBS0512BER1"
    rts = tp.round_trips("TBS", "2026-12")
    assert len(rts) == 1 and rts[0].destination == "SAW" and rts[0].nights == 5 and rts[0].transfers == 1


def test_should_notify():
    now = datetime(2026, 11, 11, 12, 0)
    d = Deal("TBS", "BER", "BER", "TBS", D0, D0 + timedelta(days=4), 180)
    ncfg = {"renotify_drop_percent": 10, "renotify_after_days": 7}
    assert should_notify(d, P, {}, ncfg, now)
    st = {"notified": {"BER": {"price": 190, "at": now.isoformat(), "depart": "2026-12-01"}}}
    assert not should_notify(d, P, st, ncfg, now)          # only 5% cheaper
    st["notified"]["BER"]["price"] = 210
    assert should_notify(d, P, st, ncfg, now)              # >10% cheaper
    st["notified"]["BER"].update(price=190, at=(now - timedelta(days=8)).isoformat())
    assert should_notify(d, P, st, ncfg, now)              # a week passed


def test_month_list():
    assert month_list(date(2026, 11, 12), date(2027, 5, 20)) == [
        "2026-11", "2026-12", "2027-01", "2027-02", "2027-03", "2027-04", "2027-05"]


def test_export_and_history(tmp_path):
    import json
    from zoneinfo import ZoneInfo
    from flight_alerts.export import export_all

    places = Places(airport_tz={"BUD": "Europe/Budapest"})
    s = {"max_price_gel": 220}
    tz = ZoneInfo("Asia/Tbilisi")
    for day, price in ((0, 100), (1, 100), (2, 80)):
        now = datetime(2026, 11, 10 + day, 12, tzinfo=tz)
        fl = [Flight("KUT", "BUD", D0, price, "W6", 0, "", "wizzair", "06:00"),
              Flight("BUD", "KUT", D0 + timedelta(days=4), 50, "W6", 0, "", "wizzair", "20:00")]
        deals = combine_one_ways(fl, ["TBS", "KUT"], places, 3, 7, 1)
        export_all(tmp_path, fl, [], deals, places, s, {"EUR": 3}, ["TBS", "KUT"], now, {})
    data = json.loads((tmp_path / "flights.json").read_text())
    hist = json.loads((tmp_path / "history.json").read_text())
    leg = dict(zip(data["leg_fields"], data["legs"][0]))
    assert leg["dur"] and leg["est"] == 1 and leg["arr"].startswith("2026-12-05T")   # estimated from distance
    assert hist["legs"]["KUT|BUD|2026-12-05"] == [["2026-11-10", 100], ["2026-11-12", 80]]  # changes only
    assert hist["routes"]["BUD"][-1] == ["2026-11-12", 130]
    assert data["cities"]["BUD"] == "Budapest"


def test_route_pairs_and_route():
    class S:
        def get(self, url, params=None, headers=None, timeout=None):
            if "routes.json" in url:
                return FakeResp([
                    {"airline_iata": "W6", "departure_airport_iata": "KUT", "arrival_airport_iata": "BUD", "codeshare": False},
                    {"airline_iata": "TK", "departure_airport_iata": "TBS", "arrival_airport_iata": "IST", "codeshare": False},
                    {"airline_iata": "XX", "departure_airport_iata": "TBS", "arrival_airport_iata": "IST", "codeshare": True},
                    {"airline_iata": "A9", "departure_airport_iata": "TBS", "arrival_airport_iata": "KUT", "codeshare": False},
                    {"airline_iata": "LH", "departure_airport_iata": "MUC", "arrival_airport_iata": "TBS", "codeshare": False},
                ])
            return FakeResp({"success": True, "data": [
                {"origin_airport": params["origin"], "destination_airport": params["destination"], "price": 30,
                 "airline": "W6", "departure_at": "2026-12-05T06:00:00+04:00", "transfers": 0}]})
    tp = Travelpayouts(S(), "t", Converter({"EUR": 3.0}))
    assert tp.route_pairs(["TBS", "KUT"]) == {("KUT", "BUD"), ("TBS", "IST")}
    fl = tp.route("BUD", "KUT")
    assert fl[0].origin == "BUD" and fl[0].price_gel == 90


def test_per_route_search_uses_seen_destinations():
    from flight_alerts.main import per_route_search

    class TP:
        def __init__(self):
            self.calls = []
        def route_pairs(self, origins):
            raise RuntimeError("offline")
        def route(self, a, b):
            self.calls.append((a, b))
            return []
    tp = TP()
    per_route_search(tp, ["TBS", "KUT"], [f("TBS", "BER", 0, 50), f("ATH", "KUT", 3, 50)], 200)
    assert set(tp.calls) == {("TBS", "BER"), ("BER", "TBS"), ("KUT", "ATH"), ("ATH", "KUT")}
