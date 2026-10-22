"""Calibrated motion plan for the take-book use case."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Tuple

from bookarm.domain.models.pose import JointPose


@dataclass(frozen=True)
class GripperCommand:
    open_deg: float = 30.0
    close_deg: float = 108.5
    open_speed_deg_s: float = 16.7
    close_speed_deg_s: float = 16.7
    effort: float = 0.50
    kp: float = 40.0
    kd: float = 3.0
    timeout_s: float = 10.0
    monitor_period_s: float = 0.05
    target_tolerance_deg: float = 2.0
    # These legacy-named fields define expected book contact: once the command
    # leads feedback, feedback must remain within this motion window long enough.
    stall_tolerance_deg: float = 0.4
    stall_time_s: float = 0.6
    min_monitor_s: float = 0.4
    hold_margin_deg: float = 0.5
    command_lead_s: float = 0.25
    stall_lead_threshold_deg: float = 3.0
    close_timeout_margin_s: float = 1.5
    start_effort: float = 0.60
    start_boost_s: float = 0.4
    # After object contact, keep a small closing lead with repeated commands.
    contact_hold_offset_deg: float = 2.0
    contact_hold_duration_s: float = 1.0
    contact_hold_rate_hz: float = 20.0
    # Two-stage grip ("grip-and-relax"): once contact has settled (object
    # contact or target reached), the control loop keeps re-sending a carry
    # frame with this reduced holding torque and lead, instead of the full
    # effort used while closing. Keeps the book without overheating motor 7.
    carry_effort: float = 0.20
    carry_lead_deg: float = 1.0


@dataclass(frozen=True)
class TakeBookMotionPlan:
    """Existing GUI takeout steps 4--10 as configuration, not widget state."""

    zero_joint: JointPose = field(
        default_factory=lambda: JointPose.from_values((0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
    )
    debug_joint: JointPose = field(
        default_factory=lambda: JointPose.from_values(
            tuple(math.radians(value) for value in (0.0, 10.0, -65.0, 50.0, 0.0, 0.0))
        )
    )
    pregrasp_offset_cm: Tuple[float, float, float] = (10.0, 0.0, 0.0)
    # Match the deployed/example take-book calibration. The previous 60°
    # default is outside the IK workspace for a boundary shelf position that
    # is reachable with the calibrated 75° wrist approach.
    grasp_rpy_deg: Tuple[float, float, float] = (75.0, 0.0, 90.0)
    # Approach is the straight-line middle leg between pregrasp and the spine:
    # only the x component should be nonzero in practice.
    approach_offset_cm: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    fine_grasp_offset_cm: Tuple[float, float, float] = (1.0, 1.5, 0.0)
    # Keep the final insertion wrist inside the 0.20 rad comfort margin across
    # the calibrated horizontal shelf workspace. 95° made the center-band IK
    # probe reject every candidate near the field-tested target.
    fine_grasp_rpy_deg: Tuple[float, float, float] = (80.0, 0.0, 90.0)
    post_grasp_offset_cm: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    post_grasp_rpy_offset_deg: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    rod_grasp_deg: float = -70.0
    # Home/stow position the rod returns to before and after hooking.
    rod_home_deg: float = 0.0
    rod_speed: int = 1000
    rod_acceleration: int = 50
    zero_duration_s: float = 3.0
    pregrasp_duration_s: float = 3.0
    approach_duration_s: float = 2.0
    fine_grasp_duration_s: float = 2.0
    post_grasp_duration_s: float = 2.0
    debug_duration_s: float = 3.0
    joint_tolerance_rad: float = 0.08
    rod_tolerance_deg: float = 1.5
    rod_timeout_s: float = 12.0
    # Unified speed preset ("slow"/"standard"/"fast"); scales every
    # *_duration_s, rod_speed and the gripper speeds/timing via
    # domain.plans.speed. "standard" is the exact legacy behaviour.
    speed_level: str = "standard"
    gripper: GripperCommand = field(default_factory=GripperCommand)
    # ---- 识别后置校验与车辆对齐（post-vision，取/还/中位共用语义）----
    # 书脊与画面竖直方向夹角超过该值判定不可执行（>60° 一般为倒伏/斜插）
    spine_tilt_max_deg: float = 60.0
    # 兜底识别（轴对齐矩形）无倾斜信息时是否判失败；默认放行并记日志
    spine_tilt_fail_on_unknown: bool = False
    # 取书时的画面横向搜索上限；IK 舒适区计算最多使用正中 20% 候选窗口，
    # 并依据当前书脊深度与完整抓取姿态链进一步收窄。
    align_center_band_ratio: float = 0.40
    # Optional workspace clearance beyond the unchanged mechanical joint limits.
    # Per-machine calibration may reduce this to the normal IK margin (0.05 rad).
    align_joint_comfort_margin_rad: float = 0.20
    # 车辆对齐低速由车端配置；该字段保留旧 profile 兼容。
    align_pulse_speed_mps: float = 0.03
    # 旧调参字段，仅为读取历史 profile 保留；运行时使用外参估算距离，
    # 每次最多 20 cm（车端定距接口的硬上限）。
    align_step_cm: float = 20.0
    # 旧版像素距离增益，保留 profile 兼容；运行时距离由相机外参映射计算。
    align_px_to_mm: float = 0.5
    align_pulse_min_ms: int = 100
    align_pulse_max_ms: int = 500
    # 每次脉冲后的稳定等待
    align_settle_ms: int = 600
    align_max_moves: int = 8
    align_max_travel_m: float = 0.20
    # 画面偏右需要前进=1，需要后退=-1（相机安装方向决定，现场标定）
    align_direction_sign: int = 1

