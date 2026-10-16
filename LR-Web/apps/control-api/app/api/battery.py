"""Read-only telemetry plus explicit operator battery calibration."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Literal

from ..battery import BatteryStore
from ..config import get_settings
from ..dependencies import get_current_user
from ..schemas import User

router = APIRouter(prefix="/api/v1/power/battery", tags=["battery"])


def battery_store() -> BatteryStore:
    settings = get_settings()
    return BatteryStore(settings.battery_state_file, settings.battery_robot_id)


class BatteryConfig(BaseModel):
    capacityAh: float = Field(gt=0, le=10000, allow_inf_nan=False)
    nominalVoltageV: float = Field(gt=0, le=1000, allow_inf_nan=False)


class FullCalibration(BaseModel):
    confirmFull: Literal[True]
    confirmUnplugged: bool = False


@router.get("")
def get_battery():
    return battery_store().snapshot()


@router.put("/config")
def configure_battery(request: BatteryConfig, user: User = Depends(get_current_user)):
    if user.role != "系统管理员":
        raise HTTPException(status_code=403, detail="只有系统管理员可以修改电池配置")
    store = battery_store()
    store.configure(request.capacityAh, request.nominalVoltageV)
    return store.snapshot()


@router.post("/calibrate-full")
def calibrate_full(request: FullCalibration, user: User = Depends(get_current_user)):
    if user.role != "系统管理员":
        raise HTTPException(status_code=403, detail="只有系统管理员可以校准电量")
    store = battery_store()
    try:
        store.calibrate_full(confirm_unplugged=request.confirmUnplugged)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return store.snapshot()
