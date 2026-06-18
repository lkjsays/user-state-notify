#!/usr/bin/env python3
"""Reminder storage and matching logic for user-state-notify.

Pure logic — knows nothing about HTTP. Inputs are dicts, outputs are dicts/lists.
The proxy imports ReminderStore, exposes endpoints, and forwards fired reminders.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
from datetime import datetime
from pathlib import Path

HOME = Path.home()
DEFAULT_STATE_DIR = HOME / ".hermes" / "state"

DEFAULT_ALIASES = {
    "회사맥": {"device": "mac-studio-office"},
    "회사맥북": {"device": "macbook", "place": "office"},
    "집맥": {"device": "mac-mini-home"},
    "회사": {"place": "office"},
    "집": {"place": "home"},
}

_TOKEN_RE = re.compile(r"@([^\s@]+)")


def _empty() -> dict:
    return {"reminders": [], "sessions": {}}


class ReminderStore:
    def __init__(self, state_dir=DEFAULT_STATE_DIR, gap_min=None, now_fn=None):
        self.state_dir = Path(state_dir)
        self.reminders_path = self.state_dir / "reminders.json"
        self.aliases_path = self.state_dir / "reminder_aliases.json"
        if gap_min is not None:
            self.gap_min = gap_min
        else:
            self.gap_min = int(os.environ.get("USER_STATE_SESSION_GAP_MIN", "60"))
        self._now = now_fn or (lambda: datetime.now().astimezone())
        self._lock = threading.Lock()

    # ---- time helpers ----
    def _iso(self, dt) -> str:
        return dt.isoformat(timespec="seconds")

    def _parse_dt(self, s):
        if not s:
            return None
        try:
            return datetime.fromisoformat(s)
        except Exception:
            return None

    # ---- storage (caller holds lock) ----
    def _load(self) -> dict:
        if not self.reminders_path.exists():
            return _empty()
        try:
            data = json.loads(self.reminders_path.read_text(encoding="utf-8"))
        except Exception:
            try:
                self.reminders_path.replace(self.reminders_path.with_suffix(".json.corrupt"))
            except Exception:
                pass
            return _empty()
        data.setdefault("reminders", [])
        data.setdefault("sessions", {})
        return data

    def _save(self, data: dict) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.reminders_path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self.reminders_path)

    def _load_aliases(self) -> dict:
        if not self.aliases_path.exists():
            self.state_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.aliases_path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(DEFAULT_ALIASES, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            tmp.replace(self.aliases_path)
            return dict(DEFAULT_ALIASES)
        try:
            return json.loads(self.aliases_path.read_text(encoding="utf-8"))
        except Exception:
            return dict(DEFAULT_ALIASES)

    def _apply_tokens(self, text, aliases, place, device):
        found_place, found_device = place, device

        def repl(m):
            nonlocal found_place, found_device
            alias = aliases.get(m.group(1))
            if not alias:
                return m.group(0)  # unknown token: keep in text
            if found_device is None and alias.get("device"):
                found_device = alias["device"]
            if found_place is None and alias.get("place"):
                found_place = alias["place"]
            return ""

        new_text = _TOKEN_RE.sub(repl, text or "")
        new_text = re.sub(r"\s+", " ", new_text).strip()
        return new_text, found_place, found_device

    # ---- public API ----
    def add(self, text, place=None, device=None) -> dict:
        with self._lock:
            aliases = self._load_aliases()
            clean, place, device = self._apply_tokens(text, aliases, place, device)
            if not clean:
                raise ValueError("text required")
            if not place and not device:
                raise ValueError("reminder requires place/device or a known @token")
            data = self._load()
            rem = {
                "id": "r_" + secrets.token_hex(3),
                "text": clean,
                "place": place,
                "device": device,
                "status": "pending",
                "created_at": self._iso(self._now()),
                "done_at": None,
                "fired": {},
            }
            data["reminders"].append(rem)
            self._save(data)
            return rem

    def list(self, status=None) -> list:
        with self._lock:
            items = self._load()["reminders"]
            if status:
                items = [r for r in items if r.get("status") == status]
            return items

    def mark_done(self, rid) -> dict | None:
        with self._lock:
            data = self._load()
            for r in data["reminders"]:
                if r["id"] == rid:
                    if r["status"] != "done":
                        r["status"] = "done"
                        r["done_at"] = self._iso(self._now())
                        self._save(data)
                    return r
            return None
