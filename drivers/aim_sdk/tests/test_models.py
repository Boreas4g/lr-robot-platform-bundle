import unittest

from aim_sdk.models import join_i32, signed_i16, split_i32, unsigned_i16


class ModelConversionTests(unittest.TestCase):
    def test_signed_32_bit_round_trip(self) -> None:
        for value in (0, 1, -1, 32_768, -32_768, 2_147_483_647, -2_147_483_648):
            self.assertEqual(join_i32(*split_i32(value)), value)

    def test_signed_16_bit_conversions(self) -> None:
        self.assertEqual(signed_i16(0xFFFF), -1)
        self.assertEqual(signed_i16(0x8000), -32768)
        self.assertEqual(unsigned_i16(-1), 0xFFFF)

    def test_out_of_range_position_rejected(self) -> None:
        with self.assertRaises(ValueError):
            split_i32(2_147_483_648)


if __name__ == "__main__":
    unittest.main()
