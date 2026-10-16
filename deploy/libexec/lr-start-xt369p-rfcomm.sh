#!/usr/bin/env bash
set -euo pipefail

# Keep the local Bluetooth SPP link present for the read-only battery node.
rfcomm_index="${1:?missing RFCOMM index}"
device_address="${2:?missing XT369P Bluetooth address}"
channel="${3:?missing SPP channel}"

cleanup() {
  /usr/bin/rfcomm release "$rfcomm_index" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

while true; do
  # Release a stale connection left by BlueZ or a previous manual session.
  /usr/bin/rfcomm release "$rfcomm_index" >/dev/null 2>&1 || true
  /usr/bin/rfcomm connect "$rfcomm_index" "$device_address" "$channel" || true
  sleep 3
done
