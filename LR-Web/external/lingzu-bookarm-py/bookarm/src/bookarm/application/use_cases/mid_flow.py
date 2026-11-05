"""Shared shelf-book grasp and gap-clearing motions for mid workflows."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict

from bookarm.application.workflow_engine import WorkflowEngine
from bookarm.domain.models.book import BookTarget
from bookarm.domain.models.pose import BasePose
from bookarm.domain.plans.mid_return import MidReturnMotionPlan
from bookarm.domain.policies.gripper import ensure_grasp_contact
from bookarm.ports.devices import ArmPort, RodPort


def run_mid_grasp_chain(
    arm: ArmPort,
    rod: RodPort,
    engine: WorkflowEngine,
    task: Any,
    plan: MidReturnMotionPlan,
    target: BookTarget,
) -> Dict[str, Any]:
    """Run tuning steps 1-7: open, approach, hook, fine-grasp and close."""

    grasp_pose = target.grasp_pose
    pregrasp = grasp_pose.offset_cm(plan.pregrasp_offset_cm, rpy_deg=plan.grasp_rpy_deg)
    approach = grasp_pose.offset_cm(plan.approach_offset_cm, rpy_deg=plan.grasp_rpy_deg)
    fine_grasp = grasp_pose.offset_cm(
        plan.fine_grasp_offset_cm, rpy_deg=plan.fine_grasp_rpy_deg
    )
    open_command = replace(plan.gripper, open_deg=plan.pickup_open_deg)
    arm.open_gripper(plan.pickup_open_deg, open_command)
    engine.raise_if_cancelled(task)
    rod.move_to_deg(
        plan.rod_home_deg,
        plan.rod_speed,
        plan.rod_acceleration,
        plan.rod_tolerance_deg,
        plan.rod_timeout_s,
    )
    engine.raise_if_cancelled(task)
    arm.move_to_pose_by_move_j(pregrasp, plan.pregrasp_duration_s)
    engine.raise_if_cancelled(task)
    arm.move_l(approach, plan.approach_duration_s)
    engine.raise_if_cancelled(task)
    rod.move_to_deg(
        plan.rod_grasp_deg,
        plan.rod_speed,
        plan.rod_acceleration,
        plan.rod_tolerance_deg,
        plan.rod_timeout_s,
    )
    engine.raise_if_cancelled(task)
    arm.move_to_pose_by_move_j(fine_grasp, plan.fine_grasp_duration_s)
    engine.raise_if_cancelled(task)
    grasp_result = ensure_grasp_contact(
        arm.close_gripper_monitored(plan.gripper),
        scenario="empty slot or misalignment",
    )
    return {
        "pregrasp_base_pose": pregrasp.values(),
        "fine_grasp_base_pose": fine_grasp.values(),
        "fine_grasp_pose": fine_grasp,
        "gripper_grasp_result": grasp_result,
    }


def run_mid_put_back_before_lower(
    arm: ArmPort,
    rod: RodPort,
    engine: WorkflowEngine,
    task: Any,
    plan: MidReturnMotionPlan,
    fine_grasp: BasePose,
    *,
    rod_home_before_re_push: bool = False,
) -> Dict[str, Any]:
    """Run put-back steps 8-11, optionally homing the rod before the re-push."""

    def home_rod() -> None:
        rod.move_to_deg(
            plan.rod_putback_deg,
            plan.rod_speed,
            plan.rod_acceleration,
            plan.rod_tolerance_deg,
            plan.rod_timeout_s,
        )
        engine.raise_if_cancelled(task)

    push_in = fine_grasp.offset_cm((plan.push_in_x_offset_cm, 0.0, 0.0))
    arm.move_l(push_in, plan.push_in_duration_s)
    engine.raise_if_cancelled(task)
    partial_command = replace(plan.gripper, open_deg=plan.partial_release_deg)
    arm.open_gripper(plan.partial_release_deg, partial_command)
    engine.raise_if_cancelled(task)
    if rod_home_before_re_push:
        home_rod()
    re_push = push_in.offset_cm((plan.re_push_x_offset_cm, 0.0, 0.0))
    arm.move_l(re_push, plan.re_push_duration_s)
    engine.raise_if_cancelled(task)
    if not rod_home_before_re_push:
        home_rod()
    return {
        "push_in_base_pose": push_in.values(),
        "re_push_base_pose": re_push.values(),
        "partial_command": partial_command,
    }


def run_mid_put_back_prefix(
    arm: ArmPort,
    rod: RodPort,
    engine: WorkflowEngine,
    task: Any,
    plan: MidReturnMotionPlan,
    fine_grasp: BasePose,
) -> Dict[str, Any]:
    """Run tuning steps 8-12: push, release, re-push, rod home and lower."""

    put_back = run_mid_put_back_before_lower(
        arm, rod, engine, task, plan, fine_grasp
    )
    anchor = BasePose.from_values(put_back["re_push_base_pose"])
    details: Dict[str, Any] = {}
    if hasattr(plan, "raise_z_offset_cm"):
        anchor = anchor.offset_cm((0.0, 0.0, plan.raise_z_offset_cm))
        arm.move_l(anchor, plan.raise_duration_s)
        engine.raise_if_cancelled(task)
        details["raise_base_pose"] = anchor.values()
    lower = anchor.offset_cm(
        getattr(plan, "lower_offset_cm", (0.0, 0.0, plan.lower_z_offset_cm)),
        rpy_offset_deg=getattr(plan, "lower_rpy_offset_deg", (0.0, 0.0, 0.0)),
    )
    arm.move_l(lower, plan.lower_duration_s)
    engine.raise_if_cancelled(task)
    return {
        **put_back,
        "lower_base_pose": lower.values(),
        **details,
    }
