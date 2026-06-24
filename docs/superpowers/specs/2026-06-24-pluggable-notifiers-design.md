# Pluggable Notifiers — Hermes 의존 제거 설계

## Context

현재 `user-state-notify`는 이벤트(로그인/wake/unlock/위치)와 리마인더 발화를
[`scripts/user_state_notify_proxy.py`](../../../scripts/user_state_notify_proxy.py)의
`forward_to_hermes()` 함수 하나를 통해 Hermes로 전달하고, Hermes가 텔레그램으로 라우팅한다.

이 단일 함수가 시스템의 유일한 Hermes 의존이다. 나머지(HTTP 서버, 상태 저장, 리마인더 엔진,
LaunchAgent)는 전부 자체 보유하므로 시스템은 이미 거의 독립적이다. 그러나 Hermes에 묶여 있어:

- **안정성**: Hermes 재설치/장애가 알림 전체를 멈춘다 (2026-06-19 실제 발생).
- **이식성**: Hermes 없는 환경(리눅스 VPS, 라즈베리파이 등)에서 운영 불가.
- **확장성**: 텔레그램 외 채널이나 다른 에이전트로 보내려면 Hermes를 거쳐야 한다.

**목표**: 알림 전송을 플러그인화한다. Hermes를 "여러 notifier 중 하나"로 격하하고,
`send()` 구현 + 설정 한 줄만 추가하면 임의의 채널/에이전트로 확장 가능한 구조를 만든다.
외부 의존성 0(Python 표준 라이브러리만)과 단일 프로세스 구조는 그대로 유지한다.

## 비목표 (Non-goals)

- 무중단/점진 이행. **한 번에 정확히 전환**한다 (집맥·회사맥 모두 새 config.json을 설정).
  레거시 Hermes 폴백 로직은 두지 않는다.
- 새 프로세스/데몬 추가, 외부 패키지 도입, 메시지 큐 등. 범위 밖.

## 아키텍처

### 새 모듈: `scripts/notifiers.py`

순수 로직 모듈(HTTP 서버와 분리, `reminders.py`와 동일한 결 — 단독 테스트 가능).

**Notifier 인터페이스** — 각 notifier는 설정 dict로 생성되고 다음 하나를 구현:

```
send(message: str, event: dict) -> tuple[bool, str]   # (ok, detail)
```

**내장 구현 3종** (열린 집합 — 이후 `send()` 클래스 추가로 무한 확장):

| type | 동작 | 필드 |
|------|------|------|
| `telegram` | Bot API(`sendMessage`)로 직접 전송. `urllib`. | `bot_token`, `chat_id` |
| `webhook` | 임의 URL로 JSON POST. `urllib`. | `url`, `headers`(선택) |
| `hermes` | 기존 `hermes webhook trigger/send` subprocess 호출을 흡수. | `webhook_name` |

**디스패처** `notify(message, event) -> tuple[bool, dict]`:

- config에서 `enabled`인 notifier 목록을 읽어 각각 인스턴스화.
- 순회하며 `send()` 호출. 각 notifier는 개별 try/except + 개별 타임아웃으로 격리 —
  한 notifier의 예외/타임아웃이 다른 notifier 전송을 막지 않는다.
- 결과를 채널별로 집계해 반환.

**HTTP 호출부 격리**: `telegram`·`webhook`은 얇은 `_http_post(url, data, headers, timeout)`
함수를 통해 전송한다. 테스트에서 이 함수를 주입/교체해 네트워크 없이 검증한다.

### 프록시 변경: `scripts/user_state_notify_proxy.py`

- `forward_to_hermes()` 삭제 → `notifiers.notify()` 호출로 교체.
- `forward_reminder_message()`도 `notifiers.notify()` 사용.
- 프록시는 notifier 종류를 전혀 알지 못한다. 채널 추가는 `notifiers.py` + config.json에서만 이뤄진다.

## 설정

### `~/.user-state-notify/config.json` (권한 600)

Hermes 영역(`~/.hermes/`) 밖에 위치 → Hermes 재설치에도 보존. 비밀값(토큰)도 이 파일에서 관리.

```json
{
  "notifiers": [
    { "type": "telegram", "enabled": true,
      "bot_token": "123456:ABC...", "chat_id": "987654321" },
    { "type": "webhook", "enabled": true,
      "url": "https://hooks.example.com/abc",
      "headers": { "Authorization": "Bearer ..." } },
    { "type": "hermes", "enabled": false,
      "webhook_name": "user-state-notify" }
  ]
}
```

- `type` 으로 notifier 클래스 결정, 나머지 필드는 타입 전용.
- `enabled: false` 로 삭제 없이 비활성화.
- config가 **없거나 파싱 실패** → 프록시는 로그에 명확한 에러를 남기고 **알림만 건너뜀**.
  이벤트의 로컬 기록·리마인더 저장은 계속 동작한다(프록시는 죽지 않음).

### 설치 연동

- `install.sh`: `~/.user-state-notify/config.json`이 없으면 주석 포함 샘플(`config.json.example`
  또는 템플릿)을 같은 위치에 배치하고 안내 메시지 출력. 기존 config는 덮어쓰지 않는다.
- 토큰/URL 같은 실제 값은 사용자가 직접 채운다(설치 시 자동 주입하지 않음).

## 에러 의미 (fan-out)

- enabled notifier 전부에 전송 시도 → 채널별 `(ok, detail)` 집계.
- HTTP 응답:
  - 하나라도 성공 → **200**
  - 전부 실패 → **502**
  - 설정된(enabled) notifier 0개 → **200** + 응답 본문에 `"notified": false`
- 로그: `notify type=telegram ok=true / type=webhook ok=false detail=...` 식으로 채널별 결과 기록.

## 테스트: `tests/test_notifiers.py`

기존 `tests/test_reminders.py` 패턴(주입 가능한 의존 + 표준 라이브러리 unittest):

- **설정 파싱**: 정상 / 타입별 필수 필드 누락 / 깨진 JSON / 파일 없음.
- **fan-out 집계**: 전부 성공 / 일부 실패 / 전부 실패 / 0개 notifier.
- **격리**: 한 notifier가 예외·타임아웃이어도 다른 notifier는 정상 전송됨.
- **페이로드 형식**: telegram `sendMessage` 파라미터, webhook JSON 본문/헤더.
- HTTP는 `_http_post`를 mock으로 교체해 검증(네트워크 미사용).

## 영향 범위 / 변경 파일

- 신규: `scripts/notifiers.py`, `tests/test_notifiers.py`, `config.json` 샘플(템플릿).
- 수정: `scripts/user_state_notify_proxy.py`(forward 경로 교체), `install.sh`(config 샘플 배치),
  `README.md`(notifier 설정·채널 추가 방법 문서화).
- 운영: 집맥(server)·회사맥 모두 `~/.user-state-notify/config.json`을 새로 작성하여 일괄 전환.

## 검증 (구현 후)

1. `python3 -m unittest tests.test_notifiers tests.test_reminders` 통과.
2. telegram notifier 단독 config로 프록시 기동 → 수동 `POST /device/login` → 텔레그램 수신 확인.
3. telegram + webhook fan-out config → 한쪽 URL을 일부러 깨뜨려 → 텔레그램은 도착, 로그에
   webhook 실패 기록, HTTP 200 확인.
4. config.json 제거 후 기동 → 프록시는 살아있고, 이벤트는 기록되며, 로그에 "notifier 미설정" 경고 확인.
