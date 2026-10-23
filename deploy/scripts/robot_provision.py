#!/usr/bin/env python3
"""Seed fresh appliance users, identity and approved maps with the API stopped.

Called by robot_setup inside the isolated API venv; no hardware imports or actions.
"""
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone

from robot_setup import read_env


def provision(p, private, settings):
    """Initialize one appliance using explicit settings (also usable in isolation)."""
    from app.db import Database, UserModel, RobotModel, MapVersionModel
    from app.store import _hash_password
    from app.map_files import parse_pgm, parse_ros_map_yaml, pgm_preview_png
    from sqlalchemy import select

    database = Database(settings)
    database.initialize()
    with database.session() as session:
        robots = list(session.scalars(select(RobotModel)))
        if any(item.id != p["robot_id"] for item in robots):
            raise RuntimeError("Existing database belongs to another robot; refusing to overwrite it")
        # The profile remains authoritative when resuming an interrupted installation.
        for username, name, role, password in (
            ("operator", "图书馆操作员", "图书馆操作员", p["operator_password"]),
            ("admin", "维护管理员", "系统管理员", private["admin"]),
        ):
            if session.get(UserModel, username) is None:
                session.add(UserModel(username=username, name=name, role=role, password_hash=_hash_password(password)))
            else:
                session.get(UserModel, username).password_hash = _hash_password(password)
        if session.get(RobotModel, p["robot_id"]) is None:
            session.add(RobotModel(id=p["robot_id"], name=p["robot_name"], status="offline", location="等待真实定位",
                        current_task="", map_version="迁移地图", map_id=p["active_map_id"], pose=None,
                        localization_status="unknown", localization_scan_mode="unknown", health={},
                        updated_at=datetime.now(timezone.utc).isoformat()))
        baseline = Path(p["baseline"])
        registry = json.loads((baseline / "robot/map-registry.json").read_text())
        import pwd
        account = pwd.getpwnam(p["service_user"])
        for map_id in registry["maps"]:
            if session.get(MapVersionModel, map_id) is not None:
                continue
            source = baseline / "maps" / map_id
            yaml_data, pgm_data = (source / "map.yaml").read_bytes(), (source / "map.pgm").read_bytes()
            metadata, image = parse_ros_map_yaml(yaml_data, "map.pgm"), parse_pgm(pgm_data)
            directory = Path(settings.map_storage_dir) / map_id
            directory.mkdir(parents=True, exist_ok=True)
            os.chown(directory, account.pw_uid, account.pw_gid)
            directory.chmod(0o750)
            for name, data in (("map.yaml", yaml_data), ("map.pgm", pgm_data), ("preview.png", pgm_preview_png(image, metadata))):
                file = directory / name
                file.write_bytes(data)
                os.chown(file, account.pw_uid, account.pw_gid)
                file.chmod(0o640)
            session.add(MapVersionModel(id=map_id, name=map_id, version="baseline", yaml_file="map.yaml", pgm_file="map.pgm",
                width=image.width, height=image.height, resolution=metadata.resolution, origin=list(metadata.origin),
                mode=metadata.mode, negate=metadata.negate, occupied_threshold=metadata.occupied_threshold,
                free_threshold=metadata.free_threshold, status="published", created_at=datetime.now(timezone.utc), created_by="admin"))
    if all(p["battery"].get(key) is not None for key in ("capacity_ah", "nominal_voltage_v")):
        from app.battery import BatteryStore
        # Nominal specifications transfer; SOC/full-charge confirmation and samples do not.
        battery = BatteryStore(settings.battery_state_file, p["robot_id"])
        battery.configure(p["battery"]["capacity_ah"], p["battery"]["nominal_voltage_v"])
        import pwd
        account = pwd.getpwnam(p["service_user"])
        os.chown(settings.battery_state_file, account.pw_uid, account.pw_gid)
        os.chmod(settings.battery_state_file, 0o600)
    database.engine.dispose()


def main():
    p = json.loads(Path(sys.argv[1]).read_text())
    os.environ.update(read_env("/etc/lr-platform/control-api.env"))
    from app.config import Settings

    private = json.loads(Path("/etc/lr-platform/setup-secrets.json").read_text())
    provision(p, private, Settings(_env_file=None))


if __name__ == "__main__":
    main()
