"""Offline regressions for the 2026-10-22 take-book profile failure."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from bookarm.application.post_vision import (
    _joint_clearance_error,
    _take_book_chain_is_comfortable,
    calculate_comfortable_center_band,
)
from bookarm.devices.arm.kinematics import PinocchioKinematics
from bookarm.devices.arm.protocol import DEFAULT_JOINT_LIMITS
from bookarm.devices.arm.service import BOOK_DEBUG_JOINT, DEFAULT_TCP_OFFSET, ZERO_JOINT
from bookarm.domain.models.book import BookTarget
from bookarm.domain.models.pose import BasePose, JointPose
from bookarm.domain.plans.take_book import TakeBookMotionPlan


@pytest.fixture
def offline_arm():
    pytest.importorskip("pinocchio")
    kinematics = PinocchioKinematics(
        Path(__file__).resolve().parents[1] / "resources/urdf/el_a3.urdf",
        DEFAULT_TCP_OFFSET,
    )

    def check(pose, seed, *, label):
        return kinematics.solve_ik(pose, seed, fallback_seeds=(ZERO_JOINT, BOOK_DEBUG_JOINT))

    return SimpleNamespace(
        config=SimpleNamespace(joint_limits=DEFAULT_JOINT_LIMITS),
        check_pose_reachable_offworker=check,
    )


def field_plan(angle, margin=0.20):
    # Explicit incident settings, independent of mutable on-machine profiles.
    return replace(
        TakeBookMotionPlan(), grasp_rpy_deg=(75.0, 10.0, 90.0),
        fine_grasp_offset_cm=(1.0, 1.5, -1.0),
        fine_grasp_rpy_deg=(angle, 0.0, 90.0),
        post_grasp_offset_cm=(15.0, 0.0, 8.0),
        post_grasp_rpy_offset_deg=(0.0, 0.0, 0.0),
        align_joint_comfort_margin_rad=margin,
    )


def target_at(x=-0.39700005054473875, z=0.18722332502539107):
    pose = BasePose(x, -0.28158208707189175, z, 0.0, 0.0, 0.0)
    # Representative calibrated projection; the task store retained the base
    # point, but not intrinsics. This models the observed camera transform.
    pixel_scale = (0.15 - x) / 900.0
    return BookTarget(
        raw_pose=pose, grasp_pose=pose,
        pixel_uv=(640.0 + (pose.y_m + 0.29) / pixel_scale, 360),
        frame_width_px=1280, frame_height_px=720,
        horizontal_pixel_to_base_m=(0.0, pixel_scale, 0.0),
    )


def test_incident_profile_has_no_comfortable_center_band(offline_arm):
    band, details = calculate_comfortable_center_band(target_at(), field_plan(90), offline_arm)
    assert band is None
    assert details["reachable_sample_count"] == 0
    assert "关节" in details["detail"]
    assert "余量" in details["detail"]
    assert "IK 探测未得到可达解" not in details["detail"]


def test_calibrated_profile_passes_exact_failed_target(offline_arm):
    comfortable, error = _take_book_chain_is_comfortable(offline_arm, target_at(), field_plan(80))
    assert comfortable, error


def test_90_degree_field_profile_passes_with_configured_005_rad_clearance(offline_arm):
    band, details = calculate_comfortable_center_band(
        target_at(), field_plan(90, margin=0.05), offline_arm
    )
    assert band is not None, details
    assert details["joint_comfort_margin_rad"] == 0.05
    assert details["reachable_sample_count"] >= 10


@pytest.mark.parametrize("dx", [-0.005, 0.0, 0.005])
@pytest.mark.parametrize("dz", [-0.003, 0.0, 0.003])
def test_calibrated_profile_retains_band_under_small_measurement_changes(offline_arm, dx, dz):
    band, details = calculate_comfortable_center_band(
        target_at(-0.39700005054473875 + dx, 0.18722332502539107 + dz),
        field_plan(80), offline_arm,
    )
    assert band is not None, details
    assert band[1] - band[0] > 0.01
    assert details["joint_comfort_margin_rad"] == 0.20


@pytest.mark.parametrize("dx", [-0.005, 0.0, 0.005])
@pytest.mark.parametrize("dz", [-0.003, 0.0, 0.003])
def test_90_degree_profile_retains_band_under_small_measurement_changes(offline_arm, dx, dz):
    band, details = calculate_comfortable_center_band(
        target_at(-0.39700005054473875 + dx, 0.18722332502539107 + dz),
        field_plan(90, margin=0.05), offline_arm,
    )
    assert band is not None, details
    assert band[1] - band[0] > 0.01
    assert details["joint_comfort_margin_rad"] == 0.05


def test_clearance_error_identifies_limiting_joint_and_actual_margin():
    arm = SimpleNamespace(config=SimpleNamespace(joint_limits={i: (-1, 1) for i in range(1, 7)}))
    error = _joint_clearance_error(arm, JointPose.from_values((0, 0, 0, 0, 0.89, 0)))
    assert "第 5 关节" in error
    assert "0.110 rad" in error
    assert "0.20 rad" in error


def test_nonfinite_joint_solution_cannot_pass_clearance():
    arm = SimpleNamespace(config=SimpleNamespace(joint_limits={i: (-1, 1) for i in range(1, 7)}))
    assert _joint_clearance_error(arm, SimpleNamespace(values_rad=(float("nan"), 0, 0, 0, 0, 0)))
