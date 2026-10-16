#!/usr/bin/env python3
"""
Control one or more DDSM115 motors through Waveshare DDSM Driver HAT (A).

The HAT factory firmware accepts newline-terminated JSON commands over the
ESP32 serial port. This script is for quick manual tests on Ubuntu/ROS 2.
"""

import argparse
import json
import sys
import time
from typing import Dict, Iterable, List, Optional

try:
    import serial
except ImportError:
    print("Missing dependency: pyserial. Install it with: sudo apt install python3-serial")
    sys.exit(1)


DEFAULT_PORT = "/dev/chassis_serial_port"
DEFAULT_IDS = [1, 2, 3, 4]


class DDSMDriverHat:
    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 0.25):
        self.ser = serial.Serial(port, baudrate=baudrate, timeout=timeout, write_timeout=1.0, dsrdtr=None)
        # Waveshare's example explicitly drops RTS/DTR after opening the port.
        self.ser.setRTS(False)
        self.ser.setDTR(False)
        time.sleep(0.2)
        self.ser.reset_input_buffer()

    def close(self) -> None:
        self.ser.close()

    def send(self, command: Dict[str, int], read_time: float = 0.25) -> List[str]:
        payload = json.dumps(command, separators=(",", ":")).encode("utf-8") + b"\n"
        print(f"> {payload.decode('utf-8').strip()}")
        self.ser.write(payload)
        self.ser.flush()
        return self.read_lines(read_time)

    def read_lines(self, read_time: float) -> List[str]:
        lines = []
        deadline = time.monotonic() + read_time
        while time.monotonic() < deadline:
            raw = self.ser.readline()
            if raw:
                text = raw.decode("utf-8", errors="replace").strip()
                if text:
                    lines.append(text)
        for line in lines:
            print(f"< {line}")
        return lines

    def configure_for_ddsm115(self, heartbeat_ms: int) -> None:
        self.send({"T": 11002, "type": 115})
        self.send({"T": 11001, "time": heartbeat_ms})

    def set_velocity_mode(self, motor_id: int) -> None:
        self.send({"T": 10012, "id": motor_id, "mode": 2})

    def set_rpm(self, motor_id: int, rpm: int, accel: int) -> None:
        self.send({"T": 10010, "id": motor_id, "cmd": rpm, "act": accel})

    def stop(self, motor_id: int, accel: int) -> None:
        self.set_rpm(motor_id, 0, accel)

    def info(self, motor_id: int) -> None:
        self.send({"T": 10032, "id": motor_id}, read_time=0.4)


def parse_ids(values: Iterable[str]) -> List[int]:
    ids: List[int] = []
    for value in values:
        if value.lower() == "all":
            ids.extend(DEFAULT_IDS)
            continue
        motor_id = int(value)
        if motor_id not in DEFAULT_IDS:
            raise argparse.ArgumentTypeError("motor id must be 1, 2, 3, 4, or all")
        ids.append(motor_id)
    return sorted(set(ids))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Move selected DDSM115 motors forward/backward through DDSM Driver HAT (A)."
    )
    parser.add_argument("--port", default=DEFAULT_PORT, help=f"Serial port, default: {DEFAULT_PORT}")
    parser.add_argument(
        "--id",
        nargs="+",
        default=["1"],
        help="Motor ID(s): 1 2 3 4, or all. Example: --id 1 3",
    )
    parser.add_argument(
        "--direction",
        "-d",
        choices=["forward", "backward", "stop"],
        required=True,
        help="Motor direction. forward sends positive rpm, backward sends negative rpm.",
    )
    parser.add_argument("--rpm", type=int, default=30, help="Speed in rpm for DDSM115, default: 30")
    parser.add_argument("--seconds", type=float, default=1.5, help="Run time before auto-stop, default: 1.5")
    parser.add_argument("--accel", type=int, default=3, help="HAT act field, default: 3")
    parser.add_argument("--heartbeat-ms", type=int, default=1000, help="HAT safety heartbeat, default: 1000")
    parser.add_argument("--continuous", action="store_true", help="Do not auto-stop after --seconds")
    parser.add_argument("--skip-init", action="store_true", help="Skip DDSM115 type, heartbeat, and velocity-mode setup")
    parser.add_argument("--info", action="store_true", help="Read motor info after command")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        motor_ids = parse_ids(args.id)
    except (ValueError, argparse.ArgumentTypeError) as exc:
        parser.error(str(exc))

    rpm = abs(args.rpm)
    if args.direction == "backward":
        rpm = -rpm
    elif args.direction == "stop":
        rpm = 0

    print("DDSM Driver HAT (A) motor test")
    print(f"port={args.port} ids={motor_ids} direction={args.direction} rpm={rpm}")
    print("Make sure the wheels are lifted or the robot is safely supported.")

    hat: Optional[DDSMDriverHat] = None
    try:
        hat = DDSMDriverHat(args.port)

        if not args.skip_init:
            hat.configure_for_ddsm115(args.heartbeat_ms)
            for motor_id in motor_ids:
                hat.set_velocity_mode(motor_id)

        for motor_id in motor_ids:
            hat.set_rpm(motor_id, rpm, args.accel)

        if args.info:
            for motor_id in motor_ids:
                hat.info(motor_id)

        if args.direction != "stop" and not args.continuous:
            time.sleep(args.seconds)
            print("Auto-stop")
            for motor_id in motor_ids:
                hat.stop(motor_id, args.accel)

    except KeyboardInterrupt:
        print("\nInterrupted, stopping selected motors...")
        if hat is not None:
            for motor_id in motor_ids:
                hat.stop(motor_id, args.accel)
        return 130
    except serial.SerialException as exc:
        print(f"Serial error: {exc}")
        return 1
    finally:
        if hat is not None:
            hat.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
