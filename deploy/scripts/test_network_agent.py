"""No real bus/network access: every switching operation uses a fake NM."""
import importlib.util
import copy
import json
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import uuid

spec = importlib.util.spec_from_file_location('network_agent', Path(__file__).parents[1] / 'libexec/lr-network-agent.py')
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


def request(**kwargs):
    return dict({'request_id': str(uuid.uuid4()), 'interface': 'wlan0', 'ssid': '图书馆 WiFi',
                 'password': 'super-secret', 'security': 'wpa-psk', 'acknowledged': True}, **kwargs)


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.nm = Mock()
        self.nm.status.return_value = {'wireless_enabled': True, 'hardware_enabled': True, 'local_url': 'http://robot.local:8000/system/network'}
        self.nm.device.return_value = ('device', {})
        self.nm.checkpoint.return_value = 'checkpoint'
        self.nm.activate.return_value = ('connection', 'active', True)
        self.nm.ready.return_value = ['10.10.0.20']
        self.nm.hotspots.return_value = [{'uuid': '8e1d12a1-b6fd-4132-9a64-dc442d22b572'}]
        self.time = 1000
        self.action = None
        self.c = a.NetworkController(lambda: self.nm, clock=lambda: self.time, sleep=self.sleep)
        self.thread = patch.object(a.threading, 'Thread').start()
        self.addCleanup(patch.stopall)

    def sleep(self, seconds):
        self.time += seconds
        if self.action and self.c.operation['phase'] == 'awaiting_confirmation':
            action, self.action = self.action, None
            action()

    def scheduled(self, data=None):
        data = data or request()
        result = self.c.schedule(data)
        self.assertNotIn('super-secret', json.dumps(result))
        return data, result

    def test_read_status_and_scheduling_do_not_activate(self):
        self.c.status()
        self.scheduled()
        self.nm.activate.assert_not_called()
        self.nm.checkpoint.assert_not_called()

    def test_retry_idempotency_and_busy_rejection(self):
        data, original = self.scheduled()
        self.assertEqual(original, self.c.schedule(data))
        with self.assertRaises(a.NetworkError):
            self.c.schedule(request())
        self.assertEqual(self.thread.call_count, 1)

    def test_confirm_on_new_address_persists(self):
        data, result = self.scheduled()
        self.action = lambda: self.c.confirm(result['id'], '::ffff:10.10.0.20')
        self.c._switch(data)
        self.assertEqual(self.c.operation['phase'], 'confirmed')
        self.nm.prefer.assert_called_once_with('connection', 'wlan0', [])
        self.nm.destroy.assert_called_once_with('checkpoint')
        self.nm.rollback.assert_not_called()
        self.assertNotIn('password', data)

    def test_unconfirmed_connection_rolls_back_and_deletes_temporary_profile(self):
        data, _ = self.scheduled()
        self.c._switch(data)
        self.assertEqual(self.c.operation['phase'], 'restored')
        self.nm.rollback.assert_called_once_with('checkpoint')
        self.nm.delete.assert_called_once_with('connection')
        self.nm.prefer.assert_not_called()

    def test_wrong_password_restores_without_secret_in_output(self):
        data, _ = self.scheduled()
        self.nm.activate.side_effect = RuntimeError('super-secret')
        self.c._switch(data)
        self.assertEqual(self.c.operation['phase'], 'restored')
        self.nm.rollback.assert_called_once()
        self.assertNotIn('super-secret', json.dumps(self.c.status()))

    def test_no_dhcp_address_restores(self):
        self.nm.ready.return_value = []
        data, _ = self.scheduled()
        self.c._switch(data)
        self.assertEqual(self.c.operation['phase'], 'restored')
        self.assertLess(self.time, 1100)

    def test_old_hotspot_cannot_confirm_target_network(self):
        data, result = self.scheduled()
        def action():
            with self.assertRaises(a.NetworkError):
                self.c.confirm(result['id'], '192.168.4.1')
        self.action = action
        self.c._switch(data)
        self.nm.prefer.assert_not_called()
        self.assertEqual(self.c.operation['phase'], 'restored')

    def test_failed_manual_rollback_keeps_nm_rollback_timer(self):
        self.nm.rollback.side_effect = RuntimeError('bus temporarily unavailable')
        data, _ = self.scheduled()
        self.c._switch(data)
        self.nm.destroy.assert_not_called()
        self.nm.delete.assert_not_called()
        self.assertEqual(self.c.operation['phase'], 'recovery_required')
        with self.assertRaises(a.NetworkError):
            self.c.schedule(request())

    def test_failure_to_create_checkpoint_never_switches(self):
        self.nm.checkpoint.side_effect = RuntimeError('unavailable')
        data, _ = self.scheduled()
        self.c._switch(data)
        self.nm.activate.assert_not_called()

    def test_failed_save_restores_preferences_before_device_rollback(self):
        def prefer(path, interface, journal):
            journal.append(('previous', {'connection': {'autoconnect-priority': 999}}))
            raise RuntimeError('save failed')
        self.nm.prefer.side_effect = prefer
        data, result = self.scheduled()
        self.action = lambda: self.c.confirm(result['id'], '10.10.0.20')
        self.c._switch(data)
        self.nm.restore_preferences.assert_called_once()
        self.nm.rollback.assert_called_once_with('checkpoint')
        self.assertEqual(self.c.operation['phase'], 'restored')

    def test_confirmation_uses_current_address_not_stale_dhcp(self):
        data, result = self.scheduled()
        def action():
            self.nm.ready.return_value = ['10.10.0.21']
            with self.assertRaises(a.NetworkError):
                self.c.confirm(result['id'], '10.10.0.20')
        self.action = action
        self.c._switch(data)
        self.nm.prefer.assert_not_called()

    def test_hotspot_restore_only_known_profile(self):
        data = request(hotspot_uuid='8e1d12a1-b6fd-4132-9a64-dc442d22b572')
        for key in ['ssid', 'password', 'security']:
            data.pop(key)
        _, result = self.scheduled(data)
        self.assertIn('192.168.4.1', result['local_url'])

    def test_rejects_bad_parameters_without_accessing_network(self):
        bad = [request(acknowledged=False), request(interface='; reboot'), request(ssid='你'*12),
               request(password='short'), request(security='enterprise'), request(command='sh'),
               request(password='hello\nworld'), request(hidden='yes')]
        for payload in bad:
            with self.assertRaises(a.NetworkError):
                self.c.schedule(payload)
        self.nm.device.assert_not_called()

    def test_open_network_and_punctuation_are_valid(self):
        self.assertEqual(a.checked_request(request(ssid='图书馆:5G; main', password='', security='open'))['security'], 'open')
        self.assertEqual(a.checked_request(request(password='a$;"\\ hello'))['password'], 'a$;"\\ hello')

    def test_ap_scan_never_requests_active_rescan(self):
        manager = a.NetworkManager.__new__(a.NetworkManager)
        manager.device = Mock(return_value=('device', {'ActiveConnection': 'active'}))
        manager.active = Mock(return_value={'Connection': 'connection'})
        manager.settings = Mock(return_value={'802-11-wireless': {'mode': 'ap'}})
        iface = Mock()
        iface.GetAllAccessPoints.return_value = []
        manager.interface = Mock(return_value=iface)
        self.assertTrue(manager.scan('wlan0', True)['cached'])
        iface.RequestScan.assert_not_called()


class ProfileTests(unittest.TestCase):
    def test_confirmed_profile_priority_preserves_secrets_and_unrelated_profiles(self):
        manager = a.NetworkManager.__new__(a.NetworkManager)
        manager.dbus = SimpleNamespace(Int32=int, UInt32=int, Boolean=bool, Dictionary=lambda v, **_: v)
        profiles = {name: {'connection': {'interface-name': iface, 'autoconnect-priority': priority},
                           '802-11-wireless': {'mode': mode},
                           '802-11-wireless-security': {'key-mgmt': 'wpa-psk'}}
                    for name, iface, priority, mode in [
                        ('target', 'wlan0', 0, 'infrastructure'),
                        ('previous', 'wlan0', 999, 'infrastructure'),
                        ('normal', 'wlan0', 100, 'infrastructure'),
                        ('other-device', 'wlan1', 999, 'infrastructure'),
                        ('hotspot', 'wlan0', 999, 'ap'),
                    ]}
        interfaces = {}
        for name, value in profiles.items():
            interface = Mock()
            interface.GetSettings.side_effect = lambda v=value, **_: copy.deepcopy(v)
            interface.GetSecrets.return_value = {'802-11-wireless-security': {'psk': 'preserved-secret'}}
            interfaces[name] = interface
        settings = Mock()
        settings.ListConnections.return_value = list(profiles)
        manager.interface = lambda path, _: interfaces[path] if path in interfaces else settings
        manager.settings = lambda path: copy.deepcopy(profiles[path])
        journal = []
        manager.prefer('target', 'wlan0', journal)
        target = interfaces['target'].Update2.call_args.args[0]
        previous = interfaces['previous'].Update2.call_args.args[0]
        self.assertEqual(target['connection']['autoconnect-priority'], 998)
        self.assertEqual(previous['connection']['autoconnect-priority'], 997)
        self.assertTrue(target['connection']['autoconnect'])
        for values in [target, previous]:
            self.assertEqual(values['802-11-wireless-security']['psk'], 'preserved-secret')
        interfaces['normal'].Update2.assert_not_called()
        interfaces['other-device'].Update2.assert_not_called()
        interfaces['hotspot'].Update2.assert_not_called()
        manager.restore_preferences(journal)
        self.assertEqual(interfaces['previous'].Update2.call_args.args[0]['connection']['autoconnect-priority'], 999)
        manager.prefer('hotspot', 'wlan0', [])
        hotspot = interfaces['hotspot'].Update2.call_args.args[0]
        self.assertEqual(hotspot['connection']['autoconnect-priority'], 999)
        self.assertTrue(hotspot['connection']['autoconnect'])
        self.assertEqual(hotspot['802-11-wireless-security']['psk'], 'preserved-secret')


if __name__ == '__main__':
    unittest.main()
