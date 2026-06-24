# Pluggable Notifiers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hermes 의존을 제거하고, 알림 전송을 설정 파일로 구동되는 fan-out notifier 플러그인 구조로 교체한다.

**Architecture:** 새 순수 로직 모듈 `scripts/notifiers.py`가 notifier 클래스(telegram/webhook/hermes)와 디스패처를 제공한다. 각 notifier는 `send(message, event) -> (ok, detail)` 하나를 구현하고, HTTP 호출부(`_http_post`)와 subprocess 실행부(`runner`)는 주입 가능해 네트워크 없이 테스트한다. 프록시는 `forward_to_hermes()`를 제거하고 `notifiers.notify(...)`만 호출한다.

**Tech Stack:** Python 3 표준 라이브러리만 (`urllib.request`, `subprocess`, `json`, `unittest`). 외부 패키지 0.

## Global Constraints

- 외부 의존성 0 — Python 표준 라이브러리만 사용 (`urllib.request`로 HTTP, 새 pip 패키지 금지).
- 설정 파일 경로: `~/.user-state-notify/config.json` (스크립트 설치 위치와 같은 루트, `~/.hermes/` 밖).
- 무중단/레거시 폴백 없음 — config 없으면 알림만 건너뛰고 프록시는 계속 동작.
- 테스트는 `unittest`(기존 `tests/test_reminders.py` 패턴), 의존성은 주입으로 교체해 네트워크 미사용.
- 응답 규칙: enabled notifier 0개 → 200 + `notified:false`; 하나라도 성공 → 200; 전부 실패 → 502.

## File Structure

- **Create `scripts/notifiers.py`** — config 로더, `_http_post`, notifier 3종, `build_notifiers`, `notify` 디스패처. 단일 책임: "메시지를 설정된 채널들로 보낸다".
- **Create `tests/test_notifiers.py`** — 위 모듈 단위 테스트.
- **Create `config.json.example`** — 설정 샘플(레포 루트).
- **Modify `scripts/user_state_notify_proxy.py`** — `forward_to_hermes`/`forward_reminder_message` 교체, 모듈 로드시 notifier 구성, 응답 상태 규칙 반영, 미사용 `subprocess`/`WEBHOOK_NAME` 정리.
- **Modify `install.sh`** — `config.json.example`를 설치 루트와 `~/.user-state-notify/`에 배치(기존 config는 덮어쓰지 않음).
- **Modify `README.md`** — notifier 설정·채널 추가 방법 문서화.

---

### Task 1: 설정 로더와 HTTP 헬퍼

**Files:**
- Create: `scripts/notifiers.py`
- Test: `tests/test_notifiers.py`

**Interfaces:**
- Produces:
  - `DEFAULT_CONFIG_PATH: Path` = `~/.user-state-notify/config.json`
  - `load_config(path=DEFAULT_CONFIG_PATH) -> tuple[dict | None, str | None]` — 성공시 `(config_dict, None)`, 파일 없음/파싱 실패시 `(None, error_message)`.
  - `_http_post(url: str, data: bytes, headers: dict, timeout: int = 10) -> tuple[bool, str]` — 2xx면 `(True, detail)`, 아니면 `(False, detail)`. 예외도 `(False, str)`.

- [ ] **Step 1: Write the failing test**

`tests/test_notifiers.py`:
```python
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import notifiers  # noqa: E402


class LoadConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_valid_config(self):
        p = self.tmp / "config.json"
        p.write_text(json.dumps({"notifiers": [{"type": "telegram"}]}), encoding="utf-8")
        config, err = notifiers.load_config(p)
        self.assertIsNone(err)
        self.assertEqual(config["notifiers"][0]["type"], "telegram")

    def test_missing_file(self):
        config, err = notifiers.load_config(self.tmp / "nope.json")
        self.assertIsNone(config)
        self.assertIn("not found", err)

    def test_broken_json(self):
        p = self.tmp / "config.json"
        p.write_text("{ not json", encoding="utf-8")
        config, err = notifiers.load_config(p)
        self.assertIsNone(config)
        self.assertIn("invalid", err.lower())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_notifiers -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'notifiers'`

- [ ] **Step 3: Write minimal implementation**

`scripts/notifiers.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_notifiers -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/notifiers.py tests/test_notifiers.py
git commit -m "feat: add notifier config loader and http helper"
```

---

### Task 2: TelegramNotifier

**Files:**
- Modify: `scripts/notifiers.py`
- Test: `tests/test_notifiers.py`

**Interfaces:**
- Consumes: `_http_post` (Task 1).
- Produces: `TelegramNotifier(conf: dict, *, http_post=_http_post, runner=subprocess.run)` with attribute `type = "telegram"` and method `send(message: str, event: dict) -> tuple[bool, str]`. Raises `ValueError` if `bot_token` or `chat_id` missing.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_notifiers.py`:
```python
class FakeHTTP:
    def __init__(self, result=(True, "200 ok")):
        self.result = result
        self.calls = []

    def __call__(self, url, data, headers, timeout=10):
        self.calls.append({"url": url, "data": data, "headers": headers})
        return self.result


class TelegramTests(unittest.TestCase):
    def test_send_posts_to_bot_api(self):
        http = FakeHTTP()
        n = notifiers.TelegramNotifier(
            {"bot_token": "TK", "chat_id": "42"}, http_post=http
        )
        ok, detail = n.send("안녕", {"type": "device.login"})
        self.assertTrue(ok)
        self.assertEqual(n.type, "telegram")
        self.assertIn("/botTK/sendMessage", http.calls[0]["url"])
        payload = json.loads(http.calls[0]["data"].decode("utf-8"))
        self.assertEqual(payload["chat_id"], "42")
        self.assertEqual(payload["text"], "안녕")

    def test_missing_field_raises(self):
        with self.assertRaises(ValueError):
            notifiers.TelegramNotifier({"bot_token": "TK"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_notifiers.TelegramTests -v`
Expected: FAIL — `AttributeError: module 'notifiers' has no attribute 'TelegramNotifier'`

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/notifiers.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_notifiers -v`
Expected: PASS (all Task 1 + Task 2 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/notifiers.py tests/test_notifiers.py
git commit -m "feat: add TelegramNotifier"
```

---

### Task 3: WebhookNotifier

**Files:**
- Modify: `scripts/notifiers.py`
- Test: `tests/test_notifiers.py`

**Interfaces:**
- Consumes: `_http_post` (Task 1).
- Produces: `WebhookNotifier(conf: dict, *, http_post=_http_post, runner=subprocess.run)` with `type = "webhook"` and `send(message, event) -> (ok, detail)`. Raises `ValueError` if `url` missing. Posts JSON `{"message", "text", "event"}` with optional `conf["headers"]` merged.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_notifiers.py`:
```python
class WebhookTests(unittest.TestCase):
    def test_send_posts_json_with_headers(self):
        http = FakeHTTP()
        n = notifiers.WebhookNotifier(
            {"url": "https://h.example/hook", "headers": {"Authorization": "Bearer X"}},
            http_post=http,
        )
        ok, _ = n.send("메모", {"type": "device.wake"})
        self.assertTrue(ok)
        self.assertEqual(n.type, "webhook")
        call = http.calls[0]
        self.assertEqual(call["url"], "https://h.example/hook")
        self.assertEqual(call["headers"]["Authorization"], "Bearer X")
        self.assertEqual(call["headers"]["Content-Type"], "application/json; charset=utf-8")
        body = json.loads(call["data"].decode("utf-8"))
        self.assertEqual(body["message"], "메모")
        self.assertEqual(body["text"], "메모")
        self.assertEqual(body["event"]["type"], "device.wake")

    def test_missing_url_raises(self):
        with self.assertRaises(ValueError):
            notifiers.WebhookNotifier({})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_notifiers.WebhookTests -v`
Expected: FAIL — `AttributeError: ... no attribute 'WebhookNotifier'`

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/notifiers.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_notifiers -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/notifiers.py tests/test_notifiers.py
git commit -m "feat: add WebhookNotifier"
```

---

### Task 4: HermesNotifier

**Files:**
- Modify: `scripts/notifiers.py`
- Test: `tests/test_notifiers.py`

**Interfaces:**
- Produces: `HermesNotifier(conf: dict, *, http_post=_http_post, runner=subprocess.run)` with `type = "hermes"` and `send(message, event) -> (ok, detail)`. Uses injected `runner` (default `subprocess.run`); tries `hermes webhook trigger` then `send`. `webhook_name` defaults to `"user-state-notify"`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_notifiers.py`:
```python
class FakeProc:
    def __init__(self, returncode=0, stdout="ok", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class HermesTests(unittest.TestCase):
    def test_send_invokes_hermes_trigger(self):
        calls = []

        def runner(cmd, **kwargs):
            calls.append(cmd)
            return FakeProc(returncode=0, stdout="delivered")

        n = notifiers.HermesNotifier({"webhook_name": "wh"}, runner=runner)
        ok, detail = n.send("hi", {"type": "device.login"})
        self.assertTrue(ok)
        self.assertEqual(n.type, "hermes")
        self.assertEqual(calls[0][:4], ["hermes", "webhook", "trigger", "wh"])

    def test_send_falls_back_to_send_subcommand(self):
        seq = [FakeProc(returncode=1, stderr="no trigger"), FakeProc(returncode=0, stdout="sent")]

        def runner(cmd, **kwargs):
            return seq.pop(0)

        n = notifiers.HermesNotifier({}, runner=runner)  # default webhook_name
        ok, _ = n.send("hi", {})
        self.assertTrue(ok)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_notifiers.HermesTests -v`
Expected: FAIL — `AttributeError: ... no attribute 'HermesNotifier'`

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/notifiers.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_notifiers -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/notifiers.py tests/test_notifiers.py
git commit -m "feat: add HermesNotifier wrapping existing webhook CLI"
```

---

### Task 5: build_notifiers + notify 디스패처 (fan-out)

**Files:**
- Modify: `scripts/notifiers.py`
- Test: `tests/test_notifiers.py`

**Interfaces:**
- Consumes: `TelegramNotifier`, `WebhookNotifier`, `HermesNotifier` (Tasks 2-4).
- Produces:
  - `REGISTRY: dict[str, type]` = `{"telegram": ..., "webhook": ..., "hermes": ...}`
  - `build_notifiers(config: dict, *, http_post=_http_post, runner=subprocess.run) -> tuple[list, list[str]]` — `(notifiers, errors)`. `enabled` 누락시 기본 True. 알 수 없는 type/구성 오류는 건너뛰고 `errors`에 사유 기록.
  - `notify(message: str, event: dict, notifiers: list) -> tuple[bool, list[dict]]` — 각 notifier를 try/except로 격리 호출, `(any_ok, [{"type","ok","detail"}, ...])` 반환.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_notifiers.py`:
```python
class BuildNotifiersTests(unittest.TestCase):
    def test_builds_enabled_only_and_records_errors(self):
        http = FakeHTTP()
        config = {"notifiers": [
            {"type": "telegram", "enabled": True, "bot_token": "T", "chat_id": "1"},
            {"type": "webhook", "enabled": False, "url": "https://x"},
            {"type": "telegram", "enabled": True, "bot_token": "T"},   # missing chat_id
            {"type": "mystery", "enabled": True},                       # unknown type
        ]}
        ns, errors = notifiers.build_notifiers(config, http_post=http)
        self.assertEqual([n.type for n in ns], ["telegram"])
        self.assertEqual(len(errors), 2)

    def test_enabled_defaults_true(self):
        config = {"notifiers": [{"type": "webhook", "url": "https://x"}]}
        ns, errors = notifiers.build_notifiers(config)
        self.assertEqual(len(ns), 1)
        self.assertEqual(errors, [])


class NotifyTests(unittest.TestCase):
    def test_fanout_partial_failure_is_any_ok(self):
        ok_http = FakeHTTP((True, "200"))
        bad_http = FakeHTTP((False, "boom"))
        ns = [
            notifiers.TelegramNotifier({"bot_token": "T", "chat_id": "1"}, http_post=ok_http),
            notifiers.WebhookNotifier({"url": "https://x"}, http_post=bad_http),
        ]
        any_ok, results = notifiers.notify("m", {"type": "device.wake"}, ns)
        self.assertTrue(any_ok)
        self.assertEqual([r["ok"] for r in results], [True, False])

    def test_all_fail(self):
        bad = FakeHTTP((False, "boom"))
        ns = [notifiers.WebhookNotifier({"url": "https://x"}, http_post=bad)]
        any_ok, results = notifiers.notify("m", {}, ns)
        self.assertFalse(any_ok)

    def test_empty_notifiers(self):
        any_ok, results = notifiers.notify("m", {}, [])
        self.assertFalse(any_ok)
        self.assertEqual(results, [])

    def test_exception_in_one_does_not_block_others(self):
        class Boom:
            type = "boom"
            def send(self, message, event):
                raise RuntimeError("kaboom")
        ok_http = FakeHTTP((True, "200"))
        ns = [Boom(), notifiers.TelegramNotifier({"bot_token": "T", "chat_id": "1"}, http_post=ok_http)]
        any_ok, results = notifiers.notify("m", {}, ns)
        self.assertTrue(any_ok)
        self.assertFalse(results[0]["ok"])
        self.assertIn("kaboom", results[0]["detail"])
        self.assertTrue(results[1]["ok"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_notifiers.BuildNotifiersTests tests.test_notifiers.NotifyTests -v`
Expected: FAIL — `AttributeError: ... no attribute 'build_notifiers'`

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/notifiers.py`:
```python
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


def notify(message: str, event: dict, notifiers: list) -> tuple[bool, list[dict]]:
    results: list[dict] = []
    any_ok = False
    for n in notifiers:
        try:
            ok, detail = n.send(message, event)
        except Exception as exc:
            ok, detail = False, f"exception: {exc}"
        results.append({"type": getattr(n, "type", "?"), "ok": bool(ok), "detail": detail})
        any_ok = any_ok or bool(ok)
    return any_ok, results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_notifiers -v`
Expected: PASS (all notifier tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/notifiers.py tests/test_notifiers.py
git commit -m "feat: add build_notifiers and fan-out notify dispatcher"
```

---

### Task 6: 프록시 연동 (forward_to_hermes 제거)

**Files:**
- Modify: `scripts/user_state_notify_proxy.py`

**Interfaces:**
- Consumes: `notifiers.load_config`, `notifiers.build_notifiers`, `notifiers.notify` (Tasks 1-5).
- Produces: 프록시는 더 이상 `forward_to_hermes`/`WEBHOOK_NAME`/`subprocess`를 갖지 않는다. 이벤트 응답에 `notified: bool`, `notify_results: list` 필드 포함, 상태 코드는 Global Constraints 규칙을 따른다.

- [ ] **Step 1: 모듈 로드시 notifier 구성 추가**

[`scripts/user_state_notify_proxy.py:28-34`](../../../scripts/user_state_notify_proxy.py#L28) 부근. `WEBHOOK_NAME` 라인을 제거하고 `import reminders` 옆에 `import notifiers`를 추가, notifier 구성을 모듈 레벨에 둔다:

```python
DEFAULT_PORT = int(os.environ.get("USER_STATE_PORT", "8645"))

import reminders
import notifiers

EXPECTED_SECRET = os.environ.get("USER_STATE_SECRET", "hermes-claude-hook")
REMINDER_STORE = reminders.ReminderStore()

NOTIFY_CONFIG, NOTIFY_CONFIG_ERR = notifiers.load_config()
if NOTIFY_CONFIG is None:
    NOTIFIERS, NOTIFY_BUILD_ERRS = [], [NOTIFY_CONFIG_ERR]
else:
    NOTIFIERS, NOTIFY_BUILD_ERRS = notifiers.build_notifiers(NOTIFY_CONFIG)
```

Also remove `import subprocess` from the top import block (line 13) — it is no longer used.

- [ ] **Step 2: forward 함수 교체**

Replace the whole `forward_to_hermes(...)` function ([lines 170-195](../../../scripts/user_state_notify_proxy.py#L170)) and `forward_reminder_message(...)` ([lines 198-201](../../../scripts/user_state_notify_proxy.py#L198)) with:

```python
def forward_event(event: dict) -> tuple[bool, list[dict]]:
    message = event.get("message") or event.get("type") or "user-state event"
    return notifiers.notify(message, event, NOTIFIERS)


def forward_reminder_message(message: str) -> bool:
    any_ok, results = notifiers.notify(message, {"message": message}, NOTIFIERS)
    log_line(f"reminder_forward ok={any_ok} results={results}")
    return any_ok
```

- [ ] **Step 3: 핸들러 이벤트 응답 교체**

Replace [lines 276-288](../../../scripts/user_state_notify_proxy.py#L276) (from `state = update_state(event)` to the final `self.write_json(...)`) with:

```python
        state = update_state(event)
        any_ok, results = forward_event(event)
        log_line(f"event={event.get('type')} path={path} notify_results={results}")

        if (event.get("type") or "").startswith("device."):
            try:
                fired = REMINDER_STORE.on_device_event(event, forward_reminder_message)
                if fired:
                    log_line(f"reminders_fired count={len(fired)} ids={[r['id'] for r in fired]}")
            except Exception as exc:  # reminders are additive; never break the event response
                log_line(f"reminder_error={exc}")

        if not NOTIFIERS:
            status, notified = 200, False
        elif any_ok:
            status, notified = 200, True
        else:
            status, notified = 502, False
        self.write_json(status, {
            "ok": True, "event": event,
            "notified": notified, "notify_results": results,
            "state_updated_at": state.get("updated_at"),
        })
```

- [ ] **Step 4: 시작 로그에 notifier 상태 반영**

In `main()` replace [line 299](../../../scripts/user_state_notify_proxy.py#L299):

```python
    log_line(f"starting host={args.host} port={args.port} "
             f"notifiers={[n.type for n in NOTIFIERS]} config_errors={NOTIFY_BUILD_ERRS}")
```

- [ ] **Step 5: 회귀 + import 검증**

Run: `python3 -m unittest tests.test_reminders tests.test_notifiers -v`
Expected: PASS (모든 테스트)

Run (config 없는 환경에서 import/구문 검증):
```bash
python3 -c "import sys; sys.path.insert(0,'scripts'); import user_state_notify_proxy as p; print('notifiers=', [n.type for n in p.NOTIFIERS], 'err=', p.NOTIFY_BUILD_ERRS)"
```
Expected: 깨끗하게 import 됨. config.json이 없으면 `notifiers= [] err= ['config not found: ...']` 출력(에러 없이).

- [ ] **Step 6: Commit**

```bash
git add scripts/user_state_notify_proxy.py
git commit -m "feat: route events through pluggable notifiers, drop forward_to_hermes"
```

---

### Task 7: 설정 샘플 + install.sh + README

**Files:**
- Create: `config.json.example`
- Modify: `install.sh`, `README.md`

**Interfaces:**
- Consumes: `INSTALL_ROOT` (`install.sh`, 이미 `~/.user-state-notify/scripts`).

- [ ] **Step 1: 설정 샘플 작성**

`config.json.example`:
```json
{
  "notifiers": [
    { "type": "telegram", "enabled": true,
      "bot_token": "PUT-BOT-TOKEN-HERE", "chat_id": "PUT-CHAT-ID-HERE" },
    { "type": "webhook", "enabled": false,
      "url": "https://example.com/hook", "headers": {} },
    { "type": "hermes", "enabled": false,
      "webhook_name": "user-state-notify" }
  ]
}
```

- [ ] **Step 2a: 서버 설치가 notifiers.py를 가져오도록 수정**

`install_server()`는 현재 `user_state_notify_proxy.py`, `reminders.py`, `location_proxy.py`만 fetch한다([install.sh:66-71](../../../install.sh#L66)). 프록시가 `import notifiers` 하므로 `reminders.py` fetch 줄 바로 다음에 추가한다:

```bash
  fetch scripts/notifiers.py "$INSTALL_ROOT/notifiers.py"
```

(client 설치는 셸 스크립트만 쓰므로 notifiers.py 불필요 — 수정하지 않는다.)

- [ ] **Step 2b: install.sh가 샘플을 배치하도록 수정**

`install.sh`의 `fetch()` 정의 다음에 헬퍼를 추가하고, `server`/`client` 양쪽에서 호출한다. `~/.user-state-notify/config.json`이 **없을 때만** 샘플을 같은 디렉토리에 `config.json`으로 복사하고 안내를 출력한다(기존 config 보존):

```bash
install_config_sample() {
  local cfg_dir="$HOME/.user-state-notify"
  mkdir -p "$cfg_dir"
  fetch config.json.example "$cfg_dir/config.json.example"
  if [[ ! -f "$cfg_dir/config.json" ]]; then
    cp "$cfg_dir/config.json.example" "$cfg_dir/config.json"
    chmod 600 "$cfg_dir/config.json"
    echo "Created $cfg_dir/config.json from sample — edit it with your bot token / webhook URL."
  else
    echo "Kept existing $cfg_dir/config.json"
  fi
}
```

Call `install_config_sample` at the end of both `install_server()` and `install_client()` (just before their closing `}`), so every install path lays down the sample.

- [ ] **Step 3: README에 notifier 설정 문서 추가**

Add a section after "구성 파일" describing `~/.user-state-notify/config.json`, the three built-in types and their fields, fan-out behavior, the 200/502/`notified:false` response rule, and how to add a new channel (implement a class with `type` + `send()` in `scripts/notifiers.py`, register in `REGISTRY`, add a config entry). Keep it concise and in Korean to match the file.

- [ ] **Step 4: 전체 검증**

Run: `python3 -m unittest discover -s tests -v`
Expected: PASS (test_reminders + test_notifiers).

Manual end-to-end (실제 토큰을 넣은 config.json로):
```bash
# telegram 단독 config로 프록시 기동 후
curl -fsS -X POST -H 'Content-Type: application/json' \
  -H 'X-Webhook-Secret: hermes-claude-hook' \
  --data '{"device":"mac-studio-office","place":"office","message":"notifier 테스트"}' \
  http://127.0.0.1:8645/device/login
```
Expected: 텔레그램에 "notifier 테스트" 수신, 응답 `{"ok":true,"notified":true,...}`.

- [ ] **Step 5: Commit**

```bash
git add config.json.example install.sh README.md
git commit -m "feat: ship config sample, install hook, and notifier docs"
```

---

## Verification (전체)

1. **단위 테스트**: `python3 -m unittest discover -s tests -v` → `test_reminders` + `test_notifiers` 전부 PASS.
2. **프록시 import**: config 없는 상태에서도 깨끗이 import, `NOTIFIERS=[]` + config_not_found 에러 기록(Task 6 Step 5).
3. **telegram 단독**: 실제 토큰 config로 기동 → `POST /device/login` → 텔레그램 수신, 응답 `notified:true`.
4. **fan-out 부분 실패**: telegram + 깨진 webhook config → 텔레그램 도착, 로그에 webhook 실패, HTTP 200.
5. **미설정**: config.json 제거 후 기동 → 프록시 생존, 이벤트는 기록, 응답 `notified:false`, 로그에 config_not_found.

## 운영 전환 (구현 후, 별도)

- 집맥(server)·회사맥 모두 `~/.user-state-notify/config.json`을 실제 값으로 작성.
- LaunchAgent 재기동(`launchctl unload/load`)으로 새 프록시·notifier 적용.
