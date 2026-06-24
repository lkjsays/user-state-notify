#!/usr/bin/env python3
"""Backward-compatible wrapper for older launchd/iPhone setup names."""

from pathlib import Path
import runpy

script = Path.home() / ".user-state-notify" / "scripts" / "user_state_notify_proxy.py"
runpy.run_path(str(script), run_name="__main__")
