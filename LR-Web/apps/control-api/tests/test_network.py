from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api import network
from app.config import get_settings
from app.dependencies import get_current_user
from app.main import app
from app.schemas import User
from app.store import store


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(get_settings(), "auth_enabled", True)
    monkeypatch.setattr(store, "tasks", [])
    monkeypatch.setattr(store, "robots", [])
    app.dependency_overrides[get_current_user] = lambda: User(username="operator", name="操作员", role="图书馆操作员")
    yield TestClient(app, client=("127.0.0.1", 42000))
    app.dependency_overrides.pop(get_current_user, None)


def payload(**overrides):
    return dict(
        {
            "request_id": str(uuid4()),
            "interface": "wlan0",
            "ssid": "Library",
            "password": "secret123",
            "security": "wpa-psk",
            "acknowledged": True,
        },
        **overrides,
    )


def test_all_network_endpoints_require_login(monkeypatch):
    monkeypatch.setattr(get_settings(), "auth_enabled", True)
    c = TestClient(app)
    for method, url in [("GET", ""), ("POST", "/scan"), ("POST", "/connect"), ("POST", "/confirm")]:
        assert c.request(method, "/api/v1/system/network" + url).status_code == 401


def test_operator_can_request_async_switch_without_exposing_password(client, monkeypatch):
    calls = []

    def agent(method, path, data):
        calls.append((method, path, data))
        return {"id": data["request_id"], "phase": "scheduled"}

    monkeypatch.setattr(network, "agent_request", agent)
    r = client.post("/api/v1/system/network/connect", json=payload())
    assert r.status_code == 202
    assert "secret123" not in r.text
    assert calls[0][2]["password"] == "secret123"
    assert "refresh" not in calls[0][2]


def test_active_work_blocks_switch_before_agent(client, monkeypatch):
    monkeypatch.setattr(store, "tasks", [SimpleNamespace(status="running")])
    monkeypatch.setattr(network, "agent_request", lambda *_: pytest.fail("agent must not be called"))
    assert client.post("/api/v1/system/network/connect", json=payload()).status_code == 409


def test_idle_robot_can_switch_with_historical_queued_and_paused_tasks(client, monkeypatch):
    monkeypatch.setattr(
        store,
        "tasks",
        [SimpleNamespace(status="queued"), SimpleNamespace(status="paused")],
    )
    monkeypatch.setattr(store, "robots", [SimpleNamespace(status="idle")])
    calls = []
    monkeypatch.setattr(network, "agent_request", lambda *args: calls.append(args) or {"phase": "scheduled"})
    response = client.post("/api/v1/system/network/connect", json=payload())
    assert response.status_code == 202
    assert calls[0][1] == "/connect"


@pytest.mark.parametrize("status", ["busy", "mapping", "navigating", "manual"])
def test_robot_movement_blocks_network_switch(client, monkeypatch, status):
    monkeypatch.setattr(store, "robots", [SimpleNamespace(status=status)])
    monkeypatch.setattr(network, "agent_request", lambda *_: pytest.fail("agent must not be called"))
    assert client.post("/api/v1/system/network/connect", json=payload()).status_code == 409


def test_unknown_fields_and_missing_acknowledgement_rejected(client, monkeypatch):
    monkeypatch.setattr(network, "agent_request", lambda *_: pytest.fail("agent must not be called"))
    assert client.post("/api/v1/system/network/connect", json=payload(acknowledged=False)).status_code == 422
    response = client.post("/api/v1/system/network/connect", json=payload(command="reboot"))
    assert response.status_code == 422
    assert "secret123" not in response.text


def test_auth_disabled_cannot_expose_network_control(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "auth_enabled", False)
    assert client.get("/api/v1/system/network").status_code == 503


def test_role_restriction(client, monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: User(username="reader", name="读者", role="读者")
    monkeypatch.setattr(network, "agent_request", lambda *_: pytest.fail("agent must not be called"))
    assert client.get("/api/v1/system/network").status_code == 403


def test_confirm_passes_proxy_local_address(client, monkeypatch):
    calls = []
    monkeypatch.setattr(network, "agent_request", lambda *args: calls.append(args) or {"phase": "confirmed"})
    r = client.post(
        "/api/v1/system/network/confirm", json={"id": str(uuid4())}, headers={"x-lr-local-address": "10.0.0.2"}
    )
    assert r.status_code == 200
    assert calls[0][2]["local_address"] == "10.0.0.2"


def test_direct_remote_client_cannot_forge_confirmation(client, monkeypatch):
    monkeypatch.setattr(network, "agent_request", lambda *_: pytest.fail("agent must not be called"))
    c = TestClient(app, client=("10.0.0.10", 42000))
    assert (
        c.post(
            "/api/v1/system/network/confirm", json={"id": str(uuid4())}, headers={"x-lr-local-address": "10.0.0.2"}
        ).status_code
        == 403
    )


def test_unavailable_agent_reports_503(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "network_agent_socket", None)
    assert client.get("/api/v1/system/network").status_code == 503


def test_search_requires_explicit_acknowledgement_and_id(client, monkeypatch):
    monkeypatch.setattr(network, 'agent_request', lambda *_: pytest.fail('must not search'))
    assert client.post('/api/v1/system/network/scan', json={'interface': 'wlo1', 'refresh': True}).status_code == 409


def test_background_search_passes_id_and_acknowledgement(client, monkeypatch):
    calls = []
    monkeypatch.setattr(network, 'agent_request', lambda *args: calls.append(args) or {'networks': []})
    request_id = str(uuid4())
    response = client.post('/api/v1/system/network/scan', json={
        'interface': 'wlo1', 'refresh': True, 'acknowledged': True, 'request_id': request_id})
    assert response.status_code == 200
    assert calls[0][2]['request_id'] == request_id
    assert calls[0][2]['acknowledged'] is True


def test_robot_movement_blocks_rescan_but_allows_reading_list(client, monkeypatch):
    monkeypatch.setattr(store, 'robots', [SimpleNamespace(status='navigating')])
    calls = []
    monkeypatch.setattr(network, 'agent_request', lambda *args: calls.append(args) or {'networks': []})
    assert client.post('/api/v1/system/network/scan', json={'interface': 'wlo1', 'refresh': True,
        'acknowledged': True, 'request_id': str(uuid4())}).status_code == 409
    assert not calls
    assert client.post('/api/v1/system/network/scan', json={'interface': 'wlo1'}).status_code == 200
