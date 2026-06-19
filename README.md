# user-state-notify

Mac/iPhone 상태 이벤트를 Hermes webhook으로 보내고, 로컬 상태 파일에 기록하는 작은 macOS용 알림/상태 동기화 프로젝트입니다.

새 Mac을 장만했을 때 이 링크만 열어서 설치할 수 있게 만든 부트스트랩 리포지토리입니다.

## 무엇을 하나요?

- iPhone 단축어 위치 이벤트 수신
  - `/home_arrive`
  - `/home_depart`
  - `/office_arrive`
  - `/office_depart`
- Mac 이벤트 수신/전송
  - `/device/login` — 로그인/부팅 시 (RunAtLoad)
  - `/device/wake` — 절전 해제 시 (KeepAlive 감시)
  - `/device/unlock` — 화면 잠금 해제 시 (KeepAlive 감시)
  - `/mac_login`
- Hermes webhook으로 Telegram 등 연결된 채널에 알림 전송
- 위치/컨텍스트 리마인더 (아래 [위치/컨텍스트 리마인더](#위치컨텍스트-리마인더) 참고)
  - `/remind` — 리마인더 등록
  - `/reminders` — 목록 조회
  - `/reminders/{id}/done` — 완료 처리
- 상태 파일 저장
  - `~/.hermes/state/user_state.json`
  - `~/.hermes/state/reminders.json`
  - `~/.hermes/state/reminder_aliases.json`
- 이벤트 로그 저장
  - `~/.hermes/logs/user_state_events.jsonl`

## 빠른 설치

### 1) 새 Mac에서 로그인 알림만 설치하기

중앙 서버가 이미 있고, 새 Mac에서는 로그인 이벤트만 보내면 되는 경우입니다.

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/lkjsays/user-state-notify/main/install.sh)" -- client --server-url http://YOUR_SERVER_OR_TAILSCALE_IP:8645
```

예시 — Mac Studio에서 Mac Mini(서버, Tailscale IP)로 이벤트 전송:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/lkjsays/user-state-notify/main/install.sh)" -- client --server-url http://100.79.41.62:8645
```

디바이스 이름에 "Studio", "mini", "Book"이 포함되면 자동으로 canonical 이름과 장소(office/home/mobile)를 매핑합니다. 수동으로 지정하려면:

```bash
USER_STATE_PLACE=office USER_STATE_DEVICE_NAME=mac-studio-office \
  ~/.hermes/scripts/notify_login.sh --server-url http://100.79.41.62:8645
```

### 2) 현재 Mac을 중앙 수신 서버로 설치하기

Hermes Agent가 설치되어 있고 webhook delivery를 받을 Mac에서 실행합니다.

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/lkjsays/user-state-notify/main/install.sh)" -- server
```

### 3) 서버 + 클라이언트 둘 다 설치하기

한 Mac에서 수신 서버도 띄우고 로그인 이벤트도 자기 자신에게 보내려면:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/lkjsays/user-state-notify/main/install.sh)" -- all --server-url http://127.0.0.1:8645
```

## 설치 후 확인

```bash
launchctl list | grep -E 'user-state|location-proxy|session-watch'
curl -fsS http://127.0.0.1:8645/health
```

로그:

```bash
# 서버 수신 로그
tail -f ~/.hermes/logs/user_state_notify_proxy.log
tail -f ~/.hermes/logs/user_state_events.jsonl

# 클라이언트 절전 해제/잠금 해제 감시 로그
tail -f ~/.hermes/logs/session_watch.log
tail -f ~/.hermes/logs/session_watch.err.log
```

상태 파일:

```bash
cat ~/.hermes/state/user_state.json
# 절전 해제/잠금 감시 내부 상태
cat ~/.hermes/state/session_watch_heartbeat
cat ~/.hermes/state/session_watch_lock_state
```

## iPhone 단축어 URL

서버 URL이 `http://100.x.y.z:8645`라면:

- 집 도착: `http://100.x.y.z:8645/home_arrive`
- 집 출발: `http://100.x.y.z:8645/home_depart`
- 회사 도착: `http://100.x.y.z:8645/office_arrive`
- 회사 출발: `http://100.x.y.z:8645/office_depart`

POST 방식 권장. GET도 호환됩니다.

## Hermes webhook 준비

서버 모드는 Hermes Agent의 webhook subscription 이름 `user-state-notify`로 전달합니다.

Hermes 환경에 맞춰 webhook이 먼저 설정되어 있어야 합니다. 이미 설정되어 있다면 추가 작업이 필요 없습니다.

필요한 경우 Hermes 설정에서 다음 의도를 가진 webhook을 만들어주세요.

- name: `user-state-notify`
- delivery: direct
- 목적: Telegram 등 기본 채널로 이벤트 메시지 전달

## 구성 파일

설치 후 생성/복사되는 주요 파일:

- `~/.hermes/scripts/user_state_notify_proxy.py`
- `~/.hermes/scripts/reminders.py`
- `~/.hermes/scripts/location_proxy.py`
- `~/.hermes/scripts/notify_login.sh`
- `~/.hermes/scripts/watch_macos_session.sh`
- `~/Library/LaunchAgents/com.kjlee.location-proxy.plist`
- `~/Library/LaunchAgents/com.kjlee.user-state-login-notify.plist`
- `~/Library/LaunchAgents/com.kjlee.user-state-session-watch.plist`

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

> **주의:** `place`가 설정된 별칭(예: `회사맥북` → `place: office`)은 클라이언트가 해당 장소를 실제로 보고할 때만 발화합니다. `notify_login.sh`는 MacBook을 기본적으로 `place=mobile`로 매핑하므로, `@회사맥북`(place=office) 리마인더는 클라이언트를 `--place office`로 설치·실행하지 않으면 MacBook 로그인 시 발화하지 않습니다.

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

## 절전 해제 / 잠금 해제 감지 방식

`watch_macos_session.sh`는 KeepAlive LaunchAgent로 실행되며 5초마다 폴링합니다.

- **절전 해제**: 하트비트 파일의 타임스탬프 갭이 60초를 초과하면 Mac이 잠들었다가 깨어난 것으로 판단 → `/device/wake` 전송
- **잠금 해제**: `ioreg -n Root -d1`에서 `IOConsoleLocked` 키를 읽어 `잠김→해제` 전환 감지 → `/device/unlock` 전송
- **중복 방지**: 같은 이벤트 타입은 60초 이내 재전송하지 않음
- **항상 실행 중**: Mac이 잠들어도 launchd가 깨어날 때 자동으로 재시작

## 제거

```bash
launchctl unload ~/Library/LaunchAgents/com.kjlee.user-state-login-notify.plist 2>/dev/null || true
launchctl unload ~/Library/LaunchAgents/com.kjlee.user-state-session-watch.plist 2>/dev/null || true
launchctl unload ~/Library/LaunchAgents/com.kjlee.location-proxy.plist 2>/dev/null || true
rm -f ~/Library/LaunchAgents/com.kjlee.user-state-login-notify.plist
rm -f ~/Library/LaunchAgents/com.kjlee.user-state-session-watch.plist
rm -f ~/Library/LaunchAgents/com.kjlee.location-proxy.plist
```

스크립트/로그/상태 파일은 안전을 위해 자동 삭제하지 않습니다.

## 인증 시크릿

클라이언트가 프록시로 POST를 보낼 때 `X-Webhook-Secret` 헤더를 사용합니다.

기본값 `hermes-claude-hook`은 스크립트에 내장되어 있으며, 환경 변수나 플래그로 재정의할 수 있습니다:

```bash
# 환경 변수로 지정
export USER_STATE_SECRET=my-secret
~/.hermes/scripts/notify_login.sh --server-url http://...

# 플래그로 지정
~/.hermes/scripts/notify_login.sh --server-url http://... --secret my-secret
```

프록시 서버는 `USER_STATE_SECRET` 환경 변수(기본값 `hermes-claude-hook`)로 기대값을 정합니다. 클라이언트가 보내는 시크릿이 이 값과 일치해야 합니다.

> 참고: 현재 시크릿 검증은 리마인더 쓰기 엔드포인트(`POST /remind`, `POST /reminders/{id}/done`)에만 적용됩니다. 디바이스/위치 이벤트 엔드포인트는 호환성을 위해 검증하지 않습니다.

## 보안 메모

- 이 리포지토리에는 토큰, 개인 IP, Hermes 설정 파일 원본을 넣지 않습니다.
- 서버 URL은 설치 시 `--server-url`로 주입합니다.
- 기본 시크릿(`hermes-claude-hook`)을 변경하려면 `USER_STATE_SECRET` 환경 변수를 설정하세요.
  - TODO: 민감 환경에서는 launchd plist에 `EnvironmentVariables` 키로 주입하거나, 배포 전 기본값을 변경하세요.
