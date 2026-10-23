"""Hardware-free migration checks. No system service or network is changed."""
import copy
import io
from pathlib import Path
import pwd
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import robot_setup as setup
import robot_bootstrap as bootstrap


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.baseline = self.root / "baseline"
        self.baseline.mkdir()
        configs = {"camera": {"serial": "OLD", "fps": 6},
                   "arm": {"backend": "socketcan", "can_interface": "can0", "can_bitrate": 1000000},
                   "lift": {"port": "/dev/lift_port"}, "rod": {"port": "/dev/rodmotor"}}
        for name, value in configs.items():
            setup.write_private(self.baseline / f"bookarm/devices/{name}.json", setup.json_text(value))
        setup.write_private(self.baseline / "robot/map-registry.json", setup.json_text({"maps": {"MAP-SITE": {}}}))
        self.user = next(account.pw_name for account in pwd.getpwall() if account.pw_uid >= 1000 and account.pw_uid < 60000)
        self.profile = {"schema": 1, "robot_id": "LR-02", "robot_name": "图书馆机器人", "service_user": self.user,
                        "baseline": str(self.baseline), "camera_serial": "CAMERA02", "camera": {}, "arm": {}, "lift": {}, "rod": {},
                        "devices": {role: {"vid": "1a86", "pid": "55d4", "serial": f"DEVICE{i}", "id_path": ""}
                                    for i, role in enumerate(setup.ROLES)},
                        "battery": {"serial": "", "capacity_ah": 20, "nominal_voltage_v": 24},
                        "hotspot": {"enabled": True, "interface": "wlan1", "mac": "02:11:22:33:44:55",
                                    "ssid": "图书馆机器人", "password": "12345678", "address": "192.168.4.1/24", "channel": 6},
                        "bluetooth_name": "图书馆机器人", "operator_password": "123456", "active_map_id": "MAP-SITE",
                        **{key: True for key in ("hardware_autostart", "calibration_reviewed", "map_site_reviewed", "site_start_confirmed")}}

    def test_valid_complete_profile(self):
        setup.validate(self.profile)

    def test_six_digit_website_password_does_not_become_hotspot_password(self):
        self.profile["hotspot"]["password"] = "123456"
        with self.assertRaisesRegex(setup.SetupError, "WPA2"):
            setup.validate(self.profile)

    def test_fixed_address_cannot_silently_drift(self):
        self.profile["hotspot"]["address"] = "10.42.0.1/24"
        with self.assertRaisesRegex(setup.SetupError, "192.168.4.1"):
            setup.validate(self.profile)

    def test_hardware_autostart_requires_reviewed_site_and_calibration(self):
        for key in ("calibration_reviewed", "map_site_reviewed", "site_start_confirmed"):
            profile = copy.deepcopy(self.profile)
            profile[key] = False
            with self.assertRaisesRegex(setup.SetupError, "硬件自启前"):
                setup.validate(profile)

    def test_duplicate_device_and_unknown_map_are_rejected(self):
        profile = copy.deepcopy(self.profile)
        profile["devices"]["laser_back"] = profile["devices"]["laser_port"]
        with self.assertRaisesRegex(setup.SetupError, "同一硬件"):
            setup.validate(profile)
        self.profile["active_map_id"] = "MAP-WRONG-SITE"
        with self.assertRaisesRegex(setup.SetupError, "地图注册表"):
            setup.validate(self.profile)

    def test_unknown_hardware_fields_are_not_ignored(self):
        self.profile["camera"]["framez"] = 30
        with self.assertRaisesRegex(setup.SetupError, "字段"):
            setup.validate(self.profile)

    def test_hardware_off_profile_has_no_boot_hardware_owners(self):
        self.profile["hardware_autostart"] = False
        units = setup.enabled_units(self.profile)
        self.assertTrue(set(setup.CORE).issubset(units))
        self.assertFalse(set(setup.HARDWARE).intersection(units))
        self.assertNotIn("lr-robot-mapping.service", units)
        self.assertNotIn('SUBSYSTEM=="tty"', setup.udev_rules(self.profile))

    def test_network_keyfile_preserves_fixed_subnet_and_password(self):
        value = setup.hotspot_keyfile(self.profile, "test-uuid")
        for expected in ("mode=ap", "method=shared", "address1=192.168.4.1/24", "ssid=图书馆机器人", "psk=12345678", "never-default=true"):
            self.assertIn(expected, value)
        self.assertNotIn("123456\n", value)

    def test_udev_selectors_and_realsense_permissions(self):
        self.profile["devices"]["imu_port"].update(serial="", id_path="pci-0000:00:14.0-usb-0:2.2:1.0")
        value = setup.udev_rules(self.profile)
        self.assertIn('ENV{ID_PATH}=="pci-0000:00:14.0-usb-0:2.2:1.0"', value)
        self.assertIn('SYMLINK+="imu_port"', value)
        self.assertIn('ATTR{product}=="*RealSense*"', value)
        self.assertNotIn('MODE="0666"', value)

    def test_rendered_units_bind_private_backend_and_explicit_calibration(self):
        self.profile["arm"] = {"can_interface": "can1", "can_bitrate": 500000}
        self.profile["battery"]["serial"] = "BATTERY02"
        units = setup.render_units(self.profile)
        self.assertIn("--host 127.0.0.1 --port 8080", units["lr-control-api.service"])
        self.assertIn(".venv-api/bin/uvicorn", units["lr-control-api.service"])
        self.assertIn("--camera-calibration /etc/lr-bookarm/config/calibration/camera_to_base.json", units["lr-bookarm-takeout.service"])
        self.assertIn("can1 500000", units["lr-bookarm-can.service"])
        self.assertIn("--serial BATTERY02", units["lr-xt369-usb.service"])
        self.assertIn("--port 8000", units["lr-web-static.service"])
        self.assertNotIn("8001", "".join(units.values()))

    def test_live_robot_apply_refuses_before_bootstrap_or_other_mutation(self):
        with patch.object(setup.os, "geteuid", return_value=0), patch.object(setup, "run", return_value=SimpleNamespace(returncode=0)) as run, \
                patch.object(bootstrap, "bootstrap") as install:
            with self.assertRaisesRegex(setup.SetupError, "正在运行"):
                setup.apply_profile(self.profile, "unused", install_deps=True, start=True)
        install.assert_not_called()
        self.assertEqual(run.call_args.args[0][:3], ["systemctl", "is-active", "--quiet"])
        self.assertEqual(run.call_count, 1)

    def test_preflight_uses_only_sysfs_and_readonly_iw_queries(self):
        hw = {"realsense_serials": ["CAMERA02"], "wifi": [{"interface": "wlan1", "mac": "02:11:22:33:44:55", "phy": "phy1"}],
              "serial_devices": [{"ID_VENDOR_ID": d["vid"], "ID_MODEL_ID": d["pid"], "ID_SERIAL_SHORT": d["serial"]}
                                 for d in self.profile["devices"].values()]}
        with patch.object(setup, "scan", return_value=hw), patch.object(setup.shutil, "which", side_effect=lambda command: "/usr/sbin/iw" if command == "iw" else None), \
                patch.object(setup, "run", return_value=SimpleNamespace(stdout="Supported interface modes:\n\t * managed\n\t * AP\nBand 1:\n * 2437 MHz [6] (20.0 dBm)\n")) as run:
            setup.check_hardware_bindings(self.profile)
            run.assert_called_once_with(["iw", "phy", "phy1", "info"], capture=True)
        hw["realsense_serials"] = []
        with patch.object(setup, "scan", return_value=hw), self.assertRaisesRegex(setup.SetupError, "相机未接入"):
            setup.check_hardware_bindings(self.profile)

    def test_env_round_trip_and_private_file_mode(self):
        path = self.root / "private.env"
        values = {"NAME": "图书馆 机器人", "PASSWORD": "a'$()#& value"}
        setup.write_private(path, setup.env_text(values))
        self.assertEqual(setup.read_env(path), values)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def manifest(self):
        files = {str(p.relative_to(self.baseline)): setup.digest(p) for p in self.baseline.rglob("*") if p.is_file()}
        setup.write_private(self.baseline / "manifest.json", setup.json_text({"schema": 1, "files": files}))

    def test_baseline_tamper_is_detected(self):
        self.manifest()
        setup.verify_baseline(self.baseline, verify_source=False)
        (self.baseline / "bookarm/devices/camera.json").write_text("{}")
        with self.assertRaisesRegex(setup.SetupError, "基线校验失败"):
            setup.verify_baseline(self.baseline, verify_source=False)

    def test_baseline_cannot_escape_its_directory(self):
        outside = self.root / "outside"
        outside.write_text("data")
        setup.write_private(self.baseline / "manifest.json", setup.json_text({"schema": 1, "files": {"../outside": setup.digest(outside)}}))
        with self.assertRaisesRegex(setup.SetupError, "基线校验失败"):
            setup.verify_baseline(self.baseline, verify_source=False)

    def test_pack_includes_approved_sources_and_baseline_only(self):
        source = self.root / "deploy/example.py"
        setup.write_private(source, "print('test')\n")
        setup.write_private(self.root / ".env", "PRIVATE=yes")
        setup.write_private(self.baseline / "versions/source.json", setup.json_text({"deploy/example.py": setup.digest(source)}))
        self.manifest()
        destination = self.root / "robot.tar.gz"
        with patch.object(setup, "ROOT", self.root), patch("sys.stdout", new_callable=io.StringIO):
            setup.pack(self.baseline, destination)
        with tarfile.open(destination) as archive:
            names = archive.getnames()
        self.assertIn("lr-robot-platform-bundle/deploy/example.py", names)
        self.assertIn("lr-robot-platform-bundle/.local-deploy/migration-baseline/manifest.json", names)
        self.assertFalse(any(Path(name).name == ".env" for name in names))
        self.assertTrue(Path(str(destination) + ".sha256").exists())
        self.assertEqual(destination.stat().st_mode & 0o777, 0o600)

    def test_export_from_archive_without_git_uses_original_source_list(self):
        source = self.root / "deploy/example.py"
        setup.write_private(source, "print('test')\n")
        setup.write_private(self.root / ".local-deploy/migration-baseline/versions/source.json",
                            setup.json_text({"deploy/example.py": "old-checksum"}))
        setup.write_private(self.root / "deploy/private-new-file.txt", "not part of approved sources")
        with patch.object(setup, "ROOT", self.root), patch.object(setup, "run", return_value=SimpleNamespace(returncode=128)):
            self.assertEqual(setup.source_files(), {"deploy/example.py": setup.digest(source)})

    def test_apt_service_policy_is_restored_after_error(self):
        policy = self.root / "policy-rc.d"
        policy.write_text("#!/bin/sh\nexit 0\n")
        policy.chmod(0o750)
        with patch.object(bootstrap, "Path", return_value=policy):
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                with bootstrap.no_service_restarts():
                    self.assertIn("exit 101", policy.read_text())
                    raise RuntimeError("interrupted")
        self.assertIn("exit 0", policy.read_text())
        self.assertEqual(policy.stat().st_mode & 0o777, 0o750)


if __name__ == "__main__":
    unittest.main()
