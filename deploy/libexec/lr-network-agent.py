#!/usr/bin/python3
"""Private NetworkManager bridge. Startup/GET never change network connections.

Only explicit authenticated API requests schedule changes. NetworkManager owns
the rollback timer so recovery still works if this agent or the API crashes.
Passwords go over D-Bus, never command-line arguments, logs or response bodies.
"""
from __future__ import annotations

import argparse
import copy
import ipaddress
import json
import os
from pathlib import Path
import re
import socketserver
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler

NM = 'org.freedesktop.NetworkManager'
BASE = '/org/freedesktop/NetworkManager'
PROPS = 'org.freedesktop.DBus.Properties'
ROLLBACK_SECONDS = 300
SWITCH_DELAY = 5
BUSY = {'scheduled', 'connecting', 'awaiting_confirmation', 'confirming', 'restoring'}


class NetworkError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def checked_request(data):
    if not isinstance(data, dict) or set(data) - {'request_id', 'interface', 'ssid', 'password', 'security', 'hidden', 'hotspot_uuid', 'acknowledged'}:
        raise NetworkError('网络请求字段不合法')
    if data.get('acknowledged') is not True:
        raise NetworkError('请先确认切换期间的重新连接步骤')
    try:
        uuid.UUID(data.get('request_id', ''))
    except (ValueError, TypeError, AttributeError):
        raise NetworkError('切换请求编号不合法') from None
    if not isinstance(data.get('interface'), str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,15}', data['interface']):
        raise NetworkError('请选择无线网卡')
    if data.get('hotspot_uuid'):
        try:
            uuid.UUID(data['hotspot_uuid'])
        except (ValueError, TypeError, AttributeError):
            raise NetworkError('热点配置编号不合法') from None
        if any(data.get(key) for key in ('ssid', 'password', 'security', 'hidden')):
            raise NetworkError('恢复热点请求不能包含 Wi-Fi 密码或网络参数')
        return dict(data)
    ssid, password = data.get('ssid'), data.get('password', '')
    if not isinstance(ssid, str) or not 1 <= len(ssid.encode('utf-8')) <= 32 or any(ord(c) < 32 or ord(c) == 127 for c in ssid):
        raise NetworkError('Wi-Fi 名称必须为 1–32 字节，不能包含控制字符')
    if not isinstance(password, str) or any(ord(c) < 32 or ord(c) == 127 for c in password):
        raise NetworkError('Wi-Fi 密码格式不合法')
    if not isinstance(data.get('hidden', False), bool):
        raise NetworkError('隐藏网络选项不合法')
    security = data.get('security')
    if security not in {'open', 'wpa-psk', 'sae'}:
        raise NetworkError('目前支持开放网络和 WPA/WPA2/WPA3 个人网络；企业认证需要管理员配置')
    if security == 'open' and password:
        raise NetworkError('开放网络不需要密码')
    if security == 'wpa-psk' and not (8 <= len(password.encode('utf-8')) <= 63 or re.fullmatch(r'[0-9a-fA-F]{64}', password)):
        raise NetworkError('WPA/WPA2 密码需要 8–63 字节或 64 位十六进制密钥')
    if security == 'sae' and not 1 <= len(password.encode('utf-8')) <= 63:
        raise NetworkError('WPA3 密码需要 1–63 字节')
    return dict(data)


class NetworkManager:
    def __init__(self):
        import dbus
        self.dbus = dbus
        # Each worker/request creates its own bus connection. No shared GLib loop.
        self.bus = dbus.SystemBus(private=True)
        self.manager = self.interface(BASE, NM)

    def interface(self, path, name):
        return self.dbus.Interface(self.bus.get_object(NM, path), name)

    def properties(self, path, name):
        return self.interface(path, PROPS).GetAll(name, timeout=10)

    def device(self, name):
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,15}', name):
            raise NetworkError('无线网卡名称不合法')
        path = self.manager.GetDeviceByIpIface(name, timeout=10)
        values = self.properties(path, NM + '.Device')
        if int(values['DeviceType']) != 2 or not values.get('Managed'):
            raise NetworkError('该接口不是由 NetworkManager 管理的无线网卡')
        return path, values

    def active(self, path):
        return self.properties(path, NM + '.Connection.Active') if str(path) != '/' else {}

    def settings(self, path):
        return self.interface(path, NM + '.Settings.Connection').GetSettings(timeout=10)

    @staticmethod
    def ssid(value):
        return bytes(value).decode('utf-8', errors='replace') if value else ''

    def ips(self, device):
        path = device.get('Ip4Config', '/')
        if str(path) == '/':
            return []
        return [str(item['address']) for item in self.properties(path, NM + '.IP4Config').get('AddressData', [])]

    def hotspots(self, interface):
        result = []
        for path in self.interface(BASE + '/Settings', NM + '.Settings').ListConnections(timeout=10):
            values = self.settings(path)
            connection, wifi, ipv4 = (values.get(key, {}) for key in ('connection', '802-11-wireless', 'ipv4'))
            if wifi.get('mode') != 'ap' or connection.get('interface-name', interface) != interface:
                continue
            addresses = ipv4.get('address-data', [])
            if not any(str(item.get('address')) == '192.168.4.1' and int(item.get('prefix', 0)) == 24 for item in addresses):
                continue
            result.append({'uuid': str(connection['uuid']), 'ssid': self.ssid(wifi.get('ssid')), 'path': str(path)})
        return result

    def status(self):
        root = self.properties(BASE, NM)
        devices = []
        for path in self.manager.GetDevices(timeout=10):
            d = self.properties(path, NM + '.Device')
            if int(d['DeviceType']) != 2:
                continue
            active = self.active(d.get('ActiveConnection', '/'))
            values = self.settings(active['Connection']) if active else {}
            wifi = values.get('802-11-wireless', {})
            name = str(d['Interface'])
            devices.append({'interface': name, 'managed': bool(d['Managed']), 'state': int(d['State']),
                            'mode': str(wifi.get('mode', 'disconnected')), 'ssid': self.ssid(wifi.get('ssid')),
                            'addresses': self.ips(d), 'hotspots': [{k: v for k, v in h.items() if k != 'path'} for h in self.hotspots(name)]})
        local_url = ''
        try:
            avahi = self.dbus.Interface(self.bus.get_object('org.freedesktop.Avahi', '/'), 'org.freedesktop.Avahi.Server')
            hostname = str(avahi.GetHostNameFqdn(timeout=3))
            if re.fullmatch(r'[a-zA-Z0-9.-]+\.local', hostname):
                local_url = f'http://{hostname}:8000/system/network'
        except self.dbus.DBusException:
            pass
        return {'wireless_enabled': bool(root.get('WirelessEnabled')), 'hardware_enabled': bool(root.get('WirelessHardwareEnabled')),
                'devices': devices, 'local_url': local_url, 'rollback_seconds': ROLLBACK_SECONDS, 'switch_delay': SWITCH_DELAY}

    def scan(self, interface, refresh=False):
        path, device = self.device(interface)
        active = self.active(device.get('ActiveConnection', '/'))
        current = self.settings(active['Connection']).get('802-11-wireless', {}) if active else {}
        # Off-channel scanning in AP mode can disrupt associated clients. Show
        # NM's cached results and offer manual SSID entry instead.
        ap_mode = current.get('mode') == 'ap'
        if refresh and not ap_mode:
            self.interface(path, NM + '.Device.Wireless').RequestScan(self.dbus.Dictionary({}, signature='sv'), timeout=10)
            time.sleep(2)
        networks = {}
        for ap in self.interface(path, NM + '.Device.Wireless').GetAllAccessPoints(timeout=10):
            a = self.properties(ap, NM + '.AccessPoint')
            ssid = self.ssid(a.get('Ssid'))
            if not ssid:
                continue
            flags = int(a.get('WpaFlags', 0)) | int(a.get('RsnFlags', 0))
            security = 'wpa-psk' if flags & 0x100 else 'sae' if flags & 0x400 else 'unsupported' if flags or int(a.get('Flags', 0)) & 1 else 'open'
            key = ssid, security
            item = {'ssid': ssid, 'security': security, 'signal': int(a.get('Strength', 0)), 'frequency': int(a.get('Frequency', 0))}
            if key not in networks or item['signal'] > networks[key]['signal']:
                networks[key] = item
        return {'networks': sorted(networks.values(), key=lambda a: -a['signal']), 'cached': ap_mode,
                'message': '当前网卡正在提供热点，仅显示缓存网络；未列出时请手动填写 Wi-Fi 名称。' if ap_mode else ''}

    def checkpoint(self, interface):
        path, _ = self.device(interface)
        # Flags 0 restrict rollback to this existing device and do not globally
        # delete profiles created by unrelated desktop/network operations.
        return str(self.manager.CheckpointCreate([path], self.dbus.UInt32(ROLLBACK_SECONDS), self.dbus.UInt32(0), timeout=10))

    def activate(self, data):
        d = self.dbus
        path, _ = self.device(data['interface'])
        if data.get('hotspot_uuid'):
            match = next((h for h in self.hotspots(data['interface']) if h['uuid'] == data['hotspot_uuid']), None)
            if not match:
                raise NetworkError('未找到该网卡已配置的 192.168.4.1 热点')
            active = self.manager.ActivateConnection(match['path'], path, '/', timeout=15)
            return str(match['path']), str(active), False
        values = {
            'connection': {'id': 'lr-wifi-' + uuid.uuid4().hex[:12], 'uuid': str(uuid.uuid4()),
                           'type': '802-11-wireless', 'interface-name': data['interface'], 'autoconnect': False, 'mdns': d.Int32(2)},
            '802-11-wireless': {'ssid': d.ByteArray(data['ssid'].encode('utf-8')), 'mode': 'infrastructure', 'hidden': data.get('hidden', False)},
            'ipv4': {'method': 'auto'}, 'ipv6': {'method': 'auto'},
        }
        if data['security'] != 'open':
            values['802-11-wireless-security'] = {'key-mgmt': data['security'], 'psk': data['password'], 'psk-flags': d.UInt32(0)}
        values = d.Dictionary({k: d.Dictionary(v, signature='sv') for k, v in values.items()}, signature='sa{sv}')
        connection, active, _ = self.manager.AddAndActivateConnection2(values, path, '/', d.Dictionary({'persist': 'memory'}, signature='sv'), timeout=15)
        return str(connection), str(active), True

    def ready(self, interface, active):
        _, device = self.device(interface)
        if str(device.get('ActiveConnection')) != active:
            return []
        if int(self.active(active).get('State', 0)) != 2:
            return []
        return self.ips(device)

    def profile_with_secrets(self, path):
        connection = self.interface(path, NM + '.Settings.Connection')
        values = connection.GetSettings(timeout=10)
        # GetSettings omits secrets; preserve them whenever updating a profile.
        if '802-11-wireless-security' in values:
            secret = connection.GetSecrets('802-11-wireless-security', timeout=10)
            values['802-11-wireless-security'].update(secret.get('802-11-wireless-security', {}))
        return values

    def update_profile(self, path, values):
        self.interface(path, NM + '.Settings.Connection').Update2(
            values, self.dbus.UInt32(1), self.dbus.Dictionary({}, signature='sv'), timeout=10)

    def prefer(self, path, interface, journal):
        # Use NM's highest priority for the confirmed choice. Only demote a
        # competing maximum-priority profile; preserve all other preferences.
        settings = self.interface(BASE + '/Settings', NM + '.Settings')
        for other_path in settings.ListConnections(timeout=10):
            if str(other_path) == str(path):
                continue
            profile = self.settings(other_path)
            other_connection = profile.get('connection', {})
            if (profile.get('802-11-wireless') and
                    other_connection.get('interface-name', interface) == interface and
                    int(other_connection.get('autoconnect-priority', 0)) >= 999):
                values = self.profile_with_secrets(other_path)
                journal.append((other_path, copy.deepcopy(values)))
                values['connection']['autoconnect-priority'] = self.dbus.Int32(998)
                self.update_profile(other_path, values)
        values = self.profile_with_secrets(path)
        journal.append((path, copy.deepcopy(values)))
        values['connection']['autoconnect'] = self.dbus.Boolean(True)
        values['connection']['autoconnect-priority'] = self.dbus.Int32(999)
        self.update_profile(path, values)

    def restore_preferences(self, journal):
        for path, values in reversed(journal):
            self.update_profile(path, values)

    def destroy(self, checkpoint):
        self.manager.CheckpointDestroy(checkpoint, timeout=10)

    def rollback(self, checkpoint):
        results = self.manager.CheckpointRollback(checkpoint, timeout=15)
        if any(int(code) != 0 for code in results.values()):
            raise NetworkError('原网络恢复未完成，请联系现场维护人员', 503)

    def delete(self, path):
        self.interface(path, NM + '.Settings.Connection').Delete(timeout=10)


class NetworkController:
    def __init__(self, factory=NetworkManager, *, clock=time.time, sleep=time.sleep):
        self.factory, self.clock, self.sleep = factory, clock, sleep
        self.lock = threading.RLock()
        self.operation = None
        self.checkpoint = self.connection = None
        self.new_connection = False
        self.active_connection = None

    def status(self):
        status = self.factory().status()
        with self.lock:
            status['operation'] = copy.deepcopy(self.operation)
        return status

    def schedule(self, payload):
        data = checked_request(payload)
        with self.lock:
            if self.operation and self.operation['id'] == data['request_id']:
                return copy.deepcopy(self.operation)
            if self.operation and self.operation['phase'] in BUSY:
                raise NetworkError('已有网络切换等待完成，请勿重复提交', 409)
            if self.operation and self.operation['phase'] == 'recovery_required':
                raise NetworkError('上次网络恢复尚未确认，请联系现场维护人员检查后再操作', 409)
            manager = self.factory()
            manager.device(data['interface'])
            status = manager.status()
            if not status['wireless_enabled'] or not status['hardware_enabled']:
                raise NetworkError('无线网卡已关闭，请由现场管理员开启；网页不会解除硬件飞行模式')
            if data.get('hotspot_uuid') and not any(h['uuid'] == data['hotspot_uuid'] for h in manager.hotspots(data['interface'])):
                raise NetworkError('该网卡没有可恢复的固定 IP 热点')
            self.checkpoint = self.connection = self.active_connection = None
            self.new_connection = False
            self.operation = {'id': data['request_id'], 'phase': 'scheduled', 'interface': data['interface'],
                              'ssid': data.get('ssid', '机器人热点'), 'message': '已受理，5 秒后开始切换。请按页面提示连接目标网络。',
                              'rollback_at': self.clock() + SWITCH_DELAY + ROLLBACK_SECONDS, 'addresses': [],
                              'local_url': 'http://192.168.4.1:8000/system/network' if data.get('hotspot_uuid') else status['local_url']}
            threading.Thread(target=self._switch, args=(data,), daemon=True).start()
            return copy.deepcopy(self.operation)

    def _switch(self, data):
        self.sleep(SWITCH_DELAY)
        manager = self.factory()
        try:
            with self.lock:
                self.operation.update(phase='connecting', message='正在连接目标网络；原页面暂时断开属于预期。')
                self.checkpoint = manager.checkpoint(data['interface'])
                self.operation['rollback_at'] = self.clock() + ROLLBACK_SECONDS
                self.connection, active, self.new_connection = manager.activate(data)
                self.active_connection = active
            data.pop('password', None)
            deadline = self.clock() + 45
            while self.clock() < deadline:
                addresses = manager.ready(data['interface'], active)
                if addresses:
                    with self.lock:
                        self.operation.update(phase='awaiting_confirmation', addresses=addresses,
                                              message='已取得网络地址，请从目标网络登录后点击“确认保留此连接”。')
                    break
                self.sleep(1)
            else:
                self._restore('连接失败或未取得 IP，已请求恢复原网络。')
                return
            while self.clock() < self.operation['rollback_at'] - 3:
                with self.lock:
                    if self.operation['id'] != data['request_id'] or self.operation['phase'] not in BUSY:
                        return
                self.sleep(1)
            with self.lock:
                if self.operation['id'] == data['request_id'] and self.operation['phase'] in BUSY:
                    self._restore('切换开始后约 5 分钟内未确认访问，已恢复原网络。')
        except Exception:
            # D-Bus error text can contain provider data. Do not expose it.
            with self.lock:
                if self.operation['id'] == data['request_id']:
                    self._restore('切换未成功，已请求恢复原网络；请检查密码、信号和路由器设置。')
        finally:
            data.pop('password', None)

    def _restore(self, message):
        with self.lock:
            self.operation.update(phase='restoring', message='正在恢复原网络…')
            restored = True
            try:
                manager = self.factory()
            except Exception:
                manager = None
                restored = False
            if self.checkpoint:
                if manager is not None:
                    try:
                        manager.rollback(self.checkpoint)
                    except Exception:
                        restored = False
                else:
                    restored = False
                if restored:
                    try:
                        manager.destroy(self.checkpoint)
                    except Exception:
                        pass
            # Never destroy the independent rollback timer after a failed rollback.
            if restored and self.new_connection and self.connection:
                try:
                    manager.delete(self.connection)
                except Exception:
                    restored = False
            self.checkpoint = self.connection = None
            self.new_connection = False
            self.operation.update(phase='restored' if restored else 'recovery_required',
                                  message=message if restored else '恢复请求未完成；NetworkManager 将继续按检查点超时恢复，请等待并联系现场维护人员。')

    def confirm(self, operation_id, local_address):
        with self.lock:
            if not self.operation or self.operation['id'] != operation_id:
                raise NetworkError('切换记录已变化，请刷新页面', 409)
            if self.operation['phase'] == 'confirmed':
                return copy.deepcopy(self.operation)
            if self.operation['phase'] != 'awaiting_confirmation' or self.clock() >= self.operation['rollback_at'] - 15:
                raise NetworkError('当前无法确认，请等待恢复后重试', 409)
            try:
                address = ipaddress.ip_address(local_address)
                address = str(address.ipv4_mapped) if getattr(address, 'ipv4_mapped', None) else str(address)
            except ValueError:
                raise NetworkError('请通过目标网络的 8000 端口访问本页，再确认连接', 409) from None
            addresses = self.factory().ready(self.operation['interface'], self.active_connection)
            if address not in addresses:
                raise NetworkError('请让手机或电脑连接目标 Wi-Fi，使用机器人新地址登录后再确认', 409)
            self.operation['phase'] = 'confirming'
            journal = []
            try:
                manager = self.factory()
                manager.prefer(self.connection, self.operation['interface'], journal)
                manager.destroy(self.checkpoint)
                self.checkpoint = None
                self.operation.update(phase='confirmed', message='连接已保留，开机优先自动连接此网络。')
            except Exception:
                if journal:
                    try:
                        manager.restore_preferences(journal)
                    except Exception:
                        pass  # Keep the independent device rollback timer alive.
                self._restore('保存连接失败，已请求恢复原网络。')
            return copy.deepcopy(self.operation)


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_args):
        pass  # Never log request bodies, SSIDs, credentials or tokens.

    def do_GET(self):
        self.dispatch()

    def do_POST(self):
        self.dispatch()

    def dispatch(self):
        try:
            self.connection.settimeout(15)
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 <= length <= 4096 or self.headers.get('Transfer-Encoding'):
                raise NetworkError('请求大小不合法', 413)
            data = json.loads(self.rfile.read(length)) if length else {}
            if not isinstance(data, dict):
                raise NetworkError('网络请求必须是对象')
            controller = self.server.controller
            if self.command == 'GET' and self.path == '/status':
                payload = controller.status()
            elif self.command == 'POST' and self.path == '/scan':
                if set(data) - {'interface', 'refresh'} or not isinstance(data.get('refresh', False), bool):
                    raise NetworkError('扫描参数不合法')
                with controller.lock:
                    if controller.operation and controller.operation['phase'] in BUSY:
                        raise NetworkError('切换期间请等待，暂不扫描', 409)
                payload = controller.factory().scan(data.get('interface', ''), data.get('refresh', False))
            elif self.command == 'POST' and self.path == '/connect':
                payload = controller.schedule(data)
            elif self.command == 'POST' and self.path == '/confirm':
                payload = controller.confirm(data.get('id'), data.get('local_address', ''))
            else:
                raise NetworkError('不支持的网络操作', 404)
            self.respond(200, payload)
        except NetworkError as error:
            self.respond(error.status, {'detail': str(error)})
        except (ValueError, TypeError):
            self.respond(400, {'detail': '网络请求格式不合法'})
        except Exception:
            self.respond(503, {'detail': '网络管理暂不可用，请检查 NetworkManager 和网络代理服务'})

    def respond(self, status, payload):
        content = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(content)


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True

    def __init__(self, path, controller):
        self.controller = controller
        super().__init__(path, Handler)
        os.chmod(path, 0o660)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--socket', default='/run/lr-network-agent/network.sock')
    args = parser.parse_args()
    path = Path(args.socket)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not path.is_socket():
            raise RuntimeError('refusing to replace non-socket')
        path.unlink()
    with Server(str(path), NetworkController()) as server:
        server.serve_forever()


if __name__ == '__main__':
    main()
