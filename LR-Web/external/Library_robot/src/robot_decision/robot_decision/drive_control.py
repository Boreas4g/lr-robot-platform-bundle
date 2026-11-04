from __future__ import annotations

import math
from typing import Any, Literal


ControlMode = Literal["differential", "ackermann"]
DIFFERENTIAL = "differential"
ACKERMANN = "ackermann"
DEFAULT_MIN_TURNING_RADIUS_M = 1.0
DEFAULT_MIN_TURN_LINEAR_SPEED_MPS = 0.08


def control_mode(payload: dict[str, Any]) -> ControlMode:
    value = payload.get("controlMode", DIFFERENTIAL)
    if value not in {DIFFERENTIAL, ACKERMANN}:
        raise ValueError("controlMode must be differential or ackermann")
    return value


def constrain_ackermann_velocity(
    linear: float,
    angular: float,
    min_turning_radius: float = DEFAULT_MIN_TURNING_RADIUS_M,
    min_turn_linear_speed: float = DEFAULT_MIN_TURN_LINEAR_SPEED_MPS,
) -> tuple[float, float]:
    if not math.isfinite(linear) or not math.isfinite(angular):
        raise ValueError("velocity must be finite")
    if min_turning_radius <= 0.0 or min_turn_linear_speed <= 0.0:
        raise ValueError("turning constraints must be positive")
    if angular == 0.0 or (linear == 0.0 and angular == 0.0):
        return linear, angular
    if abs(linear) < min_turn_linear_speed:
        linear = math.copysign(min_turn_linear_speed, linear if linear != 0.0 else 1.0)
    max_angular = abs(linear) / min_turning_radius
    return linear, max(-max_angular, min(max_angular, angular))
