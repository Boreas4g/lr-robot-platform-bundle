#!/usr/bin/env python3
"""
Simple DDSM115 four-motor forward/backward test.

Default behavior is deliberately conservative: test motor IDs 1, 2, 3, 4 one
at a time at low RPM, then stop/brake each motor.
"""

import argparse
import struct
import sys
import time
from typing import List, Optional, Tuple

try:
    import serial
except ImportError:
    print("Missing dependency: pyserial. Install it with: pip3 install pyserial")
    sys.exit(1)


DEFAULT_IDS = [1, 2, 3, 4]
MODE_CURRENT = 0x01
MODE_VELOCITY = 0x02
MODE_POSITION = 0x03


def crc8_maxim(data: bytes) -> int:
    """CRC-8/MAXIM, polynomial 0x31 reflected as 0x8C."""
    crc = 0x00
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x01:
                crc = (crc >> 1) ^ 0x8C
            else:
                crc >>= 1
            crc &= 0xFF
    return crc


def int16_to_bytes(value: int) -> Tuple[int, int]:
    packed = struct.pack(">h", int(value))
    return packed[0], packed[1]


def bytes_to_int16(high: int, low: int) -> int:
    return struct.unpack(">h", bytes([high, low]))[0]


def attach_crc(frame_without_crc: bytes) -> bytes:
    return frame_without_crc + bytes([crc8_maxim(frame_without_crc)])


class DDSM115Bus:
    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 0.08):
        self.ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=timeout,
            write_timeout=0.5,
        )
        self.gap_s = 0.02

    def close(self) -> None:
        self.ser.close()

    def set_velocity_mode(self, motor_id: int) -> None:
        # Waveshare mode-switch frame uses DATA[9] as the mode value, not CRC.
        frame = bytes([motor_id, 0xA0, 0, 0, 0, 0, 0, 0, 0, MODE_VELOCITY])
        self.ser.write(frame)
        self.ser.flush()
        time.sleep(self.gap_s)

    def send_rpm(self, motor_id: int, rpm: int, accel_time: int = 0) -> Optional[bytes]:
        rpm = max(-330, min(330, int(rpm)))
        hi, lo = int16_to_bytes(rpm)
        frame = attach_crc(bytes([motor_id, 0x64, hi, lo, 0, 0, accel_time & 0xFF, 0, 0]))
        self.ser.reset_input_buffer()
        self.ser.write(frame)
        self.ser.flush()
        reply = self.read_reply(motor_id)
        time.sleep(self.gap_s)
        return reply

    def brake(self, motor_id: int) -> Optional[bytes]:
        frame = attach_crc(bytes([motor_id, 0x64, 0, 0, 0, 0, 0, 0xFF, 0]))
        self.ser.reset_input_buffer()
        self.ser.write(frame)
        self.ser.flush()
        reply = self.read_reply(motor_id)
        time.sleep(self.gap_s)
        return reply

    def read_reply(self, motor_id: int) -> Optional[bytes]:
        deadline = time.monotonic() + 0.12
        buf = bytearray()
        while time.monotonic() < deadline:
            chunk = self.ser.read(1)
            if not chunk:
                continue

            byte = chunk[0]
            if not buf:
                if byte == motor_id:
                    buf.append(byte)
                continue

            buf.append(byte)
            if len(buf) == 10:
                if crc8_maxim(bytes(buf[:9])) == buf[9]:
                    return bytes(buf)
                buf.clear()

        return None


def describe_reply(reply: Optional[bytes]) -> str:
    if reply is None:
        return "no reply"

    current_raw = bytes_to_int16(reply[2], reply[3])
    rpm = bytes_to_int16(reply[4], reply[5])
    error = reply[8]
    current_a = current_raw * 8.0 / 32767.0
    return f"mode={reply[1]} rpm={rpm} current={current_a:.2f}A error=0x{error:02X}"


def stop_all(bus: DDSM115Bus, motor_ids: List[int]) -> None:
    for motor_id in motor_ids:
        try:
            bus.send_rpm(motor_id, 0)
            bus.brake(motor_id)
        except serial.SerialException as exc:
            print(f"ID {motor_id}: stop failed: {exc}")


def test_one_by_one(bus: DDSM115Bus, motor_ids: List[int], rpm: int, seconds: float) -> None:
    for motor_id in motor_ids:
        print(f"\nID {motor_id}: set velocity mode")
        bus.set_velocity_mode(motor_id)

        print(f"ID {motor_id}: forward {rpm} rpm")
        print(f"  {describe_reply(bus.send_rpm(motor_id, rpm))}")
        time.sleep(seconds)

        print(f"ID {motor_id}: stop")
        print(f"  {describe_reply(bus.send_rpm(motor_id, 0))}")
        time.sleep(0.5)

        print(f"ID {motor_id}: backward {-rpm} rpm")
        print(f"  {describe_reply(bus.send_rpm(motor_id, -rpm))}")
        time.sleep(seconds)

        print(f"ID {motor_id}: brake")
        print(f"  {describe_reply(bus.brake(motor_id))}")
        time.sleep(0.5)


def test_together(bus: DDSM115Bus, motor_ids: List[int], rpm: int, seconds: float) -> None:
    for motor_id in motor_ids:
        bus.set_velocity_mode(motor_id)

    print(f"\nAll motors: forward {rpm} rpm")
    for motor_id in motor_ids:
        print(f"  ID {motor_id}: {describe_reply(bus.send_rpm(motor_id, rpm))}")
    time.sleep(seconds)

    print("All motors: stop")
    for motor_id in motor_ids:
        print(f"  ID {motor_id}: {describe_reply(bus.send_rpm(motor_id, 0))}")
    time.sleep(0.5)

    print(f"All motors: backward {-rpm} rpm")
    for motor_id in motor_ids:
        print(f"  ID {motor_id}: {describe_reply(bus.send_rpm(motor_id, -rpm))}")
    time.sleep(seconds)

    print("All motors: brake")
    for motor_id in motor_ids:
        print(f"  ID {motor_id}: {describe_reply(bus.brake(motor_id))}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test DDSM115 motor IDs 1,2,3,4 forward and backward over RS485."
    )
    parser.add_argument("--port", default="/dev/rs485", help="Serial port, e.g. /dev/rs485 or /dev/ttyUSB0")
    parser.add_argument("--rpm", type=int, default=20, help="Test speed, limited by motor protocol to +/-330")
    parser.add_argument("--seconds", type=float, default=1.5, help="Run time for each direction")
    parser.add_argument("--ids", type=int, nargs="+", default=DEFAULT_IDS, help="Motor IDs to test")
    parser.add_argument("--together", action="store_true", help="Run all selected motors at the same time")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    motor_ids = list(args.ids)
    rpm = abs(args.rpm)

    print("DDSM115 four-motor test")
    print(f"port={args.port} ids={motor_ids} rpm={rpm} seconds={args.seconds}")
    print("Keep the robot lifted or wheels clear before running this test.")

    bus = DDSM115Bus(args.port)
    try:
        if args.together:
            test_together(bus, motor_ids, rpm, args.seconds)
        else:
            test_one_by_one(bus, motor_ids, rpm, args.seconds)
    except KeyboardInterrupt:
        print("\nInterrupted, stopping all motors...")
        stop_all(bus, motor_ids)
        return 130
    finally:
        stop_all(bus, motor_ids)
        bus.close()

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
