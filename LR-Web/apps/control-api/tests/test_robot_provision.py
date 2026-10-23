"""Exercise appliance provisioning with a temporary SQLite DB and tiny real map."""
import json
import os
from pathlib import Path
import pwd

import pytest
from sqlalchemy import select

from app.config import Settings
from app.db import Base, Database, MapVersionModel, RobotModel, UserModel


@pytest.fixture
def appliance(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[4] / "deploy/scripts"))
    from robot_provision import provision

    monkeypatch.setattr(Database, "initialize", lambda self: Base.metadata.create_all(self.engine))
    monkeypatch.setattr(os, "chown", lambda *args: None)
    baseline = tmp_path / "baseline"
    (baseline / "robot").mkdir(parents=True)
    (baseline / "robot/map-registry.json").write_text(json.dumps({"maps": {"MAP-SITE": {}}}))
    source = baseline / "maps/MAP-SITE"
    source.mkdir(parents=True)
    (source / "map.yaml").write_text("image: map.pgm\nresolution: 0.05\norigin: [0, 0, 0]\nnegate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.196\n")
    (source / "map.pgm").write_bytes(b"P5\n2 2\n255\n\x00\xff\xcd\xff")
    settings = Settings(_env_file=None, database_url=f"sqlite:///{tmp_path}/database.sqlite3",
                        map_storage_dir=str(tmp_path / "maps"), battery_state_file=str(tmp_path / "battery.sqlite3"))
    profile = {"robot_id": "LR-02", "robot_name": "图书馆机器人", "operator_password": "123456",
               "service_user": pwd.getpwuid(os.getuid()).pw_name, "baseline": str(baseline),
               "active_map_id": "MAP-SITE", "battery": {"capacity_ah": None, "nominal_voltage_v": None}}
    return provision, profile, {"admin": "unique-admin-password"}, settings


def test_provision_creates_real_identity_and_retries_without_duplicating(appliance):
    provision, profile, private, settings = appliance
    provision(profile, private, settings)
    provision(profile, private, settings)
    database = Database(settings)
    with database.session() as session:
        users = list(session.scalars(select(UserModel)))
        assert {u.username: u.role for u in users} == {"operator": "图书馆操作员", "admin": "系统管理员"}
        assert all(u.password_hash not in ("123456", private["admin"]) for u in users)
        robots = list(session.scalars(select(RobotModel)))
        assert len(robots) == 1
        assert robots[0].id == "LR-02" and robots[0].pose is None
        assert robots[0].status == "offline" and robots[0].localization_status == "unknown"
        assert session.get(MapVersionModel, "MAP-SITE").status == "published"
    assert (Path(settings.map_storage_dir) / "MAP-SITE/preview.png").read_bytes().startswith(b"\x89PNG")
    database.engine.dispose()


def test_provision_refuses_database_of_another_robot(appliance):
    provision, profile, private, settings = appliance
    provision(profile, private, settings)
    profile["robot_id"] = "LR-OTHER"
    with pytest.raises(RuntimeError, match="another robot"):
        provision(profile, private, settings)


def test_provision_transfers_battery_specifications_without_full_charge(appliance):
    from app.battery import BatteryStore

    provision, profile, private, settings = appliance
    profile["battery"].update(capacity_ah=20, nominal_voltage_v=24)
    provision(profile, private, settings)
    state = BatteryStore(settings.battery_state_file, "LR-02").snapshot()
    assert state["capacityAh"] == 20 and state["nominalVoltageV"] == 24
    assert state["quality"] == "uncalibrated" and state["percent"] is None
    assert state["calibratedAt"] is None and state["sampleCount"] == 0
