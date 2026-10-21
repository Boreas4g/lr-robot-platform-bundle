#!/usr/bin/env bash
# Local-deployment adapter for the dashboard's "一键启动" button.
#
# The production scripts/start-all.sh starts systemd units and Docker. This
# host runs a rootless, user-space station (see deploy/local/README.md), so the
# dashboard button would otherwise report robot-runtime/mapping-agent/Docker as
# failed even though the control station is healthy.
#
# This adapter starts the local user-space stack and the local vehicle-side
# driver/gateway/mapping stack. It does not start Nav2/AMCL or the arm; those
# remain explicitly skipped. No motion command is published at startup.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
. "$SCRIPT_DIR/env.sh"

LOG="$STACK_LOGS/start-all-local.log"
mkdir -p "$STACK_LOGS"

step() { printf 'STEP %s %s %s\n' "$1" "$2" "$3"; }

export LR_BOOKARM_FAKE="${LR_BOOKARM_FAKE:-true}"

if timeout 90 bash "$SCRIPT_DIR/start-local.sh" >>"$LOG" 2>&1; then
  step bookarm-conflict OK "未检测到旧 BookArm TCP 服务"
else
  step local-stack FAILED "用户态服务启动失败；日志：$LOG"
  tail -30 "$LOG" 2>/dev/null || true
  exit 1
fi

if curl -fsS --max-time 5 "http://127.0.0.1:${LR_PORT}/health" >/dev/null 2>&1 \
  && curl -fsS --max-time 5 "http://127.0.0.1:${LR_WEB_PORT:-8000}/health" >/dev/null 2>&1; then
  step platform-web OK "用户态静态站点与 control-api 在线（:${LR_WEB_PORT:-8000} / :${LR_PORT}）"
else
  step platform-web FAILED "静态站点或 control-api 健康检查失败；日志：$LOG"
  tail -30 "$LOG" 2>/dev/null || true
  exit 1
fi

if curl -fsS --unix-socket "$LR_BOOKARM_SOCKET" --max-time 3 \
  http://localhost/api/v1/takeout/health 2>/dev/null | grep -q '"mode":"fake"'; then
  step bookarm-service OK "BookArm --fake 模拟服务在线（未连接真实机械臂）"
else
  step bookarm-service SKIPPED "BookArm fake 服务未启动；真实机械臂硬件未接入"
fi

# Start the vehicle stack detached. Its first start can take 10-20 seconds
# (serial devices, DDS discovery, Gateway MQTT); waiting here would keep the
# dashboard request open and is unnecessary. start-vehicle-local.sh uses a
# lock and is idempotent, so repeated clicks do not create duplicates.
if [ -x "$SCRIPT_DIR/start-vehicle-local.sh" ]; then
  # Close all inherited fds in the child: the API reads our stdout pipe until
  # EOF, and a detached grandchild inheriting it would keep that request open.
  if /usr/bin/python3 "$SCRIPT_DIR/spawn-detached.py" "$LOG" \
    bash "$SCRIPT_DIR/start-vehicle-local.sh"; then
    step vehicle-stack STARTED "车端驱动/Gateway/建图代理启动中（约 10–20 秒）"
    step vehicle-drivers STARTED "IMU、底盘、双雷达、里程计与雷达合并正在启动"
    step manual-localization STARTED "手动初始位姿→map TF 正在启动（点云叠图用，非 AMCL）"
    step edge-gateway STARTED "Edge Gateway 正在连接本机 MQTT（LR-01）"
    step mapping-agent STARTED "建图代理 :18090 正在启动"
  else
    step vehicle-stack FAILED "无法派发车端启动进程"
    exit 1
  fi
else
  step vehicle-stack FAILED "缺少 start-vehicle-local.sh"
  exit 1
fi

step can0 SKIPPED "本机无 CAN 机械臂硬件；未配置 can0"
step robot-runtime SKIPPED "仅启动驱动/网关；Nav2/AMCL 导航未安装，未启动自主导航"
step arm-service SKIPPED "真实机械臂硬件未接入；BookArm 保持 fake"

echo "[start-all] returning $(date -Is)" >>"$LOG"
exit 0
