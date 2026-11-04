"""Mid-takeout mode, step composition and independent calibration tests."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile

from bookarm.api.requests import TakeBookStage, TakeoutMode
from bookarm.domain.models.task import TaskState
from bookarm.domain.plans.mid_takeout import MidTakeoutMotionPlan
from bookarm.domain.plans.speed import apply_speed_level
from bookarm.infrastructure.config.calibration import load_book_stand_slots
from bookarm.infrastructure.config.profiles import load_mid_takeout_motion_plan
from bookarm.service.tuning import create_fake_tuning
from bookarm.service.runner import FakeWorkflowRunner
from bookarm.service.studio import FakeStudioBackend, StudioStore
from bookarm.application.use_cases.mid_takeout import MidTakeoutUseCase

from test_workflows import FakeArm, FakeReservation, _request, _sdk, _slots


def test_mid_takeout_full_close_skips_full_open_then_post_grasp_and_debug():
    plan = MidTakeoutMotionPlan()
    sdk, arm, _reservation = _sdk(arm=FakeArm(enabled=True))
    sdk._mid_takeout = MidTakeoutUseCase(
        task_manager=sdk._task_manager,
        reservation=FakeReservation(),
        lift=sdk._take_book.lift,
        vision=sdk._take_book.vision,
        arm=arm,
        rod=sdk._take_book.rod,
        slots=_slots(),
        plan=plan,
    )
    request = replace(
        _request(stop_after=TakeBookStage.BOOK_GRASP),
        takeout_mode=TakeoutMode.MID,
    )

    task = sdk.take_book(request)

    assert task.state is TaskState.SUCCEEDED
    open_angles = [call[1] for call in arm.calls if call[0] == "open_gripper"]
    assert open_angles == [50.0, 80.0]
    assert len([call for call in arm.calls if call == "close_gripper"]) == 2
    pose_moves = [call for call in arm.calls if call[0] == "move_to_pose_by_move_j"]
    assert pose_moves[-1][1].values() == task.result.payload["post_grasp_base_pose"]
    assert arm.calls[-1] == (
        "move_j",
        plan.debug_joint,
        plan.return_debug_duration_s,
    )


def test_mid_takeout_tuning_steps_reuse_the_requested_boundaries():
    with tempfile.TemporaryDirectory() as directory:
        runner = FakeWorkflowRunner(stage_delay_s=0.01)
        studio = FakeStudioBackend(
            StudioStore(Path(directory) / "studio"), busy_lock=runner.busy_lock
        )
        tuning = create_fake_tuning(runner, studio, store_dir=Path(directory) / "tuning")
        plan = runner.mid_takeout_plan

        names = [step.name for step in tuning.mid_takeout.session._steps(plan)]
        mid_names = [step.name for step in tuning.mid_return.session._steps(plan)]
        take_names = [step.name for step in tuning.take.session._steps(plan)]

        assert names[:10] == mid_names[:10]
        assert names[10] == "机械臂上移"
        assert names[11] == mid_names[10]
        assert names[12] == mid_names[11]
        assert names[13] == "完全闭合夹爪"
        assert names[14:] == take_names[8:]
        assert "midtakeout_place" in tuning.book_stand.view()
        runner.shutdown()


def test_mid_takeout_profile_is_independent_and_speed_scales_post_grasp():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "midtakeout.json"
        path.write_text(
            json.dumps(
                {
                    "speed_level": "fast",
                    "post_grasp_offset_cm": [15.0, 2.0, 8.0],
                    "post_grasp_duration_s": 2.0,
                }
            ),
            encoding="utf-8",
        )

        plan = load_mid_takeout_motion_plan(path)

        assert plan.post_grasp_offset_cm == (15.0, 2.0, 8.0)
        assert plan.post_grasp_duration_s == 2.0
        assert plan.raise_duration_s == 1.2
        assert plan.return_debug_duration_s == 1.8
        assert plan.gripper.kp == 40.0
        assert plan.gripper.kd == 3.0
        assert plan.gripper.carry_effort == 0.2
        assert apply_speed_level(MidTakeoutMotionPlan()).post_grasp_duration_s == 2.0


def test_packaged_mid_takeout_slots_contain_only_calibrated_poses():
    path = (
        Path(__file__).resolve().parents[1]
        / "config"
        / "calibration"
        / "midtakeout_book_stand_slots.json"
    )

    slots = load_book_stand_slots(path)

    assert set(slots) == {1, 2, 3}
    for plan in slots.values():
        assert plan.lower_place.z_m > 0.0


def test_mid_takeout_lower_profile_supports_six_offsets_and_legacy_z():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "midtakeout.json"
        path.write_text(
            json.dumps(
                {
                    "lower_z_offset_cm": -3.0,
                    "lower_rpy_offset_deg": [4.0, 5.0, 6.0],
                }
            ),
            encoding="utf-8",
        )

        plan = load_mid_takeout_motion_plan(path)

        assert plan.lower_offset_cm == (0.0, 0.0, -3.0)
        assert plan.lower_rpy_offset_deg == (4.0, 5.0, 6.0)


def test_mid_takeout_lower_motion_applies_six_offsets():
    sdk, arm, _reservation = _sdk(arm=FakeArm(enabled=True))
    plan = replace(
        MidTakeoutMotionPlan(),
        lower_offset_cm=(1.0, 2.0, -3.0),
        lower_rpy_offset_deg=(4.0, 5.0, 6.0),
    )
    sdk._mid_takeout = MidTakeoutUseCase(
        task_manager=sdk._task_manager,
        reservation=FakeReservation(),
        lift=sdk._take_book.lift,
        vision=sdk._take_book.vision,
        arm=arm,
        rod=sdk._take_book.rod,
        slots=_slots(),
        plan=plan,
    )
    request = replace(
        _request(stop_after=TakeBookStage.BOOK_GRASP),
        takeout_mode=TakeoutMode.MID,
    )

    task = sdk.take_book(request)

    assert task.state is TaskState.SUCCEEDED
    target = sdk._take_book.vision.locate_book(request.spine_template)
    fine = target.grasp_pose.offset_cm(
        plan.fine_grasp_offset_cm, rpy_deg=plan.fine_grasp_rpy_deg
    )
    push_in = fine.offset_cm((plan.push_in_x_offset_cm, 0.0, 0.0))
    re_push = push_in.offset_cm((plan.re_push_x_offset_cm, 0.0, 0.0))
    raised = re_push.offset_cm((0.0, 0.0, plan.raise_z_offset_cm))
    expected = raised.offset_cm(
        plan.lower_offset_cm, rpy_offset_deg=plan.lower_rpy_offset_deg
    )
    assert task.result.payload["raise_base_pose"] == raised.values()
    assert task.result.payload["lower_base_pose"] == expected.values()
    assert [call[1] for call in arm.calls if call[0] == "move_l"][-3:] == [
        re_push,
        raised,
        expected,
    ]
