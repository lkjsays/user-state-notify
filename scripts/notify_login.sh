#!/usr/bin/env bash
set -euo pipefail

SERVER_URL="${USER_STATE_SERVER_URL:-}"
EVENT_PATH="${USER_STATE_EVENT_PATH:-/device/login}"
SECRET="${USER_STATE_SECRET:-hermes-claude-hook}"
PLACE="${USER_STATE_PLACE:-}"
_DEVICE_EXPLICIT=0

DEVICE_NAME="$(scutil --get ComputerName 2>/dev/null || hostname)"
if [[ -n "${USER_STATE_DEVICE_NAME:-}" ]]; then
  DEVICE_NAME="${USER_STATE_DEVICE_NAME}"
  _DEVICE_EXPLICIT=1
fi

usage() {
  cat <<USAGE
Usage: notify_login.sh --server-url URL [options]

Options:
  --server-url URL    Required. Proxy URL (e.g. http://100.79.41.62:8645)
  --event-path PATH   Event path. Default: /device/login
  --device-name NAME  Override detected device name (skips auto-mapping)
  --secret SECRET     X-Webhook-Secret value (USER_STATE_SECRET; default: hermes-claude-hook)
  --place PLACE       Location hint: home, office, mobile (USER_STATE_PLACE)

Environment variables:
  USER_STATE_SERVER_URL   USER_STATE_EVENT_PATH   USER_STATE_DEVICE_NAME
  USER_STATE_SECRET       USER_STATE_PLACE
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --server-url)   SERVER_URL="$2";  shift 2 ;;
    --event-path)   EVENT_PATH="$2";  shift 2 ;;
    --device-name)  DEVICE_NAME="$2"; _DEVICE_EXPLICIT=1; shift 2 ;;
    --secret)       SECRET="$2";      shift 2 ;;
    --place)        PLACE="$2";       shift 2 ;;
    -h|--help)      usage; exit 0 ;;
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

# Map known device names to canonical identifiers and infer place.
# Skipped when --device-name is given explicitly.
if [[ "$_DEVICE_EXPLICIT" -eq 0 ]]; then
  case "$DEVICE_NAME" in
    *[Mm]ini*|*mac-mini*)
      DEVICE_NAME="mac-mini-home"
      PLACE="${PLACE:-home}"
      ;;
    *[Ss]tudio*)
      DEVICE_NAME="mac-studio-office"
      PLACE="${PLACE:-office}"
      ;;
    *[Bb]ook*)
      DEVICE_NAME="macbook"
      PLACE="${PLACE:-mobile}"
      ;;
  esac
fi

SERVER_URL="${SERVER_URL%/}"
URL="${SERVER_URL}${EVENT_PATH}"

payload=$(DEVICE_NAME="$DEVICE_NAME" PLACE="$PLACE" python3 - <<PY
import json, os
name = os.environ["DEVICE_NAME"]
place = os.environ.get("PLACE", "")
data = {
    "source": "macos_launchd",
    "device": name,
    "message": f"{name} 로그인 감지",
}
if place:
    data["place"] = place
print(json.dumps(data, ensure_ascii=False))
PY
)

curl -fsS \
  -X POST \
  -H 'Content-Type: application/json; charset=utf-8' \
  -H "X-Webhook-Secret: ${SECRET}" \
  --data "$payload" \
  --max-time 10 \
  "$URL" >/dev/null
