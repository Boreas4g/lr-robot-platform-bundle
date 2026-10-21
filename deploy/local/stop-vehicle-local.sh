#!/usr/bin/env bash
# Stop the local vehicle-side stack started by start-vehicle-local.sh.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
. "$SCRIPT_DIR/env.sh"

RUN_DIR="$STACK_RUN/vehicle"

log() { printf '[vehicle-stop] %s\n' "$*"; }

stop_one() {
  local name=$1
  local pidfile="$RUN_DIR/$name.pid"
  [ -f "$pidfile" ] || return 0
  local pid
  pid="$(cat "$pidfile" 2>/dev/null || true)"
  rm -f "$pidfile"
  [ -n "$pid" ] || return 0
  if ! kill -0 "$pid" 2>/dev/null; then
    return 0
  fi
  log "stopping $name (pid $pid)"
  # setsid puts the node in its own process group; kill the whole group.
  kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  for _ in $(seq 1 25); do
    kill -0 "$pid" 2>/dev/null || return 0
    sleep 0.2
  done
  kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
}

# Reverse startup order.
for name in gateway mapping_agent pose_bridge laser_merger tf_rear tf_front \
  lidar_rear lidar_front odometry chassis imu; do
  stop_one "$name"
done

# PID files can miss orphans from an interrupted start (setsid reparents
# children). Sweep any remaining node owned by this bundle.
for pid in $(ps -eo pid,args | grep -E '[.]local-stack/ros-install|[d]eploy/local/manual_pose_bridge.py|[s]cripts/mapping_agent.py' | awk '{print $1}'); do
  log "stopping orphan vehicle process (pid $pid)"
  kill -9 "$pid" 2>/dev/null || true
done

# Killed Fast DDS processes leave shared-memory segments that break the next
# ROS 2 discovery. The local stack owns the machine's ROS graph, so clear them
# once every node is gone.
rm -f /dev/shm/fastrtps_* /dev/shm/sem.fastrtps_* 2>/dev/null || true

log "vehicle stack stopped"
