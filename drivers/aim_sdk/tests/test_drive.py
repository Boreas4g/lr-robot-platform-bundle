import unittest

from aim_sdk import AimDrive, AimDriveGroup, AxisMove, SimulatedAimDevice, SimulatedTransport
from aim_sdk.exceptions import SafetyInterlockError
from aim_sdk.models import BaudRate, SpecialFunction
from aim_sdk.registers import Register


class DriveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.device = SimulatedAimDevice(address=1)
        self.transport = SimulatedTransport(self.device)
        self.drive = AimDrive.from_transport(self.transport, address=1)

    def enable_for_motion(self) -> None:
        self.drive.enable_modbus()
        self.drive.enable_output()

    def test_enable_configure_and_status(self) -> None:
        self.enable_for_motion()
        config = self.drive.configure_motion(
            max_speed_rpm=1000,
            acceleration_rpm_s=5000,
            position_kp=3000,
            speed_kp=1.5,
            speed_integral_ms=100,
            speed_feedforward_v_per_krpm=1.0,
        )
        self.assertEqual(config.max_speed_rpm, 1000)
        status = self.drive.read_status()
        self.assertTrue(status.modbus_enabled)
        self.assertTrue(status.output_enabled)
        self.assertEqual(self.device.registers[Register.SPEED_KP], 1500)
        self.assertEqual(self.device.registers[Register.SPEED_FEEDFORWARD], 327)

    def test_relative_moves_use_both_documented_forms(self) -> None:
        self.enable_for_motion()
        self.drive.move_relative(32_768)
        self.drive.move_relative_vendor(-10)
        self.assertEqual(self.drive.read_absolute_position(), 32_758)

    def test_absolute_move_and_wait(self) -> None:
        self.enable_for_motion()
        self.drive.move_absolute(65_536, wait=True)
        self.assertEqual(self.drive.read_absolute_position(), 65_536)

    def test_zero_absolute_position_requires_explicit_acknowledgement(self) -> None:
        self.enable_for_motion()
        with self.assertRaises(SafetyInterlockError):
            self.drive.move_absolute(0)
        self.drive.move_absolute(100)
        self.drive.clear_absolute_position(acknowledge=True)
        self.assertEqual(self.drive.read_absolute_position(), 0)

    def test_motion_needs_explicit_output_enable(self) -> None:
        self.drive.enable_modbus()
        with self.assertRaises(SafetyInterlockError):
            self.drive.move_relative(100)

    def test_special_modes_and_save(self) -> None:
        self.drive.set_encoder_follow_mode()
        self.assertEqual(self.device.registers[Register.SPECIAL_FUNCTION], SpecialFunction.ENCODER_FOLLOW)
        self.drive.set_powerup_angle(100, save=True)
        self.assertEqual(self.device.registers[Register.SPECIAL_FUNCTION], 100)
        self.assertEqual(self.device.registers[Register.SAVE_PARAMETERS], 2)

    def test_baud_rate_sequence_uses_documented_internal_values(self) -> None:
        result = self.drive.configure_baud_rate(BaudRate.BPS_115200)
        self.assertEqual(result, BaudRate.BPS_115200)
        self.assertEqual(self.device.registers[Register.ACCELERATION], 803)
        self.assertEqual(self.device.registers[Register.WEAK_FIELD_ANGLE], 129)
        self.assertEqual(self.device.registers[Register.MODBUS_ENABLE], 506)


class GroupTests(unittest.TestCase):
    def test_broadcast_synchronized_absolute_move(self) -> None:
        device_1 = SimulatedAimDevice(address=1)
        device_2 = SimulatedAimDevice(address=2)
        transport = SimulatedTransport(device_1, device_2)
        axis_1 = AimDrive.from_transport(transport, address=1)
        axis_2 = AimDrive.from_transport(transport, address=2)
        for axis in (axis_1, axis_2):
            axis.enable_modbus()
            axis.enable_output()
        group = AimDriveGroup([axis_1, axis_2])
        group.move_absolute_sync(
            [
                AxisMove(position=32_768, speed_rpm=500, acceleration_rpm_s=3000),
                AxisMove(position=-100, speed_rpm=600, acceleration_rpm_s=4000),
            ]
        )
        self.assertEqual(device_1.absolute_position, 32_768)
        self.assertEqual(device_2.absolute_position, -100)
        self.assertEqual(device_2.registers[Register.TARGET_SPEED], 600)


if __name__ == "__main__":
    unittest.main()
