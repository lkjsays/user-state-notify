# 사용 중 Mac의 Claude 알림 스킵 — 설계

날짜: 2026-07-15
상태: 승인됨

## 문제

Claude Code 훅(`~/.claude/hooks/notify.sh`)은 Stop/StopFailure/Notification 이벤트를
무조건 텔레그램 + Hermes 웹훅으로 전송한다. 사용자가 해당 Mac 앞에 앉아
화면을 직접 보고 있을 때도 같은 알림이 텔레그램으로 날아와 중복이 된다.

user-state-notify는 디바이스 활동 상태를 이미 추적하지만, notify.sh는 이를
참조하지 않는다. 그리고 "이 Mac을 지금 사용 중인가"는 서버 조회 없이
로컬 ioreg 신호만으로 판정할 수 있다.

## 결정 사항 (사용자 확정)

- 판정 기준: **잠금 해제 상태 + 최근 N분 이내 키보드/마우스 입력** (로컬 판정)
- 스킵 범위: **텔레그램 + Hermes 웹훅 둘 다**
- 대상 이벤트: **Stop / StopFailure / Notification 셋 다**
- 구현 위치: **이 레포에 헬퍼 스크립트 추가**, notify.sh는 헬퍼 호출만

## 구성 요소

### 신규: `scripts/is_user_active.sh`

"지금 이 Mac을 사용 중인가"를 판정하는 단일 목적 스크립트.
`install.sh` client 모드가 `~/.user-state-notify/scripts/is_user_active.sh`로 배포한다.

판정 로직 — 둘 다 만족해야 활성:

1. `ioreg -n Root -d1 -a`의 `IOConsoleLocked`가 `false` (화면 잠금 해제)
2. `ioreg -c IOHIDSystem`의 `HIDIdleTime`(나노초)을 초로 환산한 값이
   임계값 이하 (최근 입력 있음)

설정:

- 임계값 기본 **180초**, 환경 변수 `USER_STATE_ACTIVE_IDLE_SEC`로 재정의.

종료 코드 계약:

- `0` = 활성 → 호출자는 알림을 스킵한다
- 그 외 = 비활성 또는 판정 불가 → 호출자는 알림을 전송한다
- ioreg 실패, 키 누락, 파싱 오류 등 모든 예외는 비활성 취급(**fail-open**).
  중복 알림이 알림 유실보다 낫다.

진단:

- `--explain` 플래그: locked 여부, idle 초, 임계값, 판정 결과를 stdout에 출력.

### 변경: `~/.claude/hooks/notify.sh` (레포 밖)

스크립트 맨 앞(stdin 읽기 전)에 추가:

```bash
ACTIVE_CHECK="$HOME/.user-state-notify/scripts/is_user_active.sh"
if [ -x "$ACTIVE_CHECK" ] && "$ACTIVE_CHECK" >/dev/null 2>&1; then
  exit 0   # 이 Mac을 사용 중 — 화면에서 직접 보고 있으므로 알림 생략
fi
```

- 헬퍼가 없는 Mac에서는 조건이 성립하지 않아 기존 동작 그대로 전송.
- 세 이벤트 모두 이 스크립트 하나를 거치므로 자동으로 전부 적용.
- 이 스니펫은 README에 문서화해 새 Mac 셋업 시 참조한다.

### 변경: `install.sh`

client 섹션에 `fetch scripts/is_user_active.sh "$INSTALL_ROOT/is_user_active.sh"`
및 실행 권한 부여 추가.

### 변경: `README.md`

"사용 중 Mac의 Claude 알림 스킵" 섹션 추가 — 동작 원리, notify.sh 스니펫,
임계값 환경 변수, `--explain` 진단법.

## 데이터 흐름

```
Claude Code 훅 이벤트 (Stop/StopFailure/Notification)
  → notify.sh
      → is_user_active.sh
          exit 0 (잠금 해제 + idle ≤ 180s) → 알림 전체 생략, 종료
          그 외                             → 기존 경로: 텔레그램 + Hermes 웹훅
```

크로스 디바이스 시나리오는 자연 해결: 각 Mac이 자기 콘솔 상태만 보므로,
집맥에서 돌던 Claude의 알림은 회사맥 사용 중에도 정상 도착한다.

## 오류 처리

- ioreg 부재/실패, plist 파싱 실패, HIDIdleTime 키 누락 → 비활성 취급, 알림 전송.
- notify.sh 쪽은 `-x` 검사로 헬퍼 부재 시 무조건 전송.
- 헬퍼는 절대 notify.sh를 블로킹하지 않도록 외부 네트워크 호출 없음(순수 로컬).

## 테스트

- `tests/test_is_user_active.py` (기존 pytest 관례):
  PATH에 가짜 `ioreg`를 심어 시나리오별 종료 코드 검증 —
  잠금 상태 / 잠금 해제+idle 짧음 / 잠금 해제+idle 김 /
  HIDIdleTime 키 누락 / ioreg 실패 / 임계값 env 재정의.
- 수동 검증: 이 Mac에서 `--explain` 출력 확인, 실제 Stop 훅 스킵 확인.

## 배포

- 이 Mac(맥스튜디오): 헬퍼 로컬 설치 + notify.sh 패치 즉시 적용.
- 맥미니(서버): `install.sh` client 재실행 + notify.sh 동일 패치 필요 — 작업
  마무리 시 안내.

## 범위 밖 (YAGNI)

- 서버 user_state 기반 크로스 디바이스 판정
- 프록시 경유 Claude 이벤트 라우팅
- 이벤트 타입별 개별 스킵 정책
