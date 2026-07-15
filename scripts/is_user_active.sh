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
    data = plistlib.loads(sys.stdin.buffer.read())
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
