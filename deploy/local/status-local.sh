#!/usr/bin/env bash
# Show the state of the user-space local deployment.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
. "$SCRIPT_DIR/env.sh"

PG_BIN="$STACK_ROOT/usr/lib/postgresql/16/bin"
WEB_PORT="${LR_WEB_PORT:-8000}"

check() {
  local name=$1
  local port=$2
  if ss -ltn 2>/dev/null | awk '{print $4}' | grep -q ":$port$"; then
    printf '  %-12s listening on %s\n' "$name" "$port"
  else
    printf '  %-12s DOWN (%s)\n' "$name" "$port"
  fi
}

printf 'Local LR control station\n'
check PostgreSQL "$LR_PG_PORT"
check Redis "$LR_REDIS_PORT"
check Mosquitto "$LR_MQTT_PORT"
check control-api "$LR_PORT"
check web "$WEB_PORT"

if "$PG_BIN/pg_isready" -h 127.0.0.1 -p "$LR_PG_PORT" >/dev/null 2>&1; then
  printf '  version      %s\n' "$("$PG_BIN/psql" -h 127.0.0.1 -p "$LR_PG_PORT" -U "$(id -un)" \
    -d library_robot -tAc 'SELECT version()' | cut -d' ' -f1-2)"
fi

if [ -S "$LR_BOOKARM_SOCKET" ]; then
  mode="$(curl -fsS --unix-socket "$LR_BOOKARM_SOCKET" http://localhost/api/v1/takeout/health 2>/dev/null || true)"
  printf '  BookArm      socket %s %s\n' "$LR_BOOKARM_SOCKET" "$mode"
else
  printf '  BookArm      not running (no %s)\n' "$LR_BOOKARM_SOCKET"
fi

if curl -fsS "http://127.0.0.1:$WEB_PORT/health" >/dev/null 2>&1; then
  printf '\nhealth via web proxy:\n'
  curl -fsS "http://127.0.0.1:$WEB_PORT/health" | "$BUNDLE_ROOT/LR-Web/.venv/bin/python" -m json.tool
else
  printf '\nweb health endpoint unreachable\n'
fi

printf '\nlogs: %s\n' "$STACK_LOGS"
