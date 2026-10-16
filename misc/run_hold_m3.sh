#!/bin/bash
cd /home/boreas
sudo ip link set can0 down 2>/dev/null || true
sudo ip link set can0 type can bitrate 1000000 fd off loopback off
sudo ip link set can0 up
nohup python3 /home/boreas/hold_position_m3.py --duration 300 > /home/boreas/m3_hold.log 2>&1 &
echo "PID=$!"
