import unittest

from aim_sdk.exceptions import CrcError
from aim_sdk.modbus import append_crc, crc16, validate_crc


class CrcTests(unittest.TestCase):
    def test_manual_enable_modbus_frame_crc(self) -> None:
        payload = bytes.fromhex("01 06 00 00 00 01")
        self.assertEqual(append_crc(payload), bytes.fromhex("01 06 00 00 00 01 48 0A"))

    def test_manual_absolute_position_read_frame_crc(self) -> None:
        payload = bytes.fromhex("01 03 00 16 00 02")
        self.assertEqual(crc16(payload), 0xCF25)
        self.assertEqual(append_crc(payload), bytes.fromhex("01 03 00 16 00 02 25 CF"))

    def test_invalid_crc_is_rejected(self) -> None:
        with self.assertRaises(CrcError):
            validate_crc(bytes.fromhex("01 03 00 16 00 02 00 00"))


if __name__ == "__main__":
    unittest.main()
