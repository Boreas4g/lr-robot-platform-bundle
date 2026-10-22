"""Vehicle alignment HTTP errors should distinguish missing routes from outages."""

from __future__ import annotations

import io
import unittest
import urllib.error
from unittest.mock import patch

from bookarm.infrastructure.vehicle_align import VehicleAlignClient


class VehicleAlignHttpErrorTests(unittest.TestCase):
    def test_status_404_reports_missing_runtime_endpoint(self) -> None:
        error = urllib.error.HTTPError(
            "http://127.0.0.1:18091/status",
            404,
            "Not Found",
            {},
            io.BytesIO(b""),
        )
        client = VehicleAlignClient()

        with patch(
            "bookarm.infrastructure.vehicle_align.urllib.request.urlopen",
            side_effect=error,
        ):
            with self.assertRaisesRegex(RuntimeError, "接口不存在.*HTTP 404"):
                client.status()

    def test_move_distance_404_reports_missing_runtime_endpoint(self) -> None:
        error = urllib.error.HTTPError(
            "http://127.0.0.1:18091/move-distance",
            404,
            "Not Found",
            {},
            io.BytesIO(b""),
        )
        client = VehicleAlignClient()

        with patch(
            "bookarm.infrastructure.vehicle_align.urllib.request.urlopen",
            side_effect=error,
        ):
            with self.assertRaisesRegex(RuntimeError, "接口不存在.*HTTP 404"):
                client.move_distance("forward", 0.1)


if __name__ == "__main__":
    unittest.main()
