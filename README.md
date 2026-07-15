# user-state-notify

Mac/iPhone 상태 이벤트를 설정한 알림 채널(텔레그램 직접 연동·범용 웹훅·Hermes 등)로 보내고, 로컬 상태 파일에 기록하는 작은 macOS용 알림/상태 동기화 프로젝트입니다.

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
- 설정한 알림 채널(텔레그램 직접 연동·범용 웹훅·Hermes)로 이벤트 알림 전송 (아래 [알림 채널 설정](#알림-채널-설정) 참고)
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
  ~/.user-state-notify/scripts/notify_login.sh --server-url http://100.79.41.62:8645
```

### 2) 현재 Mac을 중앙 수신 서버로 설치하기

이벤트를 수신해 설정한 알림 채널로 전달할 Mac에서 실행합니다. (Hermes는 `hermes` notifier를 쓸 때만 필요하며, 텔레그램 직접 연동·웹훅만 쓰면 Hermes 없이 동작합니다.)

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

## Hermes webhook 준비 (`hermes` notifier 사용 시에만)

알림 채널은 [알림 채널 설정](#알림-채널-설정)의 `config.json`으로 정합니다. 텔레그램 직접 연동(`telegram`)이나 범용 웹훅(`webhook`)만 쓰면 이 절은 건너뛰어도 됩니다.

`hermes` notifier를 활성화한 경우에만, 서버는 Hermes Agent의 webhook subscription 이름(기본 `user-state-notify`, config의 `webhook_name`)으로 전달합니다. 이때 Hermes 환경에 webhook이 먼저 설정되어 있어야 합니다(이미 있다면 추가 작업 불필요).

필요하면 Hermes 설정에서 다음 의도를 가진 webhook을 만들어주세요.

- name: `user-state-notify`
- delivery: direct
- 목적: Telegram 등 기본 채널로 이벤트 메시지 전달

## 구성 파일

설치 후 생성/복사되는 주요 파일:

- `~/.user-state-notify/scripts/user_state_notify_proxy.py`
- `~/.user-state-notify/scripts/reminders.py`
- `~/.user-state-notify/scripts/location_proxy.py`
- `~/.user-state-notify/scripts/notify_login.sh`
- `~/.user-state-notify/scripts/is_user_active.sh`
- `~/.user-state-notify/scripts/watch_macos_session.sh`
- `~/Library/LaunchAgents/com.kjlee.location-proxy.plist`
- `~/Library/LaunchAgents/com.kjlee.user-state-login-notify.plist`
- `~/Library/LaunchAgents/com.kjlee.user-state-session-watch.plist`

> 스크립트는 `~/.hermes/`가 아닌 `~/.user-state-notify/scripts/`에 둡니다. Hermes를 재설치하면 `~/.hermes/`가 초기화되어 스크립트가 삭제되기 때문입니다. 로그/state는 `~/.hermes/` 아래 유지되며, 삭제되어도 스크립트가 자동으로 재생성합니다.

## 알림 채널 설정

이벤트 수신 시 어느 채널로 알림을 보낼지 `~/.user-state-notify/config.json`으로 지정합니다. 설치 시 샘플이 자동 배치되며, 기존 파일이 있으면 덮어쓰지 않습니다.

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

### 내장 채널 종류

| type | 필수 필드 | 설명 |
|------|-----------|------|
| `telegram` | `bot_token`, `chat_id` | Telegram Bot API로 직접 메시지 전송 |
| `webhook` | `url` | 지정 URL에 JSON POST. `headers`로 인증 헤더 추가 가능 |
| `hermes` | `webhook_name` | 로컬 Hermes Agent webhook subscription으로 전달 |

### 동작 방식

- `enabled: true`인 항목 전체에 **팬아웃** — 여러 채널을 동시에 설정할 수 있습니다.
- 하나 이상의 채널이 성공하면 HTTP 200 응답, `notified: true`.
- 활성화된 채널이 없거나 전부 실패하면 HTTP 502 응답 또는 `notified: false`.
- config.json이 없거나 `notifiers` 목록이 비어 있으면 이벤트는 로그에 기록되지만 알림은 전송되지 않으며 응답에 `notified: false`가 포함됩니다.

### 새 채널 추가

1. `~/.user-state-notify/scripts/notifiers.py`에 클래스를 구현합니다.

   ```python
   class MyNotifier:
       type = "mytype"

       def __init__(self, conf: dict, *, http_post=_http_post, runner=subprocess.run):
           # conf는 config.json notifiers 배열의 해당 항목
           # 필수 필드가 없으면 ValueError를 raise하세요 (build_notifiers가 errors에 기록하고 건너뜁니다)
           self.target = conf["my_param"]

       def send(self, message: str, event: dict) -> tuple[bool, str]:
           # 성공 시 (True, detail), 실패 시 (False, detail) 반환
           ...
   ```

2. 같은 파일 하단의 `REGISTRY`에 등록합니다.

   ```python
   REGISTRY["mytype"] = MyNotifier
   ```

3. `~/.user-state-notify/config.json`의 `notifiers` 배열에 항목을 추가합니다.

   ```json
   { "type": "mytype", "enabled": true, "my_param": "value" }
   ```

4. 프록시를 재시작하면 즉시 적용됩니다(`launchctl unload/load com.kjlee.location-proxy.plist`).

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

### Hermes 스킬 (Telegram으로 등록)

Telegram으로 Hermes에게 말하면 위 `/remind` 엔드포인트를 대신 호출하도록, Hermes 스킬을 제공합니다 (`hermes/SKILL.md`).

#### 어디에 설치하나

**Telegram 메시지를 받아 처리하는 Hermes(게이트웨이)가 도는 Mac**에 설치합니다 — 보통 항상 켜져 있는 서버 Mac(프록시와 같은 곳).

> 이 스킬은 클라이언트 Mac이 아니라 게이트웨이 Mac에 있어야 합니다. 게이트웨이 위치는 그 Mac에서 `hermes gateway status`로 확인할 수 있습니다(`running`이면 거기가 맞습니다).

#### 설치

게이트웨이 Mac에서:

```bash
hermes skills install \
  https://raw.githubusercontent.com/lkjsays/user-state-notify/main/hermes/SKILL.md \
  --category personal --name location-reminders -y
```

- 게이트웨이 Mac이 **프록시와 같은 곳**이면 base URL 기본값 `http://127.0.0.1:8645`가 그대로 동작합니다 — 추가 설정 불필요.
- **다른 Mac**이면 Hermes 환경에 `USER_STATE_SERVER_URL`을 서버 주소로 설정하세요. 시크릿이 기본값과 다르면 `USER_STATE_SECRET`도.

#### 확인

```bash
hermes skills list | grep location-reminders   # enabled 로 표시되면 OK
```

#### 동작 테스트

Telegram으로 Hermes에게 보냅니다:

- "회사 가면 보고서 쓰라고 알려줘" → Hermes가 `{"text":"보고서 작성","place":"office"}`로 등록
- "@회사맥 책상 정리 기억해" → `{"text":"책상 정리","device":"mac-studio-office"}`로 등록

그 뒤 해당 장소/디바이스에서 Mac을 켜면(login/wake/unlock) 알림이 옵니다. 완료하면 "그거 완료" 같은 말로 Hermes가 `/reminders/{id}/done`을 호출합니다.

#### 참고: `apple-reminders`와 구분

Hermes 기본 스킬 `apple-reminders`(시간/날짜 기반, iPhone 동기화)와 이 스킬(장소/디바이스 컨텍스트 기반)이 "리마인더"라는 말에 둘 다 반응할 수 있습니다. 스킬 설명에 "시간 기반은 apple-reminders, 장소/디바이스 기반은 이쪽"이라고 구분을 넣어두었습니다. Hermes가 헷갈리면 "회사 가면"/"~ 켜면"처럼 컨텍스트를 명확히 말하면 됩니다.

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
- `USER_STATE_ACTIVE_IDLE_SEC=-1`로 실행하면 idle 초가 항상 임계값을 넘겨
  무조건 "비활성" 판정이 되므로, 전송 경로를 강제로 테스트하고 싶을 때 씁니다
  (임계값 `0`은 idle이 0초로 절사되면 여전히 활성 판정이라 강제 수단이 아닙니다).

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
~/.user-state-notify/scripts/notify_login.sh --server-url http://...

# 플래그로 지정
~/.user-state-notify/scripts/notify_login.sh --server-url http://... --secret my-secret
```

프록시 서버는 `USER_STATE_SECRET` 환경 변수(기본값 `hermes-claude-hook`)로 기대값을 정합니다. 클라이언트가 보내는 시크릿이 이 값과 일치해야 합니다.

> 참고: 현재 시크릿 검증은 리마인더 쓰기 엔드포인트(`POST /remind`, `POST /reminders/{id}/done`)에만 적용됩니다. 디바이스/위치 이벤트 엔드포인트는 호환성을 위해 검증하지 않습니다.

## 보안 메모

- 이 리포지토리에는 토큰, 개인 IP, Hermes 설정 파일 원본을 넣지 않습니다.
- 서버 URL은 설치 시 `--server-url`로 주입합니다.
- 기본 시크릿(`hermes-claude-hook`)을 변경하려면 `USER_STATE_SECRET` 환경 변수를 설정하세요.
  - TODO: 민감 환경에서는 launchd plist에 `EnvironmentVariables` 키로 주입하거나, 배포 전 기본값을 변경하세요.
