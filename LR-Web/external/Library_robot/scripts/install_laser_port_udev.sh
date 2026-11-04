#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_STAMP="$(date +%Y%m%dT%H%M%S%N)"

for rule in 99-robot-serial.rules 99-lr-lift-port.rules; do
  rule_src="${REPO_DIR}/config/${rule}"
  rule_dst="/etc/udev/rules.d/${rule}"
  if [[ -f "${rule_dst}" ]] && ! cmp -s "${rule_src}" "${rule_dst}"; then
    sudo cp -a "${rule_dst}" "${rule_dst}.bak.${BACKUP_STAMP}"
  fi
  sudo install -m 0644 "${rule_src}" "${rule_dst}"
done
sudo udevadm control --reload-rules
sudo udevadm trigger --action=add --subsystem-match=tty
sudo udevadm settle

echo "Installed robot and lift serial rules; existing rules were backed up if changed."
ls -l /dev/chassis_serial_port /dev/laser_port /dev/laser_back /dev/imu_port /dev/lift_port /dev/rodmotor
echo "Services were not restarted."
