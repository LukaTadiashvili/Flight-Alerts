"""User settings that can be changed from the phone through an ntfy topic.

Send any of these to the settings topic (case-insensitive, Georgian works too):
    200            / max 200 / ზღვარი 200   → max round-trip price 200₾
    nights 3-7     / ღამე 3-7                → trip length
    direct         / პირდაპირი               → only direct flights
    transfers 1    / გადაჯდომა 1             → allow up to 1 transfer
    pause          / პაუზა                   → stop notifications
    resume         / ჩართვა                  → resume notifications
    status         / სტატუსი                 → send current settings
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass


@dataclass
class Settings:
    max_price_gel: float = 220
    min_nights: int = 3
    max_nights: int = 7
    max_transfers: int = 1
    paused: bool = False

    @classmethod
    def from_state(cls, defaults: dict, stored: dict | None) -> "Settings":
        s = cls(**{k: v for k, v in defaults.items() if k in cls.__dataclass_fields__})
        for k, v in (stored or {}).items():
            if k in cls.__dataclass_fields__:
                setattr(s, k, v)
        return s

    def to_dict(self) -> dict:
        return asdict(self)

    def describe(self) -> str:
        tr = "მხოლოდ პირდაპირი" if self.max_transfers == 0 else f"მაქს. {self.max_transfers} გადაჯდომა"
        state = "⏸ პაუზაზეა" if self.paused else "▶️ აქტიურია"
        return (f"{state}\n💰 ზღვარი: {self.max_price_gel:g}₾ (წასვლა+დაბრუნება)\n"
                f"🌙 {self.min_nights}–{self.max_nights} ღამე\n✈️ {tr}")


HELP = ("ბრძანებები: «200» (ზღვარი ლარში), «ღამე 3-7», «პირდაპირი», "
        "«გადაჯდომა 1», «პაუზა», «ჩართვა», «სტატუსი»")

_NUM = r"(\d{2,5})"


def apply_command(settings: Settings, text: str) -> tuple[bool, str]:
    """Apply one command. Returns (understood, reply text)."""
    t = text.strip().lower().replace("₾", " ").replace("gel", " ").replace("ლარი", " ").strip()

    if m := re.fullmatch(rf"(?:max|limit|price|ზღვარი|ფასი|მაქს)?\s*[:=]?\s*{_NUM}\s*", t):
        value = int(m.group(1))
        if not 20 <= value <= 10000:
            return False, f"❓ {value}₾ არარეალური ზღვარია"
        settings.max_price_gel = value
        return True, f"✅ ახალი ზღვარი: {value}₾"

    if m := re.fullmatch(r"(?:nights|days|ღამე|ღამეები|დღე|დღეები)\s*[:=]?\s*(\d{1,2})\s*[-–—]\s*(\d{1,2})", t):
        a, b = sorted((int(m.group(1)), int(m.group(2))))
        if a < 1 or b > 30:
            return False, "❓ ღამეები 1–30 შუალედში უნდა იყოს"
        settings.min_nights, settings.max_nights = a, b
        return True, f"✅ მოგზაურობის ხანგრძლივობა: {a}–{b} ღამე"

    if t in ("direct", "პირდაპირი", "პირდაპირ"):
        settings.max_transfers = 0
        return True, "✅ მხოლოდ პირდაპირი ფრენები"

    if m := re.fullmatch(r"(?:transfers|stops|გადაჯდომა|გადაჯდომები)\s*[:=]?\s*(\d)", t):
        settings.max_transfers = int(m.group(1))
        return True, f"✅ მაქსიმუმ {settings.max_transfers} გადაჯდომა"

    if t in ("pause", "stop", "off", "პაუზა", "გაჩერება", "გამორთვა"):
        settings.paused = True
        return True, "⏸ შეტყობინებები შეჩერებულია. ჩასართავად გამოგზავნე «ჩართვა»"

    if t in ("resume", "start", "on", "ჩართვა", "გაგრძელება"):
        settings.paused = False
        return True, "▶️ შეტყობინებები ჩართულია"

    if t in ("status", "settings", "სტატუსი", "პარამეტრები", "?"):
        return True, "ℹ️ მიმდინარე პარამეტრები"

    return False, f"❓ ვერ გავიგე: «{text.strip()[:40]}». {HELP}"
