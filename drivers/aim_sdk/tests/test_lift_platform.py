import unittest
from decimal import Decimal

from aim_sdk import AimDrive, LiftPlatform, SimulatedAimDevice, SimulatedTransport
from aim_sdk.registers import Register


class LiftPlatformTests(unittest.TestCase):
    def setUp(self) -> None:
        self.device = SimulatedAimDevice(address=1)
        self.drive = AimDrive.from_transport(SimulatedTransport(self.device), address=1)
        self.drive.enable_modbus()
        self.drive.enable_output()
        self.lift = LiftPlatform(self.drive)

    def test_height_to_absolute_position_uses_the_calibrated_mapping(self) -> None:
        self.assertEqual(self.lift.height_to_absolute_position("54"), 1)
        self.assertEqual(self.lift.height_to_absolute_position("56.2"), 100_001)
        self.assertEqual(self.lift.height_to_absolute_position("120"), 3_000_001)

    def test_move_applies_the_selected_speed_profile_before_positioning(self) -> None:
        target = self.lift.move_to_height("56.2", speed=2)

        self.assertEqual(target, 100_001)
        self.assertEqual(self.device.registers[Register.TARGET_SPEED], 400)
        self.assertEqual(self.device.registers[Register.ACCELERATION], 400)
        self.assertEqual(self.device.absolute_position, target)
        self.assertEqual(self.lift.read_height_cm(), Decimal("56.2"))

    def test_height_and_speed_validation(self) -> None:
        with self.assertRaises(ValueError):
            self.lift.height_to_absolute_position("53.99")
        with self.assertRaises(ValueError):
            self.lift.height_to_absolute_position("120.01")
        with self.assertRaises(ValueError):
            self.lift.speed_profile(0)
        with self.assertRaises(ValueError):
            self.lift.speed_profile(4)
        with self.assertRaises(ValueError):
            self.lift.speed_profile(1.0)

    def test_speed_profiles_match_the_lift_configuration(self) -> None:
        self.assertEqual(self.lift.speed_profile(1).target_speed_rpm, 200)
        self.assertEqual(self.lift.speed_profile(1).acceleration_rpm_s, 400)
        self.assertEqual(self.lift.speed_profile(2).target_speed_rpm, 400)
        self.assertEqual(self.lift.speed_profile(2).acceleration_rpm_s, 400)
        self.assertEqual(self.lift.speed_profile(3).target_speed_rpm, 600)
        self.assertEqual(self.lift.speed_profile(3).acceleration_rpm_s, 600)


if __name__ == "__main__":
    unittest.main()
