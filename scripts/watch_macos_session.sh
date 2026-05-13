#!/usr/bin/env bash
# Long-lived macOS session event watcher (wake from sleep, screen unlock).
# Runs as a KeepAlive LaunchAgent; posts events to the user-state proxy.
set -uo pipefail

SERVER_URL="${USER_STATE_SERVER_URL:-}"
SECRET="${USER_STATE_SECRET:-hermes-claude-hook}"
PLACE="${USER_STATE_PLACE:-}"
DEVICE_NAME="$(scutil --get ComputerName 2>/dev/null || hostname)"
_DEVICE_EXPLICIT=0

POLL_INTERVAL=5
DEDUP_WINDOW=60
# Gap in seconds between heartbeats that indicates the Mac was asleep.
# Must be > (ThrottleInterval + POLL_INTERVAL) to avoid false positives on script restart.
WAKE_GAP=60

STATE_DIR="$HOME/.hermes/state"
LOG_FILE="$HOME/.hermes/logs/session_watch.log"
HEARTBEAT_FILE="$STATE_DIR/session_watch_heartbeat"
LOCK_STATE_FILE="$STATE_DIR/session_watch_lock_state"

usage() {
  cat <<USAGE
Usage: watch_macos_session.sh --server-url URL [options]

Options:
  --server-url URL    Required. Proxy URL (e.g. http://100.79.41.62:8645)
  --device-name NAME  Override detected device name (skips auto-mapping)
  --secret SECRET     X-Webhook-Secret value (USER_STATE_SECRET; default: hermes-claude-hook)
  --place PLACE       Location hint: home, office, mobile (USER_STATE_PLACE)

Environment variables:
  USER_STATE_SERVER_URL  USER_STATE_SECRET  USER_STATE_PLACE  USER_STATE_DEVICE_NAME
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --server-url)   SERVER_URL="$2";  shift 2 ;;
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

# Device/place mapping — mirrors notify_login.sh.
if [[ "$_DEVICE_EXPLICIT" -eq 0 ]]; then
  if [[ -n "${USER_STATE_DEVICE_NAME:-}" ]]; then
    DEVICE_NAME="${USER_STATE_DEVICE_NAME}"
    _DEVICE_EXPLICIT=1
  else
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
fi

SERVER_URL="${SERVER_URL%/}"

mkdir -p "$STATE_DIR" "$HOME/.hermes/logs"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
}

# Check current screen lock state via ioreg.
# Prints: 1=locked, 0=unlocked, -1=unknown
check_lock_state() {
  python3 - <<'PY' 2>/dev/null
import subprocess, sys

def find_key(obj, key):
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = find_key(v, key)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for item in obj:
            r = find_key(item, key)
            if r is not None:
                return r
    return None

# Primary: ioreg Root node — contains IOConsoleLocked and CGSSessionScreenIsLocked
try:
    import plistlib
    r = subprocess.run(
        ['ioreg', '-n', 'Root', '-d', '1', '-a'],
        capture_output=True, timeout=5
    )
    if r.returncode == 0 and r.stdout.strip():
        data = plistlib.loads(r.stdout)
        # IOConsoleLocked is the simplest top-level key
        locked = find_key(data, 'IOConsoleLocked')
        if locked is None:
            locked = find_key(data, 'CGSSessionScreenIsLocked')
        if locked is not None:
            print(1 if locked else 0)
            sys.exit(0)
except Exception:
    pass

# Fallback: ScreenSaverEngine running is a proxy for screensaver/lock
try:
    r2 = subprocess.run(
        ['pgrep', '-x', 'ScreenSaverEngine'],
        capture_output=True, timeout=3
    )
    print(1 if r2.returncode == 0 else 0)
    sys.exit(0)
except Exception:
    pass

print(-1)
PY
}

# Build JSON payload and POST to /device/<event_type>.
# Always returns 0 so loop stays alive on network errors.
send_event() {
  local event_type="$1"
  local dedup_file="${STATE_DIR}/session_watch_last_${event_type}"
  local now
  now=$(date +%s)

  if [[ -f "$dedup_file" ]]; then
    local last
    last=$(cat "$dedup_file" 2>/dev/null || echo 0)
    if (( now - last < DEDUP_WINDOW )); then
      log "skip ${event_type}: dedup ($((now - last))s < ${DEDUP_WINDOW}s)"
      return 0
    fi
  fi

  local url="${SERVER_URL}/device/${event_type}"
  local payload
  payload=$(EVENT_TYPE="$event_type" _DEVICE="$DEVICE_NAME" _PLACE="$PLACE" \
    python3 - <<'PY' 2>/dev/null
import json, os
event = os.environ['EVENT_TYPE']
name  = os.environ['_DEVICE']
place = os.environ.get('_PLACE', '')
labels = {'wake': '절전 해제', 'unlock': '화면 잠금 해제'}
msg = f"{name} {labels.get(event, event)}"
d = {'source': 'macos_session_watch', 'device': name, 'message': msg}
if place:
    d['place'] = place
print(json.dumps(d, ensure_ascii=False))
PY
  ) || { log "payload build failed for ${event_type}"; return 0; }

  if curl -fsS \
      -X POST \
      -H 'Content-Type: application/json; charset=utf-8' \
      -H "X-Webhook-Secret: ${SECRET}" \
      --data "$payload" \
      --max-time 10 \
      "$url" >/dev/null 2>&1; then
    echo "$now" > "$dedup_file"
    log "sent ${event_type} -> ${url}"
  else
    log "warn: curl failed for ${event_type} -> ${url} (server may be unavailable)"
  fi
  return 0
}

log "start: device=${DEVICE_NAME} place=${PLACE:-auto} server=${SERVER_URL} poll=${POLL_INTERVAL}s wake_gap=${WAKE_GAP}s"

while true; do
  NOW=$(date +%s)

  # Wake detection: a heartbeat gap larger than WAKE_GAP means the Mac was asleep.
  # Works whether launchd suspends or kills the script during sleep — both leave a stale heartbeat.
  if [[ -f "$HEARTBEAT_FILE" ]]; then
    LAST_HB=$(cat "$HEARTBEAT_FILE" 2>/dev/null || echo "$NOW")
    GAP=$(( NOW - LAST_HB ))
    if (( GAP > WAKE_GAP )); then
      log "wake detected: gap=${GAP}s"
      send_event "wake"
    fi
  fi
  echo "$NOW" > "$HEARTBEAT_FILE"

  # Unlock detection: fire on locked(1) -> unlocked(0) transition.
  CURRENT_LOCK=$(check_lock_state)
  PREV_LOCK=$(cat "$LOCK_STATE_FILE" 2>/dev/null || echo "-1")

  if [[ "$PREV_LOCK" == "1" && "$CURRENT_LOCK" == "0" ]]; then
    log "unlock detected (lock_state: ${PREV_LOCK} -> ${CURRENT_LOCK})"
    send_event "unlock"
  fi

  if [[ "$CURRENT_LOCK" != "-1" ]]; then
    echo "$CURRENT_LOCK" > "$LOCK_STATE_FILE"
  fi

  sleep "$POLL_INTERVAL"
done
