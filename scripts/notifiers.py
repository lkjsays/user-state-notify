#!/usr/bin/env python3
"""Pluggable notification dispatch for user-state-notify.

Pure logic, no HTTP server coupling. HTTP and subprocess calls are injectable
so the dispatcher and notifiers can be tested without a network or Hermes.
"""

from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".user-state-notify" / "config.json"


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> tuple[dict | None, str | None]:
    path = Path(path)
    if not path.exists():
        return None, f"config not found: {path}"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except Exception as exc:
        return None, f"invalid config json ({path}): {exc}"


def _http_post(url: str, data: bytes, headers: dict, timeout: int = 10) -> tuple[bool, str]:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            return 200 <= resp.status < 300, f"{resp.status} {body[:200]}"
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace") if hasattr(exc, "read") else ""
        return False, f"http {exc.code} {detail[:200]}"
    except Exception as exc:
        return False, str(exc)


class TelegramNotifier:
    type = "telegram"

    def __init__(self, conf: dict, *, http_post=_http_post, runner=subprocess.run):
        try:
            self.bot_token = conf["bot_token"]
            self.chat_id = conf["chat_id"]
        except KeyError as exc:
            raise ValueError(f"telegram notifier missing field: {exc}") from exc
        self._http_post = http_post

    def send(self, message: str, event: dict) -> tuple[bool, str]:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        data = json.dumps({"chat_id": self.chat_id, "text": message}, ensure_ascii=False).encode("utf-8")
        return self._http_post(url, data, {"Content-Type": "application/json; charset=utf-8"}, 10)


class WebhookNotifier:
    type = "webhook"

    def __init__(self, conf: dict, *, http_post=_http_post, runner=subprocess.run):
        url = conf.get("url")
        if not url:
            raise ValueError("webhook notifier missing field: 'url'")
        self.url = url
        self.extra_headers = dict(conf.get("headers") or {})
        self._http_post = http_post

    def send(self, message: str, event: dict) -> tuple[bool, str]:
        data = json.dumps(
            {"message": message, "text": message, "event": event}, ensure_ascii=False
        ).encode("utf-8")
        headers = {"Content-Type": "application/json; charset=utf-8", **self.extra_headers}
        return self._http_post(self.url, data, headers, 10)


class HermesNotifier:
    type = "hermes"

    def __init__(self, conf: dict, *, http_post=_http_post, runner=subprocess.run):
        self.webhook_name = conf.get("webhook_name", "user-state-notify")
        self._runner = runner

    def send(self, message: str, event: dict) -> tuple[bool, str]:
        payload = json.dumps(
            {"event": event, "message": message, "text": message}, ensure_ascii=False
        )
        candidates = [
            ["hermes", "webhook", "trigger", self.webhook_name, "--json", payload],
            ["hermes", "webhook", "send", self.webhook_name, "--json", payload],
        ]
        last = ""
        for cmd in candidates:
            try:
                proc = self._runner(cmd, text=True, capture_output=True, timeout=20)
            except FileNotFoundError:
                return False, "hermes command not found"
            except Exception as exc:
                last = str(exc)
                continue
            if proc.returncode == 0:
                return True, (proc.stdout or "").strip()
            last = ((proc.stderr or proc.stdout) or "").strip()
        return False, last


REGISTRY = {
    "telegram": TelegramNotifier,
    "webhook": WebhookNotifier,
    "hermes": HermesNotifier,
}


def build_notifiers(config: dict, *, http_post=_http_post, runner=subprocess.run) -> tuple[list, list[str]]:
    built: list = []
    errors: list[str] = []
    for i, conf in enumerate(config.get("notifiers", [])):
        if not conf.get("enabled", True):
            continue
        ntype = conf.get("type")
        cls = REGISTRY.get(ntype)
        if cls is None:
            errors.append(f"unknown notifier type {ntype!r} (entry {i})")
            continue
        try:
            built.append(cls(conf, http_post=http_post, runner=runner))
        except ValueError as exc:
            errors.append(f"{ntype} config error (entry {i}): {exc}")
    return built, errors


def notify(message: str, event: dict, targets: list) -> tuple[bool, list[dict]]:
    results: list[dict] = []
    any_ok = False
    for n in targets:
        try:
            ok, detail = n.send(message, event)
        except Exception as exc:
            ok, detail = False, f"exception: {exc}"
        results.append({"type": getattr(n, "type", "?"), "ok": bool(ok), "detail": detail})
        any_ok = any_ok or bool(ok)
    return any_ok, results
