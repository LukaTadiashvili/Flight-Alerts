"""ntfy.sh publishing (JSON API, so Georgian text works) and reading the settings topic."""
from __future__ import annotations

import json
import logging

import requests

log = logging.getLogger(__name__)


class Ntfy:
    def __init__(self, session: requests.Session, server: str, topic: str, dry_run: bool = False):
        self.session = session
        self.server = server.rstrip("/")
        self.topic = topic
        self.settings_topic = f"{topic}-settings"
        self.dry_run = dry_run
        self.sent = 0

    @property
    def settings_url(self) -> str:
        return f"{self.server}/{self.settings_topic}"

    def price_buttons(self, values: list[int]) -> list[dict]:
        """Buttons that change the price limit with a tap (posts to the settings topic)."""
        return [
            {"action": "http", "label": f"{v}₾", "url": self.settings_url,
             "method": "POST", "body": str(v), "clear": True}
            for v in values
        ]

    def send(self, title: str, message: str, *, tags: list[str] | None = None, priority: int = 3,
             click: str | None = None, actions: list[dict] | None = None) -> None:
        payload = {"topic": self.topic, "title": title, "message": message, "priority": priority}
        if tags:
            payload["tags"] = tags
        if click:
            payload["click"] = click
        if actions:
            payload["actions"] = actions[:3]  # ntfy allows max 3 buttons
        self.sent += 1
        if self.dry_run:
            log.info("[dry-run] ntfy:\n%s", json.dumps(payload, ensure_ascii=False, indent=2))
            return
        resp = self.session.post(self.server, data=json.dumps(payload).encode(), timeout=30)
        resp.raise_for_status()

    def read_commands(self, since_time: int) -> list[dict]:
        """Messages posted to the settings topic after `since_time` (unix seconds).
        ntfy.sh keeps messages ~12h, runs are every 6h, so nothing gets lost."""
        resp = self.session.get(f"{self.settings_url}/json", params={"poll": "1", "since": "all"}, timeout=30)
        resp.raise_for_status()
        out = []
        for line in resp.text.splitlines():
            if not line.strip():
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("event") == "message" and int(msg.get("time", 0)) > since_time:
                out.append(msg)
        return sorted(out, key=lambda m: m.get("time", 0))
