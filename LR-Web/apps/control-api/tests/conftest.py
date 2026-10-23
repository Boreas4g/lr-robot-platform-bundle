import os
import socket
import subprocess
from pathlib import Path

import pytest

from app.config import Settings, get_settings

# Collection imports app.main before fixtures run. Never inherit a deployed
# robot's credentials, database, MQTT endpoint or host-agent socket here.
for name in tuple(os.environ):
    if name.startswith("LR_"):
        del os.environ[name]
Settings.model_config["env_file"] = None
get_settings.cache_clear()
get_settings().vehicle_map_register_enabled = False

from app.store import store


@pytest.fixture(autouse=True)
def isolate_live_appliance(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail closed if an unmocked test tries a host service or hardware action."""
    original_connect = socket.socket.connect
    original_popen = subprocess.Popen

    def connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            raise AssertionError(f"Tests must mock outbound network connections: {address}")
        if sock.family == socket.AF_UNIX and isinstance(address, (str, bytes)):
            path = os.fsdecode(address)
            if not path.startswith(("/tmp/", "/var/tmp/")):
                raise AssertionError("Tests must mock appliance Unix sockets")
        return original_connect(sock, address)

    def popen(args, *positional, **kwargs):
        command = args[0] if isinstance(args, (list, tuple)) else args
        if isinstance(command, (str, bytes, os.PathLike)):
            command = os.fsdecode(command)
            if Path(command).name in {"sudo", "systemctl", "nmcli", "ip", "cansend", "candump"} or command.startswith("/usr/local/libexec/"):
                raise AssertionError("Tests must mock appliance command execution")
        return original_popen(args, *positional, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(subprocess, "Popen", popen)


@pytest.fixture(autouse=True)
def synchronous_persist(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests write-through: persist synchronously instead of debouncing."""
    monkeypatch.setattr(store, "persist_delay_seconds", 0)
