#!/usr/bin/env bash
# Bind the USB serial device currently at ttyUSB1 by its USB physical port.
set -euo pipefail

device=/dev/ttyUSB1
rule_file=/etc/udev/rules.d/99-lift-platform.rules

if [[ ! -c "$device" ]]; then
    echo "Error: $device is not present. Connect the lift controller and try again." >&2
    exit 1
fi

properties=$(udevadm info --query=property --name="$device")
vendor_id=$(printf '%s\n' "$properties" | sed -n 's/^ID_VENDOR_ID=//p')
model_id=$(printf '%s\n' "$properties" | sed -n 's/^ID_MODEL_ID=//p')
device_path=$(printf '%s\n' "$properties" | sed -n 's/^ID_PATH=//p')

if [[ -z "$vendor_id" || -z "$model_id" || -z "$device_path" ]]; then
    echo "Error: could not determine a stable USB identity for $device." >&2
    exit 1
fi

# This adapter has no unique serial number.  ID_PATH is stable for this USB port
# and remains valid even if the kernel assigns it a different ttyUSB number.
rule="SUBSYSTEM==\"tty\", KERNEL==\"ttyUSB*\", ENV{ID_VENDOR_ID}==\"$vendor_id\", ENV{ID_MODEL_ID}==\"$model_id\", ENV{ID_PATH}==\"$device_path\", SYMLINK+=\"lift_port\", MODE=\"0660\", GROUP=\"dialout\""

printf '%s\n' "$rule" | sudo tee "$rule_file" >/dev/null
sudo udevadm control --reload-rules
sudo udevadm trigger --action=add --subsystem-match=tty --sysname-match="${device##*/}"

if [[ "$(readlink -f /dev/lift_port 2>/dev/null || true)" == "$device" ]]; then
    ls -l /dev/lift_port
    echo "Done: this device is available at /dev/lift_port when connected to this USB port."
else
    echo "Rule installed, but /dev/lift_port does not point to $device yet. Unplug and reconnect the controller once." >&2
    exit 1
fi
