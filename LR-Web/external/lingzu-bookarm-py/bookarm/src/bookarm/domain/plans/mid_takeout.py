"""Motion plan for mid takeout, with an independent post-grasp chain."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple

from bookarm.domain.plans.mid_return import MidReturnMotionPlan
from bookarm.domain.plans.take_book import GripperCommand


@dataclass(frozen=True)
class MidTakeoutMotionPlan(MidReturnMotionPlan):
    gripper: GripperCommand = field(
        default_factory=lambda: GripperCommand(kp=40.0, kd=3.0, carry_effort=0.2)
    )
    raise_z_offset_cm: float = 3.0
    raise_duration_s: float = 2.0
    lower_offset_cm: Tuple[float, float, float] = (0.0, 0.0, -5.0)
    lower_rpy_offset_deg: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    post_grasp_offset_cm: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    post_grasp_rpy_offset_deg: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    post_grasp_duration_s: float = 2.0
