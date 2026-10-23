"""Verify that hotspot preflight cannot modify or reuse the uplink radio."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('robot_hotspot', Path(__file__).with_name('robot-hotspot.py'))
hotspot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hotspot)


class HotspotIsolationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.net = self.root / 'net'
        self.net.mkdir()
        for name in ('phy0', 'phy1'):
            (self.root / name).mkdir()
        self.interface('wlo1', 'phy0')
        self.interface('usbwifi', 'phy1')
        self.calls = []
        self.link = 'Not connected.\n'
        self.addresses = [{'addr_info': []}]
        self.capabilities = 'Supported interface modes:\n\t* managed\n\t* AP\n\t* 2437 MHz [6] (20.0 dBm)\n'

    def interface(self, name, phy):
        path = self.net / name
        path.mkdir()
        (path / 'phy80211').symlink_to(self.root / phy)

    def runner(self, *args):
        self.calls.append(args)
        if args[:2] == ('iw', 'dev') and args[-1] == 'link':
            return SimpleNamespace(stdout=self.link)
        if args[:3] == ('ip', '-j', 'address'):
            return SimpleNamespace(stdout=json.dumps(self.addresses))
        if args[:2] == ('iw', 'phy') and args[-1] == 'info':
            return SimpleNamespace(stdout=self.capabilities)
        raise AssertionError(f'Unexpected or mutating command: {args}')

    def validate(self, name='usbwifi'):
        return hotspot.validate_radio(name, 'wlo1', self.net, self.runner)

    def test_same_radio_rejected_before_any_commands(self):
        self.interface('virtual', 'phy0')
        for name in ('wlo1', 'virtual'):
            with self.assertRaisesRegex(ValueError, 'protected'):
                self.validate(name)
        self.assertEqual(self.calls, [])

    def test_missing_or_invalid_adapter_rejected_before_commands(self):
        for name in ('', 'missing', '../wlo1'):
            with self.assertRaises(ValueError):
                self.validate(name)
        self.assertEqual(self.calls, [])

    def test_protected_radio_must_be_identifiable(self):
        (self.net / 'wlo1' / 'phy80211').unlink()
        with self.assertRaises(ValueError):
            self.validate()
        self.assertEqual(self.calls, [])

    def test_connected_secondary_radio_rejected(self):
        self.link = 'Connected to 01:02:03:04:05:06 (on usbwifi)\n'
        with self.assertRaisesRegex(ValueError, 'already in use'):
            self.validate()

    def test_addressed_secondary_radio_rejected(self):
        self.addresses = [{'addr_info': [{'local': '10.0.0.5'}]}]
        with self.assertRaisesRegex(ValueError, 'already in use'):
            self.validate()

    def test_existing_ap_on_upstream_rejected(self):
        self.interface('lr-ap0', 'phy0')
        with self.assertRaisesRegex(ValueError, 'another radio'):
            self.validate()

    def test_unsupported_or_restricted_ap_rejected(self):
        self.capabilities = 'Supported interface modes:\n\t* managed\n'
        with self.assertRaisesRegex(ValueError, 'AP mode'):
            self.validate()
        self.capabilities = '* AP\n* 2437 MHz [6] (no IR)\n'
        with self.assertRaisesRegex(ValueError, 'cannot broadcast'):
            self.validate()

    def test_independent_unused_ap_allowed_with_read_only_queries(self):
        self.assertEqual(self.validate(), 'phy1')
        self.assertFalse(any('wlo1' in args for args in self.calls))

    def test_entrypoint_stops_before_serving_when_preflight_fails(self):
        with patch.object(hotspot, 'validate_radio', side_effect=ValueError('blocked')), patch.object(hotspot, 'serve') as serve:
            self.assertEqual(hotspot.main(), 78)
            serve.assert_not_called()

    def test_check_mode_never_runs_service(self):
        with patch.object(hotspot, 'validate_radio', return_value='phy1'), patch.object(hotspot, 'serve') as serve, patch.object(hotspot.sys, 'argv', ['robot-hotspot.py', '--check']):
            self.assertEqual(hotspot.main(), 0)
            serve.assert_not_called()

    def test_standalone_allows_unused_onboard_radio(self):
        self.assertEqual(hotspot.validate_radio('wlo1', 'wlo1', self.net, self.runner, mode='standalone'), 'phy0')

    def test_standalone_cannot_take_connected_radio(self):
        self.link = 'Connected to 01:02:03:04:05:06 (on wlo1)'
        with self.assertRaisesRegex(ValueError, 'already in use'):
            hotspot.validate_radio('wlo1', 'wlo1', self.net, self.runner, mode='standalone')

    def test_standalone_cannot_take_addressed_radio(self):
        self.addresses = [{'addr_info': [{'local': '192.168.3.22'}]}]
        with self.assertRaisesRegex(ValueError, 'already in use'):
            hotspot.validate_radio('wlo1', 'wlo1', self.net, self.runner, mode='standalone')

    def test_decimal_frequency_output_is_supported(self):
        self.capabilities = '* AP' + chr(10) + '* 2437.0 MHz [6] (20.0 dBm)'
        self.assertEqual(self.validate(), 'phy1')

    def test_unknown_mode_rejected_without_commands(self):
        with self.assertRaises(ValueError):
            hotspot.validate_radio('wlo1', 'wlo1', self.net, self.runner, mode='dedicated')
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
