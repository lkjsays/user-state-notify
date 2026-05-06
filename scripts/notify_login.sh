#!/usr/bin/env bash
set -euo pipefail

SERVER_URL="${USER_STATE_SERVER_URL:-}"
EVENT_PATH="${USER_STATE_EVENT_PATH:-/device/login}"
DEVICE_NAME="${USER_STATE_DEVICE_NAME:-$(scutil --get ComputerName 2>/dev/null || hostname)}"

usage() {
  cat <<USAGE
Usage: notify_login.sh --server-url URL [--event-path /device/login] [--device-name NAME]

Environment alternatives:
  USER_STATE_SERVER_URL
  USER_STATE_EVENT_PATH
  USER_STATE_DEVICE_NAME
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --server-url)
      SERVER_URL="$2"; shift 2 ;;
    --event-path)
      EVENT_PATH="$2"; shift 2 ;;
    --device-name)
      DEVICE_NAME="$2"; shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2 ;;
  esac
done

if [[ -z "${SERVER_URL}" ]]; then
  echo "USER_STATE_SERVER_URL or --server-url is required" >&2
  exit 2
fi

SERVER_URL="${SERVER_URL%/}"
URL="${SERVER_URL}${EVENT_PATH}"

payload=$(DEVICE_NAME="$DEVICE_NAME" python3 - <<PY
import json, os, socket
name = os.environ.get("DEVICE_NAME") or socket.gethostname()
print(json.dumps({
  "source": "macos_launchd",
  "device": name,
  "message": f"{name} 로그인 감지",
}, ensure_ascii=False))
PY
)

curl -fsS \
  -X POST \
  -H 'Content-Type: application/json; charset=utf-8' \
  --data "$payload" \
  --max-time 10 \
  "$URL" >/dev/null
