"""post_vision（书脊倾斜判定 + 车辆里程计定距居中）单元测试。"""

from __future__ import annotations

import math

import pytest

from bookarm.application.post_vision import (
    align_vehicle_to_center,
    calculate_comfortable_center_band,
    center_x_ratio,
    check_spine_tilt,
    compute_spine_tilt_deg,
)
from bookarm.domain.models.book import BookTarget
from bookarm.domain.models.pose import BasePose, JointPose
from bookarm.domain.plans.take_book import TakeBookMotionPlan


def _quad(cx: float, tilt_deg: float = 0.0, w: float = 100.0, h: float = 300.0,
          cy: float = 360.0):
    """生成中心在 (cx, cy)、宽 w 高 h、顺时针旋转 tilt_deg 度的四边形角点。"""
    rad = math.radians(tilt_deg)
    cos_r, sin_r = math.cos(rad), math.sin(rad)
    points = []
    for dx, dy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)):
        points.append((cx + dx * cos_r - dy * sin_r, cy + dx * sin_r + dy * cos_r))
    return tuple(points)


def _target(cx: float, tilt_deg: float = 0.0, frame_w: int = 1280) -> BookTarget:
    pose = BasePose(-0.3, 0.0, 0.5, 0.0, 0.0, 0.0)
    return BookTarget(
        raw_pose=pose,
        grasp_pose=pose,
        pixel_uv=(int(cx), 360),
        polygon_uv=_quad(cx, tilt_deg),
        frame_width_px=frame_w,
        frame_height_px=720,
        horizontal_pixel_to_base_m=(0.0005, 0.0, 0.0),
    )


def _projected_target(cx: float = 640.0) -> BookTarget:
    target = _target(cx)
    return BookTarget(
        raw_pose=target.raw_pose,
        grasp_pose=target.grasp_pose,
        pixel_uv=(int(cx), 360),
        polygon_uv=target.polygon_uv,
        frame_width_px=1280,
        frame_height_px=720,
        horizontal_pixel_to_base_m=(0.0005, 0.0, 0.0),
    )


class _ReachabilityArm:
    class _Config:
        joint_limits = {joint_id: (-1.0, 1.0) for joint_id in range(1, 7)}

    config = _Config()

    def check_pose_reachable_offworker(self, pose, seed, *, label):
        if pose.x_m < -0.32:
            raise RuntimeError("outside comfortable left workspace: %s" % label)
        return JointPose.from_values((0.0,) * 6)


class _FakeVehicle:
    def __init__(self):
        self.moves = []

    def move_distance(self, direction: str, distance_m: float):
        self.moves.append((direction, distance_m))
        return {
            "ok": True,
            "travelled_distance_m": distance_m,
            "error_m": 0.0,
            "duration_s": 1.0,
        }


class _FakeVision:
    """每次 locate_book 依队列返回识别结果。"""

    def __init__(self, targets):
        self._targets = list(targets)
        self.calls = 0

    def locate_book(self, template):
        self.calls += 1
        if not self._targets:
            raise RuntimeError("no more targets")
        return self._targets.pop(0)


class TestTilt:
    def test_vertical_is_zero(self):
        assert compute_spine_tilt_deg(_quad(640.0)) == pytest.approx(0.0, abs=0.5)

    def test_tilt_30(self):
        assert compute_spine_tilt_deg(_quad(640.0, tilt_deg=30.0)) == pytest.approx(30.0, abs=0.5)

    def test_horizontal_is_90(self):
        assert compute_spine_tilt_deg(_quad(640.0, w=300.0, h=100.0)) == pytest.approx(90.0, abs=0.5)

    def test_none_and_malformed(self):
        assert compute_spine_tilt_deg(None) is None
        assert compute_spine_tilt_deg(((0, 0), (1, 1), (2, 2))) is None

    def test_boundary_60(self):
        plan = TakeBookMotionPlan()
        # 恰好 60° 不超过阈值 → 放行
        assert check_spine_tilt(_target(640.0, tilt_deg=60.0), plan) == pytest.approx(60.0, abs=0.5)
        # 61° 超过 → 中止
        with pytest.raises(RuntimeError, match="书脊倾斜"):
            check_spine_tilt(_target(640.0, tilt_deg=61.0), plan)

    def test_unknown_tilt_policy(self):
        target = BookTarget(
            raw_pose=BasePose(-0.3, 0.0, 0.5, 0.0, 0.0, 0.0),
            grasp_pose=BasePose(-0.3, 0.0, 0.5, 0.0, 0.0, 0.0),
        )
        assert check_spine_tilt(target, TakeBookMotionPlan()) is None
        strict = TakeBookMotionPlan(spine_tilt_fail_on_unknown=True)
        with pytest.raises(RuntimeError, match="无法计算"):
            check_spine_tilt(target, strict)


class TestCenterAlign:
    def test_center_ratio(self):
        assert center_x_ratio(_target(640.0)) == pytest.approx(0.5, abs=0.01)
        assert center_x_ratio(_target(960.0)) == pytest.approx(0.75, abs=0.01)

    def test_ik_comfort_band_excludes_unreachable_left_center(self):
        band, details = calculate_comfortable_center_band(
            _projected_target(), TakeBookMotionPlan(), _ReachabilityArm()
        )

        assert band is not None
        assert band[0] > 0.46
        assert band[1] == pytest.approx(0.60, abs=0.001)
        assert details["checked"] is True
        assert details["sample_count"] == 21
        assert details["reachable_sample_count"] < details["sample_count"]

    def test_already_centered_no_move(self):
        vehicle = _FakeVehicle()
        target = _target(640.0)
        final, details = align_vehicle_to_center(
            _FakeVision([]), None, target, vehicle, TakeBookMotionPlan()
        )
        assert final is target
        assert details["aligned"] is False
        assert vehicle.moves == []

    def test_right_offset_moves_forward_then_rescans(self):
        vehicle = _FakeVehicle()
        # 初始偏右（0.86），动一次后居中
        vision = _FakeVision([_target(640.0)])
        final, details = align_vehicle_to_center(
            vision, None, _target(1100.0), vehicle, TakeBookMotionPlan()
        )
        assert vehicle.moves, "应发出里程计定距移动"
        assert vehicle.moves[0][0] == "forward"
        assert vehicle.moves[0][1] == pytest.approx(0.20)
        assert details["aligned"] is True
        assert details["align_moves"] == 1
        assert details["align_move_details"][0]["offset_px"] == pytest.approx(460.0)
        assert details["align_move_details"][0]["estimated_distance_m"] == pytest.approx(0.23)
        assert details["align_move_details"][0]["travelled_distance_m"] == pytest.approx(0.20)
        assert details["align_center_target_x_ratio"] == pytest.approx(0.5)
        assert details["align_center_error_ratio"] == pytest.approx(0.0)
        assert details["align_completion_reason"] == "inside_comfort_band"
        assert vision.calls == 1

    def test_sign_minus_one_reverses_direction(self):
        vehicle = _FakeVehicle()
        vision = _FakeVision([_target(640.0)])
        plan = TakeBookMotionPlan(align_direction_sign=-1)
        align_vehicle_to_center(vision, None, _target(1100.0), vehicle, plan)
        assert vehicle.moves[0][0] == "backward"

    def test_off_center_move_requires_camera_extrinsic_projection(self):
        target = _target(1100.0)
        target = BookTarget(
            raw_pose=target.raw_pose,
            grasp_pose=target.grasp_pose,
            polygon_uv=target.polygon_uv,
            frame_width_px=target.frame_width_px,
            frame_height_px=target.frame_height_px,
        )
        with pytest.raises(RuntimeError, match="相机外参"):
            align_vehicle_to_center(
                _FakeVision([]), None, target, _FakeVehicle(), TakeBookMotionPlan()
            )

    def test_default_step_distance_moves_directly_to_the_computed_center(self):
        vehicle = _FakeVehicle()
        vision = _FakeVision([_target(640.0)])
        plan = TakeBookMotionPlan()
        _, details = align_vehicle_to_center(vision, None, _target(1100.0), vehicle, plan)
        # 目标偏差 23 cm，高于累计安全上限时单次移动上限仍是 20 cm。
        assert vehicle.moves[0][0] == "forward"
        assert vehicle.moves[0][1] == pytest.approx(0.20)
        move = details["align_move_details"][0]
        assert move["direction"] == "forward"
        assert move["requested_distance_m"] == pytest.approx(0.20)

    def test_legacy_small_step_setting_does_not_split_full_distance_correction(self):
        vehicle = _FakeVehicle()
        vision = _FakeVision([_target(640.0)])
        # A previously saved small value must not force six or more tiny moves.
        plan = TakeBookMotionPlan(align_step_cm=2.0)
        align_vehicle_to_center(vision, None, _target(1100.0), vehicle, plan)
        assert vehicle.moves == [("forward", pytest.approx(0.20))]

    def test_target_already_in_stable_band_does_not_move(self, monkeypatch):
        monkeypatch.setattr(
            "bookarm.application.post_vision.calculate_comfortable_center_band",
            lambda *_args: ((0.55, 0.75), {"checked": True}),
        )
        vehicle = _FakeVehicle()
        vision = _FakeVision([])
        initial = _projected_target(896.0)  # 70%, already inside 55%~75% band.
        final, details = align_vehicle_to_center(
            vision,
            None,
            initial,
            vehicle,
            TakeBookMotionPlan(),
            arm=_ReachabilityArm(),
        )

        assert final is initial
        assert vehicle.moves == []
        assert details["align_center_target_x_ratio"] == pytest.approx(0.65)
        assert details["align_center_x_final"] == pytest.approx(0.70)
        assert details["align_moves"] == 0

    def test_capture_inside_safe_band_after_move_completes_without_reversal(self):
        vehicle = _FakeVehicle()
        # Small residual from the camera/odom is fine once the target is well
        # inside the stable operating band; do not chase the exact midpoint.
        vision = _FakeVision([_target(652.0)])

        _final, details = align_vehicle_to_center(
            vision, None, _target(1100.0), vehicle, TakeBookMotionPlan()
        )

        assert len(vehicle.moves) == 1
        assert vehicle.moves[0][0] == "forward"
        assert details["align_center_x_final"] == pytest.approx(652.0 / 1280.0, abs=0.00005)
        assert details["align_moves"] == 1

    def test_overshoot_past_safe_band_aborts_before_reverse_move(self, monkeypatch):
        monkeypatch.setattr(
            "bookarm.application.post_vision.calculate_comfortable_center_band",
            lambda *_args: ((0.40, 0.60), {"checked": True}),
        )
        vehicle = _FakeVehicle()
        vision = _FakeVision([_target(256.0)])

        with pytest.raises(RuntimeError, match="跨过舒适区.*停止反向追赶"):
            align_vehicle_to_center(
                vision, None, _target(1024.0), vehicle,
                TakeBookMotionPlan(align_max_travel_m=0.20),
                arm=_ReachabilityArm(),
            )

        # First correction only.  The old loop sent a backward command here.
        assert vehicle.moves == [("forward", pytest.approx(0.192))]

    def test_alignment_stops_if_rescan_makes_no_progress(self):
        vehicle = _FakeVehicle()
        vision = _FakeVision([_target(1100.0)])

        with pytest.raises(RuntimeError, match="偏差未明显减小"):
            align_vehicle_to_center(
                vision, None, _target(1100.0), vehicle, TakeBookMotionPlan()
            )

        assert len(vehicle.moves) == 1

    def test_same_direction_correction_can_continue_when_error_shrinks(self):
        vehicle = _FakeVehicle()
        vision = _FakeVision([_target(940.0), _target(652.0)])
        _, details = align_vehicle_to_center(
            vision, None, _target(1100.0), vehicle,
            TakeBookMotionPlan(align_max_travel_m=0.5, align_settle_ms=0),
        )
        assert [direction for direction, _ in vehicle.moves] == ["forward", "forward"]
        assert details["align_moves"] == 2

    def test_missing_geometry_after_moving_aborts(self):
        vehicle = _FakeVehicle()
        pose = BasePose(-0.3, 0.0, 0.5, 0.0, 0.0, 0.0)
        vision = _FakeVision([BookTarget(raw_pose=pose, grasp_pose=pose)])
        with pytest.raises(RuntimeError, match="复扫缺少目标几何"):
            align_vehicle_to_center(
                vision, None, _target(1100.0), vehicle,
                TakeBookMotionPlan(align_settle_ms=0),
            )
        assert len(vehicle.moves) == 1

    def test_move_estimate_uses_comfort_band_center(self, monkeypatch):
        monkeypatch.setattr(
            "bookarm.application.post_vision.calculate_comfortable_center_band",
            lambda *_args: ((0.55, 0.75), {"checked": True}),
        )
        vehicle = _FakeVehicle()
        vision = _FakeVision([_projected_target(832.0)])
        plan = TakeBookMotionPlan(align_step_cm=20.0, align_px_to_mm=10.0)
        initial = _projected_target(1100.0)
        initial = BookTarget(
            raw_pose=initial.raw_pose,
            grasp_pose=initial.grasp_pose,
            pixel_uv=initial.pixel_uv,
            polygon_uv=initial.polygon_uv,
            frame_width_px=initial.frame_width_px,
            frame_height_px=initial.frame_height_px,
            horizontal_pixel_to_base_m=(0.0, 0.00005, 0.0),
        )
        _, details = align_vehicle_to_center(
            vision, None, initial, vehicle, plan, arm=_ReachabilityArm()
        )
        move = details["align_move_details"][0]
        # band center is 0.65: 268 px × 0.05 mm/px = 13.4 mm;
        # use live extrinsic projection, ignoring align_px_to_mm.
        assert move["offset_px"] == pytest.approx(268.0)
        assert vehicle.moves[0] == ("forward", pytest.approx(0.0134))

    def test_legacy_step_above_hard_limit_is_rejected(self):
        with pytest.raises(RuntimeError, match="align_step_cm"):
            align_vehicle_to_center(
                _FakeVision([]), None, _target(1100.0), _FakeVehicle(),
                TakeBookMotionPlan(align_step_cm=21.0),
            )

    def test_max_moves_exceeded(self):
        vehicle = _FakeVehicle()
        # 每次都还是偏右 → 永远对不齐
        vision = _FakeVision([_target(1100.0) for _ in range(20)])
        with pytest.raises(RuntimeError, match="车辆对齐失败"):
            align_vehicle_to_center(vision, None, _target(1100.0), vehicle, TakeBookMotionPlan())

    def test_travel_cap(self):
        vehicle = _FakeVehicle()
        vision = _FakeVision([_target(1100.0) for _ in range(20)])
        plan = TakeBookMotionPlan(align_max_travel_m=0.05, align_max_moves=20)
        with pytest.raises(RuntimeError, match="行程"):
            align_vehicle_to_center(vision, None, _target(1100.0), vehicle, plan)
