#!/usr/bin/env bash
set -eo pipefail

# The installed runner lives in /usr/local/libexec, so systemd provides the
# source workspace explicitly instead of deriving it from this copied script.
WORKSPACE="${LR_ROBOT_WORKSPACE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ROS_SETUP='/opt/ros/jazzy/setup.bash'
OVERLAY_SETUP="$WORKSPACE/install/setup.bash"
PARAMS_FILE="${1:?missing XT369P parameter file}"

if [[ ! -r "$ROS_SETUP" || ! -r "$OVERLAY_SETUP" || ! -r "$PARAMS_FILE" ]]; then
  echo 'XT369P battery runtime prerequisites are not readable.' >&2
  exit 1
fi

# This process only opens the existing RFCOMM character device for reading.
source "$ROS_SETUP"
source "$OVERLAY_SETUP"
exec ros2 run robot_decision xt369p_battery_node --ros-args --params-file "$PARAMS_FILE"
