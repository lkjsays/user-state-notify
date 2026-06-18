# 운영 메모

## 서버 Mac에서 하는 일

1. Hermes Agent 설치/로그인
2. `user-state-notify` webhook 설정
3. 설치 실행

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/lkjsays/user-state-notify/main/install.sh)" -- server
```

## 새 Mac에서 하는 일

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/lkjsays/user-state-notify/main/install.sh)" -- client --server-url http://서버주소:8645
```

## iPhone 단축어

POST 요청 URL만 서버 주소로 맞추면 됩니다.

- `/home_arrive`
- `/home_depart`
- `/office_arrive`
- `/office_depart`

## 트러블슈팅

```bash
launchctl list | grep -E 'user-state|location-proxy|session-watch'
curl -v http://127.0.0.1:8645/health
tail -n 100 ~/.hermes/logs/user_state_notify_proxy.launchd.err.log
tail -n 100 ~/.hermes/logs/user_state_notify_proxy.log

# 절전 해제/잠금 해제 감시 로그
tail -n 100 ~/.hermes/logs/session_watch.log
tail -n 100 ~/.hermes/logs/session_watch.err.log
```

## 수동 이벤트 테스트

```bash
curl -fsS -X POST http://127.0.0.1:8645/device/login \
  -H 'Content-Type: application/json' \
  -H 'X-Webhook-Secret: hermes-claude-hook' \
  -d '{"device":"test-mac","source":"manual"}'

curl -fsS -X POST http://127.0.0.1:8645/device/wake \
  -H 'Content-Type: application/json' \
  -H 'X-Webhook-Secret: hermes-claude-hook' \
  -d '{"device":"test-mac","source":"manual","message":"test-mac 절전 해제"}'

curl -fsS -X POST http://127.0.0.1:8645/device/unlock \
  -H 'Content-Type: application/json' \
  -H 'X-Webhook-Secret: hermes-claude-hook' \
  -d '{"device":"test-mac","source":"manual","message":"test-mac 화면 잠금 해제"}'
```

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

## 세션 감시 상태 확인

```bash
# 현재 화면 잠금 상태 (1=잠김, 0=해제, -1=알수없음)
cat ~/.hermes/state/session_watch_lock_state

# 마지막 하트비트 (epoch seconds)
cat ~/.hermes/state/session_watch_heartbeat

# 마지막 이벤트 전송 시각
cat ~/.hermes/state/session_watch_last_wake
cat ~/.hermes/state/session_watch_last_unlock
```

## 세션 감시 재시작

```bash
launchctl unload ~/Library/LaunchAgents/com.kjlee.user-state-session-watch.plist
launchctl load ~/Library/LaunchAgents/com.kjlee.user-state-session-watch.plist
```
