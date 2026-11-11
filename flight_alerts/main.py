"""Entry point: python -m flight_alerts"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import yaml

from .combine import best_per_destination, combine_one_ways, filter_round_trips
from .currency import Converter, load_converter
from .export import export_all
from .models import Deal, Flight
from .ntfy import Ntfy
from .places import Places, airline_name
from .settings import HELP, Settings, apply_command
from .sources.travelpayouts import Travelpayouts
from .sources.wizzair import Blocked, WizzAir

log = logging.getLogger("flight_alerts")

ROOT = Path(__file__).resolve().parent.parent
TZ = ZoneInfo("Asia/Tbilisi")
MONTHS = ["იან", "თებ", "მარ", "აპრ", "მაი", "ივნ", "ივლ", "აგვ", "სექ", "ოქტ", "ნოე", "დეკ"]
WEEKDAYS = ["ორშ", "სამ", "ოთხ", "ხუთ", "პარ", "შაბ", "კვი"]
SOURCE_FAIL_ALERT_AFTER = 4  # consecutive failed runs (= 1 day) before warning the user


def fmt_date(d: date) -> str:
    return f"{d.day} {MONTHS[d.month - 1]} ({WEEKDAYS[d.weekday()]})"


def fmt_transfers(n: int) -> str:
    return "პირდაპირი" if n == 0 else f"{n} გადაჯდომა"


def month_list(first: date, last: date) -> list[str]:
    out, y, m = [], first.year, first.month
    while (y, m) <= (last.year, last.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except (FileNotFoundError, ValueError):
        return {}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
                    encoding="utf-8")


# ---------------------------------------------------------------- settings

def process_commands(ntfy: Ntfy, state: dict, settings: Settings) -> list[str]:
    replies: list[str] = []
    try:
        msgs = ntfy.read_commands(int(state.get("last_command_time", 0)) - 1)
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not read settings topic: %s", exc)
        return replies
    seen = set(state.get("seen_command_ids", []))
    for msg in msgs:
        if msg.get("id") in seen:
            continue
        seen.add(msg.get("id"))
        state["last_command_time"] = max(int(state.get("last_command_time", 0)), int(msg["time"]))
        ok, reply = apply_command(settings, msg.get("message", ""))
        log.info("Command %r → %s", msg.get("message"), reply)
        replies.append(reply)
    state["seen_command_ids"] = sorted(seen)[-50:]
    return replies


def send_settings_reply(ntfy: Ntfy, replies: list[str], settings: Settings) -> None:
    body = "\n".join(replies) + "\n\n" + settings.describe() + "\n\nცვლილება ამოქმედდება შემდეგ შემოწმებაზე."
    ntfy.send("⚙️ პარამეტრები განახლდა", body, tags=["gear"], priority=2,
              actions=ntfy.price_buttons([150, 220, 300]))


# ---------------------------------------------------------------- collecting

def collect(cfg: dict, settings: Settings, conv: Converter, session: requests.Session,
            state: dict, today: date) -> tuple[list[Flight], list[Deal], dict[str, str]]:
    origins = cfg["origins"]
    first = today + timedelta(days=1)
    last = today + timedelta(days=int(cfg.get("days_ahead", 183)))
    flights: list[Flight] = []
    round_trips: list[Deal] = []
    errors: dict[str, str] = {}
    src = cfg.get("sources", {})

    tp_cfg = src.get("travelpayouts", {})
    token = os.environ.get("TRAVELPAYOUTS_TOKEN", "").strip()
    if tp_cfg.get("enabled", True):
        if not token:
            errors["travelpayouts"] = "TRAVELPAYOUTS_TOKEN არ არის დამატებული GitHub Secrets-ში"
        else:
            tp = Travelpayouts(session, token, conv, tp_cfg.get("currency", "eur"))
            try:
                for month in month_list(first, last + timedelta(days=settings.max_nights)):
                    for o in origins:
                        flights += tp.outbound(o, month)
                        flights += tp.inbound(o, month)
                        round_trips += tp.round_trips(o, month)
                log.info("Travelpayouts: %d requests", tp.requests_made)
            except Exception as exc:  # noqa: BLE001
                log.exception("Travelpayouts failed")
                errors["travelpayouts"] = str(exc)[:200]

    wz_cfg = src.get("wizzair", {})
    if wz_cfg.get("enabled", True):
        wz = WizzAir(session, conv, int(wz_cfg.get("window_days", 42)),
                     float(wz_cfg.get("request_delay_seconds", 1.0)),
                     str(wz_cfg.get("fallback_api_version") or ""))
        before = len(flights)
        try:
            flights += wz.collect(origins, first, last, settings.max_nights)
        except Blocked as exc:
            log.warning("%s", exc)
            errors["wizzair"] = str(exc)
        except Exception as exc:  # noqa: BLE001
            log.exception("Wizz Air failed")
            errors["wizzair"] = str(exc)[:200]
        log.info("Wizz Air: %d requests, %d prices", wz.requests_made, len(flights) - before)

    # keep only legs inside the search window
    flights = [f for f in flights if first <= f.depart <= last + timedelta(days=settings.max_nights)]
    round_trips = [d for d in round_trips if first <= d.depart <= last]
    return flights, round_trips, errors


# ---------------------------------------------------------------- notifying

def deal_message(d: Deal, places: Places, conv: Converter, settings: Settings) -> tuple[str, str]:
    dest = places.name(d.destination)
    if d.origin == d.return_to:
        route = f"{places.name(d.origin)} ⇄ {dest}"
    else:
        route = f"{places.name(d.origin)} → {dest} → {places.name(d.return_to)}"
    title = f"✈️ {d.price_gel:.0f}₾ · {route}"

    lines = []
    if d.out_leg and d.back_leg:
        o, b = d.out_leg, d.back_leg
        lines.append(f"🛫 {fmt_date(o.depart)} {o.origin}→{o.destination} · {airline_name(o.airline)}"
                     f" · {fmt_transfers(o.transfers)} · {o.price_gel:.0f}₾")
        lines.append(f"🛬 {fmt_date(b.depart)} {b.origin}→{b.destination} · {airline_name(b.airline)}"
                     f" · {fmt_transfers(b.transfers)} · {b.price_gel:.0f}₾")
    else:
        al = airline_name(d.airlines[0]) if d.airlines else "?"
        lines.append(f"🛫 {fmt_date(d.depart)} {d.origin}→{d.destination}")
        lines.append(f"🛬 {fmt_date(d.ret)} {d.return_from}→{d.return_to}")
        lines.append(f"🏷 {al} · ორმხრივი ბილეთი · {fmt_transfers(d.transfers)}")
    eur = conv.from_gel(d.price_gel, "EUR")
    eur_txt = f" (≈{eur:.0f}€)" if eur else ""
    lines.append(f"🌙 {d.nights} ღამე · სულ {d.price_gel:.0f}₾{eur_txt}")
    lines.append(f"💰 შენი ზღვარი: {settings.max_price_gel:g}₾")
    lines.append("ℹ️ ფასი ბარგის გარეშეა; დაჯავშნამდე გადაამოწმე საიტზე.")
    return title, "\n".join(lines)


def should_notify(d: Deal, places: Places, state: dict, ncfg: dict, now: datetime) -> bool:
    rec = state.get("notified", {}).get(places.city(d.destination))
    if not rec:
        return True
    last_price = float(rec.get("price", 1e9))
    last_at = datetime.fromisoformat(rec.get("at"))
    drop = float(ncfg.get("renotify_drop_percent", 10)) / 100
    if d.price_gel <= last_price * (1 - drop):
        return True
    if now - last_at >= timedelta(days=int(ncfg.get("renotify_after_days", 7))):
        return True
    # same city, but a cheaper deal on different dates appeared after the old one expired
    if date.fromisoformat(rec.get("depart", "1970-01-01")) < now.date():
        return True
    return False


def app_link(d: Deal) -> str:
    base = os.environ.get("APP_URL", "").strip()
    if not base:
        return ""
    return (f"{base.rstrip('/')}/#trip={d.origin}.{d.destination}.{d.depart.isoformat()}"
            f".{d.return_from}.{d.return_to}.{d.ret.isoformat()}")


def notify_deals(deals: list[Deal], ntfy: Ntfy, places: Places, conv: Converter, settings: Settings,
                 state: dict, ncfg: dict, now: datetime) -> int:
    fresh = [d for d in deals if should_notify(d, places, state, ncfg, now)]
    limit = int(ncfg.get("max_per_run", 5))
    urgent = settings.max_price_gel * float(ncfg.get("urgent_below_percent", 70)) / 100
    notified = state.setdefault("notified", {})

    for d in fresh[:limit]:
        title, body = deal_message(d, places, conv, settings)
        links = list(d.extra_links[:2])
        if app_link(d):
            links = links[:1] + [("📊 დეტალები", app_link(d))]
        actions = [{"action": "view", "label": label, "url": url, "clear": False} for label, url in links]
        ntfy.send(title, body, tags=["airplane"], priority=5 if d.price_gel <= urgent else 4,
                  click=d.link, actions=actions)
        notified[places.city(d.destination)] = {
            "price": round(d.price_gel, 2), "at": now.isoformat(), "depart": d.depart.isoformat(),
            "ret": d.ret.isoformat(), "route": f"{d.origin}-{d.destination}-{d.return_to}",
        }

    rest = fresh[limit:]
    if rest:
        lines = [f"• {d.price_gel:.0f}₾ {places.name(d.destination)} · {d.depart:%d.%m}–{d.ret:%d.%m}"
                 f" ({d.origin}/{d.return_to})" for d in rest[:15]]
        ntfy.send(f"✈️ კიდევ {len(rest)} იაფი მიმართულება", "\n".join(lines), tags=["airplane"], priority=3)
        for d in rest:
            notified[places.city(d.destination)] = {
                "price": round(d.price_gel, 2), "at": now.isoformat(), "depart": d.depart.isoformat(),
                "ret": d.ret.isoformat(), "route": f"{d.origin}-{d.destination}-{d.return_to}",
            }
    return len(fresh)


def report_source_health(errors: dict[str, str], state: dict, ntfy: Ntfy, sources: list[str]) -> None:
    health = state.setdefault("source_failures", {})
    for s in sources:
        if s in errors:
            health[s] = health.get(s, 0) + 1
            if health[s] == SOURCE_FAIL_ALERT_AFTER:
                ntfy.send(f"⚠️ {s} არ მუშაობს",
                          f"{s} უკვე {health[s]} შემოწმებაა ვერ იტვირთება.\nშეცდომა: {errors[s]}",
                          tags=["warning"], priority=3)
        else:
            if health.get(s, 0) >= SOURCE_FAIL_ALERT_AFTER:
                ntfy.send(f"✅ {s} ისევ მუშაობს", "წყარო აღდგა.", tags=["white_check_mark"], priority=2)
            health[s] = 0


# ---------------------------------------------------------------- main

def run() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    data_dir = Path(os.environ.get("DATA_DIR") or ROOT / "data")
    state_path = data_dir / "state.json"
    state = load_state(state_path)

    topic = os.environ.get("NTFY_TOPIC", "").strip()
    dry_run = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes") or not topic
    if not topic:
        log.warning("NTFY_TOPIC not set — running in dry-run mode (nothing will be sent)")
    session = requests.Session()
    ntfy = Ntfy(session, os.environ.get("NTFY_SERVER", "https://ntfy.sh"), topic or "dry-run", dry_run)

    now = datetime.now(TZ)
    today = now.date()
    settings = Settings.from_state(cfg.get("defaults", {}), state.get("settings"))

    replies = process_commands(ntfy, state, settings) if topic else []
    state["settings"] = settings.to_dict()
    if replies:
        send_settings_reply(ntfy, replies, settings)

    if not state.get("welcomed") and topic:
        ntfy.send("👋 ფრენების მონიტორინგი ჩაირთო",
                  settings.describe() + f"\n\nშემოწმება ყოველ 6 საათში.\n{HELP}\n"
                  f"ბრძანებები გაგზავნე თემაზე: {ntfy.settings_topic}",
                  tags=["airplane"], priority=3, actions=ntfy.price_buttons([150, 220, 300]))
        state["welcomed"] = True

    if settings.paused:
        log.info("Paused — skipping search")
        save_state(state_path, state)
        return 0

    started = time.time()
    places = Places.load(session)
    conv = load_converter(session, state, cfg.get("fallback_rates_gel", {}))
    flights, round_trips, errors = collect(cfg, settings, conv, session, state, today)

    deals = combine_one_ways(flights, cfg["origins"], places, settings.min_nights,
                             settings.max_nights, settings.max_transfers)
    deals += filter_round_trips(round_trips, places, settings.min_nights, settings.max_nights,
                                settings.max_transfers)
    best = best_per_destination(deals, places, settings.max_price_gel)
    log.info("%d one-way legs, %d round-trip fares → %d trips, %d destinations under %g₾",
             len(flights), len(round_trips), len(deals), len(best), settings.max_price_gel)
    for d in best[:20]:
        log.info("  %6.0f₾  %s→%s→%s  %s..%s (%d nights) [%s]", d.price_gel, d.origin, d.destination,
                 d.return_to, d.depart, d.ret, d.nights, d.source)

    try:
        stats = export_all(data_dir, flights, round_trips, deals, places, settings.to_dict(), conv.rates,
                           cfg["origins"], now, errors)
        log.info("Exported for the app: %s", stats)
    except Exception:  # noqa: BLE001
        log.exception("Export for the app failed")

    sent = notify_deals(best, ntfy, places, conv, settings, state, cfg.get("notifications", {}), now)
    enabled = [s for s, c in cfg.get("sources", {}).items() if c.get("enabled", True)]
    report_source_health(errors, state, ntfy, enabled)

    # prune old notification records
    state["notified"] = {k: v for k, v in state.get("notified", {}).items()
                         if datetime.fromisoformat(v["at"]) > now - timedelta(days=60)}
    cheapest = best[0] if best else None
    state["last_run"] = {
        "at": now.isoformat(timespec="minutes"),
        "seconds": round(time.time() - started),
        "legs": len(flights), "trips": len(deals), "under_limit": len(best), "notified": sent,
        "errors": errors,
        "cheapest": (f"{cheapest.price_gel:.0f}₾ {cheapest.origin}-{cheapest.destination}-"
                     f"{cheapest.return_to} {cheapest.depart}..{cheapest.ret}") if cheapest else None,
    }
    save_state(state_path, state)
    if not flights and not round_trips and errors:
        log.error("All sources failed: %s", errors)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run())
