# 위치/컨텍스트 기반 리마인더 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 특정 장소·디바이스에서 PC를 활성화했을 때, 그 컨텍스트에 묶어 둔 할 일을 Telegram(Hermes webhook)으로 자동으로 띄워 주는 리마인더 시스템을 기존 프록시에 추가한다.

**Architecture:** 리마인더의 저장·매칭·세션·수명 로직은 `scripts/reminders.py`의 `ReminderStore` 클래스에 담고(HTTP를 모르는 순수 로직, 단독 테스트 가능), 기존 `user_state_notify_proxy.py`는 HTTP/이벤트 계층으로서 새 엔드포인트를 노출하고 디바이스 이벤트 수신 시 `ReminderStore.on_device_event`를 호출한다. 발화 메시지는 기존 `forward_to_hermes`로 전송한다.

**Tech Stack:** Python 3.11 표준 라이브러리만 사용(http.server, json, threading, datetime, re, secrets). 외부 의존성 없음. 테스트는 `unittest`.

## Global Constraints

- Python 표준 라이브러리만 사용. 새 pip 의존성 추가 금지.
- 모든 상태 파일 쓰기는 원자적(tmp 파일 작성 후 `.replace()`).
- 저장 위치: `~/.hermes/state/reminders.json`, `~/.hermes/state/reminder_aliases.json`.
- 상태 변경 엔드포인트(`POST /remind`, `POST /reminders/{id}/done`)는 `X-Webhook-Secret` 헤더를 검증한다. 기대값은 `os.environ.get("USER_STATE_SECRET", "hermes-claude-hook")`.
- 세션 간격 임계값 기본 60분, `os.environ.get("USER_STATE_SESSION_GAP_MIN", "60")`로 조정.
- 디바이스 이벤트 타입 문자열: `device.login`, `device.wake`, `device.unlock` (기존 `DEVICE_EVENTS` 매핑이 생성).
- 리마인더 로직은 부가 기능 — 예외가 나도 기존 이벤트 응답(상태 기록·알림)을 막지 않는다.
- 매칭은 AND: 리마인더에 지정된 `place`/`device` 조건이 모두 일치해야 발화.
- 커밋 메시지 말미에 다음 한 줄 포함:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

## File Structure

- **Create `scripts/reminders.py`** — `ReminderStore` 클래스: 저장(load/save/원자적), `add`/`list`/`mark_done`, `@토큰` 파싱, `on_device_event`(세션 경계·매칭·발화). 별칭 기본값 자동 생성.
- **Modify `scripts/user_state_notify_proxy.py`** — device 이벤트 dict에 `place` 보존, 시크릿 검증 헬퍼, 리마인더 엔드포인트 라우팅, 디바이스 이벤트 후 `on_device_event` 호출/전송.
- **Create `tests/test_reminders.py`** — `ReminderStore` 단위 테스트(임시 디렉터리, 주입된 시계·간격).
- **Modify `install.sh`** — 서버 설치 시 `reminders.py`를 함께 내려받음.
- **Modify `README.md`, `docs/operations.md`** — 엔드포인트·토큰·완료 방법 문서화.

---

## Task 1: ReminderStore — 저장 + add/list/mark_done

**Files:**
- Create: `scripts/reminders.py`
- Test: `tests/test_reminders.py`

**Interfaces:**
- Consumes: 없음(신규 모듈).
- Produces:
  - `reminders.ReminderStore(state_dir=<path>, gap_min: int|None=None, now_fn: callable|None=None)`
  - `store.add(text: str, place: str|None=None, device: str|None=None) -> dict` — 리마인더 dict 반환. 조건 0개거나 텍스트가 비면 `ValueError`.
  - `store.list(status: str|None=None) -> list[dict]`
  - `store.mark_done(rid: str) -> dict|None` — 없으면 `None`, 있으면 리마인더 dict(멱등).
  - 리마인더 dict 형태: `{"id","text","place","device","status","created_at","done_at","fired"}`.
  - 모듈 상수 `reminders.DEFAULT_ALIASES: dict`.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_reminders.py` 생성:

```python
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import reminders  # noqa: E402

KST = timezone(timedelta(hours=9))
FIXED = datetime(2026, 6, 18, 9, 0, 0, tzinfo=KST)


def make_store(tmp, clock=None, gap_min=60):
    return reminders.ReminderStore(
        state_dir=tmp,
        gap_min=gap_min,
        now_fn=clock or (lambda: FIXED),
    )


class AddListDoneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = make_store(self.tmp)

    def test_add_with_device(self):
        r = self.store.add("보고서 작성", device="mac-studio-office")
        self.assertEqual(r["device"], "mac-studio-office")
        self.assertIsNone(r["place"])
        self.assertEqual(r["status"], "pending")
        self.assertEqual(self.store.list(status="pending")[0]["id"], r["id"])

    def test_add_parses_device_token(self):
        r = self.store.add("보고서 작성@회사맥")
        self.assertEqual(r["device"], "mac-studio-office")
        self.assertEqual(r["text"], "보고서 작성")

    def test_add_token_with_place_and_device(self):
        r = self.store.add("점심 메모@회사맥북")
        self.assertEqual(r["device"], "macbook")
        self.assertEqual(r["place"], "office")
        self.assertEqual(r["text"], "점심 메모")

    def test_explicit_arg_wins_over_token(self):
        r = self.store.add("작업@회사맥", device="override-mac")
        self.assertEqual(r["device"], "override-mac")

    def test_add_requires_condition(self):
        with self.assertRaises(ValueError):
            self.store.add("그냥 메모")

    def test_add_requires_text(self):
        with self.assertRaises(ValueError):
            self.store.add("@회사맥")

    def test_unknown_token_kept_in_text(self):
        r = self.store.add("정리@모르는곳", device="d1")
        self.assertIn("@모르는곳", r["text"])

    def test_list_filter_status(self):
        a = self.store.add("a", device="d1")
        self.store.add("b", device="d1")
        self.store.mark_done(a["id"])
        pending = self.store.list(status="pending")
        self.assertEqual(len(pending), 1)
        self.assertEqual(len(self.store.list()), 2)

    def test_mark_done(self):
        r = self.store.add("x", device="d1")
        done = self.store.mark_done(r["id"])
        self.assertEqual(done["status"], "done")
        self.assertIsNotNone(done["done_at"])
        self.assertEqual(self.store.list(status="pending"), [])

    def test_mark_done_idempotent(self):
        r = self.store.add("x", device="d1")
        self.store.mark_done(r["id"])
        again = self.store.mark_done(r["id"])
        self.assertEqual(again["status"], "done")

    def test_mark_done_missing(self):
        self.assertIsNone(self.store.mark_done("r_nope"))

    def test_aliases_file_autocreated(self):
        self.store.add("x", device="d1")  # triggers alias load
        path = Path(self.tmp) / "reminder_aliases.json"
        self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /Users/kijeonglee/Projects/user-state-notify && python3 -m unittest tests.test_reminders -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'reminders'` (또는 import 직후 AttributeError).

- [ ] **Step 3: 최소 구현 작성**

`scripts/reminders.py` 생성:

```python
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
            self.aliases_path.write_text(
                json.dumps(DEFAULT_ALIASES, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
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
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd /Users/kijeonglee/Projects/user-state-notify && python3 -m unittest tests.test_reminders -v`
Expected: PASS — `AddListDoneTests`의 모든 테스트 통과.

- [ ] **Step 5: 커밋**

```bash
cd /Users/kijeonglee/Projects/user-state-notify
git add scripts/reminders.py tests/test_reminders.py
git commit -m "$(cat <<'EOF'
feat: add ReminderStore with add/list/mark_done and @token parsing

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: ReminderStore.on_device_event — 세션 경계 · 매칭 · 발화

**Files:**
- Modify: `scripts/reminders.py` (`ReminderStore`에 `_matches`, `_build_message`, `on_device_event` 추가)
- Test: `tests/test_reminders.py` (`EventTests` 클래스 추가)

**Interfaces:**
- Consumes: Task 1의 `ReminderStore` 저장·로드 메서드.
- Produces:
  - `store.on_device_event(event: dict, forward_fn: callable) -> list[dict]`
    - `event`: `{"type": "device.login"|"device.wake"|"device.unlock", "device": str, "place": str|None, "timestamp": str(iso)}`.
    - `forward_fn(message: str) -> bool` — 전송 성공 시 True. True일 때만 `fired` 기록.
    - 반환: 이번 호출에서 실제 발화(전송 성공)한 리마인더 dict 리스트.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_reminders.py`의 맨 아래 `if __name__` 블록 **위에** 다음 클래스를 추가:

```python
class Clock:
    def __init__(self, start):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, minutes):
        self.t = self.t + timedelta(minutes=minutes)


class EventTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.clock = Clock(FIXED)
        self.store = make_store(self.tmp, clock=self.clock, gap_min=60)
        self.sent = []
        self.forward = lambda msg: (self.sent.append(msg) or True)

    def ev(self, etype, device="mac-studio-office", place="office"):
        return {
            "type": etype,
            "device": device,
            "place": place,
            "timestamp": self.clock().isoformat(timespec="seconds"),
        }

    def test_login_fires_and_forwards(self):
        self.store.add("보고서", device="mac-studio-office")
        fired = self.store.on_device_event(self.ev("device.login"), self.forward)
        self.assertEqual(len(fired), 1)
        self.assertEqual(len(self.sent), 1)

    def test_same_session_unlock_no_refire(self):
        self.store.add("보고서", device="mac-studio-office")
        self.store.on_device_event(self.ev("device.login"), self.forward)
        self.clock.advance(5)
        fired = self.store.on_device_event(self.ev("device.unlock"), self.forward)
        self.assertEqual(fired, [])

    def test_long_gap_unlock_refires(self):
        self.store.add("보고서", device="mac-studio-office")
        self.store.on_device_event(self.ev("device.login"), self.forward)
        self.clock.advance(90)
        fired = self.store.on_device_event(self.ev("device.unlock"), self.forward)
        self.assertEqual(len(fired), 1)

    def test_long_gap_wake_refires(self):
        self.store.add("보고서", device="mac-studio-office")
        self.store.on_device_event(self.ev("device.login"), self.forward)
        self.clock.advance(90)
        fired = self.store.on_device_event(self.ev("device.wake"), self.forward)
        self.assertEqual(len(fired), 1)

    def test_added_midsession_fires_next_event(self):
        self.store.on_device_event(self.ev("device.login"), self.forward)
        self.store.add("보고서", device="mac-studio-office")
        self.clock.advance(5)
        fired = self.store.on_device_event(self.ev("device.unlock"), self.forward)
        self.assertEqual(len(fired), 1)

    def test_place_match_any_device(self):
        self.store.add("회사일", place="office")
        fired = self.store.on_device_event(
            self.ev("device.login", device="some-other-mac", place="office"), self.forward
        )
        self.assertEqual(len(fired), 1)

    def test_place_mismatch(self):
        self.store.add("집안일", place="home")
        fired = self.store.on_device_event(self.ev("device.login", place="office"), self.forward)
        self.assertEqual(fired, [])

    def test_and_requires_both(self):
        self.store.add("x", place="office", device="mac-studio-office")
        f1 = self.store.on_device_event(
            self.ev("device.login", place=None), self.forward
        )
        self.assertEqual(f1, [])
        self.clock.advance(120)
        f2 = self.store.on_device_event(self.ev("device.login", place="office"), self.forward)
        self.assertEqual(len(f2), 1)

    def test_done_not_fired(self):
        r = self.store.add("x", device="d")
        self.store.mark_done(r["id"])
        fired = self.store.on_device_event(
            self.ev("device.login", device="d", place=None), self.forward
        )
        self.assertEqual(fired, [])

    def test_forward_failure_not_recorded_then_retries(self):
        self.store.add("x", device="d")
        fired = self.store.on_device_event(
            self.ev("device.login", device="d", place=None), lambda m: False
        )
        self.assertEqual(fired, [])
        self.clock.advance(5)
        retry_sent = []
        fired2 = self.store.on_device_event(
            self.ev("device.unlock", device="d", place=None),
            lambda m: retry_sent.append(m) or True,
        )
        self.assertEqual(len(fired2), 1)

    def test_message_contains_text_and_id(self):
        r = self.store.add("보고서 작성", device="mac-studio-office")
        self.store.on_device_event(self.ev("device.login"), self.forward)
        self.assertIn("보고서 작성", self.sent[0])
        self.assertIn(r["id"], self.sent[0])
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd /Users/kijeonglee/Projects/user-state-notify && python3 -m unittest tests.test_reminders.EventTests -v`
Expected: FAIL — `AttributeError: 'ReminderStore' object has no attribute 'on_device_event'`.

- [ ] **Step 3: 최소 구현 작성**

`scripts/reminders.py`의 `mark_done` 메서드 **아래에** 다음 메서드들을 추가(클래스 내부, 같은 들여쓰기):

```python
    def _matches(self, rem, device, place) -> bool:
        rd, rp = rem.get("device"), rem.get("place")
        if rd and rd != device:
            return False
        if rp and rp != place:
            return False
        return True

    def _build_message(self, device, place, fire) -> str:
        header = device + (f" ({place})" if place else "")
        lines = [f"{i + 1}. {r['text']}  [{r['id']}]" for i, r in enumerate(fire)]
        body = "\n".join(lines)
        return f"📌 {header} — 할 일 {len(fire)}건\n{body}\n완료: POST /reminders/<id>/done"

    def on_device_event(self, event, forward_fn) -> list:
        with self._lock:
            data = self._load()
            device = event.get("device") or "unknown"
            place = event.get("place")
            etype = event.get("type") or ""
            now = self._parse_dt(event.get("timestamp")) or self._now()

            sessions = data.setdefault("sessions", {})
            sess = sessions.get(device)

            new_session = False
            if etype == "device.login" or sess is None:
                new_session = True
            elif etype in ("device.wake", "device.unlock"):
                last = self._parse_dt(sess.get("last_activity_at"))
                if last is None:
                    new_session = True
                else:
                    gap_min = (now - last).total_seconds() / 60.0
                    if gap_min > self.gap_min:
                        new_session = True

            if new_session:
                sid = (sess["id"] + 1) if sess else 1
                sessions[device] = {
                    "id": sid,
                    "started_at": self._iso(now),
                    "last_activity_at": self._iso(now),
                }
            else:
                sid = sess["id"]
                sess["last_activity_at"] = self._iso(now)
                sessions[device] = sess

            fire = []
            for rem in data["reminders"]:
                if rem.get("status") != "pending":
                    continue
                if not self._matches(rem, device, place):
                    continue
                prev = rem.get("fired", {}).get(device)
                if prev and prev.get("session_id") == sid:
                    continue
                fire.append(rem)

            if fire:
                ok = bool(forward_fn(self._build_message(device, place, fire)))
                if ok:
                    for rem in fire:
                        rem.setdefault("fired", {})[device] = {
                            "session_id": sid,
                            "at": self._iso(now),
                        }
                else:
                    fire = []

            self._save(data)
            return fire
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd /Users/kijeonglee/Projects/user-state-notify && python3 -m unittest tests.test_reminders -v`
Expected: PASS — `AddListDoneTests`와 `EventTests` 전체 통과.

- [ ] **Step 5: 커밋**

```bash
cd /Users/kijeonglee/Projects/user-state-notify
git add scripts/reminders.py tests/test_reminders.py
git commit -m "$(cat <<'EOF'
feat: add gap-based session matching and firing to ReminderStore

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: 프록시 통합 — place 보존, 엔드포인트, 발화 연동

**Files:**
- Modify: `scripts/user_state_notify_proxy.py`

**Interfaces:**
- Consumes: `reminders.ReminderStore` (`add`/`list`/`mark_done`/`on_device_event`), 기존 `forward_to_hermes(event) -> (bool, str)`, `parse_body`, `log_line`, `write_json`.
- Produces: HTTP 엔드포인트 `POST /remind`, `GET /reminders`, `POST /reminders/{id}/done`. device 이벤트 dict에 `place` 필드 포함.

- [ ] **Step 1: reminders 모듈 import + 스토어/시크릿/콜백 추가**

`scripts/user_state_notify_proxy.py`에서 `WEBHOOK_NAME = ...` 줄 바로 아래에 추가:

```python
import reminders

EXPECTED_SECRET = os.environ.get("USER_STATE_SECRET", "hermes-claude-hook")
REMINDER_STORE = reminders.ReminderStore()
```

(`import reminders`는 파일 상단 import 블록으로 옮겨도 무방. launchd가 스크립트 풀패스로 실행하므로 같은 디렉터리의 `reminders.py`가 `sys.path[0]`로 잡힌다.)

`forward_to_hermes` 함수 정의 **아래에** 리마인더 전송 콜백 추가:

```python
def forward_reminder_message(message: str) -> bool:
    ok, detail = forward_to_hermes({"message": message})
    log_line(f"reminder_forward ok={ok} detail={detail[:200]}")
    return ok
```

- [ ] **Step 2: device 이벤트 dict에 place 보존**

`event_from_request`의 `if path in DEVICE_EVENTS:` 블록에서 반환 dict에 `place` 한 줄을 추가:

```python
    if path in DEVICE_EVENTS:
        event_type, default_message = DEVICE_EVENTS[path]
        return {
            "type": event_type,
            "source": body.get("source") or query.get("source") or "macos",
            "device": device,
            "place": body.get("place") or query.get("place") or None,
            "message": body.get("message") or query.get("message") or default_message,
            "timestamp": ts,
            "raw_path": path,
        }
```

- [ ] **Step 3: 시크릿 검증 메서드 + 리마인더 라우팅 추가**

`Handler` 클래스 안에 메서드 추가(예: `write_json` 아래):

```python
    def check_secret(self) -> bool:
        return self.headers.get("X-Webhook-Secret") == EXPECTED_SECRET
```

`handle_request` 메서드에서, `if path == "/health":` 블록 **바로 아래에** 리마인더 라우팅을 삽입(기존 `body = parse_body(self)` 줄 위):

```python
        if path == "/remind" and self.command == "POST":
            if not self.check_secret():
                self.write_json(401, {"ok": False, "error": "unauthorized"})
                return
            rbody = parse_body(self)
            try:
                rem = REMINDER_STORE.add(
                    text=rbody.get("text", ""),
                    place=rbody.get("place"),
                    device=rbody.get("device"),
                )
            except ValueError as exc:
                self.write_json(400, {"ok": False, "error": str(exc)})
                return
            log_line(f"remind_add id={rem['id']} place={rem.get('place')} device={rem.get('device')}")
            self.write_json(200, {"ok": True, "id": rem["id"], "reminder": rem})
            return

        if path == "/reminders" and self.command == "GET":
            self.write_json(200, {"ok": True, "reminders": REMINDER_STORE.list(query.get("status"))})
            return

        _parts = path.strip("/").split("/")
        if len(_parts) == 3 and _parts[0] == "reminders" and _parts[2] == "done" and self.command == "POST":
            if not self.check_secret():
                self.write_json(401, {"ok": False, "error": "unauthorized"})
                return
            rem = REMINDER_STORE.mark_done(_parts[1])
            if rem is None:
                self.write_json(404, {"ok": False, "error": "reminder not found", "id": _parts[1]})
                return
            self.write_json(200, {"ok": True, "id": rem["id"], "status": rem["status"]})
            return
```

- [ ] **Step 4: 디바이스 이벤트 후 리마인더 발화 연동**

`handle_request`의 마지막 부분, `state = update_state(event)` 와 `self.write_json(200, ...)` 사이에서 device 이벤트 발화를 추가. 기존:

```python
        state = update_state(event)
        ok, detail = forward_to_hermes(event)
        log_line(f"event={event.get('type')} path={path} webhook_ok={ok} detail={detail[:300]}")
        self.write_json(200, {"ok": True, "event": event, "webhook_ok": ok, "webhook_detail": detail, "state_updated_at": state.get("updated_at")})
```

를 다음으로 교체:

```python
        state = update_state(event)
        ok, detail = forward_to_hermes(event)
        log_line(f"event={event.get('type')} path={path} webhook_ok={ok} detail={detail[:300]}")

        if (event.get("type") or "").startswith("device."):
            try:
                fired = REMINDER_STORE.on_device_event(event, forward_reminder_message)
                if fired:
                    log_line(f"reminders_fired count={len(fired)} ids={[r['id'] for r in fired]}")
            except Exception as exc:  # reminders are additive; never break the event response
                log_line(f"reminder_error={exc}")

        self.write_json(200, {"ok": True, "event": event, "webhook_ok": ok, "webhook_detail": detail, "state_updated_at": state.get("updated_at")})
```

- [ ] **Step 5: 기존 테스트가 여전히 통과하는지 확인(회귀)**

Run: `cd /Users/kijeonglee/Projects/user-state-notify && python3 -m unittest tests.test_reminders -v`
Expected: PASS — 모듈 변경 없음, 전체 통과.

- [ ] **Step 6: 프록시 import 정상 확인**

Run: `cd /Users/kijeonglee/Projects/user-state-notify/scripts && python3 -c "import user_state_notify_proxy; print('import ok')"`
Expected: `import ok` (구문/임포트 오류 없음).

- [ ] **Step 7: 로컬 기동 후 엔드포인트 수동 검증**

별도 포트(8646)로 프록시를 띄우고 curl로 확인한다. `hermes` 명령이 없는 개발 환경에서는 webhook 전송은 실패하지만(리마인더 등록/조회/완료는 hermes 불필요), 엔드포인트 동작은 검증된다.

```bash
cd /Users/kijeonglee/Projects/user-state-notify/scripts
python3 user_state_notify_proxy.py --port 8646 &
PROXY_PID=$!
sleep 1

# 1) 등록 (시크릿 필요)
curl -fsS -X POST http://127.0.0.1:8646/remind \
  -H 'Content-Type: application/json' \
  -H 'X-Webhook-Secret: hermes-claude-hook' \
  -d '{"text":"보고서 작성@회사맥"}'
echo
# 기대: {"ok": true, "id": "r_...", "reminder": {... "device":"mac-studio-office", "text":"보고서 작성" ...}}

# 2) 시크릿 누락 → 401
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8646/remind \
  -H 'Content-Type: application/json' -d '{"text":"x@회사맥"}'
# 기대: 401

# 3) 조건 0개 → 400
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8646/remind \
  -H 'Content-Type: application/json' -H 'X-Webhook-Secret: hermes-claude-hook' \
  -d '{"text":"그냥 메모"}'
# 기대: 400

# 4) 목록 조회
curl -fsS "http://127.0.0.1:8646/reminders?status=pending"; echo
# 기대: {"ok": true, "reminders": [ ... 위에서 등록한 1건 ... ]}

# 5) 디바이스 이벤트 → 매칭 발화 시도 (로그로 확인)
curl -fsS -X POST http://127.0.0.1:8646/device/login \
  -H 'Content-Type: application/json' -H 'X-Webhook-Secret: hermes-claude-hook' \
  -d '{"device":"mac-studio-office","place":"office","source":"manual"}'; echo
# 기대: 이벤트 응답 200. 로그에 reminder_forward 라인이 남음(hermes 없으면 ok=False).

# 6) 완료 처리 (위 1)에서 받은 id 사용 — <ID>를 실제 값으로 치환)
curl -fsS -X POST "http://127.0.0.1:8646/reminders/<ID>/done" \
  -H 'X-Webhook-Secret: hermes-claude-hook'; echo
# 기대: {"ok": true, "id": "<ID>", "status": "done"}

# 7) 없는 id 완료 → 404
curl -s -o /dev/null -w "%{http_code}\n" -X POST "http://127.0.0.1:8646/reminders/r_nope/done" \
  -H 'X-Webhook-Secret: hermes-claude-hook'
# 기대: 404

kill $PROXY_PID
# 검증용으로 생성된 파일 정리(실제 상태와 분리하려면 확인 후 삭제)
ls -l ~/.hermes/state/reminders.json ~/.hermes/state/reminder_aliases.json
```

Expected: 1)=등록 JSON에 `device=mac-studio-office`/`text=보고서 작성`, 2)=`401`, 3)=`400`, 4)=등록 1건, 5)=200 + 로그에 `reminder_forward`, 6)=`status:done`, 7)=`404`.

> 주의: 이 수동 검증은 실제 `~/.hermes/state/reminders.json`에 데이터를 만든다. 운영 중인 서버라면 검증 후 테스트 리마인더를 `done` 처리하거나 파일을 정리한다.

- [ ] **Step 8: 커밋**

```bash
cd /Users/kijeonglee/Projects/user-state-notify
git add scripts/user_state_notify_proxy.py
git commit -m "$(cat <<'EOF'
feat: wire reminder endpoints and device-event firing into proxy

Add POST /remind, GET /reminders, POST /reminders/{id}/done with
X-Webhook-Secret verification. Preserve place on device events so
place-based reminders match. Fire matching reminders on device events.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: 설치 스크립트 + 문서

**Files:**
- Modify: `install.sh` (`install_server`에 `reminders.py` 내려받기 추가)
- Modify: `README.md`, `docs/operations.md`

**Interfaces:**
- Consumes: Task 1–3의 `scripts/reminders.py`, 새 엔드포인트.
- Produces: 없음(배포/문서).

- [ ] **Step 1: install.sh에 reminders.py fetch 추가**

`install_server()` 안에서 proxy를 내려받는 줄 다음에 `reminders.py`도 내려받도록 수정. 기존:

```bash
  fetch scripts/user_state_notify_proxy.py "$INSTALL_ROOT/user_state_notify_proxy.py"
  fetch scripts/location_proxy.py "$INSTALL_ROOT/location_proxy.py"
  chmod +x "$INSTALL_ROOT/user_state_notify_proxy.py" "$INSTALL_ROOT/location_proxy.py"
```

를 다음으로 교체:

```bash
  fetch scripts/user_state_notify_proxy.py "$INSTALL_ROOT/user_state_notify_proxy.py"
  fetch scripts/reminders.py "$INSTALL_ROOT/reminders.py"
  fetch scripts/location_proxy.py "$INSTALL_ROOT/location_proxy.py"
  chmod +x "$INSTALL_ROOT/user_state_notify_proxy.py" "$INSTALL_ROOT/location_proxy.py"
```

(`reminders.py`는 import 모듈이므로 실행 권한 불필요. 별칭 파일은 첫 `add` 호출 시 자동 생성되므로 install에서 별도 생성하지 않는다.)

- [ ] **Step 2: install.sh 구문 검사**

Run: `cd /Users/kijeonglee/Projects/user-state-notify && bash -n install.sh && echo "syntax ok"`
Expected: `syntax ok`.

- [ ] **Step 3: README에 리마인더 섹션 추가**

`README.md`의 "Mac 이벤트 수신/전송" 목록 다음, 적절한 위치에 섹션을 추가:

````markdown
## 위치/컨텍스트 리마인더

특정 장소·디바이스에서 PC를 활성화하면 묶어 둔 할 일을 알림으로 띄웁니다.

### 등록

```bash
curl -fsS -X POST http://SERVER:8645/remind \
  -H 'Content-Type: application/json' \
  -H 'X-Webhook-Secret: hermes-claude-hook' \
  -d '{"text":"보고서 작성@회사맥"}'
```

- `text`에 `@토큰`을 쓰면 `~/.hermes/state/reminder_aliases.json`의 매핑으로 장소/디바이스를 해석합니다.
- 또는 구조화 필드로 직접 지정: `{"text":"보고서 작성","device":"mac-studio-office"}` 또는 `{"text":"회사일","place":"office"}`.
- `place`/`device` 중 최소 하나가 필요합니다(없으면 400).

### 별칭 커스텀

`~/.hermes/state/reminder_aliases.json` (없으면 첫 등록 시 기본값 자동 생성):

```json
{
  "회사맥":   { "device": "mac-studio-office" },
  "회사맥북": { "device": "macbook", "place": "office" },
  "집맥":     { "device": "mac-mini-home" },
  "회사":     { "place": "office" },
  "집":       { "place": "home" }
}
```

### 조회 / 완료

```bash
curl -fsS "http://SERVER:8645/reminders?status=pending"

curl -fsS -X POST http://SERVER:8645/reminders/r_ab12cd/done \
  -H 'X-Webhook-Secret: hermes-claude-hook'
```

### 동작

- 트리거: `device.login` / `device.wake` / `device.unlock`.
- 세션당 1회 발화 — `login`은 항상 새 세션, `wake`/`unlock`은 마지막 활동 이후 간격이 임계값(기본 60분, `USER_STATE_SESSION_GAP_MIN`)을 넘을 때만 새 세션.
- 매칭은 AND: 지정한 `place`/`device` 조건이 모두 일치해야 발화.
- 완료(`done`) 표시 전까지 세션이 바뀔 때마다 다시 알립니다.
````

- [ ] **Step 4: docs/operations.md에 수동 테스트/문제해결 추가**

`docs/operations.md`의 "수동 이벤트 테스트" 섹션 다음에 추가:

````markdown
## 리마인더 수동 테스트

```bash
# 등록
curl -fsS -X POST http://127.0.0.1:8645/remind \
  -H 'Content-Type: application/json' \
  -H 'X-Webhook-Secret: hermes-claude-hook' \
  -d '{"text":"보고서 작성@회사맥"}'

# 목록
curl -fsS "http://127.0.0.1:8645/reminders?status=pending"

# 완료 (id는 등록 응답의 값)
curl -fsS -X POST http://127.0.0.1:8645/reminders/<ID>/done \
  -H 'X-Webhook-Secret: hermes-claude-hook'
```

저장 파일:

```bash
cat ~/.hermes/state/reminders.json
cat ~/.hermes/state/reminder_aliases.json
```
````

- [ ] **Step 5: 커밋**

```bash
cd /Users/kijeonglee/Projects/user-state-notify
git add install.sh README.md docs/operations.md
git commit -m "$(cat <<'EOF'
docs: install reminders.py on server and document reminder endpoints

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review 결과

- **Spec coverage:** 데이터 모델/저장소(Task 1), 별칭·@토큰(Task 1), 매칭 AND(Task 2 `_matches`), 간격 기반 세션·발화·전송 실패 미기록(Task 2), 엔드포인트·시크릿·place 보존·발화 연동(Task 3), 손상 백업(Task 1 `_load`), 설치·문서(Task 4) — 스펙 각 절에 대응 태스크 존재.
- **Placeholder scan:** 코드/명령/기대 출력 모두 구체값 기재. `<ID>`는 런타임에 생성되는 값이라 치환 안내를 명시(플레이스홀더 아님).
- **Type consistency:** `ReminderStore`의 메서드명(`add`/`list`/`mark_done`/`on_device_event`)과 콜백 시그니처 `forward_fn(message)->bool`, 콜백 구현 `forward_reminder_message`가 Task 2/3에서 일치. 이벤트 타입 문자열 `device.*`이 기존 `DEVICE_EVENTS`와 일치.
