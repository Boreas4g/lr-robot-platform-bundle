#!/usr/bin/env python3
"""Advertise a control-station appliance to operator applications on its LAN."""

from __future__ import annotations

import argparse
import json
import socket
import time
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_ADDRESS = "239.255.77.77"
DEFAULT_PORT = 39777


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LR 控制站局域网发现广播")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--interval", type=float, default=3.0)
    parser.add_argument("--address", default=DEFAULT_ADDRESS)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser.parse_args()


def load_announcement(config_path: Path) -> bytes:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    station_url = str(config.get("stationUrl", "")).strip()
    station_id = str(config.get("stationId", "")).strip()
    station_name = str(config.get("stationName", "")).strip()
    parsed = urlparse(station_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("stationUrl 必须是完整的 HTTPS 控制站地址")
    if not station_id or len(station_id) > 120:
        raise ValueError("stationId 缺失或过长")
    if not station_name or len(station_name) > 120:
        raise ValueError("stationName 缺失或过长")
    return json.dumps(
        {
            "protocol": "lr-control-station-discovery/v1",
            "stationId": station_id,
            "stationName": station_name,
            "stationUrl": f"{parsed.scheme}://{parsed.netloc}",
        },
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")


def main() -> int:
    args = parse_args()
    if args.interval < 1 or args.interval > 60:
        raise ValueError("interval 必须在 1 到 60 秒之间")
    payload = load_announcement(args.config)
    destination = (args.address, args.port)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 0)
        while True:
            sock.sendto(payload, destination)
            time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
