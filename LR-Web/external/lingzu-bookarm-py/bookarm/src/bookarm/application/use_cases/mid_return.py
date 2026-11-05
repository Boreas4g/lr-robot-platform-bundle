"""Return one onboard book to the middle of a shelf gap (mid-return)."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any, Dict, Optional, Sequence, Union

from bookarm.api.requests import MidReturnBookRequest, MidReturnStage
from bookarm.api.results import WorkflowResult, WorkflowTask
from bookarm.application.post_vision import post_vision_check_align, search_max_reachable_x
from bookarm.application.task_manager import TaskManager
from bookarm.application.use_cases.mid_flow import run_mid_grasp_chain, run_mid_put_back_prefix
from bookarm.application.workflow_engine import WorkflowEngine
from bookarm.domain.models.book import BookTarget, SpineTemplate
from bookarm.domain.models.pose import BasePose, JointPose
from bookarm.domain.models.shelf import BookStandPickupPlan
from bookarm.domain.models.task import WorkflowKind
from bookarm.domain.plans.mid_return import MidReturnMotionPlan
from bookarm.domain.plans.return_book import ReturnBookMotionPlan
from bookarm.domain.plans.take_book import GripperCommand
from bookarm.domain.policies.gripper import ensure_grasp_contact
from bookarm.domain.policies.safety import ensure_joint_target
from bookarm.ports.devices import ArmPort, LiftPort, ReservationPort, RodPort, VisionPort


# The return-book flow runs this same insert pipeline with target-relative
# positions, so the shared stages are module-level helpers parameterized by plan.
InsertChainPlan = Union[MidReturnMotionPlan, ReturnBookMotionPlan]


class OffworkerArmProbe:
    """ArmPort-shaped adapter routing IK probes off the arm command worker.

    Tuning previews/steps run on HTTP request threads and must not queue
    behind a running motion on the arm worker;
    ``check_pose_reachable_offworker`` is pure read-only kinematics (explicit
    seed, no feedback read, no motion).
    """

    def __init__(self, arm: ArmPort) -> None:
        self._arm = arm

    def check_pose_reachable(
        self, target: BasePose, seed: Optional[JointPose] = None, *, label: str
    ) -> JointPose:
        return self._arm.check_pose_reachable_offworker(target, seed, label=label)


def prepare_arm_at_debug(arm: ArmPort, plan: InsertChainPlan) -> Dict[str, Any]:
    """Enable when needed, visit zero, then land on the debug joint pose."""

    initially_enabled = arm.is_enabled()
    moved_to_zero = False
    moved_to_debug = False
    if initially_enabled:
        measured = arm.read_joint_pose()
        try:
            ensure_joint_target(plan.debug_joint, measured, plan.joint_tolerance_rad)
        except RuntimeError:
            arm.move_j(plan.debug_joint, plan.debug_duration_s)
            moved_to_debug = True
    else:
        arm.enable()
        arm.move_j(plan.zero_joint, plan.zero_duration_s)
        moved_to_zero = True
        ensure_joint_target(
            plan.zero_joint,
            arm.read_joint_pose(),
            plan.joint_tolerance_rad,
        )
        arm.move_j(plan.debug_joint, plan.debug_duration_s)
        moved_to_debug = True

    final_pose = arm.read_joint_pose()
    ensure_joint_target(plan.debug_joint, final_pose, plan.joint_tolerance_rad)
    return {
        "arm_was_enabled": initially_enabled,
        "arm_moved_to_zero": moved_to_zero,
        "arm_moved_to_debug_pose": moved_to_debug,
        "arm_debug_joint_pose_rad": plan.debug_joint.values_rad,
        "arm_measured_joint_pose_rad": final_pose.values_rad,
    }


def stand_pickup_gripper_command(plan: InsertChainPlan) -> GripperCommand:
    return replace(
        plan.gripper,
        adaptive_carry=True,
        carry_effort=max(0.50, float(plan.gripper.carry_effort)),
        carry_lead_deg=max(2.0, float(plan.gripper.carry_lead_deg)),
        adaptive_carry_max_effort=max(0.60, float(plan.gripper.adaptive_carry_max_effort)),
    )


def light_close_at_book_stand(arm: ArmPort, plan: InsertChainPlan) -> Dict[str, Any]:
    command = replace(
        plan.gripper,
        close_deg=plan.pickup_light_close_deg,
        adaptive_carry=False,
    )
    return {
        "gripper_close": arm.close_gripper_monitored(command),
        "light_close_deg": command.close_deg,
    }


def adjust_book_stand_grasp_depth(
    arm: ArmPort, pickup: BookStandPickupPlan, plan: InsertChainPlan
) -> Dict[str, Any]:
    current = arm.tcp_pose(arm.read_joint_pose())
    down_cm = float(plan.pickup_light_close_down_cm)
    rpy_offset = tuple(plan.pickup_light_close_rpy_offset_deg)
    adjusted = current.offset_cm(
        (0.0, 0.0, -down_cm), rpy_offset_deg=rpy_offset
    )
    if down_cm != 0.0 or any(rpy_offset):
        arm.move_l(adjusted, pickup.grasp_duration_s)
    return {
        "base_pose": list(adjusted.values()),
        "current_base_pose": list(current.values()),
        "down_cm": down_cm,
        "rpy_offset_deg": list(rpy_offset),
    }


def pickup_book_from_stand(
    arm: ArmPort,
    engine: WorkflowEngine,
    task: WorkflowTask,
    plan: InsertChainPlan,
    source_slot: int,
    pickup: BookStandPickupPlan,
    *,
    adaptive_hold: bool = False,
) -> Dict[str, Any]:
    """Light-close, adjust depth from the measured TCP, then close at the stand."""

    open_command = replace(plan.gripper, open_deg=plan.pickup_open_deg)
    arm.open_gripper(plan.pickup_open_deg, open_command)
    engine.raise_if_cancelled(task)
    arm.move_to_pose_by_move_j(pickup.pre_grasp, pickup.pre_grasp_duration_s)
    engine.raise_if_cancelled(task)
    arm.move_l(pickup.grasp, pickup.grasp_duration_s)
    engine.raise_if_cancelled(task)
    light_close = light_close_at_book_stand(arm, plan)
    engine.raise_if_cancelled(task)
    depth_adjustment = adjust_book_stand_grasp_depth(arm, pickup, plan)
    engine.raise_if_cancelled(task)
    # Picking the return book off the stand slot: an empty close means the
    # slot holds no book or the calibrated pose no longer matches.
    close_command = stand_pickup_gripper_command(plan) if adaptive_hold else plan.gripper
    grasp_result = ensure_grasp_contact(
        arm.close_gripper_monitored(close_command),
        scenario="empty slot or misalignment",
    )
    engine.raise_if_cancelled(task)
    details = {
        "book_stand_source_slot": source_slot,
        **light_close,
        **depth_adjustment,
        "gripper_grasp_result": grasp_result,
    }
    if adaptive_hold:
        return {
            **details,
            "returned_to_debug_pose_after_pickup": False,
            "direct_pre_insert_after_pickup": True,
        }
    arm.move_l(pickup.pre_grasp, pickup.retreat_duration_s)
    engine.raise_if_cancelled(task)
    arm.move_j(plan.debug_joint, plan.debug_duration_s)
    final_pose = arm.read_joint_pose()
    ensure_joint_target(plan.debug_joint, final_pose, plan.joint_tolerance_rad)
    return {
        **details,
        "returned_to_debug_pose_after_pickup": True,
        "arm_measured_joint_pose_rad": final_pose.values_rad,
    }


def retarget_insert_book(
    vision: VisionPort, template: SpineTemplate, context: Dict[str, Any]
) -> Dict[str, Any]:
    """Locate the reference book and cache it as the insert anchor.

    Mid-return re-targets after the neighbor put-back and before pickup so the
    held book can go directly to pre-insert. End-return re-targets while it
    holds the return book at debug. Both insert chains use fresh recognition.
    """

    target = vision.locate_book(template)
    context["insert_book_target"] = target
    return {
        "insert_book_target_raw_base_pose": target.raw_pose.values(),
        "insert_book_target_grasp_base_pose": target.grasp_pose.values(),
        "capture_id": target.capture_id,
        "confidence": target.confidence,
    }


def _insert_book_target(context: Dict[str, Any]) -> BookTarget:
    target = context.get("insert_book_target")
    if not isinstance(target, BookTarget):
        raise RuntimeError("insert book target is missing")
    return target


def _insert_target(context: Dict[str, Any]) -> BasePose:
    target = context.get("insert_target")
    if not isinstance(target, BasePose):
        raise RuntimeError("insert target is missing")
    return target


def _chain_poses_from_context(
    plan: InsertChainPlan, context: Dict[str, Any], arm: Optional[ArmPort] = None
) -> Dict[str, BasePose]:
    """The insert-chain poses for this run: the precomputed set when the
    caller cached one (the return flow's insert_target stage stores it under
    ``insert_chain_poses``), otherwise computed now from the insert target."""

    poses = context.get("insert_chain_poses")
    if poses is not None:
        return poses
    return insert_chain_poses(plan, _insert_target(context), arm)


def compute_insert_target(plan: InsertChainPlan, context: Dict[str, Any]) -> Dict[str, Any]:
    grasp_pose = _insert_book_target(context).grasp_pose
    insert_target = BasePose(grasp_pose.x_m, grasp_pose.y_m, 0.0, 0.0, 0.0, 0.0)
    context["insert_target"] = insert_target
    insert_position = BasePose(
        grasp_pose.x_m + plan.insert_xy_offset_m[0],
        grasp_pose.y_m + plan.insert_xy_offset_m[1],
        plan.insert_z_m,
        0.0,
        0.0,
        0.0,
    )
    return {
        "insert_book_target_grasp_base_pose": list(grasp_pose.values()),
        "insert_xy_offset_m": list(plan.insert_xy_offset_m),
        "insert_z_m": plan.insert_z_m,
        "insert_target_base_pose": list(insert_position.values()),
    }


# 预插入位 x search bounds: scan from the outermost candidate downward by
# the step; the first IK-converging x is the numerically greatest reachable
# one (smallest |x|), so the pre-insert pose hugs the outer reach boundary
# for clearance. Plans with pre_insert_x_max_m cap the scan start below the
# near-body flip zone; other plans scan from the module default.
PRE_INSERT_X_SEARCH_START_M = -0.05
PRE_INSERT_X_SEARCH_STEP_M = -0.01
PRE_INSERT_X_SEARCH_MIN_M = -0.80


def search_pre_insert_x(
    arm: ArmPort,
    pose_template: BasePose,
    seed: JointPose,
    x_max_m: Optional[float] = None,
) -> float:
    """Maximum reachable (numerically greatest, still negative) pre-insert x.

    Probes the same IK entry point as the reachability preflight, every
    candidate seeded at the debug joint pose exactly like the preflight's
    first probe, so a found x is judged by the same tolerances/joint-limit
    margins and always passes the later check. ``pose_template`` carries the
    fixed y/z and the required insert orientation; only x varies.
    ``x_max_m`` caps the scan start (the plan's pre_insert_x_max_m): the
    search never returns a shallower x.
    """

    return search_max_reachable_x(
        arm.check_pose_reachable,
        pose_template,
        seed,
        x_max_m,
        x_start_m=PRE_INSERT_X_SEARCH_START_M,
        x_step_m=PRE_INSERT_X_SEARCH_STEP_M,
        x_min_m=PRE_INSERT_X_SEARCH_MIN_M,
        label="pre_insert_x_search",
        error_label="预插入位",
        require_negative=True,
    )


def insert_chain_poses(
    plan: InsertChainPlan, insert_target: BasePose, arm: Optional[ArmPort] = None
) -> Dict[str, BasePose]:
    """Insert-chain arm poses in motion order, shared with the precheck.

    The pre-insert staging pose is flown MovePByJ before the final MoveL
    approach. For both return flows, ``insert_target`` carries the recognized
    target x/y; each step adds its own XY offset and uses its absolute z and
    attitude. Plans carrying ``rotate_rpy_deg`` (mid-return) append a rotate →
    press → press-retract tail after the retract pose.
    """

    insert = BasePose(
        insert_target.x_m + plan.insert_xy_offset_m[0],
        insert_target.y_m + plan.insert_xy_offset_m[1],
        plan.insert_z_m,
        0.0,
        0.0,
        0.0,
    ).offset_cm((0.0, 0.0, 0.0), rpy_deg=plan.insert_rpy_deg)
    pre_insert = BasePose(
        insert_target.x_m + plan.pre_insert_xy_offset_m[0],
        insert_target.y_m + plan.pre_insert_xy_offset_m[1],
        plan.pre_insert_z_m,
        0.0,
        0.0,
        0.0,
    ).offset_cm((0.0, 0.0, 0.0), rpy_deg=plan.pre_insert_rpy_deg)
    push = replace(
        insert,
        x_m=insert_target.x_m + plan.push_xy_offset_m[0],
        y_m=insert_target.y_m + plan.push_xy_offset_m[1],
        z_m=plan.push_z_m,
    ).offset_cm((0.0, 0.0, 0.0), rpy_offset_deg=plan.push_rpy_deg)
    # 位置仍基于推回位沿 x 回抽；带 retract_rpy_deg 的计划使用该固定安全
    # 姿态，不随插入/推回姿态变化。
    retract = push.offset_cm(
        (plan.retract_x_offset_cm, 0.0, 0.0),
        rpy_deg=getattr(plan, "retract_rpy_deg", None),
    )
    poses = {
        "pre_insert": pre_insert,
        "insert": insert,
        "push": push,
        "retract": retract,
    }
    # 中位还书在回抽后追加 旋转→推回→回抽 压书链（plan 带 rotate_rpy_deg
    # 时）：旋转只改姿态（相对回抽姿态的 rx/ry/rz 偏移），可同时叠加 z 偏
    # 移升降（getattr 缺省 0，位置不变）；推回与二次回抽只改 x；末尾还书没
    # 有这三个字段，不追加这些位姿（与 pre_insert_x_m 同模式）。
    rotate_rpy_deg = getattr(plan, "rotate_rpy_deg", None)
    if rotate_rpy_deg is not None:
        rotate = retract.offset_cm(
            (0.0, 0.0, float(getattr(plan, "rotate_z_offset_cm", 0.0))),
            rpy_offset_deg=rotate_rpy_deg,
        )
        press = rotate.offset_cm((float(plan.press_x_offset_cm), 0.0, 0.0))
        poses["rotate"] = rotate
        poses["press"] = press
        poses["press_retract"] = press.offset_cm(
            (float(plan.press_retract_x_offset_cm), 0.0, 0.0)
        )
    return poses


def check_insert_chain_reachable(
    arm: ArmPort, plan: InsertChainPlan, context: Dict[str, Any]
) -> Dict[str, Any]:
    """Fail fast when any insert-chain arm pose is unreachable; sends no motion.

    Seeded at the debug joint pose (the arm is parked there after the stand
    pickup); each solved pose seeds the next, mirroring execution continuity.
    """

    seed: JointPose = plan.debug_joint
    checked = []
    for label, pose in _chain_poses_from_context(plan, context, arm).items():
        seed = arm.check_pose_reachable(pose, seed, label=label)
        checked.append(label)
    return {"reachability_checked_poses": checked}


def run_insert_chain(
    arm: ArmPort,
    engine: WorkflowEngine,
    task: WorkflowTask,
    plan: InsertChainPlan,
    context: Dict[str, Any],
    rod: Optional[RodPort] = None,
    stand_pickup: Optional[BookStandPickupPlan] = None,
) -> Dict[str, Any]:
    """Pre-insert, insert at y=Y1, push in x, release, retract, debug.

    Plans carrying ``rotate_rpy_deg`` (mid-return) run a rotate → press →
    press-retract tail after the retract before flying back to debug. With a
    rod device and a plan carrying ``rod_insert_deg`` (mid-return again), the
    rod extends to that angle before the pre-insert flight and returns to
    ``rod_putback_deg`` right after the push, before the release. A supplied
    stand pickup adds a collision-clearing MoveL to its pre_grasp first.
    """

    poses = _chain_poses_from_context(plan, context, arm)
    pre_insert = poses["pre_insert"]
    insert = poses["insert"]
    push = poses["push"]
    retract = poses["retract"]
    rod_moves = rod is not None and getattr(plan, "rod_insert_deg", None) is not None
    if rod_moves:
        rod.move_to_deg(
            plan.rod_insert_deg,
            plan.rod_speed,
            plan.rod_acceleration,
            plan.rod_tolerance_deg,
            plan.rod_timeout_s,
        )
        engine.raise_if_cancelled(task)
    if stand_pickup is not None:
        arm.move_l(stand_pickup.pre_grasp, stand_pickup.retreat_duration_s)
        engine.raise_if_cancelled(task)
    arm.move_to_pose_by_move_j(pre_insert, plan.pre_insert_duration_s)
    engine.raise_if_cancelled(task)
    arm.move_l(insert, plan.insert_duration_s)
    engine.raise_if_cancelled(task)
    arm.move_l(push, plan.push_duration_s)
    engine.raise_if_cancelled(task)
    if rod_moves:
        rod.move_to_deg(
            plan.rod_putback_deg,
            plan.rod_speed,
            plan.rod_acceleration,
            plan.rod_tolerance_deg,
            plan.rod_timeout_s,
        )
        engine.raise_if_cancelled(task)
    release_command = replace(plan.gripper, open_deg=plan.release_open_deg)
    arm.open_gripper(plan.release_open_deg, release_command)
    engine.raise_if_cancelled(task)
    arm.move_l(retract, plan.retract_duration_s)
    engine.raise_if_cancelled(task)
    result: Dict[str, Any] = {
        "insert_base_pose": insert.values(),
        "pre_insert_base_pose": pre_insert.values(),
        "push_base_pose": push.values(),
        "gripper_release_angle_deg": plan.release_open_deg,
        "retract_base_pose": retract.values(),
    }
    if rod_moves:
        result["rod_insert_deg"] = plan.rod_insert_deg
        result["rod_putback_deg"] = plan.rod_putback_deg
    rotate = poses.get("rotate")
    if rotate is not None:
        press = poses["press"]
        press_retract = poses["press_retract"]
        arm.move_l(rotate, plan.rotate_duration_s)
        engine.raise_if_cancelled(task)
        arm.move_l(press, plan.press_duration_s)
        engine.raise_if_cancelled(task)
        arm.move_l(press_retract, plan.press_retract_duration_s)
        engine.raise_if_cancelled(task)
        result["rotate_base_pose"] = rotate.values()
        result["press_base_pose"] = press.values()
        result["press_retract_base_pose"] = press_retract.values()
    arm.move_j(plan.debug_joint, plan.debug_duration_s)
    final_pose = arm.read_joint_pose()
    ensure_joint_target(plan.debug_joint, final_pose, plan.joint_tolerance_rad)
    result["returned_to_debug_pose_after_insert"] = True
    result["arm_measured_joint_pose_rad"] = final_pose.values_rad
    return result


class MidReturnBookUseCase:
    """Seven-stage mid-return workflow mirroring the tuning session steps.

    Stages: lift to the shelf height, park the arm at the debug pose, locate
    the left-neighbor spine (first-round target), run the take-book grasp
    chain on it, put the pulled book back loosely (push in, release, clear
    out), re-locate the same target book, compute the insert target, pick the
    return book from the stand, retreat to debug, then use the end-return
    sequence through the first retract, rotate, press the book spines, retract
    again, and return to debug. The pre-insert, insert, and push steps use
    recognized target XY plus per-step XY offsets and absolute base-frame Z.
    """

    def __init__(
        self,
        *,
        task_manager: TaskManager,
        reservation: ReservationPort,
        lift: LiftPort,
        vision: VisionPort,
        arm: ArmPort,
        rod: RodPort,
        pickup_slots: Dict[int, BookStandPickupPlan],
        plan: Optional[MidReturnMotionPlan] = None,
        vehicle_align: Optional[Any] = None,
    ) -> None:
        self.task_manager = task_manager
        self.engine = WorkflowEngine(task_manager)
        self.reservation = reservation
        self.lift = lift
        self.vision = vision
        self.arm = arm
        self.rod = rod
        self.pickup_slots = dict(pickup_slots)
        self.plan = plan or MidReturnMotionPlan()
        self.vehicle_align = vehicle_align

    def create(self, request: MidReturnBookRequest) -> WorkflowTask:
        request = None
        return self.task_manager.create(WorkflowKind.MID_RETURN_BOOK)

    def execute(self, task: WorkflowTask, request: MidReturnBookRequest) -> WorkflowResult:
        pickup: Optional[BookStandPickupPlan] = None
        if self._requires_pickup(request.stop_after_stage):
            try:
                pickup = self._pickup_for(request)
            except RuntimeError as error:
                return self.engine.reject(task, MidReturnStage.BOOK_STAND_PICKUP.value, str(error))
        if not self.reservation.acquire("mid_return_book"):
            return self.engine.reject(
                task,
                "reservation",
                "bookarm hardware is reserved by another controller",
            )
        context: Dict[str, Any] = {
            "book_target": None,
            "fine_grasp_pose": None,
            "insert_book_target": None,
            "insert_target": None,
        }
        try:
            if request.injected_grasp_pose is not None:
                # Stress-test shortcut: the caller already knows the insert
                # anchor (e.g. the take-out flow's recognized grasp pose), so
                # skip the neighbor grasp+put-back and the fresh re-target;
                # pick up from the stand slot and run the insert chain
                # (tuning steps 24-32) anchored on the injected pose.
                context["insert_book_target"] = _injected_book_target(request.injected_grasp_pose)
                steps = (
                    ("lift_move", lambda: self._move_lift(request), False),
                    ("arm_debug_pose", self._prepare_arm, True),
                    (
                        "book_stand_pickup",
                        lambda: self._pickup_from_stand(task, request, self._require_pickup(pickup)),
                        True,
                    ),
                    (
                        "insert_target",
                        lambda: self._compute_insert_target(context),
                        False,
                    ),
                    (
                        "reachability_check",
                        lambda: self._check_insert_reachability(context),
                        False,
                    ),
                    ("shelf_insert", lambda: self._insert_at_centerline(task, context), True),
                )
            else:
                steps = (
                    ("lift_move", lambda: self._move_lift(request), False),
                    ("arm_debug_pose", self._prepare_arm, True),
                    (
                        "vision_target",
                        lambda: self._acquire_book_target(request, context),
                        False,
                    ),
                    (
                        "post_vision_align",
                        lambda: self._post_vision_align(
                            task, request, context, "book_target"
                        ),
                        False,
                    ),
                    ("book_grasp", lambda: self._grasp_chain(task, context), True),
                    ("book_put_back", lambda: self._put_back(task, context), True),
                    (
                        "vision_retarget",
                        lambda: self._retarget_for_insert(request, context),
                        True,
                    ),
                    (
                        "post_vision_retarget_align",
                        lambda: self._post_vision_align(
                            task, request, context, "insert_book_target"
                        ),
                        False,
                    ),
                    (
                        "insert_target",
                        lambda: self._compute_insert_target(context),
                        False,
                    ),
                    (
                        "reachability_check",
                        lambda: self._check_insert_reachability(context),
                        False,
                    ),
                    (
                        "book_stand_pickup",
                        lambda: self._pickup_from_stand(task, request, self._require_pickup(pickup)),
                        True,
                    ),
                    ("shelf_insert", lambda: self._insert_at_centerline(task, context), True),
                )
            return self.engine.run(
                task, self._steps_to_stop_stage(steps, request.stop_after_stage)
            )
        finally:
            self.reservation.release()

    @staticmethod
    def _requires_pickup(stop_after_stage: MidReturnStage) -> bool:
        return stop_after_stage in {
            MidReturnStage.BOOK_STAND_PICKUP,
            MidReturnStage.VISION_RETARGET,
            MidReturnStage.INSERT_TARGET,
            MidReturnStage.SHELF_INSERT,
        }

    @staticmethod
    def _require_pickup(pickup: Optional[BookStandPickupPlan]) -> BookStandPickupPlan:
        if pickup is None:
            raise RuntimeError("book-stand pickup plan was not prepared")
        return pickup

    @staticmethod
    def _steps_to_stop_stage(steps: tuple, stop_after_stage: MidReturnStage) -> tuple:
        for index, (name, _action, _recovery_required) in enumerate(steps):
            if name == stop_after_stage.value:
                return steps[: index + 1]
        raise ValueError("unsupported mid-return stop stage: %s" % stop_after_stage)

    def _move_lift(self, request: MidReturnBookRequest) -> Dict[str, Any]:
        result = self.lift.move_to_height_mm(
            request.target_height_mm,
            speed_level=request.lift_speed_level,
        )
        return {
            "lift_target_height_mm": result.target_height_mm,
            "lift_measured_height_mm": result.measured_height_mm,
            "lift_speed_level": request.lift_speed_level,
            "lift_tolerance_pulses": result.tolerance_pulses,
            "lift_target_pulses": result.controller_target_pulses,
            "lift_measured_pulses": result.controller_measured_pulses,
        }

    def _prepare_arm(self) -> Dict[str, Any]:
        """Use the same enable, zero, and debug-pose sequence as return_book."""

        return prepare_arm_at_debug(self.arm, self.plan)

    def _acquire_book_target(
        self,
        request: MidReturnBookRequest,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        target = self.vision.locate_book(request.left_neighbor_spine_template)
        context["book_target"] = target
        return {
            "left_neighbor_spine_template": request.left_neighbor_spine_template.path,
            "book_target_raw_base_pose": target.raw_pose.values(),
            "book_target_grasp_base_pose": target.grasp_pose.values(),
            "capture_id": target.capture_id,
            "confidence": target.confidence,
        }

    def _grasp_chain(self, task: WorkflowTask, context: Dict[str, Any]) -> Dict[str, Any]:
        """Steps 0-6 of the tuning session: open, rod home, pregrasp, approach,
        rod hook, fine grasp, close."""

        target = context.get("book_target")
        if not isinstance(target, BookTarget):
            raise RuntimeError("book target is missing")
        details = run_mid_grasp_chain(
            self.arm, self.rod, self.engine, task, self.plan, target
        )
        context["fine_grasp_pose"] = details["fine_grasp_pose"]
        return {
            "pregrasp_base_pose": details["pregrasp_base_pose"],
            "fine_grasp_base_pose": details["fine_grasp_base_pose"],
            "gripper_grasp_result": details["gripper_grasp_result"],
        }

    def _put_back(self, task: WorkflowTask, context: Dict[str, Any]) -> Dict[str, Any]:
        """Steps 7-16: push back in x, partially release, home the rod, then
        lower/full-open/re-close/shift/slight-release/forward clear-out and debug."""

        fine_grasp = context.get("fine_grasp_pose")
        if not isinstance(fine_grasp, BasePose):
            raise RuntimeError("fine-grasp pose is missing")
        plan = self.plan
        prefix = run_mid_put_back_prefix(
            self.arm, self.rod, self.engine, task, plan, fine_grasp
        )
        push_in = BasePose.from_values(prefix["push_in_base_pose"])
        partial_command = prefix["partial_command"]
        lower = BasePose.from_values(prefix["lower_base_pose"])
        # Fully open to spread the book gap, then re-grip the book so the
        # sideways shift carries it; after the shift, carry the closed-gripper
        # book forward to a camera-friendly pose, crack the gripper open just
        # enough to unload the fingers, then push forward.
        self.engine.raise_if_cancelled(task)
        full_open_command = replace(plan.gripper, open_deg=plan.full_open_deg)
        self.arm.open_gripper(plan.full_open_deg, full_open_command)
        self.engine.raise_if_cancelled(task)
        # Re-gripping the put-back book: an empty close means the book fell or
        # was pushed out of the fingers' reach during the gap spread.
        regrip_result = ensure_grasp_contact(
            self.arm.close_gripper_monitored(plan.gripper),
            scenario="book lost between the put-back release and re-grip",
        )
        self.engine.raise_if_cancelled(task)
        shift = lower.offset_cm((0.0, plan.shift_y_offset_cm, 0.0))
        self.arm.move_l(shift, plan.shift_duration_s)
        self.engine.raise_if_cancelled(task)
        carry = shift.offset_cm((plan.carry_forward_x_offset_cm, 0.0, 0.0))
        self.arm.move_l(carry, plan.carry_forward_duration_s)
        self.engine.raise_if_cancelled(task)
        self.arm.open_gripper(plan.partial_release_deg, partial_command)
        self.engine.raise_if_cancelled(task)
        forward = carry.offset_cm((plan.forward_x_offset_cm, 0.0, 0.0))
        self.arm.move_l(forward, plan.forward_duration_s)
        self.engine.raise_if_cancelled(task)
        self.arm.move_j(plan.debug_joint, plan.debug_duration_s)
        final_pose = self.arm.read_joint_pose()
        ensure_joint_target(plan.debug_joint, final_pose, plan.joint_tolerance_rad)
        return {
            "push_in_base_pose": push_in.values(),
            "forward_base_pose": forward.values(),
            "partial_release_deg": plan.partial_release_deg,
            "full_open_deg": plan.full_open_deg,
            "gripper_regrip_result": regrip_result,
            "returned_to_debug_pose": True,
            "arm_measured_joint_pose_rad": final_pose.values_rad,
        }

    def _pickup_for(self, request: MidReturnBookRequest) -> BookStandPickupPlan:
        slot = int(request.source_slot.value)
        if slot not in self.pickup_slots:
            raise RuntimeError("mid-return source slot %d is not calibrated" % slot)
        try:
            return self.pickup_slots[slot]
        except KeyError as error:
            raise RuntimeError("book-stand pickup slot %d is not calibrated" % slot) from error

    def _pickup_from_stand(
        self,
        task: WorkflowTask,
        request: MidReturnBookRequest,
        pickup: BookStandPickupPlan,
    ) -> Dict[str, Any]:
        """Open, drive onto the slot, close and retreat to debug like end-return."""

        result = pickup_book_from_stand(
            self.arm,
            self.engine,
            task,
            self.plan,
            int(request.source_slot.value),
            pickup,
            adaptive_hold=False,
        )
        self.rod.move_to_deg(
            self.plan.pickup_rod_home_deg,
            self.plan.rod_speed,
            self.plan.rod_acceleration,
            self.plan.rod_tolerance_deg,
            self.plan.rod_timeout_s,
        )
        self.engine.raise_if_cancelled(task)
        result["rod_deg"] = self.plan.pickup_rod_home_deg
        return result

    def _post_vision_align(
        self,
        task: WorkflowTask,
        request: MidReturnBookRequest,
        context: Dict[str, Any],
        context_key: str,
    ) -> Dict[str, Any]:
        # 识别后校验：倾斜超阈值即中止；按请求决定是否车辆居中对齐并更新锚点
        return post_vision_check_align(
            self.vision,
            request.left_neighbor_spine_template,
            context,
            context_key,
            self.vehicle_align,
            self.plan,
            engine=self.engine,
            task=task,
            vehicle_alignment_enabled=request.enable_vehicle_alignment,
        )

    def _retarget_for_insert(
        self,
        request: MidReturnBookRequest,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Re-locate after the put-back and before pickup so the return book
        can move directly from the stand grasp to pre-insert."""

        return retarget_insert_book(self.vision, request.left_neighbor_spine_template, context)

    def _compute_insert_target(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Compute target XY plus configured offsets and absolute Z from the
        freshly re-targeted book, then build all insert-chain poses."""

        details = compute_insert_target(self.plan, context)
        poses = insert_chain_poses(self.plan, context["insert_target"], self.arm)
        context["insert_chain_poses"] = poses
        details["pre_insert_x_m"] = poses["pre_insert"].x_m
        return details

    def _insert_poses(self, insert_target: BasePose) -> Dict[str, BasePose]:
        """Insert-chain arm poses in motion order, shared with the precheck."""

        return insert_chain_poses(self.plan, insert_target, self.arm)

    def _check_insert_reachability(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Fail fast when any insert-chain arm pose is unreachable; sends no motion.

        Seeded at the debug joint pose (the arm is parked there after the stand
        pickup); each solved pose seeds the next, mirroring execution continuity.
        """

        return check_insert_chain_reachable(self.arm, self.plan, context)

    def _insert_at_centerline(
        self,
        task: WorkflowTask,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Run the same insert, release, retract and debug chain as end-return."""

        return run_insert_chain(self.arm, self.engine, task, self.plan, context)


def _injected_book_target(values: Sequence[float]) -> BookTarget:
    """Build the insert anchor from a caller-supplied base-frame grasp pose."""

    if len(values) != 6 or not all(math.isfinite(float(v)) for v in values):
        raise RuntimeError("injected grasp pose must be six finite values (m, m, m, rad, rad, rad)")
    pose = BasePose(*(float(v) for v in values))
    return BookTarget(raw_pose=pose, grasp_pose=pose, confidence=1.0, capture_id="injected")
