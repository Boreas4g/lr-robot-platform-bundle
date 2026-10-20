#!/usr/bin/env bash
# Start the complete control station locally, without root, systemd or Docker.
#
#   PostgreSQL 127.0.0.1:55432   (unpacked under .local-stack)
#   Redis      127.0.0.1:56379
#   Mosquitto  127.0.0.1:51883
#   control-api       0.0.0.0:8080
#   static web        0.0.0.0:8000  (proxies /api and /health to control-api)
#
# Robot-side runtime, bookarm hardware service and the XT369 collector are
# intentionally not started: this deployment has no robot hardware attached.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
. "$SCRIPT_DIR/env.sh"

WEB_PORT="${LR_WEB_PORT:-8000}"
PG_BIN="$STACK_ROOT/usr/lib/postgresql/16/bin"
VENV="$BUNDLE_ROOT/LR-Web/.venv"

mkdir -p "$STACK_RUN" "$STACK_LOGS" "$STACK_DATA/redis" "$STACK_DATA/mosquitto"

log() { printf '[start] %s\n' "$*"; }

wait_for() {
  local description=$1
  shift
  for _ in $(seq 1 60); do
    if "$@" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done
  log "ERROR: timed out waiting for $description"
  return 1
}

# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------
start_postgres() {
  if "$PG_BIN/pg_isready" -h 127.0.0.1 -p "$LR_PG_PORT" >/dev/null 2>&1; then
    log "PostgreSQL already running on $LR_PG_PORT"
    return
  fi
  if [ ! -f "$STACK_DATA/postgres/PG_VERSION" ]; then
    log "initializing PostgreSQL data directory"
    "$PG_BIN/initdb" -D "$STACK_DATA/postgres" -U "$(id -un)" \
      --auth=trust --encoding=UTF8 --locale=C.UTF-8 >>"$STACK_LOGS/postgres.log" 2>&1
  fi
  log "starting PostgreSQL on $LR_PG_PORT"
  "$PG_BIN/pg_ctl" -D "$STACK_DATA/postgres" -l "$STACK_LOGS/postgres.log" \
    -o "-p $LR_PG_PORT -k /tmp -c listen_addresses=127.0.0.1" start >/dev/null
  wait_for "PostgreSQL" "$PG_BIN/pg_isready" -h 127.0.0.1 -p "$LR_PG_PORT"
}

ensure_database() {
  local exists
  exists="$("$PG_BIN/psql" -h 127.0.0.1 -p "$LR_PG_PORT" -U "$(id -un)" -d postgres -tAc \
    "SELECT 1 FROM pg_database WHERE datname='library_robot'")"
  if [ "$exists" = "1" ]; then
    return
  fi
  log "creating library_robot role and database"
  "$PG_BIN/psql" -h 127.0.0.1 -p "$LR_PG_PORT" -U "$(id -un)" -d postgres -v ON_ERROR_STOP=1 \
    -c "CREATE ROLE library_robot LOGIN PASSWORD 'change-me-before-production'" \
    -c "CREATE DATABASE library_robot OWNER library_robot" >/dev/null
}

# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------
start_redis() {
  if redis-cli -h 127.0.0.1 -p "$LR_REDIS_PORT" ping 2>/dev/null | grep -q PONG; then
    log "Redis already running on $LR_REDIS_PORT"
    return
  fi
  log "starting Redis on $LR_REDIS_PORT"
  cat >"$STACK_DIR/etc/redis.conf" <<EOF
bind 127.0.0.1
port $LR_REDIS_PORT
dir $STACK_DATA/redis
daemonize yes
pidfile $STACK_RUN/redis.pid
logfile $STACK_LOGS/redis.log
save ""
appendonly no
EOF
  redis-server "$STACK_DIR/etc/redis.conf"
  wait_for "Redis" redis-cli -h 127.0.0.1 -p "$LR_REDIS_PORT" ping
}

# ---------------------------------------------------------------------------
# Mosquitto
# ---------------------------------------------------------------------------
start_mosquitto() {
  if (exec 3<>"/dev/tcp/127.0.0.1/$LR_MQTT_PORT") 2>/dev/null; then
    log "Mosquitto already running on $LR_MQTT_PORT"
    pgrep -x mosquitto | head -1 >"$STACK_RUN/mosquitto.pid" || true
    return
  fi
  log "starting Mosquitto on $LR_MQTT_PORT"
  cat >"$STACK_DIR/etc/mosquitto.conf" <<EOF
listener $LR_MQTT_PORT 127.0.0.1
allow_anonymous true
persistence false
log_dest file $STACK_LOGS/mosquitto.log
EOF
  nohup mosquitto -c "$STACK_DIR/etc/mosquitto.conf" >/dev/null 2>&1 &
  echo $! >"$STACK_RUN/mosquitto.pid"
  wait_for "Mosquitto" bash -c "exec 3<>/dev/tcp/127.0.0.1/$LR_MQTT_PORT"
}

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
start_api() {
  if curl -fsS "http://127.0.0.1:${LR_PORT}/health" >/dev/null 2>&1; then
    log "control-api already running on $LR_PORT"
    return
  fi
  if [ ! -x "$VENV/bin/uvicorn" ]; then
    log "ERROR: Python environment missing; run deploy/local/bootstrap.sh first"
    exit 1
  fi
  log "starting control-api on $LR_PORT"
  (
    cd "$BUNDLE_ROOT/LR-Web/apps/control-api"
    nohup "$VENV/bin/uvicorn" app.main:app --host "$LR_HOST" --port "$LR_PORT" \
      >>"$STACK_LOGS/control-api.log" 2>&1 &
    echo $! >"$STACK_RUN/control-api.pid"
  )
  wait_for "control-api" curl -fsS "http://127.0.0.1:${LR_PORT}/health"
}

start_web() {
  if curl -fsS "http://127.0.0.1:${WEB_PORT}/health" >/dev/null 2>&1; then
    log "static web already running on $WEB_PORT"
    return
  fi
  if [ ! -d "$BUNDLE_ROOT/LR-Web/dist" ]; then
    log "ERROR: LR-Web/dist missing; run deploy/local/bootstrap.sh first"
    exit 1
  fi
  log "starting static web on $WEB_PORT"
  (
    cd "$BUNDLE_ROOT/LR-Web"
    nohup node scripts/serve-static.cjs --port "$WEB_PORT" \
      >>"$STACK_LOGS/static.log" 2>&1 &
    echo $! >"$STACK_RUN/static.pid"
  )
  wait_for "static web" curl -fsS "http://127.0.0.1:${WEB_PORT}/health"
}

start_postgres
ensure_database
start_redis
start_mosquitto
if [ "${LR_BOOKARM_FAKE:-false}" = true ]; then
  "$SCRIPT_DIR/start-bookarm-fake.sh"
fi
start_api
start_web

log "control station ready"
printf '  web       http://127.0.0.1:%s/\n' "$WEB_PORT"
printf '  API docs  http://127.0.0.1:%s/docs\n' "$LR_PORT"
printf '  health    http://127.0.0.1:%s/health\n' "$WEB_PORT"
