#!/usr/bin/python3
"""Bounded, best-effort scan BEFORE NetworkManager starts; never run on live Wi-Fi."""
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

spec = importlib.util.spec_from_file_location('network_agent', Path(__file__).with_name('lr-network-agent.py'))
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


def run(*args, timeout=3):
    return subprocess.run(args, text=True, capture_output=True, check=True, timeout=timeout)


def decode_ssid(value):
    # iw escapes non-printable UTF-8 bytes as \xNN. Do not interpret other escapes.
    data = bytearray()
    for token in re.findall(r'\\x[0-9a-fA-F]{2}|.', value):
        data.extend(bytes([int(token[2:], 16)]) if token.startswith('\\x') and len(token) == 4 else token.encode())
    return data.decode('utf-8', errors='replace')


def parse_scan(output):
    networks = {}
    for block in re.split(r'^BSS ', output, flags=re.M)[1:]:
        ssid = re.search(r'^\s*SSID: (.*)$', block, re.M)
        frequency = re.search(r'^\s*freq: (\d+)', block, re.M)
        signal_db = re.search(r'^\s*signal: (-?[\d.]+)', block, re.M)
        if not ssid or not frequency:
            continue
        name = decode_ssid(ssid[1])
        if not name or len(name.encode()) > 32 or any(ord(c) < 32 for c in name):
            continue
        auth = re.search(r'Authentication suites: (.*)', block)
        suites = auth[1] if auth else ''
        protected = bool(re.search(r'Privacy|^\s*(RSN|WPA):', block, re.M))
        security = ('wpa-psk' if 'PSK' in suites else 'sae' if 'SAE' in suites
                    else 'unsupported' if protected else 'open')
        item = {'ssid': name, 'frequency': int(frequency[1]), 'security': security,
                'signal': max(0, min(100, round(2 * (float(signal_db[1]) + 100)))) if signal_db else 0}
        key = name, security
        if key not in networks or item['signal'] > networks[key]['signal']:
            networks[key] = item
    return sorted(networks.values(), key=lambda item: -item['signal'])


def scan_before_networkmanager(interface):
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,15}', interface):
        raise ValueError('invalid scan interface')
    # Only the ordered boot unit can scan. A live manager (even activating) is refused.
    state = run('systemctl', 'show', 'NetworkManager.service', '-p', 'ActiveState', '--value').stdout.strip()
    if state not in ('inactive', 'failed'):
        raise RuntimeError('NetworkManager already running; network untouched')
    for _ in range(16):
        if Path('/sys/class/net', interface, 'phy80211').exists():
            break
        time.sleep(0.5)
    info = run('iw', 'dev', interface, 'info').stdout
    if not re.search(r'^\s*type managed$', info, re.M):
        raise RuntimeError('not an idle station interface')
    if 'Connected to ' in run('iw', 'dev', interface, 'link').stdout:
        raise RuntimeError('interface already connected')
    addresses = json.loads(run('ip', '-j', 'address', 'show', 'dev', interface).stdout)
    if any(item.get('addr_info') for item in addresses):
        raise RuntimeError('interface has addresses; network untouched')
    was_up = 'UP' in addresses[0].get('flags', [])
    try:
        run('ip', 'link', 'set', interface, 'up')
        result = run('iw', 'dev', interface, 'scan', timeout=12)
        agent.ScanCache().save(interface, parse_scan(result.stdout))
    finally:
        if not was_up:
            run('ip', 'link', 'set', interface, 'down')


def main():
    def interrupted(*_):
        raise RuntimeError('boot scan timed out')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGALRM, interrupted)
    signal.alarm(23)
    try:
        scan_before_networkmanager(os.environ.get('LR_SCAN_INTERFACE', 'wlo1'))
        print('Boot Wi-Fi scan saved; NetworkManager may start the hotspot.')
    except Exception:
        print('Boot scan unavailable; keeping previous list and allowing NetworkManager to start.')
    finally:
        signal.alarm(0)


if __name__ == '__main__':
    main()
