#!/usr/bin/env bash
# Keep the legacy user-space stack separate from the installed systemd stack.
# Installed but stopped units still own this deployment: never fall back to a
# second set of serial drivers, MQTT identities or simulated hardware services.

managed_deployment_unit() {
  command -v systemctl >/dev/null 2>&1 || return 1
  local unit
  for unit in lr-robot-runtime.service lr-control-api.service \
    lr-robot-mapping-agent.service lr-bookarm-takeout.service lr-platform.service; do
    if systemctl cat "$unit" >/dev/null 2>&1; then
      printf '%s\n' "$unit"
      return 0
    fi
  done
  return 1
}

require_local_deployment() {
  local unit
  if unit="$(managed_deployment_unit)"; then
    printf '[local] 检测到正式部署 %s；拒绝启动或清理旧用户态栈。请使用正式控制台。\n' "$unit" >&2
    return 1
  fi
}
