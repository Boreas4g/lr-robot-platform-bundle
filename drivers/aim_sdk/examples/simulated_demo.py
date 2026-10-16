"""Run a complete positioning flow without physical hardware."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aim_sdk import AimDrive, SimulatedAimDevice, SimulatedTransport


def main() -> None:
    transport = SimulatedTransport(SimulatedAimDevice(address=1))
    motor = AimDrive.from_transport(transport, address=1)
    motor.enable_modbus()
    motor.enable_output()
    motor.configure_motion(max_speed_rpm=800, acceleration_rpm_s=5000)
    motor.move_relative(32_768)
    print(motor.read_status())


if __name__ == "__main__":
    main()
