"""Numerical compatibility tests for BookArm and the GUI kinematics contract."""

from __future__ import annotations

import math
from pathlib import Path
import unittest

import numpy as np

from bookarm.devices.arm.kinematics import PinocchioKinematics
from bookarm.devices.arm.motion import linear_pose
from bookarm.devices.arm.protocol import DEFAULT_JOINT_LIMITS
from bookarm.devices.arm.service import BOOK_DEBUG_JOINT, DEFAULT_TCP_OFFSET, ZERO_JOINT
from bookarm.application.post_vision import calculate_comfortable_center_band
from bookarm.domain.models.book import BookTarget
from bookarm.domain.models.pose import BasePose, JointPose
from bookarm.domain.plans.take_book import TakeBookMotionPlan


_URDF = Path(__file__).resolve().parents[1] / "resources" / "urdf" / "el_a3.urdf"
_TCP = (0.0, 0.01, -0.14, 0.0, 0.0, 0.0)


class KinematicsGuiAlignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            cls.kinematics = PinocchioKinematics(_URDF, _TCP)
        except RuntimeError as error:
            raise unittest.SkipTest("Pinocchio unavailable: %s" % error) from error

    def test_fk_matches_known_gui_reference_pose(self) -> None:
        pose = self.kinematics.forward_kinematics(
            JointPose.from_values((0.2, 0.5, -1.2, 0.4, 0.3, -0.2))
        )
        expected = np.asarray((
            -0.18509801916220375,
            0.026879169013196376,
            0.469476491047346,
            1.8688624099409454,
            0.27899951427837477,
            1.5420582306414021,
        ))
        np.testing.assert_allclose(np.asarray(pose.values()), expected, rtol=0.0, atol=1e-12)

    def test_ik_uses_gui_limit_margin(self) -> None:
        target = self.kinematics.forward_kinematics(
            JointPose.from_values((0.0, 0.0, -0.5, 0.0, 0.0, 0.0))
        )
        solution = self.kinematics.inverse_kinematics(
            target,
            JointPose.from_values((0.0, 0.1, -0.5, 0.0, 0.0, 0.0)),
        )
        self.assertIsNone(solution)

    def test_ik_step_keeps_all_joints_inside_hard_limits(self) -> None:
        target = BasePose(0.2, 0.0, 0.2, 0.0, 0.0, 0.0)
        solution, _ = self.kinematics.ik_step(
            target,
            JointPose.from_values((0.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
        )
        self.assertGreaterEqual(solution.values_rad[1], 0.0)
        self.assertLessEqual(solution.values_rad[2], 0.0)

    def test_linear_pose_uses_shortest_rotation_path(self) -> None:
        start = BasePose(0.0, 0.0, 0.0, 0.0, 0.0, math.radians(179.0))
        target = BasePose(1.0, 0.0, 0.0, 0.0, 0.0, math.radians(-179.0))
        middle = linear_pose(start, target, 0.5)
        self.assertAlmostEqual(middle.x_m, 0.5)
        self.assertGreater(abs(middle.rz_rad), math.radians(170.0))

    def test_solve_ik_retries_fallback_seeds_for_seed_sensitive_target(self) -> None:
        # Regression for a field failure: the DLS iteration drove joint 1 into
        # its limit from the measured debug-pose seed even though the target
        # is reachable; zero and the nominal debug pose both solve it.
        target = BasePose(
            -0.3710000514984131, -0.17743370579474088, 0.23977270748349683,
            1.0471975511965976, 0.0, 1.5707963267948966,
        )
        measured_seed = JointPose.from_values((
            0.0005754177157246687, 0.18470908674753872, -1.1195710688944835,
            0.881348134584572, 0.0005754177157246687, -0.00019180590524214836,
        ))
        zero = JointPose.from_values((0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
        self.assertIsNone(self.kinematics.inverse_kinematics(target, measured_seed))

        solution = self.kinematics.solve_ik(target, measured_seed, fallback_seeds=(zero,))

        expected = (0.76, 1.678, -1.593, 0.588, 0.64, -0.444)
        np.testing.assert_allclose(
            np.asarray(solution.values_rad), np.asarray(expected), atol=5e-3,
        )

    def test_calibrated_pregrasp_angle_reaches_boundary_shelf_pose(self) -> None:
        # Regression for the field failure: the 60° default did not converge
        # at this previously tested shelf point, while the shipped take-book
        # profile's 75° approach has a valid in-limit solution.
        plan = TakeBookMotionPlan()
        self.assertEqual(plan.grasp_rpy_deg, (75.0, 0.0, 90.0))
        target = BasePose(
            -0.362000048160553,
            -0.3398057457260085,
            0.18158830916335394,
            math.radians(plan.grasp_rpy_deg[0]),
            math.radians(plan.grasp_rpy_deg[1]),
            math.radians(plan.grasp_rpy_deg[2]),
        )

        solution = self.kinematics.solve_ik(
            target,
            JointPose.from_values((
                0.0, 0.17453292519943295, -1.1344640137963142,
                0.8726646259971648, 0.0, 0.0,
            )),
            fallback_seeds=(JointPose.from_values((0.0, 0.0, 0.0, 0.0, 0.0, 0.0)),),
        )

        solved_pose = np.asarray(self.kinematics.forward_kinematics(solution).values())
        np.testing.assert_allclose(solved_pose, np.asarray(target.values()), rtol=0.0, atol=1e-4)

    def test_fine_grasp_angle_leaves_a_comfortable_center_band(self) -> None:
        # Regression for the next field rejection: the old 95° fine-grasp
        # default left no candidate in the 20% center window with 0.20 rad
        # clearance, while the calibrated 80° posture leaves a continuous band.
        point = (-0.3900000214576721, -0.33197222185073827, 0.1834536562395411)
        target = BookTarget(
            raw_pose=BasePose(*point, 0.0, 0.0, 0.0),
            grasp_pose=BasePose(*point, 0.0, 0.0, 0.0),
            pixel_uv=(575, 352),
            frame_width_px=1280,
            frame_height_px=720,
            horizontal_pixel_to_base_m=(0.0, point[2] / 900.0, 0.0),
        )

        class OfflineArmProbe:
            config = type("ArmConfig", (), {"joint_limits": DEFAULT_JOINT_LIMITS})()

            def check_pose_reachable_offworker(self, pose, seed, *, label):
                return self_kinematics.solve_ik(
                    pose, seed, fallback_seeds=(ZERO_JOINT, BOOK_DEBUG_JOINT)
                )

        self_kinematics = self.kinematics
        band, details = calculate_comfortable_center_band(
            target, TakeBookMotionPlan(), OfflineArmProbe()
        )

        self.assertIsNotNone(band, details)
        self.assertLessEqual(band[0], 0.5)
        self.assertGreaterEqual(band[1], 0.5)
