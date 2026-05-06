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
launchctl list | grep -E 'user-state|location-proxy'
curl -v http://127.0.0.1:8645/health
tail -n 100 ~/.hermes/logs/user_state_notify_proxy.launchd.err.log
tail -n 100 ~/.hermes/logs/user_state_notify_proxy.log
```

## 수동 이벤트 테스트

```bash
curl -fsS -X POST http://127.0.0.1:8645/device/login \
  -H 'Content-Type: application/json' \
  -d '{"device":"test-mac","source":"manual"}'
```
