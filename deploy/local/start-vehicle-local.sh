#!/usr/bin/env bash
# Start the local vehicle-side stack on the same machine as the control station.
#
# This is the no-root development counterpart of lr-robot-runtime.service plus
# the mapping agent. It starts:
#   - IMU / DDSM115 chassis / wheel odometry
#   - front and rear lidars, static laser TFs, dual laser merger
#   - manual map->odom bridge (for point-cloud visualization; NOT AMCL)
#   - Edge Gateway (localhost MQTT, no TLS)
#   - mapping agent HTTP control plane :18090
#
# It does NOT start Nav2/AMCL or the arm. No motion command is published at
# startup. Manual control becomes active only when an operator presses the
# confirmed controls in the chassis-debug page; keep the physical E-stop
# reachable.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
. "$SCRIPT_DIR/env.sh"

ROS_SETUP=/opt/ros/jazzy/setup.bash
OVL="$STACK_DIR/ros-overlay/opt/ros/jazzy"
INSTALL="$STACK_DIR/ros-install"
WS="$BUNDLE_ROOT/LR-Web/external/Library_robot"
RUN_DIR="$STACK_RUN/vehicle"
LOG_DIR="$STACK_LOGS/vehicle"
CONFIG="$SCRIPT_DIR/config/edge_gateway.local.yaml"
MARK_FILE="$STACK_DATA/mapping-marks.json"

mkdir -p "$RUN_DIR" "$LOG_DIR" "$STACK_DATA"
export ROS_DOMAIN_ID="${LR_ROS_DOMAIN_ID:-42}"

# Repeated dashboard clicks can launch this script concurrently. The lock is
# released automatically when the script exits; a second invocation exits 0.
exec 9>"$RUN_DIR/start.lock"
if ! flock -n 9; then
  log "another vehicle start is already in progress"
  exit 0
fi

# Fast DDS shared-memory segments left by a killed ROS process can silently
# break discovery (Python nodes see each other while C++ nodes vanish). When
# our stack is fully stopped, clear only those stale segments before starting.
vehicle_alive=0
for pidfile in "$RUN_DIR"/*.pid; do
  [ -f "$pidfile" ] || continue
  pid="$(cat "$pidfile" 2>/dev/null || true)"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    vehicle_alive=1
    break
  fi
done
if ps -eo args | grep -qE '[.]local-stack/ros-install|[d]eploy/local/manual_pose_bridge.py|[s]cripts/mapping_agent.py'; then
  vehicle_alive=1
fi
if [ "$vehicle_alive" -eq 0 ]; then
  rm -f "$RUN_DIR"/*.pid
  rm -f /dev/shm/fastrtps_* /dev/shm/sem.fastrtps_* 2>/dev/null || true
fi
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST

# shellcheck source=/dev/null
set +u
source "$ROS_SETUP"
source "$INSTALL/setup.bash"
set -u
export AMENT_PREFIX_PATH="$OVL${AMENT_PREFIX_PATH:+:$AMENT_PREFIX_PATH}"
export LD_LIBRARY_PATH="$STACK_ROOT/usr/lib/x86_64-linux-gnu:$OVL/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PYTHONPATH="$OVL/lib/python3.12/site-packages${PYTHONPATH:+:$PYTHONPATH}"

log() { printf '[vehicle] %s\n' "$*"; }

running() {
  local pidfile="$RUN_DIR/$1.pid"
  [ -f "$pidfile" ] || return 1
  local pid
  pid="$(cat "$pidfile" 2>/dev/null || true)"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

start_node() {
  local name=$1
  shift
  local pidfile="$RUN_DIR/$name.pid"
  local logfile="$LOG_DIR/$name.log"

  if running "$name"; then
    log "$name already running (pid $(cat "$pidfile"))"
    return 0
  fi

  log "starting $name"
  setsid nohup "$@" >>"$logfile" 2>&1 </dev/null &
  local pid=$!
  echo "$pid" >"$pidfile"
  sleep 0.8
  if ! kill -0 "$pid" 2>/dev/null; then
    log "ERROR: $name exited immediately; see $logfile"
    tail -20 "$logfile" 2>/dev/null || true
    return 1
  fi
  return 0
}

fail=0

# The mapping agent takes the HTTP port and also initialises rclpy. Start it
# before the high-rate drivers so its startup is not competing with DDS and
# serial discovery; /scan and TF are subscribed later as they appear.
export MAPPING_AGENT_HOST=127.0.0.1
export MAPPING_AGENT_PORT=18090
export MAPPING_AGENT_MARKS_FILE="$MARK_FILE"
start_node mapping_agent /usr/bin/python3 "$WS/scripts/mapping_agent.py" || fail=1

if [ "$fail" -eq 0 ]; then
  mapping_up=0
  for _ in $(seq 1 20); do
    if curl -fsS --max-time 2 http://127.0.0.1:18090/mapping/status >/dev/null 2>&1; then
      mapping_up=1
      break
    fi
    sleep 0.5
  done
  if [ "$mapping_up" -ne 1 ]; then
    log "ERROR: mapping agent did not open :18090"
    tail -20 "$LOG_DIR/mapping_agent.log" 2>/dev/null || true
    bash "$SCRIPT_DIR/stop-vehicle-local.sh" >/dev/null 2>&1 || true
    exit 1
  fi
  log "mapping agent ready on :18090"
fi

start_node imu "$INSTALL/car_ctrl/lib/car_ctrl/imu_driver" \
  --ros-args --params-file "$WS/src/car_ctrl/config/ddsm_hat_diff_drive.yaml" || fail=1
start_node chassis "$INSTALL/car_ctrl/lib/car_ctrl/ddsm_hat_diff_drive_node" \
  --ros-args --params-file "$WS/src/car_ctrl/config/ddsm_hat_diff_drive.yaml" || fail=1
start_node odometry "$INSTALL/car_ctrl/lib/car_ctrl/car_odometry" \
  --ros-args --params-file "$WS/src/car_ctrl/config/ddsm_hat_diff_drive.yaml" || fail=1

start_node lidar_front "$INSTALL/lslidar_driver/lib/lslidar_driver/lslidar_driver_node" \
  --ros-args -r __ns:=/lidar_1 \
  --params-file "$WS/src/lslidar_driver/params/lsx10_1.yaml" || fail=1
start_node lidar_rear "$INSTALL/lslidar_driver/lib/lslidar_driver/lslidar_driver_node" \
  --ros-args -r __ns:=/lidar_2 \
  --params-file "$WS/src/lslidar_driver/params/lsx10_2.yaml" || fail=1

start_node tf_front /opt/ros/jazzy/lib/tf2_ros/static_transform_publisher \
  --x 0.235 --y 0.282 --z 0.0 --roll 0.0 --pitch 0.0 --yaw 0.78539816339 \
  --frame-id base_link --child-frame-id laser_link || fail=1
start_node tf_rear /opt/ros/jazzy/lib/tf2_ros/static_transform_publisher \
  --x -0.235 --y -0.282 --z 0.0 --roll 0.0 --pitch 0.0 --yaw -2.3561944901 \
  --frame-id base_link --child-frame-id laser_link_b || fail=1

start_node laser_merger "$INSTALL/dual_laser_merger/lib/dual_laser_merger/dual_laser_merger_node" \
  --ros-args \
  -p laser_1_topic:=/scan_f -p laser_2_topic:=/scan_b \
  -p merged_scan_topic:=/scan -p merged_cloud_topic:=/merged_cloud \
  -p target_frame:=base_link \
  -p angle_min:=-3.141592654 -p angle_max:=3.141592654 \
  -p angle_increment:=0.001 -p scan_time:=0.15 \
  -p range_min:=0.01 -p range_max:=25.0 \
  -p min_height:=-1.0 -p max_height:=1.0 \
  -p allowed_radius:=0.45 \
  -p enable_shadow_filter:=true -p enable_average_filter:=false \
  -p enable_single_laser_fallback:=true -p single_laser_timeout:=0.6 \
  -p scan_status_topic:=/localization/scan_mode || fail=1

start_node pose_bridge /usr/bin/python3 "$SCRIPT_DIR/manual_pose_bridge.py" \
  --ros-args -p initial_x:=0.0 -p initial_y:=0.0 -p initial_yaw:=0.0 || fail=1

start_node gateway "$INSTALL/robot_decision/lib/robot_decision/edge_gateway_node" \
  --ros-args --params-file "$CONFIG" || fail=1

if [ "$fail" -ne 0 ]; then
  log "one or more vehicle nodes failed to start; cleaning up"
  bash "$SCRIPT_DIR/stop-vehicle-local.sh" >/dev/null 2>&1 || true
  exit 1
fi

log "waiting for topics and gateway telemetry"
sleep 7

mapping_ready=0
for _ in $(seq 1 40); do
  if curl -fsS --max-time 3 http://127.0.0.1:18090/mapping/status >/dev/null 2>&1; then
    mapping_ready=1
    break
  fi
  sleep 0.5
done
if [ "$mapping_ready" -ne 1 ]; then
  log "ERROR: mapping agent HTTP endpoint is not ready"
  tail -20 "$LOG_DIR/mapping_agent.log" 2>/dev/null || true
  bash "$SCRIPT_DIR/stop-vehicle-local.sh" >/dev/null 2>&1 || true
  exit 1
fi
log "mapping agent ready on :18090"

for name in imu chassis odometry lidar_front lidar_rear tf_front tf_rear laser_merger pose_bridge mapping_agent gateway; do
  if ! running "$name"; then
    log "ERROR: $name is no longer running; see $LOG_DIR/$name.log"
    bash "$SCRIPT_DIR/stop-vehicle-local.sh" >/dev/null 2>&1 || true
    exit 1
  fi
done

log "vehicle stack running"
exit 0
