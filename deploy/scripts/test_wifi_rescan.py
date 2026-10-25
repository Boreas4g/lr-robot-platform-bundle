"""Exercise scan recovery without changing host networking."""
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid

spec = importlib.util.spec_from_file_location('agent', Path(__file__).parents[1] / 'libexec/lr-network-agent.py')
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)
spec = importlib.util.spec_from_file_location('boot_scan', Path(__file__).parents[1] / 'libexec/lr-wifi-boot-scan.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


class RescanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = a.ScanCache(self.tmp.name)
        self.old = [{'ssid': 'Old', 'security': 'wpa-psk', 'signal': 50, 'frequency': 2412}]
        self.cache.save('wlo1', self.old)
        self.nm = Mock()
        self.nm.status.return_value = {'wireless_enabled': True, 'hardware_enabled': True,
            'devices': [{'interface': 'wlo1', 'mode': 'ap', 'ssid': '机器人'}]}
        self.nm.current_profile.return_value = 'original-profile'
        self.nm.checkpoint.return_value = 'checkpoint'
        self.nm.profile_ready.return_value = True
        self.nm.scan.return_value = {'networks': []}
        self.recovery = Path(self.tmp.name) / 'recovery.json'
        self.c = a.NetworkController(lambda: self.nm, cache=self.cache, sleep=lambda _: None, recovery_file=self.recovery)
        self.thread = patch.object(a.threading, 'Thread').start()
        self.addCleanup(patch.stopall)

    def schedule(self):
        result = self.c.scan('wlo1', True, True, str(uuid.uuid4()))
        return result['scan_operation']

    def test_page_read_only_uses_persisted_snapshot(self):
        self.assertEqual(self.c.scan('wlo1')['networks'], self.old)
        self.nm.scan.assert_not_called()
        self.nm.disconnect_for_scan.assert_not_called()

    def test_success_restores_even_with_no_browsers_connected(self):
        op = self.schedule()
        self.nm.disconnect_for_scan.assert_not_called()
        self.c._rescan(op)
        self.assertEqual(self.c.scan_operation['phase'], 'complete')
        self.assertEqual(self.cache.read('wlo1')['networks'], [])
        self.nm.checkpoint.assert_called_once_with('wlo1', 90)
        self.nm.rollback.assert_called_once_with('checkpoint')
        self.nm.destroy.assert_called_once_with('checkpoint')
        self.assertFalse(self.recovery.exists())
        calls = [call[0] for call in self.nm.mock_calls]
        self.assertLess(calls.index('checkpoint'), calls.index('disconnect_for_scan'))
        self.assertLess(calls.index('disconnect_for_scan'), calls.index('scan'))
        self.assertLess(calls.index('scan'), calls.index('rollback'))

    def test_scan_error_preserves_old_timestamp_and_restores(self):
        before = self.cache.read('wlo1')
        op = self.schedule()
        self.nm.scan.side_effect = RuntimeError('provider secret')
        self.c._rescan(op)
        self.assertEqual(self.cache.read('wlo1'), before)
        self.assertEqual(self.c.scan_operation['phase'], 'failed')
        self.nm.rollback.assert_called_once()
        self.assertNotIn('provider secret', str(self.c.scan_operation))

    def test_checkpoint_failure_never_disconnects(self):
        op = self.schedule()
        self.nm.checkpoint.side_effect = RuntimeError()
        self.c._rescan(op)
        self.nm.disconnect_for_scan.assert_not_called()
        self.nm.rollback.assert_not_called()

    def test_failed_restore_leaves_nm_timer_and_blocks_other_changes(self):
        op = self.schedule()
        self.nm.rollback.side_effect = RuntimeError()
        self.nm.profile_ready.return_value = False
        self.c._rescan(op)
        self.assertEqual(self.c.scan_operation['phase'], 'recovery_required')
        self.nm.destroy.assert_not_called()
        self.assertTrue(self.recovery.exists())
        with self.assertRaises(a.NetworkError):
            self.c.scan('wlo1', True, True, str(uuid.uuid4()))

    def test_worker_restart_reads_recovery_and_only_unlocks_after_original_ready(self):
        self.schedule()
        self.nm.profile_ready.return_value = False
        restarted = a.NetworkController(lambda: self.nm, cache=self.cache, recovery_file=self.recovery)
        self.assertEqual(restarted.status()['scan_operation']['phase'], 'recovery_required')
        self.nm.profile_ready.return_value = True
        self.assertEqual(restarted.status()['scan_operation']['phase'], 'failed')
        self.assertFalse(self.recovery.exists())

    def test_duplicate_requests_reuse_worker_and_other_operations_are_blocked(self):
        op = self.schedule()
        self.assertEqual(self.c.scan('wlo1', True, True, op['id'])['scan_operation']['id'], op['id'])
        self.assertEqual(self.thread.call_count, 1)
        with self.assertRaises(a.NetworkError):
            self.c.scan('wlo1', True, True, str(uuid.uuid4()))
        with self.assertRaises(a.NetworkError):
            self.c.schedule({'request_id': str(uuid.uuid4()), 'interface': 'wlo1', 'ssid': 'Target',
                             'security': 'open', 'password': '', 'acknowledged': True})

    def test_live_desktop_change_during_delay_is_not_disconnected(self):
        op = self.schedule()
        self.nm.current_profile.return_value = 'different-profile'
        self.c._rescan(op)
        self.nm.disconnect_for_scan.assert_not_called()
        self.nm.scan.assert_not_called()

    def test_unacknowledged_refresh_is_rejected(self):
        with self.assertRaises(a.NetworkError):
            self.c.scan('wlo1', True)
        self.thread.assert_not_called()

    def test_station_scan_never_disconnects_or_rolls_back(self):
        self.nm.status.return_value['devices'][0]['mode'] = 'infrastructure'
        self.c._rescan(self.schedule())
        self.nm.scan.assert_called_once_with('wlo1', True)
        self.nm.disconnect_for_scan.assert_not_called()
        self.nm.rollback.assert_not_called()


class BootScanTests(unittest.TestCase):
    def test_refuses_live_networkmanager_before_touching_radio(self):
        with patch.object(b, 'run', return_value=SimpleNamespace(stdout='active\n')) as run:
            with self.assertRaises(RuntimeError):
                b.scan_before_networkmanager('wlo1')
        self.assertEqual(run.call_count, 1)

    def test_scan_timeout_restores_original_link_state(self):
        calls = []
        def run(*args, **kwargs):
            calls.append(args)
            if args[0] == 'systemctl':
                return SimpleNamespace(stdout='inactive')
            if args[:4] == ('iw', 'dev', 'wlo1', 'info'):
                return SimpleNamespace(stdout='Interface wlo1\n\ttype managed\n')
            if args[:4] == ('iw', 'dev', 'wlo1', 'link'):
                return SimpleNamespace(stdout='Not connected.')
            if args[:2] == ('ip', '-j'):
                return SimpleNamespace(stdout='[{"flags": [], "addr_info": []}]')
            if args[:4] == ('iw', 'dev', 'wlo1', 'scan'):
                raise TimeoutError()
            return SimpleNamespace(stdout='')
        with patch.object(b, 'run', side_effect=run), patch.object(b.Path, 'exists', return_value=True):
            with self.assertRaises(TimeoutError):
                b.scan_before_networkmanager('wlo1')
        self.assertEqual(calls[-1], ('ip', 'link', 'set', 'wlo1', 'down'))

    def test_parse_unicode_security_dedup_and_hidden(self):
        text = r'''BSS aa:bb:cc:dd:ee:ff(on wlo1)
    freq: 2412
    signal: -55.00 dBm
    SSID: \xe5\x9b\xbe\xe4\xb9\xa6\xe9\xa6\x86
    RSN:
         * Authentication suites: PSK SAE
BSS aa:bb:cc:dd:ee:00(on wlo1)
    freq: 5220
    signal: -70.00 dBm
    SSID: \xe5\x9b\xbe\xe4\xb9\xa6\xe9\xa6\x86
    RSN:
         * Authentication suites: PSK
BSS aa:bb:cc:dd:ee:01(on wlo1)
    freq: 2437
    SSID: Enterprise
    RSN:
         * Authentication suites: IEEE 802.1X
BSS aa:bb:cc:dd:ee:02(on wlo1)
    freq: 2437
    SSID:
'''
        networks = b.parse_scan(text)
        self.assertEqual(len(networks), 2)
        self.assertEqual(networks[0]['ssid'], '图书馆')
        self.assertEqual(networks[0]['security'], 'wpa-psk')
        self.assertEqual(networks[1]['security'], 'unsupported')


class ScanCompletionTests(unittest.TestCase):
    def manager(self):
        nm = a.NetworkManager.__new__(a.NetworkManager)
        nm.device = Mock(return_value=('device', {}))
        nm.active = Mock(return_value={})
        nm.dbus = SimpleNamespace(Dictionary=lambda v, **_: v)
        nm.interface = Mock()
        nm.interface.return_value.GetAllAccessPoints.return_value = []
        nm.properties = Mock(side_effect=[{'LastScan': 10}, {'LastScan': 10}, {'LastScan': 11}])
        return nm

    def test_waits_for_completed_scan_instead_of_fixed_sleep(self):
        nm = self.manager()
        with patch.object(a.time, 'sleep'):
            self.assertFalse(nm.scan('wlo1', True)['cached'])
        self.assertEqual(nm.properties.call_count, 3)

    def test_scan_timeout_does_not_claim_new_results(self):
        nm = self.manager()
        nm.properties.side_effect = None
        nm.properties.return_value = {'LastScan': 10}
        with patch.object(a.time, 'sleep'), self.assertRaises(a.NetworkError):
            nm.scan('wlo1', True)
        nm.interface.return_value.GetAllAccessPoints.assert_not_called()


if __name__ == '__main__':
    unittest.main()
