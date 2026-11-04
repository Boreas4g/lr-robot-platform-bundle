"""Take a shelf book through the mid-flow gap-clearing chain."""

from __future__ import annotations

from typing import Any, Dict, Optional

from bookarm.api.requests import TakeBookRequest
from bookarm.api.results import WorkflowTask
from bookarm.application.use_cases.mid_flow import (
    run_mid_grasp_chain,
    run_mid_put_back_prefix,
)
from bookarm.application.use_cases.take_book import TakeBookUseCase
from bookarm.domain.models.book import BookTarget
from bookarm.domain.plans.mid_takeout import MidTakeoutMotionPlan
from bookarm.domain.policies.gripper import ensure_grasp_contact


class MidTakeoutUseCase(TakeBookUseCase):
    def __init__(self, **kwargs: Any) -> None:
        if kwargs.get("plan") is None:
            kwargs["plan"] = MidTakeoutMotionPlan()
        super().__init__(**kwargs)

    def _grasp_book(self, task: WorkflowTask, context: Dict[str, Any]) -> Dict[str, Any]:
        target = context.get("target")
        if not isinstance(target, BookTarget):
            raise RuntimeError("book target is missing")
        plan = self.plan
        grasp = run_mid_grasp_chain(self.arm, self.rod, self.engine, task, plan, target)
        put_back = run_mid_put_back_prefix(
            self.arm,
            self.rod,
            self.engine,
            task,
            plan,
            grasp["fine_grasp_pose"],
        )
        close_result = ensure_grasp_contact(
            self.arm.close_gripper_monitored(plan.gripper),
            scenario="book lost before the mid-takeout full close",
        )
        self.engine.raise_if_cancelled(task)
        poses = context.get("grasp_poses") or self._grasp_poses(target)
        post_grasp = poses["arm_post_grasp"]
        self.arm.move_to_pose_by_move_j(post_grasp, plan.post_grasp_duration_s)
        self.engine.raise_if_cancelled(task)
        self.arm.move_j(plan.debug_joint, plan.return_debug_duration_s)
        return {
            "mid_takeout": True,
            "pregrasp_base_pose": grasp["pregrasp_base_pose"],
            "fine_grasp_base_pose": grasp["fine_grasp_base_pose"],
            "raise_base_pose": put_back.get("raise_base_pose"),
            "lower_base_pose": put_back["lower_base_pose"],
            "post_grasp_base_pose": post_grasp.values(),
            "gripper_grasp_result": grasp["gripper_grasp_result"],
            "gripper_full_close_result": close_result,
            "returned_to_debug_pose": True,
        }
