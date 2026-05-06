#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-}"
shift || true
SERVER_URL=""
REPO_RAW_BASE="https://raw.githubusercontent.com/lkjsays/user-state-notify/main"
INSTALL_ROOT="$HOME/.hermes/scripts"
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

install_server() {
  echo "Installing user-state-notify server..."
  fetch scripts/user_state_notify_proxy.py "$INSTALL_ROOT/user_state_notify_proxy.py"
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
}

install_client() {
  echo "Installing user-state-notify client..."
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
  echo "Client launchd loaded: $plist"

  "$INSTALL_ROOT/notify_login.sh" --server-url "$SERVER_URL" || {
    echo "Warning: immediate login notification test failed. Check server URL: $SERVER_URL" >&2
  }
}

if [[ "$MODE" == "server" || "$MODE" == "all" ]]; then
  install_server
fi

if [[ "$MODE" == "client" || "$MODE" == "all" ]]; then
  install_client
fi

echo "Done."
