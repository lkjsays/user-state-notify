# 위치/컨텍스트 기반 리마인더 설계

작성일: 2026-06-18

## 목적

이동하여 특정 장소·디바이스에서 PC를 활성화했을 때, 그 컨텍스트에 묶어 둔 할 일을
자동으로 띄워 주는 리마인더 시스템. 예: "보고서 작성@회사맥"을 등록해 두면, 회사에 도착해
해당 Mac을 켰을 때 Telegram으로 알림이 온다.

기존 `user-state-notify` 프록시가 이미 위치 이벤트(iPhone 단축어)와 디바이스 이벤트
(login/wake/unlock)를 수신해 상태를 기록하고 Hermes webhook으로 전달하고 있으므로,
이 흐름 위에 리마인더 발화를 얹는다.

## 핵심 결정 사항

| 항목 | 결정 |
|---|---|
| 알림 전달 | 기존 Hermes webhook(Telegram 등), 단방향 |
| 조건 | 장소(place) 또는 디바이스(device). 둘 다 지정 시 모두 일치(AND) |
| 등록 | HTTP 엔드포인트(핵심). AI agent·curl·단축어가 호출. Telegram/AI 입력은 그 위에 얹힘 |
| 수명 | 완료 표시 전까지 반복 |
| 트리거 이벤트 | login / wake / unlock 모두 |
| 재알림 주기 | **세션당 1회** (login·wake가 새 세션 시작, unlock은 같은 세션) |
| 완료 처리 | HTTP 엔드포인트 |
| 별칭(@토큰) | 사용자 편집 설정 파일로 커스텀 |

## 아키텍처

접근 방식 C — 리마인더 로직을 별도 모듈로 분리하고 프록시가 호출한다.

```
[AI agent / curl / 단축어]
        │ POST /remind, /reminders/{id}/done, GET /reminders
        ▼
user_state_notify_proxy.py  (HTTP/이벤트 계층)
        │  ├─ 디바이스 이벤트(login/wake/unlock) 수신 시 reminders.on_device_event(event) 호출
        │  └─ 리마인더 엔드포인트 라우팅
        ▼
reminders.py  (저장·매칭·세션·수명 — 순수 로직, 단독 테스트)
        │  발화 대상 리마인더 반환
        ▼
forward_to_hermes()  (기존 함수 재사용) → Telegram
```

- 단일 프로세스, 기존 launchd 구성 그대로. 새 외부 의존성 없음(Python 표준 라이브러리).
- `reminders.py`는 HTTP를 모른다 — 입력은 dict, 출력은 dict/list. `python3 -m unittest`로 단독 테스트 가능.
- 리마인더는 부가 기능. 리마인더 로직이 예외를 던져도 기존 이벤트 응답(상태 기록·알림)은 정상 반환한다.

### 컴포넌트 책임

- **reminders.py** — 무엇을 하나: 리마인더 저장·조회·완료, 디바이스 이벤트에 대한 매칭과 세션 기반 발화 판정. 어떻게 쓰나: `add_reminder`, `list_reminders`, `mark_done`, `on_device_event` 함수 호출. 의존: 저장 파일 경로, 별칭 설정, `threading.Lock`. (Hermes 전송은 콜백/반환값으로 위임 — 모듈은 전송하지 않고 "발화 대상"만 돌려준다.)
- **user_state_notify_proxy.py** — 무엇을 하나: HTTP 라우팅, 바디 파싱, 시크릿 검증, 디바이스 이벤트 수신 시 `reminders.on_device_event` 호출 후 반환된 발화 대상을 `forward_to_hermes`로 전송. 어떻게 쓰나: 기존대로 launchd가 기동. 의존: reminders 모듈.

> 주의(기존 코드 수정): 현재 `event_from_request`는 `DEVICE_EVENTS` 분기에서 `place`를
> 반환하지 않는다(클라이언트 스크립트는 `place`를 보내지만 device 이벤트 dict에서 버려진다).
> place 기반 매칭이 동작하려면 device 이벤트 dict에도 `place`(body/query/디바이스 매핑)를
> 포함시켜야 한다 — 이 작은 수정을 구현 범위에 포함한다.

## 데이터 모델

리마인더 1건:

```json
{
  "id": "r_a1b2c3",
  "text": "보고서 작성",
  "place": "office",
  "device": "mac-studio-office",
  "status": "pending",
  "created_at": "2026-06-18T09:00:00+09:00",
  "done_at": null,
  "fired": {
    "mac-studio-office": { "session_id": 5, "at": "2026-06-18T09:10:00+09:00" }
  }
}
```

- `place`, `device`는 각각 선택이며 최소 하나는 있어야 한다.
- `fired`는 디바이스별 마지막 발화 세션을 기록한다.

### 매칭 규칙

리마인더는 디바이스 이벤트에 대해 **지정된 조건이 모두 일치**할 때 매칭된다.

- `device`만 지정 → 이벤트의 device가 같아야 한다.
- `place`만 지정 → 이벤트의 place가 같아야 한다(그 장소의 어떤 디바이스든).
- 둘 다 지정 → 둘 다 일치(AND).

## 저장소

`~/.hermes/state/reminders.json` (기존 state 디렉터리 재사용):

```json
{
  "reminders": [ ... ],
  "sessions": { "mac-studio-office": { "id": 5, "started_at": "..." } }
}
```

- 기존 `save_state`처럼 원자적 쓰기(tmp → replace).
- `ThreadingHTTPServer`이므로 동시 쓰기 가능 → 모듈 내 `threading.Lock`으로 모든 read-modify-write 보호.
- 파싱 실패 시 빈 구조로 시작하고 손상 파일은 `.corrupt`로 백업한다.

## 별칭 설정 (@토큰)

`~/.hermes/state/reminder_aliases.json` — 사용자가 직접 편집:

```json
{
  "회사맥":   { "device": "mac-studio-office" },
  "회사맥북": { "device": "macbook", "place": "office" },
  "집맥":     { "device": "mac-mini-home" },
  "회사":     { "place": "office" },
  "집":       { "place": "home" }
}
```

- `POST /remind`의 `text`에서 `@회사맥` 같은 토큰을 만나면 이 맵으로 해석해 `device`/`place`를 채운다. 해석된 토큰은 텍스트에서 제거한다.
- 한 토큰이 `device`+`place`를 동시에 줄 수 있다(예: `회사맥북`).
- 구조화 필드(`place`/`device`)를 직접 명시하면 토큰 해석보다 우선한다.
- 파일이 없으면 위 예시를 기본값으로 자동 생성한다(install 시 또는 첫 실행 시). 이후 사용자가 자유롭게 추가/변경.
- 알 수 없는 토큰은 무시하고 로그만 남긴다.

## 엔드포인트

| 메서드 · 경로 | 동작 | 바디/응답 |
|---|---|---|
| `POST /remind` | 리마인더 등록 | `{text, place?, device?}` → `{ok, id}` |
| `GET /reminders` | 목록 조회 | `?status=pending`(기본 전체) → `{reminders:[...]}` |
| `POST /reminders/{id}/done` | 완료 처리 | → `{ok, id, status:"done"}` |

- 상태를 바꾸는 엔드포인트(`/remind`, `/reminders/{id}/done`)는 `X-Webhook-Secret` 검증을 추가한다.
- `{id}` 경로 파싱: `urlparse` 후 path를 `/`로 split.

## 발화/세션 로직

`reminders.on_device_event(event)`가 디바이스 이벤트마다 호출된다:

1. `event.type`이 `device.login` 또는 `device.wake` → 해당 디바이스 **세션 id를 +1**(새 세션 시작). `device.unlock` → 세션 id 유지(같은 세션).
2. 현재 세션 id를 확보한다.
3. `status == "pending"` 이면서 이벤트의 device/place에 매칭되는 리마인더를 순회:
   - `reminder.fired[device].session_id == 현재 세션 id` → 건너뜀(이번 세션 이미 발화).
   - 아니면 발화 목록에 추가하고 `fired[device] = {session_id, at}` 기록.
4. 발화 목록이 있으면 한 건의 묶음 메시지로 `forward_to_hermes` 전송.

결과적으로:

- 자리에 와서 부팅(login) 또는 절전 해제(wake) → 새 세션 → 대기 중 리마인더 발화.
- 같은 세션 중 잠금해제(unlock) 반복 → 재발화 안 함.
- 세션 도중 새로 등록한 리마인더는 이번 세션 발화 기록이 없으므로 다음 이벤트(unlock 포함)에서 1회 발화 후 같은 세션은 침묵.

### Telegram 묶음 메시지 예시

```
📌 mac-studio-office (office) — 할 일 2건
1. 보고서 작성  [r_a1b2c3]
2. 책상 정리    [r_d4e5f6]
완료: POST /reminders/<id>/done
```

## 에러 처리

- **검증**: `text` 없거나 `place`/`device`/유효한 `@토큰` 중 아무 조건도 없으면 `400`. 조건이 하나라도 있으면 등록 진행.
- **완료**: 존재하지 않는 `id`면 `404`. 이미 `done`이면 `200`(멱등).
- **저장소 손상**: 파싱 실패 시 빈 구조로 시작, 손상 파일은 `.corrupt`로 백업.
- **Hermes 전송 실패**: 발화 시 전송이 실패하면 `fired` 기록을 남기지 않는다(다음 이벤트에 재시도). 로그에 경고. → 알림 유실보다 중복이 낫다.
- **동시성**: 모듈 `threading.Lock`으로 모든 read-modify-write 보호.
- 디바이스 이벤트 처리 중 리마인더 로직 예외 → 기존 이벤트 응답은 정상 반환, 예외는 로그.

## 테스트

`tests/test_reminders.py` — 표준 라이브러리 `unittest`, `python3 -m unittest`로 실행. `reminders.py`를 임시 디렉터리에 붙여 순수 로직을 검증:

1. 등록 → `list_reminders`에 pending으로 보임
2. `@토큰` 파싱: `회사맥` → `device=mac-studio-office`
3. 조건 0개 등록 거부
4. login 이벤트 → 매칭 리마인더 발화, `fired` 기록
5. 같은 세션 unlock → 재발화 안 함
6. wake(새 세션) → 재발화
7. 세션 도중 등록 → 다음 이벤트에서 1회 발화
8. place 매칭 / device 매칭 / 둘 다(AND)
9. 완료 처리 → 이후 발화 안 함, 멱등성
10. Hermes 전송 실패 시 `fired` 미기록(재시도 보장)

프록시 HTTP 계층은 기존에 테스트가 없으므로 핵심 로직에 테스트를 집중하고, 엔드포인트는 수동 `curl` 확인으로 둔다.

## 설치/배포

- `install.sh`: 서버 설치 시 `reminder_aliases.json` 기본값 생성. launchd 변경 없음(기존 프록시가 새 엔드포인트를 자동 포함).
- `README.md` / `docs/operations.md`에 엔드포인트·토큰·완료 방법 문서화.

## 범위 밖 (YAGNI)

- Telegram 답장으로 완료 처리(Hermes inbound 메시지 연동 필요) — 추후 HTTP 엔드포인트 위에 얹을 수 있음.
- 시간 기반 리마인더, 반복 일정, 우선순위/태그.
- 별도 리마인더 서비스/launchd 분리(접근 방식 B).
