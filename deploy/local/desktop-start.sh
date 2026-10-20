#!/usr/bin/env bash
# Desktop launcher helper: start the complete local control station.
#
# Intended to be invoked by ~/Desktop/启动图书馆机器人.desktop. It starts the
# user-space PostgreSQL/Redis/Mosquitto stack, control-api, the static web
# server and the BookArm --fake service, then opens the operator page.
#
# Remove LR_BOOKARM_FAKE (or set it to false) here once real BookArm hardware
# is connected; the fake service would otherwise report simulated device health.

set -uo pipefail

BUNDLE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="$BUNDLE_ROOT/.local-stack/logs"
LOCK="$BUNDLE_ROOT/.local-stack/run/desktop-start.lock"
LOG="$LOG_DIR/desktop-start.log"
WEB_URL="http://localhost:8000"

mkdir -p "$LOG_DIR" "$(dirname "$LOCK")"

notify() {
  local urgency=$1 title=$2 body=$3
  if command -v notify-send >/dev/null 2>&1; then
    notify-send -u "$urgency" -i "$BUNDLE_ROOT/LR-Web/public/icons/icon-192x192.png" \
      "$title" "$body" 2>/dev/null || true
  fi
}

# A double click must not race two start-local runs against the same data dirs.
exec 9>"$LOCK"
if ! flock -n 9; then
  notify normal "图书馆机器人" "正在启动中，请稍候…"
  exit 0
fi

{
  echo
  echo "===== $(date -Is) desktop start ====="
  LR_BOOKARM_FAKE=true bash "$BUNDLE_ROOT/deploy/local/start-local.sh"
} >>"$LOG" 2>&1
status=$?

if [ "$status" -eq 0 ]; then
  notify normal "图书馆机器人已启动" "网页：$WEB_URL\nAPI 文档：http://localhost:8080/docs"
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$WEB_URL/" >/dev/null 2>&1 &
  fi
else
  notify critical "图书馆机器人启动失败" "详情见日志：$LOG"
  if command -v zenity >/dev/null 2>&1; then
    zenity --error --title="图书馆机器人启动失败" --width=560 \
      --text="部分服务未能启动。\n\n日志：$LOG\n\n可运行 deploy/local/status-local.sh 查看端口状态。"
  fi
fi

exit "$status"
