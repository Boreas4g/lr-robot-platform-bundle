"""Load per-appliance parameters without constructing or starting hardware."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from bookarm.devices.arm.service import ArmDeviceConfig
from bookarm.devices.camera.service import D435BookSpineLocatorConfig
from bookarm.service.composition import _load_device_config


class ApplianceConfigTests(unittest.TestCase):
    def test_external_device_config_and_numeric_joint_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "devices/arm.json"
            path.parent.mkdir()
            path.write_text(json.dumps({"can_interface": "can1", "joint_offsets": {"1": 0.125}, "tcp_offset": [0, 0, 0, 0, 0, 0]}))
            with patch.dict(os.environ, {"LR_BOOKARM_CONFIG_DIR": directory}):
                config = _load_device_config("arm", ArmDeviceConfig())
            self.assertEqual(config.can_interface, "can1")
            self.assertEqual(config.joint_offsets, {1: 0.125})
            self.assertIsInstance(config.tcp_offset, tuple)

    def test_camera_serial_from_external_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "devices/camera.json"
            path.parent.mkdir()
            path.write_text(json.dumps({"serial": "NEW-CAMERA", "fps": 6}))
            with patch.dict(os.environ, {"LR_BOOKARM_CONFIG_DIR": directory}):
                config = _load_device_config("camera", D435BookSpineLocatorConfig())
            self.assertEqual(config.serial, "NEW-CAMERA")

    def test_missing_appliance_config_and_misspelled_fields_fail(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"LR_BOOKARM_CONFIG_DIR": directory}):
            with self.assertRaisesRegex(ValueError, "Missing appliance"):
                _load_device_config("camera", D435BookSpineLocatorConfig())
            path = Path(directory) / "devices/camera.json"
            path.parent.mkdir()
            path.write_text('{"serial_number_typo":"wrong"}')
            with self.assertRaisesRegex(ValueError, "Unknown camera"):
                _load_device_config("camera", D435BookSpineLocatorConfig())

    def test_studio_writes_same_external_calibration_file_as_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            code = "from bookarm.service.studio import DEFAULT_CAMERA_TRANSFORM_PATH; print(DEFAULT_CAMERA_TRANSFORM_PATH)"
            result = subprocess.run([sys.executable, "-c", code], env={**os.environ, "LR_BOOKARM_CONFIG_DIR": directory},
                                    check=True, text=True, capture_output=True)
            self.assertEqual(result.stdout.strip(), str(Path(directory) / "calibration/camera_to_base.json"))


if __name__ == "__main__":
    unittest.main()
