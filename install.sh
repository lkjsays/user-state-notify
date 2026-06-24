#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-}"
shift || true
SERVER_URL=""
REPO_RAW_BASE="https://raw.githubusercontent.com/lkjsays/user-state-notify/main"
# Scripts live OUTSIDE ~/.hermes so a Hermes reinstall (which wipes ~/.hermes)
# does not delete the user-state-notify client/server scripts. Logs and state
# stay under ~/.hermes and are recreated on demand by the scripts.
INSTALL_ROOT="$HOME/.user-state-notify/scripts"
LAUNCHD_DIR="$HOME/Library/LaunchAgents"

usage() {
  cat <<USAGE
Usage:
  install.sh server
  install.sh client --server-url http://HOST:8645
  install.sh all --server-url http://HOST:8645

Modes:
  server  Install local HTTP receiver on port 8645.
  client  Install login notifier that sends events to --server-url.
  all     Install both server and client.

Options:
  --server-url URL   Required for client/all. Example: http://100.x.y.z:8645
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --server-url)
      SERVER_URL="$2"; shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2 ;;
  esac
done

if [[ -z "$MODE" || "$MODE" == "-h" || "$MODE" == "--help" ]]; then
  usage
  exit 0
fi

case "$MODE" in
  server|client|all) ;;
  *) echo "Invalid mode: $MODE" >&2; usage >&2; exit 2 ;;
esac

if [[ "$MODE" == "client" || "$MODE" == "all" ]]; then
  if [[ -z "$SERVER_URL" ]]; then
    echo "--server-url is required for mode: $MODE" >&2
    exit 2
  fi
fi

mkdir -p "$INSTALL_ROOT" "$HOME/.hermes/logs" "$HOME/.hermes/state" "$LAUNCHD_DIR"

fetch() {
  local src="$1"
  local dst="$2"
  curl -fsSL "$REPO_RAW_BASE/$src" -o "$dst"
}

install_config_sample() {
  local cfg_dir="$HOME/.user-state-notify"
  mkdir -p "$cfg_dir"
  fetch config.json.example "$cfg_dir/config.json.example"
  if [[ ! -f "$cfg_dir/config.json" ]]; then
    cp "$cfg_dir/config.json.example" "$cfg_dir/config.json"
    chmod 600 "$cfg_dir/config.json"
    echo "Created $cfg_dir/config.json from sample — edit it with your bot token / webhook URL."
  else
    echo "Kept existing $cfg_dir/config.json"
  fi
}

install_server() {
  echo "Installing user-state-notify server..."
  fetch scripts/user_state_notify_proxy.py "$INSTALL_ROOT/user_state_notify_proxy.py"
  fetch scripts/reminders.py "$INSTALL_ROOT/reminders.py"
  fetch scripts/notifiers.py "$INSTALL_ROOT/notifiers.py"
  fetch scripts/location_proxy.py "$INSTALL_ROOT/location_proxy.py"
  chmod +x "$INSTALL_ROOT/user_state_notify_proxy.py" "$INSTALL_ROOT/location_proxy.py"

  local plist="$LAUNCHD_DIR/com.kjlee.location-proxy.plist"
  fetch launchd/com.kjlee.location-proxy.plist.template "$plist.tmp"
  sed "s#__HOME__#$HOME#g" "$plist.tmp" > "$plist"
  rm -f "$plist.tmp"

  launchctl unload "$plist" >/dev/null 2>&1 || true
  launchctl load "$plist"
  echo "Server launchd loaded: $plist"

  sleep 1
  if curl -fsS "http://127.0.0.1:8645/health" >/dev/null; then
    echo "Server health OK: http://127.0.0.1:8645/health"
  else
    echo "Warning: health check failed. See ~/.hermes/logs/user_state_notify_proxy.launchd.err.log" >&2
  fi
  install_config_sample
}

install_client() {
  echo "Installing user-state-notify client..."

  # Login notifier (RunAtLoad, one-shot)
  fetch scripts/notify_login.sh "$INSTALL_ROOT/notify_login.sh"
  chmod +x "$INSTALL_ROOT/notify_login.sh"

  local plist="$LAUNCHD_DIR/com.kjlee.user-state-login-notify.plist"
  fetch launchd/com.kjlee.user-state-login-notify.plist.template "$plist.tmp"
  python3 - "$plist.tmp" "$plist" "$HOME" "$SERVER_URL" <<'PY'
import sys
src, dst, home, server_url = sys.argv[1:]
text = open(src, encoding='utf-8').read()
text = text.replace('__HOME__', home).replace('__SERVER_URL__', server_url)
open(dst, 'w', encoding='utf-8').write(text)
PY
  rm -f "$plist.tmp"

  launchctl unload "$plist" >/dev/null 2>&1 || true
  launchctl load "$plist"
  echo "Login notifier launchd loaded: $plist"

  "$INSTALL_ROOT/notify_login.sh" --server-url "$SERVER_URL" || {
    echo "Warning: immediate login notification test failed. Check server URL: $SERVER_URL" >&2
  }

  # Session watcher (KeepAlive, long-lived — detects wake and screen unlock)
  fetch scripts/watch_macos_session.sh "$INSTALL_ROOT/watch_macos_session.sh"
  chmod +x "$INSTALL_ROOT/watch_macos_session.sh"

  local watch_plist="$LAUNCHD_DIR/com.kjlee.user-state-session-watch.plist"
  fetch launchd/com.kjlee.user-state-session-watch.plist.template "$watch_plist.tmp"
  python3 - "$watch_plist.tmp" "$watch_plist" "$HOME" "$SERVER_URL" <<'PY'
import sys
src, dst, home, server_url = sys.argv[1:]
text = open(src, encoding='utf-8').read()
text = text.replace('__HOME__', home).replace('__SERVER_URL__', server_url)
open(dst, 'w', encoding='utf-8').write(text)
PY
  rm -f "$watch_plist.tmp"

  launchctl unload "$watch_plist" >/dev/null 2>&1 || true
  launchctl load "$watch_plist"
  echo "Session watcher launchd loaded: $watch_plist"
  install_config_sample
}

if [[ "$MODE" == "server" || "$MODE" == "all" ]]; then
  install_server
fi

if [[ "$MODE" == "client" || "$MODE" == "all" ]]; then
  install_client
fi

echo "Done."
