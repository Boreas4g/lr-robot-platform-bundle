"""Public login must protect APIs as well as hide the debug menu."""
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import get_settings
from app.main import app
from app.schemas import User
from app.store import _hash_password, store


@pytest.fixture
def public_session(monkeypatch):
    monkeypatch.setattr(get_settings(), 'auth_enabled', True)
    monkeypatch.setattr(get_settings(), 'single_operator', False)
    user = User(username='public-access-test', name='操作员', role='图书馆操作员')
    monkeypatch.setitem(store.users, user.username, (user, _hash_password('test-password')))
    client = TestClient(app)
    response = client.post('/api/v1/auth/login', json={'username': user.username, 'password': 'test-password'})
    assert response.status_code == 200
    token = response.json()['token']
    yield client, {'Authorization': f'Bearer {token}'}, token
    store.revoke_token(token)


@pytest.mark.parametrize('method,path', [
    ('GET', '/api/v1/robots'), ('GET', '/api/v1/library/maps'),
    ('GET', '/api/v1/debug/chassis-params'),
    ('POST', '/api/v1/robots/LR-01/manual-control/jog'),
    ('POST', '/api/v1/system/start-all'), ('POST', '/api/v1/auth/register'),
    ('GET', '/api/v1/auth/bookarm-access?path=/v1/studio/library&method=GET'),
])
def test_anonymous_client_cannot_operate(public_session, method, path):
    client, _, _ = public_session
    assert client.request(method, path).status_code == 401


@pytest.mark.parametrize('path', ['/api/v1/robots', '/api/v1/dispatch/tasks', '/api/v1/books', '/api/v1/library/maps'])
def test_public_modules_are_available(public_session, path):
    client, headers, _ = public_session
    assert client.get(path, headers=headers).status_code == 200


def test_public_account_cannot_debug_or_create_accounts(public_session):
    client, headers, _ = public_session
    assert client.get('/api/v1/debug/stress-test/templates', headers=headers).status_code == 403
    assert client.get('/api/v1/debug/chassis-params', headers=headers).status_code == 403
    assert client.post('/api/v1/robots/LR-01/lift/move', headers=headers, json={}).status_code == 403
    assert client.post('/api/v1/auth/register', headers=headers, json={'username': 'other', 'password': '12345678', 'name': 'other'}).status_code == 403


@pytest.mark.parametrize('path,method,expected', [
    ('/v1/studio/library', 'GET', 200), ('/v1/studio/library', 'POST', 200),
    ('/v1/studio/library/verify-all', 'POST', 200),
    ('/v1/studio/library/book-id/image', 'GET', 200),
    ('/v1/studio/hardware/status', 'GET', 200),
    ('/v1/studio/joints/move', 'POST', 403),
    ('/v1/studio/camera/frame', 'GET', 403),
    ('/v1/tuning/profile', 'PUT', 403), ('/v1/takeout/start', 'POST', 403),
    ('/v1/studio/library', 'DELETE', 403),
])
def test_private_arm_proxy_checks_each_operation(public_session, path, method, expected):
    client, headers, _ = public_session
    assert client.get('/api/v1/auth/bookarm-access', params={'path': path, 'method': method}, headers=headers).status_code == expected


def test_logout_and_expired_sessions_are_rejected(public_session):
    client, headers, token = public_session
    assert client.get('/api/v1/auth/me', headers=headers).status_code == 200
    store.session_expires[token] = time.time() - 1
    assert client.get('/api/v1/auth/me', headers=headers).status_code == 401
    response = client.post('/api/v1/auth/login', json={'username': 'public-access-test', 'password': 'test-password'})
    headers = {'Authorization': f"Bearer {response.json()['token']}"}
    assert client.post('/api/v1/auth/logout', headers=headers).status_code == 204
    assert client.get('/api/v1/auth/me', headers=headers).status_code == 401


def test_realtime_requires_session(public_session):
    client, _, token = public_session
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/api/v1/realtime/robots'):
            pass
    with client.websocket_connect('/api/v1/realtime/robots', subprotocols=[f'lr-auth.{token}']) as socket:
        assert socket.receive_json()['type'] == 'robots.snapshot'
