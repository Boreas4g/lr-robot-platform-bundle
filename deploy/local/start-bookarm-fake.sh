#!/usr/bin/env bash
# Start the BookArm service in explicit --fake mode for hardware-free demo and
# integration tests. No CAN, camera, lift or rod device is touched; the service
# reports mode=fake on its own health endpoint.
#
# The socket lives under .local-stack so it works without root. Both the static
# proxy (LR_BOOKARM_SOCKET) and control-api (LR_BOOKARM_SOCKET_PATH) must point
# at the same path; .env already does.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
. "$SCRIPT_DIR/env.sh"

BOOKARM_ROOT="$BUNDLE_ROOT/LR-Web/external/lingzu-bookarm-py/bookarm"
BOOKARM_BIN="$BUNDLE_ROOT/LR-Web/.venv/bin/bookarm-takeout-service"
SOCKET="$LR_BOOKARM_SOCKET"

log() { printf '[bookarm] %s\n' "$*"; }

if curl -fsS --unix-socket "$SOCKET" http://localhost/api/v1/takeout/health 2>/dev/null \
  | grep -q '"mode":"fake"'; then
  log "fake BookArm already running at $SOCKET"
  # Recover the pid from the listening socket for a later clean stop.
  ss -lxnp 2>/dev/null | grep -F "$SOCKET" | grep -o 'pid=[0-9]*' | cut -d= -f2 \
    | head -1 >"$STACK_RUN/bookarm.pid" || true
  exit 0
fi

if [ ! -x "$BOOKARM_BIN" ]; then
  log "ERROR: bookarm-takeout-service missing; run deploy/local/bootstrap.sh"
  exit 1
fi

mkdir -p "$(dirname "$SOCKET")" "$STACK_DATA/bookarm/templates" "$STACK_DATA/bookarm/studio"
rm -f "$SOCKET"

log "starting fake BookArm at $SOCKET"
(
  cd "$BOOKARM_ROOT"
  nohup "$BOOKARM_BIN" \
    --fake \
    --unix-socket "$SOCKET" \
    --task-store-path "$STACK_DATA/bookarm/tasks.json" \
    --upload-dir "$STACK_DATA/bookarm/templates" \
    --studio-dir "$STACK_DATA/bookarm/studio" \
    >>"$STACK_LOGS/bookarm.log" 2>&1 &
  echo $! >"$STACK_RUN/bookarm.pid"
)

for _ in $(seq 1 40); do
  if curl -fsS --unix-socket "$SOCKET" http://localhost/api/v1/takeout/health 2>/dev/null \
    | grep -q '"mode":"fake"'; then
    log "fake BookArm ready"
    exit 0
  fi
  sleep 0.25
done

log "ERROR: fake BookArm did not become ready; see $STACK_LOGS/bookarm.log"
exit 1
