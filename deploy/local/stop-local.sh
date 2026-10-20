#!/usr/bin/env bash
# Stop the user-space local deployment started by start-local.sh.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
. "$SCRIPT_DIR/env.sh"

PG_BIN="$STACK_ROOT/usr/lib/postgresql/16/bin"

log() { printf '[stop] %s\n' "$*"; }

stop_pidfile() {
  local name=$1
  local file="$STACK_RUN/$name.pid"
  if [ ! -f "$file" ]; then
    return
  fi
  local pid
  pid="$(cat "$file")"
  if kill -0 "$pid" 2>/dev/null; then
    log "stopping $name (pid $pid)"
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.25
    done
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$file"
}

stop_pidfile static
stop_pidfile control-api
stop_pidfile bookarm
if [ -S "$LR_BOOKARM_SOCKET" ]; then
  for pid in $(ss -lxnp 2>/dev/null | grep -F "$LR_BOOKARM_SOCKET" \
    | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u); do
    log "stopping bookarm socket owner (pid $pid)"
    kill "$pid" 2>/dev/null || true
  done
  rm -f "$LR_BOOKARM_SOCKET"
fi
stop_pidfile mosquitto
# The broker may have been adopted from a previous run without a pidfile.
for pid in $(pgrep -x mosquitto); do
  log "stopping mosquitto (pid $pid)"
  kill "$pid" 2>/dev/null || true
done

if redis-cli -h 127.0.0.1 -p "$LR_REDIS_PORT" ping 2>/dev/null | grep -q PONG; then
  log "shutting down Redis"
  redis-cli -h 127.0.0.1 -p "$LR_REDIS_PORT" shutdown nosave 2>/dev/null || true
fi

if "$PG_BIN/pg_isready" -h 127.0.0.1 -p "$LR_PG_PORT" >/dev/null 2>&1; then
  log "stopping PostgreSQL"
  "$PG_BIN/pg_ctl" -D "$STACK_DATA/postgres" -m fast stop >/dev/null
fi

log "stopped"
