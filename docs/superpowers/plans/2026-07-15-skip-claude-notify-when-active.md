# 사용 중 Mac의 Claude 알림 스킵 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사용자가 해당 Mac을 실제로 사용 중(잠금 해제 + 최근 3분 이내 입력)일 때 Claude Code 훅의 텔레그램·Hermes 알림을 스킵한다.

**Architecture:** 판정 로직은 이 레포의 단일 목적 셸 스크립트 `scripts/is_user_active.sh`(종료 코드 0=활성)에 두고, `install.sh` client 모드가 `~/.user-state-notify/scripts/`로 배포한다. 레포 밖의 `~/.claude/hooks/notify.sh`는 맨 앞에서 이 헬퍼를 호출해 활성이면 즉시 종료한다. 판정 불가 상황은 전부 비활성 취급(fail-open — 알림 전송).

**Tech Stack:** bash, macOS `ioreg`(IOConsoleLocked, HIDIdleTime), python3 plistlib(잠금 상태 plist 파싱), pytest/unittest(가짜 ioreg를 PATH에 심어 검증).

## Global Constraints

- 스크립트 배포 경로는 `~/.user-state-notify/scripts/` — `~/.hermes/`는 Hermes 재설치 시 초기화되므로 금지 (spec: 배포 절, install.sh:8-11 주석과 동일한 이유).
- 유휴 임계값 기본 **180초**, 환경 변수 `USER_STATE_ACTIVE_IDLE_SEC`로 재정의.
- 종료 코드 계약: `0` = 활성(호출자는 알림 스킵), 그 외 = 비활성/판정 불가(알림 전송). ioreg 실패·키 누락·파싱 오류 전부 비활성.
- 헬퍼는 외부 네트워크 호출 금지(순수 로컬 판정).
- 테스트는 기존 관례(unittest 클래스, `tests/` 아래, pytest로 실행)를 따른다.

---

### Task 1: `is_user_active.sh` 판정 스크립트 + 테스트

**Files:**
- Create: `scripts/is_user_active.sh`
- Test: `tests/test_is_user_active.py`

**Interfaces:**
- Produces: `scripts/is_user_active.sh` — 인자 없이 실행하면 종료 코드로만 판정 결과 전달(0=활성, 1=비활성/판정불가). `--explain` 인자를 주면 `locked=<true|false|unknown> idle_sec=<n|unknown> threshold_sec=<n> verdict=<active|inactive>` 한 줄을 stdout에 출력. 환경 변수 `USER_STATE_ACTIVE_IDLE_SEC`(기본 180)으로 임계값 재정의. Task 2(install.sh)와 Task 3(notify.sh 패치)이 이 경로·계약에 의존한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_is_user_active.py` 생성:

```python
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "is_user_active.sh"

# ioreg 호출을 가로채는 가짜 바이너리. 환경 변수로 시나리오를 제어한다:
#   FAKE_LOCKED=true|false     IOConsoleLocked 값
#   FAKE_IDLE_NS=<nanoseconds> HIDIdleTime 값
#   FAKE_NO_IDLE=1             HIDIdleTime 키 자체를 생략
#   FAKE_IOREG_FAIL=1          ioreg가 비정상 종료
FAKE_IOREG = r"""#!/bin/bash
if [ "${FAKE_IOREG_FAIL:-}" = "1" ]; then exit 1; fi
case "$*" in
  *"-n Root"*)
    cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>IOConsoleLocked</key>
  <${FAKE_LOCKED:-false}/>
</dict>
</plist>
EOF
    ;;
  *"-c IOHIDSystem"*)
    if [ "${FAKE_NO_IDLE:-}" = "1" ]; then
      echo '      "SomethingElse" = 1'
    else
      echo "      \"HIDIdleTime\" = ${FAKE_IDLE_NS:-0}"
    fi
    ;;
esac
"""


class IsUserActiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        fake = self.tmp / "ioreg"
        fake.write_text(FAKE_IOREG, encoding="utf-8")
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)

    def run_script(self, extra_env=None, args=()):
        env = os.environ.copy()
        env["PATH"] = f"{self.tmp}:{env['PATH']}"
        env.update(extra_env or {})
        return subprocess.run(
            [str(SCRIPT), *args], env=env,
            capture_output=True, text=True, timeout=10,
        )

    def test_unlocked_and_recent_input_is_active(self):
        r = self.run_script({"FAKE_LOCKED": "false", "FAKE_IDLE_NS": str(30 * 10**9)})
        self.assertEqual(r.returncode, 0)

    def test_unlocked_but_idle_too_long_is_inactive(self):
        r = self.run_script({"FAKE_LOCKED": "false", "FAKE_IDLE_NS": str(600 * 10**9)})
        self.assertEqual(r.returncode, 1)

    def test_locked_is_inactive_even_with_recent_input(self):
        r = self.run_script({"FAKE_LOCKED": "true", "FAKE_IDLE_NS": str(5 * 10**9)})
        self.assertEqual(r.returncode, 1)

    def test_missing_idle_key_fails_open(self):
        r = self.run_script({"FAKE_LOCKED": "false", "FAKE_NO_IDLE": "1"})
        self.assertEqual(r.returncode, 1)

    def test_ioreg_failure_fails_open(self):
        r = self.run_script({"FAKE_IOREG_FAIL": "1"})
        self.assertEqual(r.returncode, 1)

    def test_threshold_env_override(self):
        r = self.run_script({
            "FAKE_LOCKED": "false",
            "FAKE_IDLE_NS": str(240 * 10**9),
            "USER_STATE_ACTIVE_IDLE_SEC": "300",
        })
        self.assertEqual(r.returncode, 0)

    def test_explain_prints_verdict(self):
        r = self.run_script(
            {"FAKE_LOCKED": "false", "FAKE_IDLE_NS": str(30 * 10**9)},
            args=("--explain",),
        )
        self.assertEqual(r.returncode, 0)
        self.assertIn("verdict=active", r.stdout)
        self.assertIn("locked=false", r.stdout)
        self.assertIn("idle_sec=30", r.stdout)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python3 -m pytest tests/test_is_user_active.py -v`
Expected: 전체 FAIL/ERROR — `scripts/is_user_active.sh`가 없어 `FileNotFoundError` 또는 실행 실패.

- [ ] **Step 3: 스크립트 구현**

`scripts/is_user_active.sh` 생성:

```bash
#!/usr/bin/env bash
# "지금 이 Mac을 사용 중인가"를 판정한다.
#   exit 0  = 활성 (화면 잠금 해제 + 최근 입력) → 호출자는 알림을 스킵
#   exit 1  = 비활성 또는 판정 불가            → 호출자는 알림을 전송 (fail-open)
#
# Usage:
#   is_user_active.sh             # 종료 코드로만 판정
#   is_user_active.sh --explain   # locked/idle/threshold/verdict 한 줄 출력
#
# Config:
#   USER_STATE_ACTIVE_IDLE_SEC    유휴 임계값(초), 기본 180

set -u
PATH="$PATH:/usr/sbin:/usr/bin:/bin"

THRESHOLD="${USER_STATE_ACTIVE_IDLE_SEC:-180}"
EXPLAIN=0
[ "${1:-}" = "--explain" ] && EXPLAIN=1

# 1) 화면 잠금 상태: ioreg Root 노드의 IOConsoleLocked (plist로 파싱)
locked=$(ioreg -n Root -d1 -a 2>/dev/null | python3 -c '
import plistlib, sys
try:
    data = plistlib.load(sys.stdin.buffer)
    print("true" if data.get("IOConsoleLocked") else "false")
except Exception:
    print("unknown")
' 2>/dev/null) || locked="unknown"
[ -n "$locked" ] || locked="unknown"

# 2) 마지막 키보드/마우스 입력 후 경과 초: HIDIdleTime (나노초 → 초)
idle=$(ioreg -c IOHIDSystem 2>/dev/null \
  | awk '/HIDIdleTime/ {print int($NF/1000000000); exit}') || idle=""

verdict="inactive"
rc=1
if [ "$locked" = "false" ] && [ -n "$idle" ] \
   && [ "$idle" -le "$THRESHOLD" ] 2>/dev/null; then
  verdict="active"
  rc=0
fi

if [ "$EXPLAIN" = 1 ]; then
  echo "locked=$locked idle_sec=${idle:-unknown} threshold_sec=$THRESHOLD verdict=$verdict"
fi
exit "$rc"
```

생성 후 실행 권한 부여:

```bash
chmod +x scripts/is_user_active.sh
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python3 -m pytest tests/ -v`
Expected: `test_is_user_active.py` 7건 전부 PASS, 기존 테스트(test_notifiers, test_reminders)도 전부 PASS.

- [ ] **Step 5: 실제 Mac에서 스모크 테스트**

Run: `./scripts/is_user_active.sh --explain; echo "rc=$?"`
Expected (지금 이 세션에서 타이핑 직후): `locked=false idle_sec=<작은 수> threshold_sec=180 verdict=active` 그리고 `rc=0`.

- [ ] **Step 6: 커밋**

```bash
git add scripts/is_user_active.sh tests/test_is_user_active.py
git commit -m "feat: add is_user_active.sh — local console-activity check for notification skipping"
```

---

### Task 2: `install.sh` 배포 추가 + README 문서화

**Files:**
- Modify: `install.sh:112-113` 부근 (install_client 함수 시작부)
- Modify: `README.md:121-134` 구성 파일 목록, 그리고 `## 절전 해제 / 잠금 해제 감지 방식` 섹션(291행) 앞에 새 섹션 추가

**Interfaces:**
- Consumes: Task 1의 `scripts/is_user_active.sh` (레포 경로), 배포 대상 `$INSTALL_ROOT/is_user_active.sh`.
- Produces: 새 Mac에서 `install.sh client` 실행 시 `~/.user-state-notify/scripts/is_user_active.sh`가 실행 가능 상태로 존재. README에 notify.sh 연동 스니펫 문서화(Task 3이 이 스니펫을 실제 적용).

- [ ] **Step 1: install.sh의 install_client에 fetch 추가**

`install.sh` `install_client()` 함수에서, 아래 기존 블록(112-113행)

```bash
  # Login notifier (RunAtLoad, one-shot)
  fetch scripts/notify_login.sh "$INSTALL_ROOT/notify_login.sh"
  chmod +x "$INSTALL_ROOT/notify_login.sh"
```

바로 다음에 이 블록을 추가:

```bash
  # Local activity check (used by Claude Code notify hook to skip
  # notifications while the user is actively using this Mac)
  fetch scripts/is_user_active.sh "$INSTALL_ROOT/is_user_active.sh"
  chmod +x "$INSTALL_ROOT/is_user_active.sh"
```

- [ ] **Step 2: install.sh 문법 검증**

Run: `bash -n install.sh && echo OK`
Expected: `OK`

- [ ] **Step 3: README 구성 파일 목록에 추가**

`README.md`의 구성 파일 목록에서 아래 행

```markdown
- `~/.user-state-notify/scripts/notify_login.sh`
```

바로 다음에 추가:

```markdown
- `~/.user-state-notify/scripts/is_user_active.sh`
```

- [ ] **Step 4: README에 새 섹션 추가**

`## 절전 해제 / 잠금 해제 감지 방식` 섹션 바로 앞에 추가:

```markdown
## 사용 중 Mac의 Claude 알림 스킵

Claude Code 훅 알림(작업 완료/오류/권한 요청)을 받을 때, 그 Mac 앞에 앉아
화면을 직접 보고 있다면 텔레그램 알림은 중복입니다.
`~/.user-state-notify/scripts/is_user_active.sh`가 로컬 신호만으로
"지금 이 Mac을 사용 중인가"를 판정합니다.

- **활성 판정(종료 코드 0)**: 화면 잠금 해제(`IOConsoleLocked=false`)
  **그리고** 최근 입력(`HIDIdleTime` ≤ 임계값, 기본 180초).
- 그 외(잠김, 유휴 초과, ioreg 실패 등)는 전부 비활성(종료 코드 1) —
  중복 알림이 유실보다 낫다는 원칙(fail-open)입니다.
- 임계값은 `USER_STATE_ACTIVE_IDLE_SEC` 환경 변수로 재정의합니다.

진단:

```bash
~/.user-state-notify/scripts/is_user_active.sh --explain
# locked=false idle_sec=2 threshold_sec=180 verdict=active
```

Claude Code 훅 스크립트(예: `~/.claude/hooks/notify.sh`) 맨 앞에 다음을
추가하면, 사용 중일 때 알림 전송을 통째로 건너뜁니다:

```bash
ACTIVE_CHECK="$HOME/.user-state-notify/scripts/is_user_active.sh"
if [ -x "$ACTIVE_CHECK" ] && "$ACTIVE_CHECK" >/dev/null 2>&1; then
  exit 0   # 이 Mac을 사용 중 — 화면에서 직접 보고 있으므로 알림 생략
fi
```

헬퍼가 설치되지 않은 Mac에서는 조건이 성립하지 않아 기존대로 전송됩니다.
```

- [ ] **Step 5: 전체 테스트 재실행**

Run: `python3 -m pytest tests/ -v`
Expected: 전부 PASS (이 Task는 코드 로직 변경 없음 — 회귀 확인용).

- [ ] **Step 6: 커밋**

```bash
git add install.sh README.md
git commit -m "feat: deploy is_user_active.sh via install.sh client and document notify-hook integration"
```

---

### Task 3: 이 Mac에 배포 + notify.sh 패치 + 실동작 검증

이 Task는 레포 밖 파일(`~/.user-state-notify/scripts/`, `~/.claude/hooks/notify.sh`)을 다루므로 git 커밋이 없습니다.

**Files:**
- Create: `~/.user-state-notify/scripts/is_user_active.sh` (레포에서 복사)
- Modify: `~/.claude/hooks/notify.sh` (셔뱅·주석 블록 직후, `if [ -f ~/.hermes/.env ]` 행 앞)

**Interfaces:**
- Consumes: Task 1의 종료 코드 계약(0=활성→스킵), 배포 경로 `~/.user-state-notify/scripts/is_user_active.sh`.
- Produces: 이 Mac(맥스튜디오)에서 사용 중일 때 Stop/StopFailure/Notification 알림이 실제로 스킵되는 상태.

- [ ] **Step 1: 헬퍼를 로컬 설치 경로로 복사**

```bash
cp scripts/is_user_active.sh ~/.user-state-notify/scripts/is_user_active.sh
chmod +x ~/.user-state-notify/scripts/is_user_active.sh
~/.user-state-notify/scripts/is_user_active.sh --explain
```

Expected: `locked=false idle_sec=<작은 수> threshold_sec=180 verdict=active`

- [ ] **Step 2: notify.sh 패치**

`~/.claude/hooks/notify.sh`에서 상단 주석 블록(`# 맥미니/맥스튜디오 둘 다 사용 가능 (Cloudflare Tunnel)` 행)과 `if [ -f ~/.hermes/.env ]; then` 행 사이에 추가:

```bash
# 이 Mac을 사용 중(잠금 해제 + 최근 입력)이면 알림 생략 — user-state-notify 헬퍼
ACTIVE_CHECK="$HOME/.user-state-notify/scripts/is_user_active.sh"
if [ -x "$ACTIVE_CHECK" ] && "$ACTIVE_CHECK" >/dev/null 2>&1; then
  exit 0
fi
```

- [ ] **Step 3: notify.sh 문법 검증 + 스킵 동작 확인**

```bash
bash -n ~/.claude/hooks/notify.sh && echo SYNTAX_OK
echo '{"hook_event_name":"Stop","cwd":"/tmp/test-project"}' | ~/.claude/hooks/notify.sh; echo "rc=$?"
```

Expected: `SYNTAX_OK`, `rc=0`, 그리고 **텔레그램에 "✅ Claude Code 작업 완료 / 프로젝트: test-project" 메시지가 오지 않아야 함** (지금 타이핑 중 = 활성이므로 스킵). 사용자에게 텔레그램 미수신 확인 요청.

- [ ] **Step 4: 비활성 시 전송되는지 확인 (임계값 0으로 강제)**

```bash
echo '{"hook_event_name":"Stop","cwd":"/tmp/test-project"}' \
  | USER_STATE_ACTIVE_IDLE_SEC=0 ~/.claude/hooks/notify.sh; echo "rc=$?"
```

Expected: `rc=0`, 이번에는 **텔레그램에 테스트 메시지 도착** (idle > 0초 → 비활성 취급 → 전송). 사용자에게 수신 확인 요청.

- [ ] **Step 5: 맥미니 적용 안내**

맥미니(서버 Mac)에도 동일 적용이 필요함을 사용자에게 안내:

```bash
# 맥미니에서 실행 (push 이후에만 유효 — install.sh는 GitHub raw에서 받는다):
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/lkjsays/user-state-notify/main/install.sh)" -- client --server-url http://127.0.0.1:8645
# 그리고 맥미니의 ~/.claude/hooks/notify.sh에 Step 2와 같은 패치 적용
```

---

## Self-Review 결과

- **Spec coverage:** 판정 스크립트(Task 1), fail-open 계약(Task 1 테스트 4·5번), `--explain`(Task 1), install.sh 배포(Task 2), README 문서화(Task 2), notify.sh 패치·이 Mac 적용(Task 3), 맥미니 안내(Task 3 Step 5) — 스펙 전 항목 매핑 확인.
- **Placeholder scan:** 코드 블록 전부 완성본, TBD/TODO 없음.
- **Type consistency:** 경로 `~/.user-state-notify/scripts/is_user_active.sh`, 환경 변수 `USER_STATE_ACTIVE_IDLE_SEC`, 종료 코드 계약(0=활성)이 세 Task에서 동일하게 사용됨.
