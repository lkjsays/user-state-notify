#!/usr/bin/env python3
"""user-state-notify proxy.

Small HTTP server for macOS/Hermes status events.
It records events locally and forwards a human-readable message to Hermes webhook.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HOME = Path.home()
HERMES_DIR = HOME / ".hermes"
STATE_DIR = HERMES_DIR / "state"
LOG_DIR = HERMES_DIR / "logs"
STATE_FILE = STATE_DIR / "user_state.json"
EVENT_LOG = LOG_DIR / "user_state_events.jsonl"
PROXY_LOG = LOG_DIR / "user_state_notify_proxy.log"

WEBHOOK_NAME = os.environ.get("USER_STATE_WEBHOOK", "user-state-notify")
DEFAULT_PORT = int(os.environ.get("USER_STATE_PORT", "8645"))

LOCATION_EVENTS = {
    "/home_arrive": ("location.arrive", "home", "arrive", "집에 도착했어요"),
    "/home_depart": ("location.depart", "home", "depart", "집에서 출발했어요"),
    "/office_arrive": ("location.arrive", "office", "arrive", "회사에 도착했어요"),
    "/office_depart": ("location.depart", "office", "depart", "회사에서 출발했어요"),
}

DEVICE_EVENTS = {
    "/device/login": ("device.login", "Mac 로그인 감지"),
    "/device/unlock": ("device.unlock", "Mac 잠금 해제 감지"),
    "/device/wake": ("device.wake", "Mac wake 감지"),
    "/mac_login": ("device.login", "Mac 로그인 감지"),
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def ensure_dirs() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def log_line(message: str) -> None:
    ensure_dirs()
    with PROXY_LOG.open("a", encoding="utf-8") as f:
        f.write(f"{now_iso()} {message}\n")


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict) -> None:
    ensure_dirs()
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(STATE_FILE)


def append_event(event: dict) -> None:
    ensure_dirs()
    with EVENT_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def parse_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    ctype = handler.headers.get("Content-Type", "")
    try:
        if "application/json" in ctype:
            return json.loads(raw.decode("utf-8") or "{}")
        if "application/x-www-form-urlencoded" in ctype:
            return {k: v[-1] if v else "" for k, v in parse_qs(raw.decode("utf-8")).items()}
    except Exception as exc:
        log_line(f"body_parse_error={exc}")
    return {"raw_body": raw.decode("utf-8", errors="replace")}


def event_from_request(path: str, query: dict, body: dict, headers: dict) -> dict | None:
    ts = body.get("timestamp") or query.get("timestamp") or now_iso()
    device = body.get("device") or query.get("device") or headers.get("X-Device-Name") or os.uname().nodename

    if path in LOCATION_EVENTS:
        event_type, place, action, default_message = LOCATION_EVENTS[path]
        return {
            "type": event_type,
            "source": body.get("source") or query.get("source") or "iphone_shortcuts",
            "place": body.get("place") or query.get("place") or place,
            "device": device,
            "action": action,
            "message": body.get("message") or query.get("message") or default_message,
            "timestamp": ts,
            "raw_path": path,
        }

    if path in DEVICE_EVENTS:
        event_type, default_message = DEVICE_EVENTS[path]
        return {
            "type": event_type,
            "source": body.get("source") or query.get("source") or "macos",
            "device": device,
            "message": body.get("message") or query.get("message") or default_message,
            "timestamp": ts,
            "raw_path": path,
        }

    return None


def update_state(event: dict) -> dict:
    state = load_state()
    state["updated_at"] = now_iso()
    state["last_event"] = event

    if event["type"].startswith("location."):
        status = "arrived" if event.get("action") == "arrive" else "departed"
        state["current_location"] = {
            "place": event.get("place"),
            "status": status,
            "updated_at": event.get("timestamp"),
            "source": event.get("source"),
        }
        state["last_real_location_event"] = event
        state["inferred_presence"] = {
            "place": event.get("place"),
            "confidence": 0.8,
            "reason": f"최근 실제 위치 이벤트: {event.get('place')} {event.get('action')}",
            "updated_at": event.get("timestamp"),
        }
    elif event["type"].startswith("device."):
        state["last_device_event"] = event
        devices = state.setdefault("devices", {})
        devices[event.get("device") or "unknown"] = {
            "last_event_type": event.get("type"),
            "updated_at": event.get("timestamp"),
            "source": event.get("source"),
        }

    save_state(state)
    append_event(event)
    return state


def forward_to_hermes(event: dict) -> tuple[bool, str]:
    message = event.get("message") or event.get("type") or "user-state event"
    payload = {
        "event": event,
        "message": message,
        "text": message,
    }

    candidates = [
        ["hermes", "webhook", "trigger", WEBHOOK_NAME, "--json", json.dumps(payload, ensure_ascii=False)],
        ["hermes", "webhook", "send", WEBHOOK_NAME, "--json", json.dumps(payload, ensure_ascii=False)],
    ]

    last = ""
    for cmd in candidates:
        try:
            proc = subprocess.run(cmd, text=True, capture_output=True, timeout=20)
        except FileNotFoundError:
            return False, "hermes command not found"
        except Exception as exc:
            last = str(exc)
            continue
        if proc.returncode == 0:
            return True, proc.stdout.strip()
        last = (proc.stderr or proc.stdout).strip()
    return False, last


class Handler(BaseHTTPRequestHandler):
    server_version = "user-state-notify/1.0"

    def do_GET(self) -> None:
        self.handle_request()

    def do_POST(self) -> None:
        self.handle_request()

    def log_message(self, fmt: str, *args) -> None:
        log_line(fmt % args)

    def write_json(self, status: int, payload: dict) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def handle_request(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = {k: v[-1] if v else "" for k, v in parse_qs(parsed.query).items()}

        if path == "/health":
            self.write_json(200, {"status": "ok", "service": "user-state-notify"})
            return

        body = parse_body(self)
        event = event_from_request(path, query, body, dict(self.headers))
        if not event:
            self.write_json(404, {"ok": False, "error": "unknown endpoint", "path": path})
            return

        state = update_state(event)
        ok, detail = forward_to_hermes(event)
        log_line(f"event={event.get('type')} path={path} webhook_ok={ok} detail={detail[:300]}")
        self.write_json(200, {"ok": True, "event": event, "webhook_ok": ok, "webhook_detail": detail, "state_updated_at": state.get("updated_at")})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.environ.get("USER_STATE_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    ensure_dirs()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    log_line(f"starting host={args.host} port={args.port} webhook={WEBHOOK_NAME}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log_line("stopping")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
