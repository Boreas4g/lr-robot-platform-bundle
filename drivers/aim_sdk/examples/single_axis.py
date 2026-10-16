"""Move one YZ-AIM servo by one turn and read its final position."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aim_sdk import AimDrive


def main() -> None:
    # Replace /dev/lift_port and device address with the actual RS485 configuration.
    with AimDrive.connect("/dev/lift_port", address=1) as motor:
        motor.enable_modbus()
        motor.enable_output()
        motor.configure_motion(max_speed_rpm=600, acceleration_rpm_s=3000)
        motor.move_absolute(32_768, wait=True)
        print(f"Final position: {motor.read_absolute_position()} pulses")


if __name__ == "__main__":
    main()
