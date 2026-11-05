"""Calibrated motion plan for returning a book to the middle of a shelf gap."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Tuple

from bookarm.domain.models.pose import JointPose
from bookarm.domain.plans.take_book import GripperCommand


@dataclass(frozen=True)
class MidReturnMotionPlan:
    """Shared poses, offsets, and durations for the mid-return workflow.

    Stage one reuses the take-book grasp chain (open, rod home, pregrasp,
    approach, rod hook, fine grasp, close). Stage two puts the pulled book
    back loosely: push it back into the shelf along x, partially release,
    home the rod, then lower/shift/re-close/re-open/forward to clear the
    gripper out and return to the debug pose. Stage three re-locates the
    target book, then picks the return book from the calibrated stand slot.
    Stage four uses the end-return sequence through the first retract, then
    rotates the empty gripper, presses the book spines, retracts again, and
    returns to debug. The pre-insert, insert, and push steps use recognized
    target XY plus per-step XY offsets and absolute arm-base Z values, with
    independent attitudes.

    All single-axis shifts are expressed as absolute poses chained off the
    cached vision target, so re-running one step stays idempotent.
    """

    zero_joint: JointPose = field(
        default_factory=lambda: JointPose.from_values((0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
    )
    debug_joint: JointPose = field(
        default_factory=lambda: JointPose.from_values(
            tuple(math.radians(value) for value in (0.0, 10.0, -65.0, 50.0, 0.0, 0.0))
        )
    )
    joint_tolerance_rad: float = 0.08
    zero_duration_s: float = 3.0
    debug_duration_s: float = 3.0
    # Open the gripper this far before the grasp chain / the book-slot pickup.
    pickup_open_deg: float = 50.0
    # Lightly close, then adjust depth and attitude from the measured TCP before the full grasp.
    pickup_light_close_deg: float = 70.0
    pickup_light_close_down_cm: float = 1.0
    pickup_light_close_rpy_offset_deg: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    # Grasp phase, mirroring the take-book offsets with mid-return defaults.
    pregrasp_offset_cm: Tuple[float, float, float] = (10.0, 0.0, 0.0)
    grasp_rpy_deg: Tuple[float, float, float] = (75.0, 0.0, 90.0)
    approach_offset_cm: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    fine_grasp_offset_cm: Tuple[float, float, float] = (1.0, 0.0, 0.0)
    fine_grasp_rpy_deg: Tuple[float, float, float] = (80.0, 0.0, 90.0)
    pregrasp_duration_s: float = 3.0
    approach_duration_s: float = 2.0
    fine_grasp_duration_s: float = 2.0
    rod_grasp_deg: float = -70.0
    # Home/stow position the rod returns to before and after hooking.
    rod_home_deg: float = 0.0
    # Put-back phase (step 11): rod target after the re-push, before the
    # lower/shift clear-out chain. Independent of the other rod positions.
    rod_putback_deg: float = 0.0
    # Book-stand pickup phase: independent rod target before closing.
    pickup_rod_home_deg: float = 0.0
    rod_speed: int = 1000
    rod_acceleration: int = 50
    rod_tolerance_deg: float = 1.5
    rod_timeout_s: float = 12.0
    # Push the held book back into the shelf (negative x drives further in).
    push_in_x_offset_cm: float = -5.0
    push_in_duration_s: float = 2.0
    # Release the book just enough to let go (not the full stroke), then push
    # in once more so the fingers sit deep inside the gap before the rod homes.
    partial_release_deg: float = 80.0
    re_push_x_offset_cm: float = -2.0
    re_push_duration_s: float = 2.0
    # Clear-out after releasing: lower (z), shift (y), carry the closed-gripper
    # book forward to a camera-friendly pose (x), slight release, forward (x);
    # the gripper re-closes after the shift and fully re-opens before moving forward.
    full_open_deg: float = 50.0
    lower_z_offset_cm: float = -5.0
    lower_duration_s: float = 2.0
    shift_y_offset_cm: float = 5.0
    shift_duration_s: float = 2.0
    carry_forward_x_offset_cm: float = 5.0
    carry_forward_duration_s: float = 2.0
    forward_x_offset_cm: float = 10.0
    forward_duration_s: float = 2.0
    # Insert chain matches end-return: recognized target XY plus per-step XY
    # offsets, independent absolute arm-base Z, and independent attitudes.
    pre_insert_xy_offset_m: Tuple[float, float] = (0.30, 0.04)
    pre_insert_z_m: float = 0.04
    insert_xy_offset_m: Tuple[float, float] = (0.0, 0.04)
    insert_z_m: float = 0.04
    push_xy_offset_m: Tuple[float, float] = (-0.05, 0.04)
    push_z_m: float = 0.04
    pre_insert_rpy_deg: Tuple[float, float, float] = (95.0, 0.0, 90.0)
    insert_rpy_deg: Tuple[float, float, float] = (95.0, 0.0, 90.0)
    pre_insert_duration_s: float = 3.0
    insert_duration_s: float = 3.0
    push_rpy_deg: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    push_duration_s: float = 2.0
    # Partially open the gripper to release the book (not the full stroke).
    release_open_deg: float = 50.0
    # Retract from the push pose: x changes (positive leaves the shelf), with
    # the same fixed safe attitude as end-return instead of inheriting push.
    retract_x_offset_cm: float = 10.0
    retract_rpy_deg: Tuple[float, float, float] = (90.0, 0.0, 90.0)
    retract_duration_s: float = 2.0
    # Rotate at the retract pose, press the book spines along x, then retract
    # the empty gripper again. Rotation attitude is relative to the retract pose.
    rotate_rpy_deg: Tuple[float, float, float] = (0.0, 90.0, 0.0)
    rotate_z_offset_cm: float = 0.0
    rotate_duration_s: float = 2.0
    press_x_offset_cm: float = -5.0
    press_duration_s: float = 2.0
    press_retract_x_offset_cm: float = 5.0
    press_retract_duration_s: float = 2.0
    # Unified speed preset ("slow"/"standard"/"fast"); see domain.plans.speed.
    speed_level: str = "standard"
    gripper: GripperCommand = field(default_factory=GripperCommand)
    # ---- 识别后置校验与车辆对齐（post-vision，取/还/中位共用语义）----
    # 书脊与画面竖直方向夹角超过该值判定不可执行（>60° 一般为倒伏/斜插）
    spine_tilt_max_deg: float = 60.0
    # 兜底识别（轴对齐矩形）无倾斜信息时是否判失败；默认放行并记日志
    spine_tilt_fail_on_unknown: bool = False
    # 画面正中区域宽度占比（水平方向 0.40 = 正中 40% 带宽）
    align_center_band_ratio: float = 0.40
    # 车辆对齐低速由车端配置；该字段保留旧 profile 兼容。
    align_pulse_speed_mps: float = 0.03
    # 旧调参字段，仅为读取历史 profile 保留；运行时使用外参估算距离，
    # 每次最多 20 cm（车端定距接口的硬上限）。
    align_step_cm: float = 20.0
    # 旧版像素距离增益，保留 profile 兼容；运行时距离由相机外参映射计算。
    align_px_to_mm: float = 0.5
    # 旧版脉冲接口参数，保留 profile 兼容；定距移动的速度/停车由车端控制。
    align_pulse_min_ms: int = 100
    align_pulse_max_ms: int = 500
    # 每次底盘定距移动后的稳定等待
    align_settle_ms: int = 600
    align_max_moves: int = 8
    align_max_travel_m: float = 0.20
    # 画面偏右需要前进=1，需要后退=-1（相机安装方向决定，现场标定）
    align_direction_sign: int = 1

