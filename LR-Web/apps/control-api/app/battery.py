"""Local XT369 discharge accounting. No voltage-to-SOC guess or charging inference."""
from __future__ import annotations

import json
import math
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FRESH_SECONDS = 5.0
MAX_INTEGRATION_GAP = 5.0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def boot_id() -> str:
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


class BatteryStore:
    def __init__(self, path: str | Path, robot_id: str = "LR-01"):
        self.path = Path(path)
        self.robot_id = robot_id

    @contextmanager
    def _transaction(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5)
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS battery (id INTEGER PRIMARY KEY CHECK(id=1), state TEXT NOT NULL)")
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT state FROM battery WHERE id=1").fetchone()
            state = json.loads(row[0]) if row else {
                "capacityAh": None, "nominalVoltageV": None,
                "calibratedAt": None, "consumedAh": 0.0, "consumedWh": 0.0,
                "gapSeconds": 0.0, "continuityLost": False, "sampleCount": 0,
                "last": None, "previous": None, "error": None,
            }
            # Keep invalid historical estimates invalid when removing the old
            # manual charging feature. A full calibration establishes a new basis.
            state.setdefault("needsCalibration", True)
            if "powerMode" in state:
                if state.pop("powerMode") != "discharging":
                    state["needsCalibration"] = True
                state.pop("powerModeUpdatedAt", None)
            yield state
            conn.execute("INSERT INTO battery(id,state) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state",
                         (json.dumps(state, allow_nan=False),))
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self, capacity_ah: float, nominal_voltage_v: float, *, confirmed_full: bool = False):
        if not all(math.isfinite(x) and x > 0 for x in (capacity_ah, nominal_voltage_v)):
            raise ValueError("电池容量与标称电压必须为正数")
        with self._transaction() as state:
            if state["capacityAh"] is None:
                state.update(capacityAh=capacity_ah, nominalVoltageV=nominal_voltage_v)
                if confirmed_full:
                    state["calibratedAt"] = utc_now()
                    state["needsCalibration"] = False

    def record(self, measurement: Any, *, device_serial: str, boot: str | None = None):
        voltage = float(measurement.voltage_v)
        current = float(measurement.current_a)
        monotonic = float(measurement.received_monotonic)
        if not all(math.isfinite(x) for x in (voltage, current, monotonic)) or voltage <= 0 or current < 0:
            raise ValueError("XT369 返回无效电压或电流")
        sample = {
            "voltageV": voltage, "currentA": current, "powerW": voltage * current,
            "receivedAt": measurement.received_at, "monotonic": monotonic,
            "wallTime": time.time(), "bootId": boot or boot_id(), "serial": device_serial,
        }
        with self._transaction() as state:
            previous = state["previous"]
            if (previous and state["calibratedAt"]
                    and not state["needsCalibration"]):
                same_device = previous["serial"] == device_serial
                same_boot = previous["bootId"] == sample["bootId"]
                dt = monotonic - previous["monotonic"] if same_boot else sample["wallTime"] - previous["wallTime"]
                if same_device and same_boot and 0 < dt <= MAX_INTEGRATION_GAP:
                    state["consumedAh"] += (previous["currentA"] + current) * 0.5 * dt / 3600
                    state["consumedWh"] += (previous["powerW"] + sample["powerW"]) * 0.5 * dt / 3600
                else:
                    state["continuityLost"] = True
                    state["gapSeconds"] += max(0, dt)
            state.update(previous=sample, last=sample, error=None, sampleCount=state["sampleCount"] + 1)

    def fail(self, message: str):
        with self._transaction() as state:
            state["error"] = message

    def configure(self, capacity_ah: float, nominal_voltage_v: float):
        if not all(math.isfinite(x) and x > 0 for x in (capacity_ah, nominal_voltage_v)):
            raise ValueError("电池容量与标称电压必须为正数")
        with self._transaction() as state:
            state.update(capacityAh=capacity_ah, nominalVoltageV=nominal_voltage_v)

    def calibrate_full(self, *, confirm_unplugged: bool = False,
                       now: float | None = None, boot: str | None = None):
        with self._transaction() as state:
            last = state["last"]
            mono = time.monotonic() if now is None else now
            if (not last or last["bootId"] != (boot or boot_id())
                    or not 0 <= mono - last["monotonic"] <= FRESH_SECONDS or state["error"]):
                raise ValueError("请先连接 XT369 并等待有效读数，再确认电池已充满")
            if not state["capacityAh"]:
                raise ValueError("请先设置电池容量")
            if not confirm_unplugged:
                raise ValueError("当前接线无法测量充电电流，请确认电池已充满且充电器已拔下")
            # Do not integrate the part of the prior sample interval before calibration.
            state.update(calibratedAt=utc_now(), consumedAh=0.0, consumedWh=0.0,
                         gapSeconds=0.0, continuityLost=False, previous=None,
                         needsCalibration=False)

    def snapshot(self, *, now: float | None = None, boot: str | None = None) -> dict[str, Any]:
        with self._transaction() as state:
            state = dict(state)
        last = state["last"]
        mono = time.monotonic() if now is None else now
        age = mono - last["monotonic"] if last and last["bootId"] == (boot or boot_id()) else None
        online = bool(last and age is not None and 0 <= age <= FRESH_SECONDS and not state["error"])
        calibrated = bool(state["capacityAh"] and state["calibratedAt"])
        remaining = max(0.0, state["capacityAh"] - state["consumedAh"]) if calibrated else None
        percent = max(0.0, min(100.0, 100 * remaining / state["capacityAh"])) if calibrated else None
        valid_soc = online and not state["needsCalibration"]
        return {
            "source": "XT369 USB", "robotId": self.robot_id, "status": "online" if online else "offline",
            "percent": percent if valid_soc else None, "lastPercent": percent,
            "capacityAh": state["capacityAh"], "nominalVoltageV": state["nominalVoltageV"],
            "remainingAh": remaining if valid_soc else None,
            "consumedAh": state["consumedAh"], "consumedWh": state["consumedWh"],
            "voltageV": last["voltageV"] if online else None,
            "currentA": last["currentA"] if online else None,
            "powerW": last["powerW"] if online else None,
            "updatedAt": last["receivedAt"] if last else None,
            "calibratedAt": state["calibratedAt"],
            "quality": "uncalibrated" if not calibrated or state["needsCalibration"] else ("gap" if state["continuityLost"] else "estimated"),
            "gapSeconds": state["gapSeconds"], "sampleCount": state["sampleCount"],
            "deviceSerial": last["serial"] if last else None,
            "error": state["error"] if state["error"] else (None if online else "等待 XT369 有效数据"),
        }
