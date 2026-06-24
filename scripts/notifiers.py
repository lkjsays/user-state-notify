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
