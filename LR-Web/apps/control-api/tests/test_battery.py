from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from app.battery import BatteryStore
from app.main import app
from app.config import get_settings


def sample(store, t, current=2.0, boot='boot-a'):
    m=SimpleNamespace(received_monotonic=t, received_at='2026-10-16T00:00:00+00:00', voltage_v=24.0, current_a=current)
    store.record(m,device_serial='test',boot=boot)


def test_twenty_ah_discharge_and_restart(tmp_path):
    path=tmp_path/'state.db';store=BatteryStore(path)
    store.initialize(20,24,confirmed_full=True)
    for t in range(0,3601,5): sample(store,t)
    result=BatteryStore(path).snapshot(now=3601,boot='boot-a')
    assert result['percent']==pytest.approx(90)
    assert result['consumedAh']==pytest.approx(2)
    assert result['consumedWh']==pytest.approx(48)
    BatteryStore(path).initialize(20,24,confirmed_full=True)
    assert BatteryStore(path).snapshot(now=3601,boot='boot-a')['consumedAh']==pytest.approx(2)


def test_variable_current_and_stale_data(tmp_path):
    store=BatteryStore(tmp_path/'s.db');store.initialize(20,24,confirmed_full=True)
    sample(store,10,1);sample(store,12,3)
    assert store.snapshot(now=12,boot='boot-a')['consumedAh']==pytest.approx(4/3600)
    stale=store.snapshot(now=18,boot='boot-a')
    assert stale['status']=='offline' and stale['percent'] is None and stale['voltageV'] is None
    assert stale['lastPercent'] < 100


def test_disconnect_and_boot_gap_are_not_fabricated(tmp_path):
    store=BatteryStore(tmp_path/'s.db');store.initialize(20,24,confirmed_full=True)
    sample(store,10);sample(store,30)
    view=store.snapshot(now=30,boot='boot-a')
    assert view['quality']=='gap' and view['consumedAh']==0 and view['gapSeconds']==20
    sample(store,1,boot='boot-b')
    assert store.snapshot(now=1,boot='boot-b')['quality']=='gap'


def test_error_calibration_and_recovery(tmp_path):
    store=BatteryStore(tmp_path/'s.db');store.initialize(20,24,confirmed_full=True)
    sample(store,10);sample(store,11);store.fail('USB unplugged')
    assert store.snapshot(now=11,boot='boot-a')['percent'] is None
    with pytest.raises(ValueError): store.calibrate_full(confirm_unplugged=True,now=11,boot='boot-a')
    sample(store,12);store.calibrate_full(confirm_unplugged=True,now=12,boot='boot-a')
    snapshot=store.snapshot(now=12,boot='boot-a')
    assert snapshot['percent']==100 and snapshot['consumedAh']==0
    sample(store,13)
    assert store.snapshot(now=13,boot='boot-a')['consumedAh']==0


def test_missing_configuration_and_invalid_sample(tmp_path):
    store=BatteryStore(tmp_path/'s.db');sample(store,10)
    assert store.snapshot(now=10,boot='boot-a')['percent'] is None
    with pytest.raises(ValueError): sample(store,11,float('nan'))
    with pytest.raises(ValueError): store.configure(0,24)


def test_api_configuration_confirmation_and_permission(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(),'battery_state_file',str(tmp_path/'s.db'))
    client=TestClient(app)
    assert client.get('/api/v1/power/battery').json()['status']=='offline'
    assert client.put('/api/v1/power/battery/config',json={'capacityAh':20,'nominalVoltageV':24}).status_code==200
    assert client.put('/api/v1/power/battery/config',json={'capacityAh':-1,'nominalVoltageV':24}).status_code==422
    assert client.post('/api/v1/power/battery/calibrate-full',json={'confirmFull':False}).status_code==422
    assert client.post('/api/v1/power/battery/calibrate-full',json={'confirmFull':True}).status_code==409
    monkeypatch.setattr(get_settings(),'auth_enabled',True)
    assert client.get('/api/v1/power/battery').status_code==401


def test_configuration_does_not_reset_consumption_and_clamps_zero(tmp_path):
    store=BatteryStore(tmp_path/'s.db');store.initialize(0.001,24,confirmed_full=True)
    sample(store,0);sample(store,5)
    assert store.snapshot(now=5,boot='boot-a')['percent']==0
    store.configure(20,24)
    assert store.snapshot(now=5,boot='boot-a')['consumedAh']==pytest.approx(10/3600)


def test_same_boot_restart_integrates_only_short_gap(tmp_path):
    path=tmp_path/'s.db';store=BatteryStore(path);store.initialize(20,24,confirmed_full=True)
    sample(store,0)
    store=BatteryStore(path);sample(store,2)
    assert store.snapshot(now=2,boot='boot-a')['consumedAh']==pytest.approx(4/3600)


def test_websocket_snapshot_and_authentication(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(),'battery_state_file',str(tmp_path/'s.db'))
    client=TestClient(app)
    with client.websocket_connect('/api/v1/realtime/battery') as ws:
        result=ws.receive_json()
        assert result['type']=='battery.updated'
        assert result['battery']['status']=='offline'
    monkeypatch.setattr(get_settings(),'auth_enabled',True)
    from fastapi import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/api/v1/realtime/battery'): pass



@pytest.mark.parametrize('old_mode', ['charging', 'unknown', 'discharging'])
def test_remove_manual_mode_preserves_calibration_validity(tmp_path, old_mode):
    import json, sqlite3
    path=tmp_path/'s.db';store=BatteryStore(path);store.initialize(20,24,confirmed_full=True)
    sample(store,1)
    with sqlite3.connect(path) as conn:
        state=json.loads(conn.execute('select state from battery').fetchone()[0])
        state.update(powerMode=old_mode, powerModeUpdatedAt='old')
        conn.execute('update battery set state=?',(json.dumps(state),))
    sample(store,2)
    snapshot=store.snapshot(now=2,boot='boot-a')
    assert 'powerMode' not in snapshot and 'chargingSource' not in snapshot
    if old_mode != 'discharging':
        assert snapshot['percent'] is None and snapshot['consumedAh']==0
    else:
        assert snapshot['percent'] is not None
    with sqlite3.connect(path) as conn:
        state=json.loads(conn.execute('select state from battery').fetchone()[0])
        assert 'powerMode' not in state and 'powerModeUpdatedAt' not in state
    with pytest.raises(ValueError): store.calibrate_full(now=2,boot='boot-a')
    store.calibrate_full(confirm_unplugged=True,now=2,boot='boot-a')
    assert store.snapshot(now=2,boot='boot-a')['percent']==100


def test_removed_power_mode_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(),'battery_state_file',str(tmp_path/'s.db'))
    assert TestClient(app).put('/api/v1/power/battery/power-mode',json={'mode':'charging'}).status_code==404
