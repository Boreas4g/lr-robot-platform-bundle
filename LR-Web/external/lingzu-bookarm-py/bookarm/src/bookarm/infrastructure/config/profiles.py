"""Load optional workflow motion profiles without embedding GUI state."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence, Tuple

from bookarm.devices.rod.service import RodMotorService
from bookarm.domain.models.pose import JointPose
from bookarm.domain.plans.mid_return import MidReturnMotionPlan
from bookarm.domain.plans.mid_takeout import MidTakeoutMotionPlan
from bookarm.domain.plans.return_book import ReturnBookMotionPlan
from bookarm.domain.plans.speed import (
    DEFAULT_SPEED_LEVEL,
    apply_speed_level,
    validate_speed_level,
)
from bookarm.domain.plans.take_book import GripperCommand, TakeBookMotionPlan


def load_return_book_motion_plan(path: Path) -> ReturnBookMotionPlan:
    """Load a return-book plan and reject unknown or malformed fields."""

    source = dict(_read_json(path, "return-book profile"))
    # Deliberate migration: retired position fields are ignored; steps 7-9
    # use target-relative XY offsets and absolute arm-base z values.
    for legacy_name in (
        "pre_insert_x_m",
        "pre_insert_x_max_m",
        "target_y_offset_cm",
        "insert_offset_cm",
        "min_insert_z_m",
        "pre_insert_y_offset_cm",
        "pre_insert_z_offset_cm",
        "push_x_offset_cm",
        "push_z_offset_cm",
        "pre_insert_position_m",
        "insert_position_m",
        "push_position_m",
    ):
        source.pop(legacy_name, None)
    gripper_value = source.get("gripper", {})
    if not isinstance(gripper_value, Mapping):
        raise ValueError("return-book profile gripper must be an object")
    defaults = ReturnBookMotionPlan()
    unexpected = set(source.keys()) - set(defaults.__dataclass_fields__.keys())
    if unexpected:
        raise ValueError("return-book profile has unknown fields: %s" % ", ".join(sorted(unexpected)))
    gripper_unexpected = set(gripper_value.keys()) - set(defaults.gripper.__dataclass_fields__.keys())
    if gripper_unexpected:
        raise ValueError(
            "return-book gripper profile has unknown fields: %s"
            % ", ".join(sorted(gripper_unexpected))
        )
    values = dict(source)
    values["zero_joint"] = _joint(source.get("zero_joint", defaults.zero_joint.values_rad), "zero_joint")
    values["debug_joint"] = _joint(
        source.get("debug_joint", defaults.debug_joint.values_rad), "debug_joint"
    )
    for name in (
        "pre_insert_xy_offset_m",
        "insert_xy_offset_m",
        "push_xy_offset_m",
    ):
        values[name] = _pair(source.get(name, getattr(defaults, name)), name)
    for name in ("pre_insert_z_m", "insert_z_m", "push_z_m"):
        value = float(source.get(name, getattr(defaults, name)))
        if not math.isfinite(value):
            raise ValueError("%s must be finite" % name)
        values[name] = value
    for name in (
        "pickup_light_close_rpy_offset_deg",
        "pre_insert_rpy_deg",
        "insert_rpy_deg",
        "push_rpy_deg",
        "retract_rpy_deg",
    ):
        values[name] = _triple(source.get(name, getattr(defaults, name)), name)
    values["rod_home_deg"] = _rod_angle(
        source.get("rod_home_deg", defaults.rod_home_deg), "rod_home_deg"
    )
    values["gripper"] = GripperCommand(**dict(gripper_value))
    values["speed_level"] = validate_speed_level(
        source.get("speed_level", DEFAULT_SPEED_LEVEL)
    )
    _validate_post_vision_fields(values)
    return apply_speed_level(ReturnBookMotionPlan(**values))


def load_take_book_motion_plan(path: Path) -> TakeBookMotionPlan:
    """Load a complete take-book plan and reject unknown/incomplete profiles."""

    source = _read_json(path, "take-book profile")
    gripper_value = source.get("gripper", {})
    if not isinstance(gripper_value, Mapping):
        raise ValueError("take-book profile gripper must be an object")
    defaults = TakeBookMotionPlan()
    allowed = set(defaults.__dataclass_fields__.keys())
    unexpected = set(source.keys()) - allowed
    if unexpected:
        raise ValueError("take-book profile has unknown fields: %s" % ", ".join(sorted(unexpected)))
    gripper_allowed = set(defaults.gripper.__dataclass_fields__.keys())
    gripper_unexpected = set(gripper_value.keys()) - gripper_allowed
    if gripper_unexpected:
        raise ValueError("take-book gripper profile has unknown fields: %s" % ", ".join(sorted(gripper_unexpected)))
    values = dict(source)
    values["zero_joint"] = _joint(source.get("zero_joint", defaults.zero_joint.values_rad), "zero_joint")
    values["debug_joint"] = _joint(source.get("debug_joint", defaults.debug_joint.values_rad), "debug_joint")
    for name in (
        "pregrasp_offset_cm",
        "grasp_rpy_deg",
        "approach_offset_cm",
        "fine_grasp_offset_cm",
        "fine_grasp_rpy_deg",
        "post_grasp_offset_cm",
        "post_grasp_rpy_offset_deg",
    ):
        values[name] = _triple(source.get(name, getattr(defaults, name)), name)
    values["rod_grasp_deg"] = _rod_angle(
        source.get("rod_grasp_deg", defaults.rod_grasp_deg), "rod_grasp_deg"
    )
    values["rod_home_deg"] = _rod_angle(
        source.get("rod_home_deg", defaults.rod_home_deg), "rod_home_deg"
    )
    values["gripper"] = GripperCommand(**dict(gripper_value))
    values["speed_level"] = validate_speed_level(
        source.get("speed_level", DEFAULT_SPEED_LEVEL)
    )
    _validate_post_vision_fields(values)
    return apply_speed_level(TakeBookMotionPlan(**values))


def _mid_plan_values(
    source: Mapping[str, Any], defaults: MidReturnMotionPlan
) -> dict[str, Any]:
    source = dict(source)
    gripper_value = source.get("gripper", {})
    if not isinstance(gripper_value, Mapping):
        raise ValueError("mid-return profile gripper must be an object")
    for legacy_name in (
        "pre_insert_x_m",
        "pre_insert_x_max_m",
        "target_y_offset_cm",
        "insert_offset_cm",
        "min_insert_z_m",
        "pre_insert_y_offset_cm",
        "pre_insert_z_offset_cm",
        "push_x_offset_cm",
        "push_z_offset_cm",
        "rod_insert_deg",
    ):
        source.pop(legacy_name, None)
    legacy_forward_cm = source.pop("pickup_light_close_forward_cm", None)
    if legacy_forward_cm is not None and "pickup_light_close_down_cm" not in source:
        source["pickup_light_close_down_cm"] = legacy_forward_cm
    source.pop("pickup_raise_z_offset_cm", None)
    unexpected = set(source.keys()) - set(defaults.__dataclass_fields__.keys())
    if unexpected:
        raise ValueError(
            "mid-return profile has unknown fields: %s" % ", ".join(sorted(unexpected))
        )
    gripper_unexpected = set(gripper_value.keys()) - set(defaults.gripper.__dataclass_fields__.keys())
    if gripper_unexpected:
        raise ValueError(
            "mid-return gripper profile has unknown fields: %s"
            % ", ".join(sorted(gripper_unexpected))
        )
    values = dict(source)
    values["zero_joint"] = _joint(source.get("zero_joint", defaults.zero_joint.values_rad), "zero_joint")
    values["debug_joint"] = _joint(
        source.get("debug_joint", defaults.debug_joint.values_rad), "debug_joint"
    )
    for name in (
        "pregrasp_offset_cm",
        "grasp_rpy_deg",
        "approach_offset_cm",
        "fine_grasp_offset_cm",
        "fine_grasp_rpy_deg",
        "pickup_light_close_rpy_offset_deg",
        "pre_insert_rpy_deg",
        "insert_rpy_deg",
        "push_rpy_deg",
        "retract_rpy_deg",
        "rotate_rpy_deg",
    ):
        values[name] = _triple(source.get(name, getattr(defaults, name)), name)
    for name in (
        "pre_insert_xy_offset_m",
        "insert_xy_offset_m",
        "push_xy_offset_m",
    ):
        values[name] = _pair(source.get(name, getattr(defaults, name)), name)
    for name in ("pre_insert_z_m", "insert_z_m", "push_z_m"):
        value = float(source.get(name, getattr(defaults, name)))
        if not math.isfinite(value):
            raise ValueError("%s must be finite" % name)
        values[name] = value
    values["rod_grasp_deg"] = _rod_angle(
        source.get("rod_grasp_deg", defaults.rod_grasp_deg), "rod_grasp_deg"
    )
    values["rod_home_deg"] = _rod_angle(
        source.get("rod_home_deg", defaults.rod_home_deg), "rod_home_deg"
    )
    values["rod_putback_deg"] = _rod_angle(
        source.get("rod_putback_deg", defaults.rod_putback_deg), "rod_putback_deg"
    )
    values["pickup_rod_home_deg"] = _rod_angle(
        source.get("pickup_rod_home_deg", defaults.pickup_rod_home_deg),
        "pickup_rod_home_deg",
    )
    values["gripper"] = replace(defaults.gripper, **dict(gripper_value))
    values["speed_level"] = validate_speed_level(
        source.get("speed_level", DEFAULT_SPEED_LEVEL)
    )
    _validate_post_vision_fields(values)
    return values


def load_mid_return_motion_plan(path: Path) -> MidReturnMotionPlan:
    """Load a mid-return plan and reject unknown or malformed fields."""

    values = _mid_plan_values(
        dict(_read_json(path, "mid-return profile")), MidReturnMotionPlan()
    )
    return apply_speed_level(MidReturnMotionPlan(**values))


def load_mid_takeout_motion_plan(path: Path) -> MidTakeoutMotionPlan:
    """Load the independent mid-takeout plan and its post-grasp fields."""

    defaults = MidTakeoutMotionPlan()
    values = _mid_plan_values(
        dict(_read_json(path, "mid-takeout profile")), defaults
    )
    if "lower_offset_cm" not in values:
        values["lower_offset_cm"] = (
            0.0,
            0.0,
            values.get("lower_z_offset_cm", defaults.lower_offset_cm[2]),
        )
    for name in (
        "lower_offset_cm",
        "lower_rpy_offset_deg",
        "post_grasp_offset_cm",
        "post_grasp_rpy_offset_deg",
    ):
        values[name] = _triple(values.get(name, getattr(defaults, name)), name)
    return apply_speed_level(MidTakeoutMotionPlan(**values))


def _validate_post_vision_fields(values: Mapping[str, Any]) -> None:
    """识别后校验与车辆对齐参数的边界校验（三个 profile loader 共用）。"""

    tilt = float(values.get("spine_tilt_max_deg", 60.0))
    if not math.isfinite(tilt) or not 5.0 <= tilt <= 89.0:
        raise ValueError("spine_tilt_max_deg must be within 5.0..89.0 degrees")
    band = float(values.get("align_center_band_ratio", 0.40))
    if not math.isfinite(band) or not 0.05 <= band <= 0.9:
        raise ValueError("align_center_band_ratio must be within 0.05..0.9")
    margin = float(values.get("align_joint_comfort_margin_rad", 0.20))
    if not math.isfinite(margin) or not 0.05 <= margin <= 0.20:
        raise ValueError("align_joint_comfort_margin_rad must be within 0.05..0.20 rad")
    speed = float(values.get("align_pulse_speed_mps", 0.03))
    if not math.isfinite(speed) or not 0.005 <= speed <= 0.08:
        raise ValueError("align_pulse_speed_mps must be within 0.005..0.08 m/s")
    step_cm = float(values.get("align_step_cm", 20.0))
    if not math.isfinite(step_cm) or not 0.1 <= step_cm <= 20.0:
        raise ValueError("align_step_cm must be within 0.1..20.0 cm")
    # align_px_to_mm is a legacy profile field; live D435 extrinsics now supply
    # the pixel-to-base projection used for the distance command.
    pulse_min = int(values.get("align_pulse_min_ms", 100))
    pulse_max = int(values.get("align_pulse_max_ms", 500))
    if not 20 <= pulse_min <= pulse_max <= 500:
        raise ValueError("align_pulse_min/max_ms must satisfy 20<=min<=max<=500")
    if int(values.get("align_settle_ms", 600)) < 0:
        raise ValueError("align_settle_ms must be >= 0")
    if int(values.get("align_max_moves", 8)) < 1:
        raise ValueError("align_max_moves must be >= 1")
    travel = float(values.get("align_max_travel_m", 0.20))
    if not math.isfinite(travel) or not 0.02 <= travel <= 1.0:
        raise ValueError("align_max_travel_m must be within 0.02..1.0 m")
    if int(values.get("align_direction_sign", 1)) not in (-1, 1):
        raise ValueError("align_direction_sign must be 1 or -1")

def _read_json(path: Path, label: str) -> Mapping[str, Any]:
    path = Path(path)
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except FileNotFoundError as error:
        raise FileNotFoundError("%s file not found: %s" % (label, path)) from error
    except json.JSONDecodeError as error:
        raise ValueError("%s is not valid JSON: %s" % (label, error)) from error
    if not isinstance(value, Mapping):
        raise ValueError("%s root must be an object" % label)
    return value


def _joint(value: Any, name: str) -> JointPose:
    try:
        return JointPose.from_values(_triple_or_six(value, name, 6))
    except (TypeError, ValueError) as error:
        raise ValueError("%s is invalid: %s" % (name, error)) from error


def _pair(value: Any, name: str) -> Tuple[float, float]:
    values = _triple_or_six(value, name, 2)
    return (float(values[0]), float(values[1]))


def _triple(value: Any, name: str) -> Tuple[float, float, float]:
    values = _triple_or_six(value, name, 3)
    return (float(values[0]), float(values[1]), float(values[2]))


def _rod_angle(value: Any, name: str) -> float:
    """Rod angles share the device hard limits so bad values fail at load."""

    try:
        angle = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("%s must be a number" % name) from error
    if not math.isfinite(angle) or not (
        RodMotorService.MIN_ANGLE_DEG <= angle <= RodMotorService.MAX_ANGLE_DEG
    ):
        raise ValueError(
            "%s must be between %.1f and %.1f deg; got %r"
            % (name, RodMotorService.MIN_ANGLE_DEG, RodMotorService.MAX_ANGLE_DEG, angle)
        )
    return angle


def _triple_or_six(value: Any, name: str, size: int) -> Sequence[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != size:
        raise ValueError("%s must contain %d values" % (name, size))
    values = tuple(float(item) for item in value)
    if not all(math.isfinite(item) for item in values):
        raise ValueError("%s must contain finite values" % name)
    return values
