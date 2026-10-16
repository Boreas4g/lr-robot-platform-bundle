import unittest

from aim_sdk import AimDrive, SimulatedAimDevice, SimulatedTransport
from aim_sdk.gui.session import ConnectionSettings, DriveSession


class GuiSessionTests(unittest.TestCase):
    def test_settings_validation(self) -> None:
        ConnectionSettings(port="COM3", address=1, baudrate=19200).validate()
        with self.assertRaises(ValueError):
            ConnectionSettings(port="", address=1).validate()
        with self.assertRaises(ValueError):
            ConnectionSettings(port="COM3", address=248).validate()

    def test_attached_simulated_drive_can_be_controlled_and_closed(self) -> None:
        transport = SimulatedTransport(SimulatedAimDevice(address=1))
        session = DriveSession()
        session.attach(AimDrive.from_transport(transport, address=1))
        session.call(lambda drive: drive.enable_modbus())
        session.call(lambda drive: drive.enable_output())
        self.assertTrue(session.call(lambda drive: drive.read_status()).output_enabled)
        session.disconnect()
        self.assertFalse(session.connected)
        self.assertTrue(transport.closed)


if __name__ == "__main__":
    unittest.main()
