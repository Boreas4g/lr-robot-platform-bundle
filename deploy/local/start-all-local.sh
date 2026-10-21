#!/usr/bin/env bash
# Local-deployment adapter for the dashboard's "一键启动" button.
#
# The production scripts/start-all.sh starts systemd units and Docker. This
# host runs a rootless, user-space station (see deploy/local/README.md), so the
# dashboard button would otherwise report robot-runtime/mapping-agent/Docker as
# failed even though the control station is healthy.
#
# This adapter starts the local user-space stack, reports the control-station
# components as OK, and explicitly SKIPS the on-robot ROS runtime, mapping agent
# and CAN/arm services. Those still require a field-authorized vehicle runtime.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
. "$SCRIPT_DIR/env.sh"

LOG="$STACK_LOGS/start-all-local.log"
mkdir -p "$STACK_LOGS"

step() { printf 'STEP %s %s %s\n' "$1" "$2" "$3"; }

export LR_BOOKARM_FAKE="${LR_BOOKARM_FAKE:-true}"

if bash "$SCRIPT_DIR/start-local.sh" >>"$LOG" 2>&1; then
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

step can0 SKIPPED "本机无 CAN 机械臂硬件；未配置 can0"
step robot-runtime SKIPPED "本机用户态部署未启动车端 ROS 运行时；需现场授权后单独启动"
step mapping-agent SKIPPED "本机用户态部署未启动建图代理；需现场授权后单独启动"

exit 0
