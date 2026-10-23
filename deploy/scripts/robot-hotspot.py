#!/usr/bin/python3
"""Run a local robot AP on an explicitly selected, unused Wi-Fi radio.

The upstream radio is protected. --check performs read-only preflight checks.
"""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

AP = 'lr-ap0'
STATION = os.environ.get('LR_WIFI_STATION', '')
UPSTREAM = os.environ.get('LR_UPSTREAM_WIFI', 'wlo1')
MODE = os.environ.get('LR_HOTSPOT_MODE', 'isolated')
RUNTIME = Path('/run/lr-hotspot')
children = []
stopping = False


def run(*args, check=True):
    return subprocess.run(args, check=check, text=True, capture_output=True)


def validate_radio(station, upstream, net_root=Path('/sys/class/net'), runner=run, mode='isolated'):
    """Reject any setup that could occupy an existing network's Wi-Fi radio."""
    if mode not in ('isolated', 'standalone'):
        raise ValueError('LR_HOTSPOT_MODE must be isolated or standalone')
    if not station or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,15}', station):
        raise ValueError('Set LR_WIFI_STATION to an unused Wi-Fi adapter')
    station_path = net_root / station / 'phy80211'
    upstream_path = net_root / upstream / 'phy80211'
    if not station_path.exists():
        raise ValueError('Selected hotspot Wi-Fi adapter must be present')
    if mode == 'isolated' and not upstream_path.exists():
        raise ValueError('Both hotspot and protected upstream Wi-Fi adapters must be present')
    phy = station_path.resolve(strict=True)
    if mode == 'isolated' and phy == upstream_path.resolve(strict=True):
        raise ValueError(f'{station} shares the protected {upstream} radio; network left untouched')
    for interface in net_root.iterdir():
        radio = interface / 'phy80211'
        if not radio.exists() or radio.resolve() != phy:
            continue
        if interface.name == AP:
            continue
        link = runner('iw', 'dev', interface.name, 'link').stdout
        addresses = json.loads(runner('ip', '-j', 'address', 'show', 'dev', interface.name).stdout)
        if 'Connected to ' in link or any(item.get('addr_info') for item in addresses):
            raise ValueError(f'{interface.name} is already in use; network left untouched')
    existing = net_root / AP / 'phy80211'
    if existing.exists() and existing.resolve() != phy:
        raise ValueError(f'{AP} belongs to another radio; refusing to reconfigure it')
    capabilities = runner('iw', 'phy', phy.name, 'info').stdout
    if not re.search(r'^\s*\* AP\s*$', capabilities, re.M):
        raise ValueError('Selected adapter does not support AP mode')
    frequency = re.search(r'^.*2437(?:\.0)? MHz.*$', capabilities, re.M)
    if not frequency or any(flag in frequency[0].lower() for flag in ('disabled', 'no ir', 'no-ir')):
        raise ValueError('Selected adapter cannot broadcast on 2.4 GHz channel 6')
    return phy.name


def stop(_signum=None, _frame=None):
    global stopping
    stopping = True


def cleanup():
    for process in children:
        if process.poll() is None:
            process.terminate()
    for process in children:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    children.clear()


def serve(phy):
    RUNTIME.mkdir(mode=0o750, parents=True, exist_ok=True)
    if not Path(f'/sys/class/net/{AP}').exists():
        run('iw', 'phy', phy, 'interface', 'add', AP, 'type', '__ap')
    run('nmcli', 'device', 'set', AP, 'managed', 'no')
    run('ip', 'link', 'set', AP, 'down')
    run('iw', 'dev', AP, 'set', 'type', '__ap')
    run('ip', 'address', 'replace', '192.168.4.1/24', 'dev', AP)
    run('ip', 'link', 'set', AP, 'up')
    config = RUNTIME / 'hostapd.conf'
    config.write_text(f'''interface={AP}
driver=nl80211
ssid=图书馆机器人
utf8_ssid=1
hw_mode=g
channel=6
ieee80211n=1
wmm_enabled=1
auth_algs=1
wpa=2
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
wpa_passphrase=12345678
ctrl_interface={RUNTIME}/hostapd
''')
    config.chmod(0o600)
    children.append(subprocess.Popen(['hostapd', str(config)]))
    dhcp = RUNTIME / 'dnsmasq.conf'
    dhcp.write_text(f'''interface={AP}
bind-dynamic
listen-address=192.168.4.1
except-interface=lo
dhcp-range=192.168.4.20,192.168.4.200,255.255.255.0,12h
dhcp-option=3
dhcp-option=6,192.168.4.1
address=/robot.lan/192.168.4.1
dhcp-leasefile={RUNTIME}/dnsmasq.leases
pid-file={RUNTIME}/dnsmasq.pid
log-dhcp
''')
    # Run as root in a dedicated systemd service; the runtime directory is private.
    children.append(subprocess.Popen(['dnsmasq', '--keep-in-foreground', '--user=root', f'--conf-file={dhcp}']))
    print('Robot hotspot processes started: channel 6, http://192.168.4.1:8000', flush=True)
    while not stopping:
        if any(process.poll() is not None for process in children):
            raise RuntimeError('AP or DHCP process stopped; systemd will retry')
        time.sleep(5)


def main():
    try:
        phy = validate_radio(STATION, UPSTREAM, mode=MODE)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f'Hotspot not started: {error}', file=sys.stderr, flush=True)
        return 78
    if '--check' in sys.argv[1:]:
        print(f'Ready: {STATION} on {phy}; mode={MODE}; no network connection changed')
        return 0
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        serve(phy)
    finally:
        cleanup()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
