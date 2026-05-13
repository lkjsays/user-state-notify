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
  - `/device/login`
  - `/device/unlock`
  - `/device/wake`
  - `/mac_login`
- Hermes webhook으로 Telegram 등 연결된 채널에 알림 전송
- 상태 파일 저장
  - `~/.hermes/state/user_state.json`
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
launchctl list | grep -E 'user-state|location-proxy'
curl -fsS http://127.0.0.1:8645/health
```

로그:

```bash
tail -f ~/.hermes/logs/user_state_notify_proxy.log
tail -f ~/.hermes/logs/user_state_events.jsonl
```

상태 파일:

```bash
cat ~/.hermes/state/user_state.json
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
- `~/.hermes/scripts/location_proxy.py`
- `~/.hermes/scripts/notify_login.sh`
- `~/Library/LaunchAgents/com.kjlee.location-proxy.plist`
- `~/Library/LaunchAgents/com.kjlee.user-state-login-notify.plist`

## 제거

```bash
launchctl unload ~/Library/LaunchAgents/com.kjlee.user-state-login-notify.plist 2>/dev/null || true
launchctl unload ~/Library/LaunchAgents/com.kjlee.location-proxy.plist 2>/dev/null || true
rm -f ~/Library/LaunchAgents/com.kjlee.user-state-login-notify.plist
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

프록시 서버의 `CLIENT_SECRET`과 일치해야 합니다.

## 보안 메모

- 이 리포지토리에는 토큰, 개인 IP, Hermes 설정 파일 원본을 넣지 않습니다.
- 서버 URL은 설치 시 `--server-url`로 주입합니다.
- 기본 시크릿(`hermes-claude-hook`)을 변경하려면 `USER_STATE_SECRET` 환경 변수를 설정하세요.
  - TODO: 민감 환경에서는 launchd plist에 `EnvironmentVariables` 키로 주입하거나, 배포 전 기본값을 변경하세요.
