#!/bin/bash
set -euo pipefail
if [[ -r /etc/lr-platform/bluetooth.env ]]; then
  source /etc/lr-platform/bluetooth.env
fi
rfkill unblock bluetooth
# Set the adapter properties again after Bluetooth or USB adapter restarts.
for adapter in $(busctl --system tree org.bluez --list | sed -n '\|^/org/bluez/hci[0-9]*$|p'); do
  busctl --system set-property org.bluez "$adapter" org.bluez.Adapter1 Powered b true
  busctl --system set-property org.bluez "$adapter" org.bluez.Adapter1 Alias s "${LR_BLUETOOTH_NAME:-图书馆机器人}"
  busctl --system set-property org.bluez "$adapter" org.bluez.Adapter1 DiscoverableTimeout u 0
  busctl --system set-property org.bluez "$adapter" org.bluez.Adapter1 PairableTimeout u 0
  busctl --system set-property org.bluez "$adapter" org.bluez.Adapter1 Pairable b true
  busctl --system set-property org.bluez "$adapter" org.bluez.Adapter1 Discoverable b true
done
