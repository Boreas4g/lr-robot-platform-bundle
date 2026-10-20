#!/usr/bin/env bash
# Shared environment for the user-space local deployment.
#
# The bundle is deployed without root: no systemd units, no Docker. PostgreSQL,
# Redis and Mosquitto are unpacked under .local-stack/root and run on
# non-default ports. The canonical API configuration lives in
# LR-Web/apps/control-api/.env; source this file so that direct os.environ
# readers (chassis_params.py, map_register.py) see the same values as
# pydantic-settings.

set -euo pipefail

BUNDLE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export BUNDLE_ROOT

STACK_DIR="${STACK_DIR:-$BUNDLE_ROOT/.local-stack}"
export STACK_DIR
export STACK_ROOT="$STACK_DIR/root"
export STACK_RUN="$STACK_DIR/run"
export STACK_LOGS="$STACK_DIR/logs"
export STACK_DATA="$STACK_DIR/data"

# shellcheck source=/dev/null
set -a
. "$BUNDLE_ROOT/LR-Web/apps/control-api/.env"
set +a

# Ports for the user-space infrastructure (must match .env).
export LR_PG_PORT="${LR_PG_PORT:-55432}"
export LR_REDIS_PORT="${LR_REDIS_PORT:-56379}"
export LR_MQTT_PORT="${LR_MQTT_PORT:-51883}"

# Static server proxy targets.
export LR_API_TARGET="${LR_API_TARGET:-127.0.0.1:8080}"
export LR_BOOKARM_SOCKET="${LR_BOOKARM_SOCKET:-$STACK_DIR/run/bookarm/bookarm.sock}"

export PATH="$STACK_ROOT/usr/bin:$STACK_ROOT/usr/sbin:$PATH"
export LD_LIBRARY_PATH="$STACK_ROOT/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

# Deployment does not need the ROS underlay or its pytest plugins.
export PYTHONPATH=
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
