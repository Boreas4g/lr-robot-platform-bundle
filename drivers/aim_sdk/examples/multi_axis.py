"""Send a documented broadcast synchronized absolute move to two axes."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aim_sdk import AimDrive, AimDriveGroup, AxisMove
from aim_sdk.transport import SerialTransport


def main() -> None:
    transport = SerialTransport("/dev/lift_port")
    try:
        axis_1 = AimDrive.from_transport(transport, address=1)
        axis_2 = AimDrive.from_transport(transport, address=2)
        for axis in (axis_1, axis_2):
            axis.enable_modbus()
            axis.enable_output()
        axes = AimDriveGroup([axis_1, axis_2])
        axes.move_absolute_sync(
            [
                AxisMove(position=32_768, speed_rpm=500, acceleration_rpm_s=3000),
                AxisMove(position=65_536, speed_rpm=700, acceleration_rpm_s=4000),
            ]
        )
    finally:
        transport.close()


if __name__ == "__main__":
    main()
