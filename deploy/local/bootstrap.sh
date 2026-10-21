#!/usr/bin/env bash
# Bootstrap the user-space local deployment of the LR bundle.
#
# This host has no root access, no Docker and no systemd-managed lr-* units
# for this checkout. Everything therefore lives under the bundle:
#
#   .local-stack/root        PostgreSQL/Redis/Mosquitto unpacked from .deb
#   .local-stack/ros-overlay nav2_msgs + diagnostic_updater for ROS tests
#   .local-stack/data|logs   runtime state
#   LR-Web/.venv             Python environment (control-api, bookarm, aim_sdk)
#   LR-Web/node_modules      frontend dependencies
#   LR-Web/dist              frontend production build
#
# Idempotent: re-running only fills in what is missing.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
STACK_DIR="$BUNDLE_ROOT/.local-stack"
STACK_ROOT="$STACK_DIR/root"
ROS_OVERLAY="$STACK_DIR/ros-overlay"
DEB_CACHE="$STACK_DIR/debs"
VENV="$BUNDLE_ROOT/LR-Web/.venv"
PIP_INDEX="${LR_PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"

mkdir -p "$STACK_ROOT" "$DEB_CACHE" "$STACK_DIR/logs" "$STACK_DIR/run"

log() { printf '[bootstrap] %s\n' "$*"; }
die() { printf '[bootstrap] ERROR: %s\n' "$*" >&2; exit 1; }

for command in node npm python3 dpkg-deb curl git; do
  command -v "$command" >/dev/null 2>&1 || die "required command not found: $command"
done
node -e 'const v=process.versions.node.split(".").map(Number); if(v[0]<22) process.exit(1)' \
  || die "Node.js >= 22 is required"

# ---------------------------------------------------------------------------
# 1. User-space PostgreSQL / Redis / Mosquitto
# ---------------------------------------------------------------------------
download_deb() {
  local package=$1
  if ! ls "$DEB_CACHE/${package}"_*.deb >/dev/null 2>&1; then
    log "downloading $package"
    (cd "$DEB_CACHE" && apt-get download "$package" >/dev/null)
  fi
  dpkg-deb -x "$DEB_CACHE/${package}"_*.deb "$STACK_ROOT"
}

if [ ! -x "$STACK_ROOT/usr/lib/postgresql/16/bin/initdb" ]; then
  for package in \
    postgresql-16 postgresql-client-16 postgresql-common \
    redis-server redis-tools \
    mosquitto libmosquitto1 libcjson1 libwebsockets19t64 liblzf1 libjemalloc2 libdlt2; do
    download_deb "$package"
  done
else
  log "user-space infrastructure already extracted"
fi

# libpcap is only needed to compile the lslidar driver (ROS tests/build).
if [ ! -f "$STACK_ROOT/usr/include/pcap.h" ]; then
  download_deb libpcap-dev
  download_deb libpcap0.8-dev
fi
if [ -d "$STACK_ROOT/usr/lib/x86_64-linux-gnu" ]; then
  ln -sf /usr/lib/x86_64-linux-gnu/libpcap.so.0.8 "$STACK_ROOT/usr/lib/x86_64-linux-gnu/libpcap.so.0.8"
fi

# ---------------------------------------------------------------------------
# 2. Optional ROS binary overlay used by robot_decision tests/build
# ---------------------------------------------------------------------------
for package in ros-jazzy-nav2-msgs ros-jazzy-diagnostic-updater; do
  name="${package#ros-jazzy-}"
  name="${name//-/_}"
  if [ ! -d "$ROS_OVERLAY/opt/ros/jazzy/share/$name" ]; then
    if ! ls "$DEB_CACHE/${package}"_*.deb >/dev/null 2>&1; then
      log "downloading $package"
      (cd "$DEB_CACHE" && apt-get download "$package" >/dev/null)
    fi
    mkdir -p "$ROS_OVERLAY"
    dpkg-deb -x "$DEB_CACHE/${package}"_*.deb "$ROS_OVERLAY"
  fi
done

# ---------------------------------------------------------------------------
# 3. Python environment
# ---------------------------------------------------------------------------
if [ ! -x "$VENV/bin/uvicorn" ]; then
  if [ ! -x "$VENV/bin/python" ]; then
    log "creating Python virtual environment"
    if command -v virtualenv >/dev/null 2>&1; then
      python3 -m virtualenv -q "$VENV"
    else
      python3 -m venv "$VENV" || die "install python3-venv or 'pip install --user virtualenv'"
    fi
  fi
  log "installing control-api, bookarm, aim_sdk (index: $PIP_INDEX)"
  "$VENV/bin/pip" install --upgrade pip setuptools wheel \
    --index-url "$PIP_INDEX" >/dev/null
  "$VENV/bin/pip" install --index-url "$PIP_INDEX" \
    -e "$BUNDLE_ROOT/LR-Web/apps/control-api[dev]" \
    -e "$BUNDLE_ROOT/drivers/aim_sdk" \
    -e "$BUNDLE_ROOT/LR-Web/external/lingzu-bookarm-py/bookarm[service,test]" \
    'numpy<2.4' opencv-python-headless 'httpx2>=2.0' pyserial python-multipart 'pin>=4'
else
  log "Python environment already installed"
fi

# ---------------------------------------------------------------------------
# 4. Frontend dependencies and production build
# ---------------------------------------------------------------------------
cd "$BUNDLE_ROOT/LR-Web"
if [ ! -d node_modules ]; then
  log "installing frontend dependencies"
  ELECTRON_SKIP_BINARY_DOWNLOAD=1 HUSKY=0 npm ci --no-audit --no-fund
fi
if [ ! -d dist ]; then
  log "building frontend"
  UMI_ENV=production NODE_ENV=production NODE_OPTIONS=--max-old-space-size=2560 \
    RAYON_NUM_THREADS=2 npm run build
fi

# ---------------------------------------------------------------------------
# 5. Local configuration (never committed)
# ---------------------------------------------------------------------------
ENV_FILE="$BUNDLE_ROOT/LR-Web/apps/control-api/.env"
if [ ! -f "$ENV_FILE" ]; then
  log "writing $ENV_FILE"
  cat >"$ENV_FILE" <<EOF
LR_ENVIRONMENT=development
LR_STATION_NAME="LR 本地测试站"
LR_STATION_ID=local-dev-station
LR_STATION_URL=
LR_HOST=0.0.0.0
LR_PORT=8080
LR_CORS_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
LR_AUTH_ENABLED=false
LR_STORAGE_BACKEND=postgres
LR_DATABASE_URL=postgresql://library_robot:change-me-before-production@127.0.0.1:55432/library_robot
LR_REDIS_URL=redis://127.0.0.1:56379/0
LR_MQTT_URL=mqtt://127.0.0.1:51883
LR_REQUIRE_MQTT=false
LR_ROBOT_ROOT=$BUNDLE_ROOT/LR-Web/external/Library_robot
LR_REGISTER_ROBOT_MAP_SCRIPT=$BUNDLE_ROOT/LR-Web/external/Library_robot/scripts/register-robot-map.sh
LR_MAP_STORAGE_DIR=data/maps
LR_BATTERY_STATE_FILE=data/battery/state.sqlite3
LR_CRUISE_POINTS_FILE=$BUNDLE_ROOT/LR-Web/external/Library_robot/src/robot_decision/config/points.yaml
LR_CRUISE_POINTS_ENABLED=false
LR_VEHICLE_MAP_REGISTER_ENABLED=false
LR_BOOKARM_SOCKET_PATH=$STACK_DIR/run/bookarm/bookarm.sock
LR_HOST_START_ALL_SCRIPT=$BUNDLE_ROOT/deploy/local/start-all-local.sh
EOF
  chmod 600 "$ENV_FILE"
fi
mkdir -p "$BUNDLE_ROOT/LR-Web/apps/control-api/data/battery" \
  "$BUNDLE_ROOT/LR-Web/apps/control-api/data/maps"

log "done"
log "start:  bash deploy/local/start-local.sh"
log "test:   LR-Web/.venv/bin/python deploy/local/smoke-test.py"
