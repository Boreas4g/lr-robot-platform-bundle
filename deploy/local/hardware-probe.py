#!/usr/bin/env python3
"""Read-only probe for the robot's serial hardware (no motion commands).

Checks, with direct serial reads:
  * WIT IMU on a CH340 tty (default /dev/ttyUSB0, 9600 baud)
  * two LSLIDAR N10_P lidars on CDC-ACM ttys (default /dev/ttyACM0/1, 460800)
  * DDSM115 chassis motors on a CDC-ACM tty (default /dev/ttyACM2, 115200)

The chassis probe only sends the DDSM115 feedback request (0x74), never a
velocity frame, so the wheels do not move. Run it after granting access to the
serial devices (dialout group or the project's udev rules).

    python3 deploy/local/hardware-probe.py
    python3 deploy/local/hardware-probe.py --seconds 8 --chassis /dev/ttyACM2
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from dataclasses import dataclass, field

try:
    import serial
except ImportError:  # pragma: no cover
    print("pyserial is missing (apt install python3-serial)", file=sys.stderr)
    raise SystemExit(2)


# ---------------------------------------------------------------------------
# WIT IMU (0x55 frame header, 11-byte frames)
# ---------------------------------------------------------------------------
def probe_imu(port: str, baud: int, seconds: float) -> bool:
    print(f"[IMU] {port} @ {baud} baud")
    try:
        connection = serial.Serial(port=port, baudrate=baud, timeout=0.1)
    except (serial.SerialException, OSError) as error:
        print(f"  FAIL open: {error}")
        return False

    frames = {0x51: 0, 0x52: 0, 0x53: 0}
    gyro_max = [0.0, 0.0, 0.0]
    gyro_nonzero = 0
    acc = gyro = angle = None
    buffer = bytearray()
    deadline = time.monotonic() + seconds
    try:
        while time.monotonic() < deadline:
            chunk = connection.read(connection.in_waiting or 1)
            if not chunk:
                continue
            buffer.extend(chunk)
            while len(buffer) >= 11:
                if buffer[0] != 0x55:
                    del buffer[0]
                    continue
                frame = bytes(buffer[:11])
                if (sum(frame[:10]) & 0xFF) != frame[10]:
                    del buffer[0]
                    continue
                del buffer[:11]
                kind, payload = frame[1], frame[2:10]
                raw = [payload[i] | (payload[i + 1] << 8) for i in (0, 2, 4)]
                # WIT scaling differs per frame type: accel +-16 g, gyro +-2000 deg/s,
                # angle +-180 deg. Apply one scale to all three axes of that frame.
                scale = {0x51: 16.0, 0x52: 2000.0, 0x53: 180.0}.get(kind)
                if scale is None:
                    continue
                signed = []
                for value in raw:
                    value = value / 32768.0 * scale
                    if value >= scale:
                        value -= 2.0 * scale
                    signed.append(value)
                if kind == 0x51:
                    frames[kind] += 1
                    acc = [value * 9.80665 for value in signed]
                elif kind == 0x52:
                    frames[kind] += 1
                    gyro = [math.radians(value) for value in signed]
                    for axis, value in enumerate(gyro):
                        gyro_max[axis] = max(gyro_max[axis], abs(value))
                    if any(abs(value) > 1e-9 for value in gyro):
                        gyro_nonzero += 1
                elif kind == 0x53:
                    frames[kind] += 1
                    angle = [math.radians(value) for value in signed]
    except (serial.SerialException, OSError) as error:
        print(f"  FAIL read: {error}")
        return False
    finally:
        connection.close()

    total = sum(frames.values())
    rate = total / seconds
    print(f"  frames: {total} ({rate:.1f}/s)  acc={frames[0x51]} gyro={frames[0x52]} angle={frames[0x53]}")
    if acc:
        print(f"  accel  (m/s^2): {acc[0]:+.2f} {acc[1]:+.2f} {acc[2]:+.2f}")
    if gyro:
        print(f"  gyro   (deg/s): {math.degrees(gyro[0]):+.2f} {math.degrees(gyro[1]):+.2f} {math.degrees(gyro[2]):+.2f}")
        print(f"  gyro max (deg/s): {math.degrees(gyro_max[0]):.3f} {math.degrees(gyro_max[1]):.3f} {math.degrees(gyro_max[2]):.3f}"
              f"  nonzero_frames={gyro_nonzero}/{frames[0x52]}")
    if angle:
        print(f"  angle  (deg):   {math.degrees(angle[0]):+.2f} {math.degrees(angle[1]):+.2f} {math.degrees(angle[2]):+.2f}")
    if total == 0:
        print("  FAIL: no valid 0x55 WIT frames (wrong port/baud or IMU not WIT-compatible)")
        return False
    if frames[0x53] == 0:
        print("  WARN: angle frames (0x53) absent")
    return True


# ---------------------------------------------------------------------------
# LSLIDAR N10_P (A5 5A, 108-byte packets, CRC = low byte of sum of first 107)
# ---------------------------------------------------------------------------
@dataclass
class LidarStats:
    packets: int = 0
    crc_errors: int = 0
    points: int = 0
    ranges: list[float] = field(default_factory=list)
    start_angle: float | None = None
    end_angle: float | None = None


def probe_lidar(name: str, port: str, baud: int, seconds: float) -> bool:
    print(f"[{name}] {port} @ {baud} baud (N10_P)")
    try:
        connection = serial.Serial(port=port, baudrate=baud, timeout=0.1)
    except (serial.SerialException, OSError) as error:
        print(f"  FAIL open: {error}")
        return False

    stats = LidarStats()
    buffer = bytearray()
    started = time.monotonic()
    deadline = started + seconds
    try:
        while time.monotonic() < deadline:
            chunk = connection.read(connection.in_waiting or 1)
            if not chunk:
                continue
            buffer.extend(chunk)
            while True:
                start = buffer.find(b"\xa5\x5a")
                if start < 0:
                    if len(buffer) > 256:
                        del buffer[:-2]
                    break
                if start:
                    del buffer[:start]
                if len(buffer) < 108:
                    break
                packet = bytes(buffer[:108])
                if (sum(packet[:107]) & 0xFF) != packet[107]:
                    stats.crc_errors += 1
                    del buffer[0]
                    continue
                del buffer[:108]
                stats.packets += 1
                if stats.start_angle is None:
                    stats.start_angle = ((packet[5] << 8) | packet[6]) / 100.0
                    stats.end_angle = ((packet[105] << 8) | packet[106]) / 100.0
                for index in range(16):
                    offset = 7 + index * 6
                    distance = ((packet[offset] << 8) | packet[offset + 1]) / 1000.0
                    if distance > 0.0:
                        stats.points += 1
                        stats.ranges.append(distance)
    except (serial.SerialException, OSError) as error:
        print(f"  FAIL read: {error}")
        return False
    finally:
        connection.close()

    elapsed = time.monotonic() - started
    rate = stats.packets / elapsed if elapsed else 0.0
    print(f"  packets: {stats.packets} ({rate:.1f}/s)  crc_errors: {stats.crc_errors}  points: {stats.points}")
    if stats.start_angle is not None:
        print(f"  first packet angle: {stats.start_angle:.2f}° -> {stats.end_angle:.2f}°")
    if stats.ranges:
        print(f"  range: {min(stats.ranges):.3f} .. {max(stats.ranges):.3f} m")
    if stats.packets == 0:
        print("  FAIL: no valid N10_P packets (wrong port/baud, lidar off, or wrong model)")
        return False
    if stats.points == 0:
        print("  WARN: packets received but every distance is 0xFFFF/zero")
    return True


# ---------------------------------------------------------------------------
# DDSM115 RS485 chassis: feedback request only, no motion
# ---------------------------------------------------------------------------
def crc8_maxim(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc >> 1) ^ 0x8C) if crc & 0x01 else (crc >> 1)
            crc &= 0xFF
    return crc


def probe_chassis(port: str, baud: int, motor_ids: list[int], seconds: float) -> bool:
    print(f"[CHASSIS] {port} @ {baud} baud, motors {motor_ids} (feedback only)")
    try:
        connection = serial.Serial(
            port=port,
            baudrate=baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.02,
            write_timeout=0.5,
        )
    except (serial.SerialException, OSError) as error:
        print(f"  FAIL open: {error}")
        return False

    found = 0
    try:
        for motor_id in motor_ids:
            frame = bytes([motor_id, 0x74, 0, 0, 0, 0, 0, 0, 0])
            frame += bytes([crc8_maxim(frame)])
            connection.reset_input_buffer()
            connection.write(frame)
            connection.flush()
            deadline = time.monotonic() + 0.4
            buffer = bytearray()
            while time.monotonic() < deadline and len(buffer) < 10:
                chunk = connection.read(max(1, 10 - len(buffer)))
                if chunk:
                    buffer.extend(chunk)
            reply = bytes(buffer[:10])
            if len(reply) == 10 and reply[0] == motor_id and crc8_maxim(reply[:9]) == reply[9]:
                mode = reply[1]
                rpm = int.from_bytes(reply[4:6], "big", signed=True)
                found += 1
                print(f"  motor {motor_id}: reply={reply.hex(' ')} mode=0x{mode:02x} rpm={rpm}")
            else:
                print(f"  motor {motor_id}: NO VALID REPLY (raw={reply.hex(' ') if reply else 'empty'})")
    except (serial.SerialException, OSError) as error:
        print(f"  FAIL read: {error}")
        return False
    finally:
        connection.close()

    print(f"  responding motors: {found}/{len(motor_ids)}")
    if found == 0:
        print("  FAIL: no DDSM115 replies (check 24V power, RS485 A/B wiring, baud, IDs)")
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--imu", default="/dev/imu_port")
    parser.add_argument("--front-lidar", default="/dev/laser_port")
    parser.add_argument("--rear-lidar", default="/dev/laser_back")
    parser.add_argument("--chassis", default="/dev/chassis_serial_port")
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--skip-imu", action="store_true")
    parser.add_argument("--skip-lidar", action="store_true")
    parser.add_argument("--skip-chassis", action="store_true")
    args = parser.parse_args()

    results: dict[str, bool] = {}
    if not args.skip_imu:
        results["IMU"] = probe_imu(args.imu, 9600, args.seconds)
    if not args.skip_lidar:
        results["front lidar"] = probe_lidar("FRONT LIDAR", args.front_lidar, 460800, args.seconds)
        results["rear lidar"] = probe_lidar("REAR LIDAR", args.rear_lidar, 460800, args.seconds)
    if not args.skip_chassis:
        results["chassis"] = probe_chassis(args.chassis, 115200, [1, 2, 3, 4], args.seconds)

    print("\nsummary:")
    for name, ok in results.items():
        print(f"  {'OK  ' if ok else 'FAIL'} {name}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
