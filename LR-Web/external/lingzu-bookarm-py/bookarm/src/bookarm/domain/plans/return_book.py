"""Calibrated motion plan for returning a book to a shelf beside a located reference book."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Tuple

from bookarm.domain.models.pose import JointPose
from bookarm.domain.plans.take_book import GripperCommand


@dataclass(frozen=True)
class ReturnBookMotionPlan:
    """Shared poses, positions, and durations for the return-book workflow.

    The flow picks the book to be returned from the calibrated book-stand
    pickup slot and re-locates the reference book. In the insert chain, target
    grasp x/y plus each step's XY offset and its absolute arm-base z form the
    end-effector target position. Each step also has an independent attitude.
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
    # Open the gripper this far before the book-slot pickup.
    pickup_open_deg: float = 50.0
    # Lightly close at the slot, then adjust grasp depth and attitude from the measured TCP.
    pickup_light_close_deg: float = 70.0
    pickup_light_close_down_cm: float = 1.0
    pickup_light_close_rpy_offset_deg: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    pregrasp_duration_s: float = 3.0
    # Rod homing runs after the debug pose and before target recognition.
    rod_home_deg: float = 0.0
    rod_speed: int = 1000
    rod_acceleration: int = 50
    rod_tolerance_deg: float = 1.5
    rod_timeout_s: float = 12.0
    # XY offsets from the recognized target, plus absolute arm-base z (metres).
    pre_insert_xy_offset_m: Tuple[float, float] = (0.30, 0.04)
    pre_insert_z_m: float = 0.04
    insert_xy_offset_m: Tuple[float, float] = (0.0, 0.04)
    insert_z_m: float = 0.04
    push_xy_offset_m: Tuple[float, float] = (-0.05, 0.04)
    push_z_m: float = 0.04
    # Independent orientations for the pre-insert and insert poses. rx beyond
    # ~95 deg is outside the workspace at deep-shelf targets.
    pre_insert_rpy_deg: Tuple[float, float, float] = (95.0, 0.0, 90.0)
    insert_rpy_deg: Tuple[float, float, float] = (95.0, 0.0, 90.0)
    pre_insert_duration_s: float = 3.0
    insert_duration_s: float = 3.0
    # Push-pose orientation offset relative to the insert pose's
    # insert_rpy_deg orientation (deg); (0, 0, 0) keeps the insert attitude
    # (末尾还书专用，中位还书没有这个旋钮，共享插入链按字段是否存在分支）。
    push_rpy_deg: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    push_duration_s: float = 2.0
    # Partially open the gripper to release the book (not the full stroke).
    release_open_deg: float = 50.0
    # Retract from the push pose: only x changes (positive x leaves the shelf).
    retract_x_offset_cm: float = 10.0
    # Retract-pose orientation, a fixed value that does NOT follow the
    # insert/push attitude (insert_rpy_deg / push_rpy_deg have no effect on
    # it) — 末尾还书专用，中位还书没有该字段，回抽继续继承推回位姿态。
    retract_rpy_deg: Tuple[float, float, float] = (90.0, 0.0, 90.0)
    retract_duration_s: float = 2.0
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

