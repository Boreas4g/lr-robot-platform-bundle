"""Pre-insert x IK search: the return flow's 预插入位 hugs the reach boundary."""

from __future__ import annotations

from dataclasses import replace
import math
import threading
import unittest
from unittest.mock import patch

from bookarm.application.post_vision import take_book_grasp_poses
from bookarm.application.use_cases.mid_return import (
    PRE_INSERT_X_SEARCH_START_M,
    PRE_INSERT_X_SEARCH_STEP_M,
    insert_chain_poses,
    search_pre_insert_x,
)
from bookarm.devices.arm.service import ArmDeviceConfig, ArmService
from bookarm.domain.models.book import BookTarget
from bookarm.domain.models.pose import BasePose, JointPose
from bookarm.domain.plans.mid_return import MidReturnMotionPlan
from bookarm.domain.plans.return_book import ReturnBookMotionPlan
from bookarm.domain.plans.take_book import TakeBookMotionPlan


class ScriptedArm:
    """ArmPort stand-in for the search: reachable exactly up to a fixed x."""

    def __init__(self, reachable_from_x_m: float) -> None:
        self.reachable_from_x_m = reachable_from_x_m
        self.probes = []

    def check_pose_reachable(self, target, seed=None, *, label):
        self.probes.append((label, target, seed))
        # Reachable only at or beyond the boundary (further from zero).
        if target.x_m > self.reachable_from_x_m:
            raise RuntimeError("arm pose unreachable (%s): IK did not converge" % label)
        return seed or JointPose.from_values((0, 0, 0, 0, 0, 0))


class SearchLogicTests(unittest.TestCase):
    """Scripted-probe checks of the scan order, seeding and stop rules."""

    def setUp(self) -> None:
        self.plan = ReturnBookMotionPlan()
        self.template = BasePose(
            0.0, -0.03, 0.25,
            math.radians(95.0), 0.0, math.radians(90.0),
        )
        self.cap = {"x_max_m": -0.20}

    def test_first_converging_x_wins_below_an_explicit_cap(self):
        arm = ScriptedArm(reachable_from_x_m=-0.30)

        x_m = search_pre_insert_x(arm, self.template, self.plan.debug_joint, **self.cap)

        self.assertEqual(x_m, -0.30)
        self.assertLess(x_m, 0.0)
        # An explicit cap still controls the shared search used by mid-return.
        self.assertEqual(arm.probes[0][1].x_m, self.cap["x_max_m"])
        self.assertEqual(arm.probes[-1][1].x_m, -0.30)
        for _label, pose, seed in arm.probes:
            self.assertLessEqual(pose.x_m, self.cap["x_max_m"])
            self.assertEqual(seed, self.plan.debug_joint)
        # One step closer to 0 was probed and rejected first.
        self.assertTrue(any(pose.x_m == -0.29 for _l, pose, _s in arm.probes))

    def test_fully_reachable_column_returns_an_explicit_cap(self):
        arm = ScriptedArm(reachable_from_x_m=1.0)  # every candidate reachable

        x_m = search_pre_insert_x(arm, self.template, self.plan.debug_joint, **self.cap)

        self.assertEqual(x_m, self.cap["x_max_m"])
        self.assertEqual(len(arm.probes), 1)

    def test_without_a_cap_the_scan_uses_the_module_default(self):
        arm = ScriptedArm(reachable_from_x_m=1.0)

        x_m = search_pre_insert_x(arm, self.template, self.plan.debug_joint)

        self.assertEqual(x_m, PRE_INSERT_X_SEARCH_START_M)

    def test_nothing_reachable_raises_a_clear_error(self):
        arm = ScriptedArm(reachable_from_x_m=-1.0)

        with self.assertRaisesRegex(RuntimeError, "预插入位无可达 x"):
            search_pre_insert_x(arm, self.template, self.plan.debug_joint, **self.cap)

    def test_return_plan_adds_xy_offsets_to_the_recognized_target(self):
        plan = replace(self.plan, pre_insert_rpy_deg=(80.0, 5.0, 70.0))
        poses = insert_chain_poses(
            plan, BasePose(9.0, 9.0, 9.0, 0.0, 0.0, 0.0)
        )

        self.assertEqual(poses["pre_insert"].values()[:3], (9.30, 9.04, 0.04))
        self.assertEqual(poses["insert"].values()[:3], (9.0, 9.04, 0.04))
        self.assertEqual(poses["push"].values()[:3], (8.95, 9.04, 0.04))
        self.assertAlmostEqual(poses["pre_insert"].rx_rad, math.radians(80.0))
        self.assertAlmostEqual(poses["pre_insert"].ry_rad, math.radians(5.0))
        self.assertAlmostEqual(poses["pre_insert"].rz_rad, math.radians(70.0))
        self.assertAlmostEqual(poses["insert"].rx_rad, math.radians(95.0))

    def test_mid_return_recomputes_positions_for_each_fresh_insert_target(self):
        plan = MidReturnMotionPlan()
        arm = ScriptedArm(reachable_from_x_m=-0.36)

        first = insert_chain_poses(
            plan, BasePose(-0.35, -0.03, 0.25, 0.0, 0.0, 0.0), arm
        )
        second = insert_chain_poses(
            plan, BasePose(-0.42, -0.01, 0.28, 0.0, 0.0, 0.0), arm
        )

        self.assertAlmostEqual(first["pre_insert"].x_m, -0.05)
        self.assertAlmostEqual(second["pre_insert"].x_m, -0.12)
        self.assertAlmostEqual(first["pre_insert"].y_m, 0.01)
        self.assertAlmostEqual(first["pre_insert"].z_m, 0.04)
        self.assertAlmostEqual(second["pre_insert"].y_m, 0.03)
        self.assertAlmostEqual(second["pre_insert"].z_m, 0.04)
        self.assertEqual(arm.probes, [])

    def test_mid_return_uses_target_xy_offsets_and_absolute_z(self):
        plan = replace(
            MidReturnMotionPlan(),
            pre_insert_xy_offset_m=(0.30, 0.045),
            pre_insert_z_m=0.265,
            insert_xy_offset_m=(0.02, 0.03),
            insert_z_m=0.29,
            push_xy_offset_m=(-0.04, 0.03),
            push_z_m=0.32,
        )

        poses = insert_chain_poses(
            plan,
            BasePose(-0.35, -0.03, 0.25, 0.0, 0.0, 0.0),
            ScriptedArm(reachable_from_x_m=1.0),
        )

        expected = {
            "pre_insert": (-0.05, 0.015, 0.265),
            "insert": (-0.33, 0.0, 0.29),
            "push": (-0.39, 0.0, 0.32),
        }
        for name, expected_xyz in expected.items():
            pose = poses[name]
            for actual, expected_value in zip(
                (pose.x_m, pose.y_m, pose.z_m), expected_xyz
            ):
                self.assertAlmostEqual(actual, expected_value, places=6)

    def test_take_post_grasp_searches_max_x_from_the_current_round_cap(self):
        pose = BasePose(0.21, 0.10, 0.30, 0.0, 0.0, 0.0)
        target = BookTarget(
            raw_pose=pose,
            grasp_pose=pose,
            pixel_uv=(320, 240),
            confidence=0.9,
        )
        plan = replace(
            TakeBookMotionPlan(),
            post_grasp_offset_cm=(15.0, 2.0, 8.0),
        )
        arm = ScriptedArm(reachable_from_x_m=0.29)

        poses = take_book_grasp_poses(target, plan, arm.check_pose_reachable)

        self.assertAlmostEqual(poses["arm_post_grasp"].x_m, 0.29)
        self.assertAlmostEqual(poses["arm_post_grasp"].y_m, 0.135)
        self.assertAlmostEqual(poses["arm_post_grasp"].z_m, 0.38)
        self.assertAlmostEqual(arm.probes[0][1].x_m, 0.37)
        self.assertAlmostEqual(arm.probes[-1][1].x_m, 0.29)
        self.assertEqual(
            [label for label, _pose, _seed in arm.probes],
            ["arm_post_grasp_x_search"] * 9,
        )


class RealKinematicsSearchTests(unittest.TestCase):
    """The search against the stock IK model (no hardware involved)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.arm = ArmService(ArmDeviceConfig())
        cls.arm._worker.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.arm._worker.stop()

    def test_searched_x_is_negative_ik_feasible_and_on_the_boundary(self):
        plan = ReturnBookMotionPlan()
        # Representative return-flow anchor: fresh-target y=-0.03, z clamped
        # to the 0.25 m floor, insert orientation from the plan.
        insert = BasePose(-0.35, -0.03, 0.25, 0.0, 0.0, 0.0).offset_cm(
            (0.0, 0.0, 0.0), rpy_deg=plan.insert_rpy_deg
        )

        x_m = search_pre_insert_x(self.arm, insert, plan.debug_joint)

        self.assertLess(x_m, 0.0)
        self.assertLessEqual(x_m, PRE_INSERT_X_SEARCH_START_M)
        # The found pose passes the same preflight judgment, and one step
        # closer to 0 does not converge: x is the uncapped reachable maximum.
        self.arm.check_pose_reachable(replace(insert, x_m=x_m), plan.debug_joint, label="pre_insert")
        with self.assertRaisesRegex(RuntimeError, "did not converge|unreachable"):
            self.arm.check_pose_reachable(
                replace(insert, x_m=round(x_m - PRE_INSERT_X_SEARCH_STEP_M, 6)),
                plan.debug_joint,
                label="pre_insert",
            )

    def test_fully_unreachable_column_raises(self):
        plan = ReturnBookMotionPlan()
        # Below the base: no x in the search range can converge.
        insert = BasePose(-0.35, -0.03, -0.20, 0.0, 0.0, 0.0).offset_cm(
            (0.0, 0.0, 0.0), rpy_deg=plan.insert_rpy_deg
        )

        with self.assertRaisesRegex(RuntimeError, "预插入位无可达 x"):
            search_pre_insert_x(self.arm, insert, plan.debug_joint)


class OffworkerReachabilityTests(unittest.TestCase):
    """ArmService.check_pose_reachable_offworker: pure IK off the command worker."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.arm = ArmService(ArmDeviceConfig())
        cls.arm._worker.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.arm._worker.stop()

    def test_requires_an_explicit_seed(self):
        # seed=None would read live joint feedback — hardware access the
        # background thread must never do.
        with self.assertRaisesRegex(ValueError, "explicit seed"):
            self.arm.check_pose_reachable_offworker(
                BasePose(-0.35, -0.03, 0.25, 0.0, 0.0, 0.0), None, label="probe"
            )

    def test_probe_runs_while_the_worker_is_busy_with_a_long_motion(self):
        plan = ReturnBookMotionPlan()
        reachable = BasePose(-0.35, -0.03, 0.25, 0.0, 0.0, 0.0).offset_cm(
            (0.0, 0.0, 0.0), rpy_deg=plan.insert_rpy_deg
        )
        entered = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)

        def blocked_move_l(target, duration_s):
            entered.set()
            release.wait(timeout=10.0)

        # A worker-routed public motion occupies the command worker…
        with patch.object(self.arm, "_move_l", side_effect=blocked_move_l):
            motion = threading.Thread(
                target=lambda: self.arm.move_l(reachable, 5.0), daemon=True
            )
            motion.start()
            self.assertTrue(entered.wait(timeout=5.0))
            # …and the off-worker probe still completes immediately instead of
            # queueing behind the motion.
            solution = self.arm.check_pose_reachable_offworker(
                reachable, plan.debug_joint, label="pre_insert_x_search"
            )
            self.assertIsInstance(solution, JointPose)
            release.set()
            motion.join(timeout=5.0)

    def test_probe_matches_the_worker_routed_judgment(self):
        plan = ReturnBookMotionPlan()
        reachable = BasePose(-0.35, -0.03, 0.25, 0.0, 0.0, 0.0).offset_cm(
            (0.0, 0.0, 0.0), rpy_deg=plan.insert_rpy_deg
        )
        offworker = self.arm.check_pose_reachable_offworker(
            reachable, plan.debug_joint, label="probe"
        )
        onworker = self.arm.check_pose_reachable(reachable, plan.debug_joint, label="probe")
        self.assertEqual(offworker, onworker)


if __name__ == "__main__":
    unittest.main()
