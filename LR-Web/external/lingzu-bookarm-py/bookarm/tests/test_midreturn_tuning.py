"""Mid-return tuning kind tests with the hardware-free backends."""

from __future__ import annotations

import json
import math
from pathlib import Path
import tempfile
import unittest

import numpy as np
from fastapi.testclient import TestClient

from bookarm.domain.plans.mid_return import MidReturnMotionPlan
from bookarm.infrastructure.config.profiles import load_mid_return_motion_plan
from bookarm.service.app import create_app
from bookarm.service.runner import FakeWorkflowRunner
from bookarm.service.studio import FakeStudioBackend, StudioStore
from bookarm.service.tuning import create_fake_tuning, plan_to_dict


TUNING_URL = "/api/v1/tuning"
KIND_URL = "%s/midreturn" % TUNING_URL


class MidReturnProfileTests(unittest.TestCase):
    def setUp(self):
        self._dirs = tempfile.TemporaryDirectory()
        self.addCleanup(self._dirs.cleanup)
        root = Path(self._dirs.name)
        self.tuning_dir = root / "tuning"
        self.runner = FakeWorkflowRunner(stage_delay_s=0.01)
        self.addCleanup(self.runner.shutdown)
        self.studio = FakeStudioBackend(
            StudioStore(root / "studio"), busy_lock=self.runner.busy_lock
        )
        self.tuning = create_fake_tuning(self.runner, self.studio, store_dir=self.tuning_dir)
        self.client = TestClient(
            create_app(
                self.runner,
                upload_dir=root / "uploads",
                studio=self.studio,
                tuning=self.tuning,
            )
        )

    def test_get_profile_returns_all_midreturn_fields(self):
        response = self.client.get("%s/profile" % KIND_URL)

        self.assertEqual(response.status_code, 200)
        profile = response.json()
        self.assertEqual(len(profile["zero_joint"]), 6)
        self.assertEqual(len(profile["debug_joint"]), 6)
        self.assertEqual(profile["joint_tolerance_rad"], 0.08)
        self.assertEqual(profile["zero_duration_s"], 3.0)
        self.assertEqual(profile["debug_duration_s"], 3.0)
        # Grasp chain reused from the take-book flow.
        self.assertEqual(profile["pickup_open_deg"], 50.0)
        self.assertEqual(profile["pickup_light_close_rpy_offset_deg"], [0.0, 0.0, 0.0])
        self.assertEqual(profile["pregrasp_offset_cm"], [10.0, 0.0, 0.0])
        self.assertEqual(profile["grasp_rpy_deg"], [75.0, 0.0, 90.0])
        self.assertEqual(profile["approach_offset_cm"], [0.0, 0.0, 0.0])
        self.assertEqual(profile["fine_grasp_offset_cm"], [1.0, 0.0, 0.0])
        self.assertEqual(profile["fine_grasp_rpy_deg"], [80.0, 0.0, 90.0])
        self.assertEqual(profile["pregrasp_duration_s"], 3.0)
        self.assertEqual(profile["approach_duration_s"], 2.0)
        self.assertEqual(profile["fine_grasp_duration_s"], 2.0)
        self.assertEqual(profile["rod_grasp_deg"], -70.0)
        self.assertEqual(profile["rod_home_deg"], 0.0)
        self.assertEqual(profile["rod_putback_deg"], 0.0)
        self.assertEqual(profile["pickup_rod_home_deg"], 0.0)
        self.assertEqual(profile["rod_speed"], 1000)
        self.assertEqual(profile["rod_acceleration"], 50)
        self.assertEqual(profile["rod_tolerance_deg"], 1.5)
        self.assertEqual(profile["rod_timeout_s"], 12.0)
        self.assertEqual(profile["gripper"]["close_deg"], 108.5)
        self.assertEqual(profile["gripper"]["kp"], 40.0)
        self.assertEqual(profile["gripper"]["kd"], 3.0)
        # Put-back and clear-out of the pulled book.
        self.assertEqual(profile["push_in_x_offset_cm"], -5.0)
        self.assertEqual(profile["push_in_duration_s"], 2.0)
        self.assertEqual(profile["partial_release_deg"], 80.0)
        self.assertEqual(profile["full_open_deg"], 50.0)
        self.assertEqual(profile["lower_z_offset_cm"], -5.0)
        self.assertEqual(profile["lower_duration_s"], 2.0)
        self.assertEqual(profile["shift_y_offset_cm"], 5.0)
        self.assertEqual(profile["shift_duration_s"], 2.0)
        self.assertEqual(profile["forward_x_offset_cm"], 10.0)
        self.assertEqual(profile["forward_duration_s"], 2.0)
        # Steps 27-29 match end-return target XY offsets and absolute Z values.
        self.assertEqual(profile["pre_insert_xy_offset_m"], [0.30, 0.04])
        self.assertEqual(profile["pre_insert_z_m"], 0.04)
        self.assertEqual(profile["pre_insert_rpy_deg"], [95.0, 0.0, 90.0])
        self.assertEqual(profile["pre_insert_duration_s"], 3.0)
        self.assertEqual(profile["insert_xy_offset_m"], [0.0, 0.04])
        self.assertEqual(profile["insert_z_m"], 0.04)
        self.assertEqual(profile["insert_rpy_deg"], [95.0, 0.0, 90.0])
        self.assertEqual(profile["insert_duration_s"], 3.0)
        self.assertEqual(profile["push_xy_offset_m"], [-0.05, 0.04])
        self.assertEqual(profile["push_z_m"], 0.04)
        self.assertEqual(profile["push_rpy_deg"], [0.0, 0.0, 0.0])
        self.assertEqual(profile["push_duration_s"], 2.0)
        self.assertEqual(profile["release_open_deg"], 50.0)
        self.assertEqual(profile["retract_x_offset_cm"], 10.0)
        self.assertEqual(profile["retract_rpy_deg"], [90.0, 0.0, 90.0])
        self.assertEqual(profile["retract_duration_s"], 2.0)
        self.assertEqual(profile["rotate_rpy_deg"], [0.0, 90.0, 0.0])
        self.assertEqual(profile["rotate_z_offset_cm"], 0.0)
        self.assertEqual(profile["rotate_duration_s"], 2.0)
        self.assertEqual(profile["press_x_offset_cm"], -5.0)
        self.assertEqual(profile["press_duration_s"], 2.0)
        self.assertEqual(profile["press_retract_x_offset_cm"], 5.0)
        self.assertEqual(profile["press_retract_duration_s"], 2.0)
        # Fields retired with the replaced steps are gone.
        for removed in (
            "pre_insert_offset_cm",
            "gap_select",
            "scan_height_ratio",
            "scan_band_px",
            "depth_gap_mm",
            "gap_max_y_deviation_cm",
            "y_bias_cm",
            "gap_method",
            "gap_conf",
            "shake_offset_cm",
            "shake_count",
            "shake_y_offset_cm",
            "shake_duration_s",
            "push_offset_cm",
            "lower_offset_cm",
            "retreat_offset_cm",
            "retreat_duration_s",
            "rise_z_offset_cm",
            "rise_duration_s",
            "post_grasp_offset_cm",
            "post_grasp_rpy_offset_deg",
            "post_grasp_duration_s",
            "pre_place_offset_cm",
            "place_offset_cm",
            "place_rpy_deg",
            "pre_place_duration_s",
            "place_duration_s",
            "retreat_shelf_duration_s",
        ):
            self.assertNotIn(removed, profile)

    def test_legacy_light_close_forward_distance_migrates_to_down(self):
        path = Path(self._dirs.name) / "legacy-light-close.json"
        path.write_text(
            json.dumps(
                {
                    "pickup_light_close_forward_cm": 2.0,
                    "pickup_raise_z_offset_cm": 1.0,
                }
            ),
            encoding="utf-8",
        )

        plan = load_mid_return_motion_plan(path)

        self.assertEqual(plan.pickup_light_close_down_cm, 2.0)

    def test_put_partial_update_applies_and_persists(self):
        response = self.client.put(
            "%s/profile" % KIND_URL,
            json={
                "push_xy_offset_m": [-0.08, 0.065],
                "push_z_m": 0.30,
                "shift_y_offset_cm": 7.0,
                "partial_release_deg": 85.0,
                "insert_xy_offset_m": [0.01, 0.065],
                "insert_z_m": 0.28,
                "fine_grasp_rpy_deg": [85.0, 0.0, 90.0],
                "gripper": {"effort": 0.7},
            },
        )

        self.assertEqual(response.status_code, 200)
        current = self.client.get("%s/profile" % KIND_URL).json()
        self.assertEqual(current["push_xy_offset_m"], [-0.08, 0.065])
        self.assertEqual(current["push_z_m"], 0.30)
        self.assertEqual(current["shift_y_offset_cm"], 7.0)
        self.assertEqual(current["partial_release_deg"], 85.0)
        self.assertEqual(current["insert_xy_offset_m"], [0.01, 0.065])
        self.assertEqual(current["insert_z_m"], 0.28)
        self.assertEqual(current["fine_grasp_rpy_deg"], [85.0, 0.0, 90.0])
        self.assertEqual(current["gripper"]["effort"], 0.7)
        # The live plan the fake runner holds is hot-swapped, not copied.
        self.assertEqual(self.runner.mid_return_plan.push_xy_offset_m, (-0.08, 0.065))
        self.assertEqual(self.runner.mid_return_plan.insert_z_m, 0.28)

        persisted = self.tuning_dir / "midreturn_profile.json"
        self.assertTrue(persisted.is_file())
        reloaded = load_mid_return_motion_plan(persisted)
        self.assertEqual(reloaded.push_xy_offset_m, (-0.08, 0.065))
        self.assertEqual(reloaded.push_z_m, 0.30)
        self.assertEqual(reloaded.shift_y_offset_cm, 7.0)
        self.assertEqual(reloaded.partial_release_deg, 85.0)
        self.assertEqual(reloaded.insert_xy_offset_m, (0.01, 0.065))
        self.assertEqual(reloaded.insert_z_m, 0.28)
        self.assertEqual(reloaded.fine_grasp_rpy_deg, (85.0, 0.0, 90.0))
        self.assertEqual(reloaded.gripper.effort, 0.7)

    def test_put_unknown_or_invalid_field_is_rejected(self):
        unknown = self.client.put("%s/profile" % KIND_URL, json={"bogus_field": 1})
        self.assertEqual(unknown.status_code, 422)
        self.assertIn("unknown fields", unknown.json()["detail"])

        # Fields retired from the old flow are rejected like any unknown key.
        legacy = self.client.put("%s/profile" % KIND_URL, json={"shake_count": 5})
        self.assertEqual(legacy.status_code, 422)
        self.assertIn("unknown fields", legacy.json()["detail"])

        bad_gripper = self.client.put("%s/profile" % KIND_URL, json={"gripper": {"bogus": 1}})
        self.assertEqual(bad_gripper.status_code, 422)

        # The retired gap-scan fields are rejected like any unknown key.
        for retired in ("gap_select", "scan_height_ratio", "depth_gap_mm", "y_bias_cm", "gap_method", "gap_conf"):
            rejected_retired = self.client.put("%s/profile" % KIND_URL, json={retired: 1})
            self.assertEqual(rejected_retired.status_code, 422)
            self.assertIn("unknown fields", rejected_retired.json()["detail"])

        # Retired insert fields are ignored for backward-compatible profiles.
        for name in (
            "target_y_offset_cm",
            "insert_offset_cm",
            "min_insert_z_m",
            "pre_insert_x_max_m",
            "pre_insert_y_offset_cm",
            "pre_insert_z_offset_cm",
            "push_x_offset_cm",
            "push_z_offset_cm",
        ):
            accepted = self.client.put(
                "%s/profile?persist=false" % KIND_URL, json={name: 1.0}
            )
            self.assertEqual(accepted.status_code, 200, name)

        rejected = self.client.put(
            "%s/profile?persist=false" % KIND_URL,
            json={"insert_xy_offset_m": [0.0, 0.1, 0.2]},
        )
        self.assertEqual(rejected.status_code, 422)
        self.assertIn("insert_xy_offset_m", rejected.json()["detail"])
        self.assertEqual(self.runner.mid_return_plan.push_z_m, 0.04)
        self.assertFalse((self.tuning_dir / "midreturn_profile.json").exists())


class MidReturnSessionTests(unittest.TestCase):
    def setUp(self):
        self._dirs = tempfile.TemporaryDirectory()
        self.addCleanup(self._dirs.cleanup)
        root = Path(self._dirs.name)
        self.tuning_dir = root / "tuning"
        self.runner = FakeWorkflowRunner(stage_delay_s=0.01)
        self.addCleanup(self.runner.shutdown)
        self.studio = FakeStudioBackend(
            StudioStore(root / "studio"), busy_lock=self.runner.busy_lock
        )
        self.tuning = create_fake_tuning(self.runner, self.studio, store_dir=self.tuning_dir)
        self.client = TestClient(
            create_app(
                self.runner,
                upload_dir=root / "uploads",
                studio=self.studio,
                tuning=self.tuning,
            )
        )

    def library_id(self) -> str:
        image_bgr = np.full((12, 8, 3), 180, np.uint8)
        return self.studio.import_library_image(image_bgr, source="test").id

    def prepare(self, slot: int = 1) -> dict:
        response = self.client.post(
            "%s/session/prepare" % KIND_URL,
            json={"slot": slot, "template_id": self.library_id()},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_session_walks_all_thirty_five_steps(self):
        session = self.client.get("%s/session" % KIND_URL).json()
        self.assertEqual(session["step_index"], 0)
        self.assertFalse(session["has_target"])
        self.assertEqual(len(session["steps"]), 35)
        self.assertEqual(
            session["steps"],
            [
                "张开夹爪(pickup_open_deg)",
                "推杆归零",
                "预抓取位",
                "逼近目标(move_l)",
                "推杆拨书(rod_grasp_deg)",
                "精抓",
                "闭合夹爪",
                "推回(push_in_x)",
                "松开一点夹爪(partial_release_deg)",
                "推杆归位",
                "再次推回(re_push_x)",
                "机械臂下降(lower_z)",
                "完全张开夹爪(full_open_deg)",
                "闭合夹爪",
                "书本前移(carry_forward_x)",
                "松开一点夹爪(partial_release_deg)",
                "机械臂前移(forward_x)",
                "回调试位",
                "张开夹爪(pickup_open_deg)",
                "识别目标书",
                "运动到书槽(pre_grasp→grasp)",
                "推杆归位",
                "轻闭夹爪",
                "调整夹书深度",
                "闭合夹爪",
                "回调试位",
                "预插入位",
                "运动到插入位",
                "推回书架(push_x)",
                "张开夹爪(release_open_deg)",
                "回抽(retract_x)",
                "旋转",
                "压书",
                "二次回抽",
                "回调试位",
            ],
        )

        prepared = self.prepare(slot=1)
        self.assertTrue(prepared["ok"])
        self.assertEqual(len(prepared["target_base_pose"]), 6)

        step_names = []
        details = []
        for expected_index in range(1, 36):
            step = self.client.post("%s/session/step/next" % KIND_URL)
            self.assertEqual(step.status_code, 200)
            self.assertTrue(step.json()["ok"])
            self.assertEqual(step.json()["step_index"], expected_index)
            step_names.append(step.json()["step_name"])
            details.append(step.json()["detail"])
        self.assertEqual(step_names[0], "张开夹爪(pickup_open_deg)")
        self.assertEqual(step_names[-1], "回调试位")
        # Grasp chain, mirroring the take-book flow off the vision target
        # (-0.35, -0.07, 0.23): pregrasp adds +10 cm x, fine grasp +1 cm x.
        self.assertEqual(details[0]["open_deg"], 50.0)
        self.assertEqual(details[1]["rod_deg"], 0.0)
        self.assertAlmostEqual(details[2]["base_pose"][0], -0.25)
        self.assertAlmostEqual(details[2]["base_pose"][1], -0.07)
        self.assertAlmostEqual(details[2]["base_pose"][2], 0.23)
        self.assertAlmostEqual(details[3]["base_pose"][0], -0.35)
        self.assertEqual(details[4]["rod_deg"], -70.0)
        self.assertAlmostEqual(details[5]["base_pose"][0], -0.34)
        self.assertIn("gripper_close", details[6])
        self.assertAlmostEqual(details[7]["base_pose"][0], -0.39)
        self.assertEqual(details[8]["open_deg"], 80.0)
        self.assertEqual(details[9]["rod_deg"], 0.0)
        # Re-push reads the current pose and adds only its own X offset.
        self.assertAlmostEqual(details[10]["base_pose"][0], -0.41)
        self.assertAlmostEqual(details[11]["base_pose"][0], -0.41)
        self.assertAlmostEqual(details[11]["base_pose"][2], 0.18)
        # The deleted shift step no longer changes Y; each forward move starts
        # from the current pose and adds only its own X offset.
        self.assertEqual(details[12]["open_deg"], 50.0)
        self.assertIn("gripper_close", details[13])
        self.assertAlmostEqual(details[14]["base_pose"][0], -0.36)
        self.assertAlmostEqual(details[14]["base_pose"][1], -0.07)
        self.assertAlmostEqual(details[14]["base_pose"][2], 0.18)
        self.assertEqual(details[15]["open_deg"], 80.0)
        self.assertAlmostEqual(details[16]["base_pose"][0], -0.26)
        self.assertAlmostEqual(details[16]["base_pose"][1], -0.07)
        self.assertAlmostEqual(details[16]["base_pose"][2], 0.18)
        self.assertEqual(len(details[17]["debug_joint_rad"]), 6)
        self.assertEqual(details[18]["open_deg"], 50.0)
        # Retarget before pickup, then hold the book and go directly to pre-insert.
        self.assertEqual(step_names[19], "识别目标书")
        self.assertEqual(len(details[19]["target_base_pose"]), 6)
        self.assertAlmostEqual(details[19]["target_base_pose"][1], -0.07)
        self.assertEqual(len(details[20]["pre_grasp_pose"]), 6)
        self.assertEqual(len(details[20]["grasp_pose"]), 6)
        self.assertAlmostEqual(details[20]["pre_grasp_pose"][0], -0.30)
        self.assertAlmostEqual(details[20]["grasp_pose"][0], -0.34)
        self.assertEqual(details[21]["rod_deg"], 0.0)
        self.assertIn("gripper_close", details[22])
        self.assertEqual(details[22]["light_close_deg"], 70.0)
        self.assertEqual(details[23]["current_base_pose"], details[20]["grasp_pose"])
        self.assertAlmostEqual(
            details[23]["base_pose"][2], details[20]["grasp_pose"][2] - 0.01
        )
        self.assertIn("gripper_close", details[24])
        self.assertNotIn("adaptive_carry", details[24])
        self.assertEqual(len(details[25]["debug_joint_rad"]), 6)
        pre_insert_pose = details[26]["base_pose"]
        self.assertAlmostEqual(pre_insert_pose[0], -0.05)
        self.assertAlmostEqual(pre_insert_pose[1], -0.03)
        self.assertAlmostEqual(pre_insert_pose[2], 0.04)
        insert_pose = details[27]["base_pose"]
        self.assertAlmostEqual(insert_pose[0], -0.35)
        self.assertAlmostEqual(insert_pose[1], -0.03)
        self.assertAlmostEqual(insert_pose[2], 0.04)
        push_pose = details[28]["base_pose"]
        self.assertAlmostEqual(push_pose[0], -0.40)
        self.assertAlmostEqual(push_pose[1], insert_pose[1])
        self.assertAlmostEqual(push_pose[2], insert_pose[2])
        self.assertEqual(details[29]["open_deg"], 50.0)
        retract_pose = details[30]["base_pose"]
        self.assertAlmostEqual(retract_pose[0], -0.30)
        self.assertAlmostEqual(retract_pose[1], insert_pose[1])
        self.assertAlmostEqual(retract_pose[2], insert_pose[2])
        rotate_pose = details[31]["base_pose"]
        self.assertAlmostEqual(rotate_pose[0], retract_pose[0])
        self.assertAlmostEqual(rotate_pose[2], retract_pose[2])
        self.assertAlmostEqual(rotate_pose[4], retract_pose[4] + math.pi / 2)
        press_pose = details[32]["base_pose"]
        self.assertAlmostEqual(press_pose[0], rotate_pose[0] - 0.05)
        press_retract_pose = details[33]["base_pose"]
        self.assertAlmostEqual(press_retract_pose[0], press_pose[0] + 0.05)
        self.assertEqual(len(details[34]["debug_joint_rad"]), 6)

        finished = self.client.post("%s/session/step/next" % KIND_URL)
        self.assertEqual(finished.status_code, 200)
        self.assertIsNone(finished.json()["step_name"])
        self.assertTrue(finished.json()["detail"]["finished"])

        session = self.client.get("%s/session" % KIND_URL).json()
        self.assertTrue(session["has_target"])

        previous = self.client.post("%s/session/step/previous" % KIND_URL)
        self.assertEqual(previous.status_code, 200)
        self.assertEqual(previous.json()["step_name"], "回调试位")
        self.assertEqual(previous.json()["step_index"], 35)

        # run executes one arbitrary step for single-step verification.
        ran = self.client.post("%s/session/step/run" % KIND_URL, json={"index": 27})
        self.assertEqual(ran.status_code, 200)
        self.assertEqual(ran.json()["step_name"], "运动到插入位")
        out_of_range = self.client.post("%s/session/step/run" % KIND_URL, json={"index": 35})
        self.assertEqual(out_of_range.status_code, 422)

        # reset rewinds the cursor but keeps the cached target.
        reset = self.client.post("%s/session/reset" % KIND_URL)
        self.assertEqual(reset.status_code, 200)
        session = self.client.get("%s/session" % KIND_URL).json()
        self.assertEqual(session["step_index"], 0)
        self.assertTrue(session["has_target"])

    def test_target_and_order_gated_steps_return_409(self):
        # Target-dependent steps require a prepared session first.
        unprepared = self.client.post("%s/session/step/run" % KIND_URL, json={"index": 2})
        self.assertEqual(unprepared.status_code, 409)
        self.assertIn("请先准备", unprepared.json()["detail"])

        unprepared_insert = self.client.post(
            "%s/session/step/run" % KIND_URL, json={"index": 26}
        )
        self.assertEqual(unprepared_insert.status_code, 409)
        self.assertIn("请先准备", unprepared_insert.json()["detail"])

        self.prepare(slot=1)
        # The insert chain needs the pre-pickup retarget step first.
        for index in (26, 27):
            no_retarget = self.client.post(
                "%s/session/step/run" % KIND_URL, json={"index": index}
            )
            self.assertEqual(no_retarget.status_code, 409)
            self.assertIn("识别目标书", no_retarget.json()["detail"])

        retarget = self.client.post("%s/session/step/run" % KIND_URL, json={"index": 19})
        self.assertEqual(retarget.status_code, 200)
        for index in (26, 27):
            ran = self.client.post("%s/session/step/run" % KIND_URL, json={"index": index})
            self.assertEqual(ran.status_code, 200)

    def test_step_previews_follow_dependencies_and_hot_apply(self):
        # Before prepare, target- and slot-dependent steps explain why they
        # cannot be previewed.
        view = self.client.get("%s/session/step/preview?all=1" % KIND_URL).json()
        self.assertEqual(len(view["steps"]), 35)
        self.assertIsNone(view["steps"][2]["motion"])
        self.assertIn("请先准备", view["steps"][2]["reason"])
        self.assertIsNone(view["steps"][20]["motion"])
        self.assertIn("请先准备", view["steps"][20]["reason"])
        self.assertIsNone(view["steps"][27]["motion"])
        self.assertIn("识别目标书", view["steps"][27]["reason"])

        self.prepare(slot=1)
        arm = self.tuning.mid_return.session._devices.arm
        current = arm.tcp_pose(arm.read_joint_pose()).offset_cm((12.0, -3.0, 8.0))
        arm.move_l(current, 1.0)
        view = self.client.get("%s/session/step/preview?all=1" % KIND_URL).json()
        # Target-relative grasp steps keep their existing references.
        self.assertEqual(view["steps"][2]["motion"]["type"], "tcp")
        self.assertAlmostEqual(view["steps"][2]["motion"]["x_mm"], -250.0)
        self.assertAlmostEqual(view["steps"][5]["motion"]["x_mm"], -340.0)
        self.assertAlmostEqual(view["steps"][7]["motion"]["x_mm"], -390.0)
        # Re-push and the following relative moves start from the actual pose.
        self.assertEqual(view["steps"][9]["step_name"], "推杆归位")
        self.assertAlmostEqual(view["steps"][10]["motion"]["x_mm"], 100.0)
        self.assertAlmostEqual(view["steps"][10]["motion"]["y_mm"], -30.0)
        self.assertAlmostEqual(view["steps"][10]["motion"]["z_mm"], 80.0)
        self.assertAlmostEqual(view["steps"][11]["motion"]["z_mm"], 30.0)
        self.assertAlmostEqual(view["steps"][11]["motion"]["x_mm"], 120.0)
        self.assertAlmostEqual(view["steps"][14]["motion"]["x_mm"], 170.0)
        self.assertAlmostEqual(view["steps"][14]["motion"]["y_mm"], -30.0)
        self.assertAlmostEqual(view["steps"][16]["motion"]["x_mm"], 220.0)
        self.assertAlmostEqual(view["steps"][16]["motion"]["z_mm"], 80.0)
        self.assertAlmostEqual(view["steps"][20]["motion"]["x_mm"], -300.0)
        self.assertTrue(view["steps"][20]["motion"]["continues"])
        self.assertEqual(view["steps"][23]["step_name"], "调整夹书深度")
        self.assertAlmostEqual(
            view["steps"][23]["motion"]["z_mm"], current.z_m * 1000.0 - 10.0
        )
        applied = self.client.put(
            "%s/profile?persist=false" % KIND_URL,
            json={"pickup_light_close_rpy_offset_deg": [3.0, -2.0, 4.0]},
        )
        self.assertEqual(applied.status_code, 200)
        view = self.client.get("%s/session/step/preview?all=1" % KIND_URL).json()
        self.assertAlmostEqual(
            view["steps"][23]["motion"]["rx_deg"], math.degrees(current.rx_rad) + 3.0
        )
        self.assertAlmostEqual(
            view["steps"][23]["motion"]["ry_deg"], math.degrees(current.ry_rad) - 2.0
        )
        self.assertAlmostEqual(
            view["steps"][23]["motion"]["rz_deg"], math.degrees(current.rz_rad) + 4.0
        )
        self.assertAlmostEqual(view["steps"][25]["motion"]["x_mm"], -300.0)
        # The insert chain waits for the pre-pickup retarget step.
        for index in (26, 27, 28, 30):
            self.assertIsNone(view["steps"][index]["motion"])
            self.assertIn("识别目标书", view["steps"][index]["reason"])

        ran = self.client.post("%s/session/step/run" % KIND_URL, json={"index": 19})
        self.assertEqual(ran.status_code, 200)
        view = self.client.get("%s/session/step/preview?all=1" % KIND_URL).json()
        # After the retarget the insert chain uses target XY offsets and absolute Z.
        self.assertAlmostEqual(view["steps"][26]["motion"]["x_mm"], -50.0)
        self.assertEqual(view["steps"][26]["motion"]["method"], "move_p_by_j")
        self.assertAlmostEqual(view["steps"][27]["motion"]["x_mm"], -350.0)
        self.assertAlmostEqual(view["steps"][27]["motion"]["y_mm"], -30.0)
        self.assertAlmostEqual(view["steps"][27]["motion"]["rx_deg"], 95.0)
        self.assertEqual(view["steps"][27]["motion"]["method"], "move_l")
        self.assertAlmostEqual(view["steps"][28]["motion"]["x_mm"], -400.0)
        self.assertAlmostEqual(view["steps"][30]["motion"]["x_mm"], -300.0)

        # A hot-applied profile update changes the very next preview.
        applied = self.client.put(
            "%s/profile?persist=false" % KIND_URL,
            json={"insert_xy_offset_m": [0.01, 0.04]},
        )
        self.assertEqual(applied.status_code, 200)
        updated = self.client.get(
            "%s/session/step/preview?step_index=27" % KIND_URL
        ).json()
        self.assertAlmostEqual(updated["motion"]["x_mm"], -340.0)
        # The executed step sends exactly the advertised pose.
        ran = self.client.post("%s/session/step/run" % KIND_URL, json={"index": 27})
        self.assertEqual(ran.status_code, 200)
        self.assertAlmostEqual(ran.json()["detail"]["base_pose"][0], -0.34)

        applied = self.client.put(
            "%s/profile?persist=false" % KIND_URL,
            json={"insert_xy_offset_m": [0.01, 0.08]},
        )
        self.assertEqual(applied.status_code, 200)
        updated = self.client.get(
            "%s/session/step/preview?step_index=27" % KIND_URL
        ).json()
        self.assertAlmostEqual(updated["motion"]["y_mm"], 10.0)

        # Push uses an independently configured absolute Z of 10 mm.
        applied = self.client.put(
            "%s/profile?persist=false" % KIND_URL,
            json={"push_z_m": 0.01},
        )
        self.assertEqual(applied.status_code, 200)
        updated = self.client.get(
            "%s/session/step/preview?step_index=28" % KIND_URL
        ).json()
        self.assertAlmostEqual(updated["motion"]["z_mm"], 10.0)

    def test_grasp_chain_hot_apply_changes_preview_and_execution(self):
        self.prepare(slot=1)
        before = self.client.get(
            "%s/session/step/preview?step_index=5" % KIND_URL
        ).json()
        self.assertEqual(before["step_name"], "精抓")
        self.assertAlmostEqual(before["motion"]["x_mm"], -340.0)

        applied = self.client.put(
            "%s/profile?persist=false" % KIND_URL,
            json={"fine_grasp_offset_cm": [2.0, 0.0, 0.0]},
        )
        self.assertEqual(applied.status_code, 200)

        after = self.client.get(
            "%s/session/step/preview?step_index=5" % KIND_URL
        ).json()
        self.assertAlmostEqual(after["motion"]["x_mm"], -330.0)
        ran = self.client.post("%s/session/step/run" % KIND_URL, json={"index": 5})
        self.assertEqual(ran.status_code, 200)
        self.assertAlmostEqual(ran.json()["detail"]["base_pose"][0], -0.33)

    def test_pickup_slot_hot_swap_updates_the_book_slot_step(self):
        self.prepare(slot=1)
        before = self.client.get(
            "%s/session/step/preview?step_index=20" % KIND_URL
        ).json()
        self.assertAlmostEqual(before["motion"]["x_mm"], -300.0)

        document = self.client.get("%s/book-stand/slots" % TUNING_URL).json()["preplace"]
        document["slots"]["1"]["pre_grasp"][0] = -0.25
        applied = self.client.put(
            "%s/book-stand/slots/preplace?persist=false" % TUNING_URL, json=document
        )
        self.assertEqual(applied.status_code, 200)

        after = self.client.get(
            "%s/session/step/preview?step_index=20" % KIND_URL
        ).json()
        self.assertAlmostEqual(after["motion"]["x_mm"], -250.0)
        # The executed step sends exactly the advertised slot pose.
        ran = self.client.post("%s/session/step/run" % KIND_URL, json={"index": 20})
        self.assertEqual(ran.status_code, 200)
        self.assertAlmostEqual(ran.json()["detail"]["pre_grasp_pose"][0], -0.25)

    def test_rod_home_steps_hot_swap_independently(self):
        self.prepare(slot=1)
        applied = self.client.put(
            "%s/profile?persist=false" % KIND_URL, json={"rod_putback_deg": 10.0}
        )
        self.assertEqual(applied.status_code, 200)

        ran = self.client.post("%s/session/step/run" % KIND_URL, json={"index": 9})
        self.assertEqual(ran.status_code, 200)
        self.assertEqual(ran.json()["step_name"], "推杆归位")
        self.assertEqual(ran.json()["detail"]["rod_deg"], 10.0)

        applied = self.client.put(
            "%s/profile?persist=false" % KIND_URL, json={"pickup_rod_home_deg": -30.0}
        )
        self.assertEqual(applied.status_code, 200)
        ran = self.client.post("%s/session/step/run" % KIND_URL, json={"index": 21})
        self.assertEqual(ran.status_code, 200)
        self.assertEqual(ran.json()["step_name"], "推杆归位")
        self.assertEqual(ran.json()["detail"]["rod_deg"], -30.0)

        current = self.client.get("%s/profile" % KIND_URL).json()
        self.assertEqual(current["rod_putback_deg"], 10.0)
        self.assertEqual(current["pickup_rod_home_deg"], -30.0)

    def test_re_push_uses_only_current_pose_and_x_offset(self):
        self.prepare(slot=1)
        applied = self.client.put(
            "%s/profile?persist=false" % KIND_URL,
            json={
                "fine_grasp_offset_cm": [20.0, 3.0, 4.0],
                "push_in_x_offset_cm": -30.0,
                "re_push_x_offset_cm": -3.5,
            },
        )
        self.assertEqual(applied.status_code, 200)
        arm = self.tuning.mid_return.session._devices.arm
        current = arm.tcp_pose(arm.read_joint_pose()).offset_cm(
            (12.0, -3.0, 8.0), rpy_offset_deg=(5.0, -4.0, 3.0)
        )
        arm.move_l(current, 1.0)
        expected = current.offset_cm((-3.5, 0.0, 0.0))

        preview = self.client.get(
            "%s/session/step/preview?step_index=10" % KIND_URL
        ).json()
        self.assertEqual(preview["step_name"], "再次推回(re_push_x)")
        self.assertAlmostEqual(preview["motion"]["x_mm"], expected.x_m * 1000.0)
        self.assertAlmostEqual(preview["motion"]["y_mm"], expected.y_m * 1000.0)
        self.assertAlmostEqual(preview["motion"]["z_mm"], expected.z_m * 1000.0)
        self.assertAlmostEqual(preview["motion"]["rx_deg"], math.degrees(expected.rx_rad))
        self.assertAlmostEqual(preview["motion"]["ry_deg"], math.degrees(expected.ry_rad))
        self.assertAlmostEqual(preview["motion"]["rz_deg"], math.degrees(expected.rz_rad))

        ran = self.client.post("%s/session/step/run" % KIND_URL, json={"index": 10})
        self.assertEqual(ran.status_code, 200)
        for actual, target in zip(ran.json()["detail"]["base_pose"], expected.values()):
            self.assertAlmostEqual(actual, target)

    def test_hot_swapped_plan_applies_to_the_next_step(self):
        response = self.client.put("%s/profile" % KIND_URL, json={"push_xy_offset_m": [-0.08, 0.04]})
        self.assertEqual(response.status_code, 200)

        self.prepare(slot=1)
        retarget = self.client.post("%s/session/step/run" % KIND_URL, json={"index": 19})
        self.assertEqual(retarget.status_code, 200)
        step = self.client.post("%s/session/step/run" % KIND_URL, json={"index": 28})
        self.assertEqual(step.status_code, 200)
        self.assertEqual(step.json()["step_name"], "推回书架(push_x)")
        self.assertAlmostEqual(step.json()["detail"]["base_pose"][0], -0.43)

    def test_legacy_rod_insert_field_does_not_add_a_step(self):
        self.prepare(slot=1)
        applied = self.client.put(
            "%s/profile?persist=false" % KIND_URL, json={"rod_insert_deg": -30.0}
        )
        self.assertEqual(applied.status_code, 200)

        session = self.client.get("%s/session" % KIND_URL).json()
        self.assertNotIn("推杆(rod_insert_deg)", session["steps"])

    def test_session_actions_conflict_with_a_busy_runner(self):
        template_id = self.library_id()
        # The run-step path now preempts: cancel any in-flight workflow (none
        # here) and wait on the lock — shrink that wait so the test stays fast.
        self.tuning.mid_return.session._run_preempt_timeout_s = 0.05
        self.runner.busy_lock.acquire()
        try:
            self.assertEqual(
                self.client.post(
                    "%s/session/prepare" % KIND_URL,
                    json={"slot": 1, "template_id": template_id},
                ).status_code,
                409,
            )
            self.assertEqual(
                self.client.post("%s/session/step/next" % KIND_URL).status_code, 409
            )
            self.assertEqual(self.client.post("%s/arm/enable" % KIND_URL).status_code, 409)
            self.assertEqual(
                self.client.post("%s/arm/debug-pose" % KIND_URL).status_code, 409
            )
        finally:
            self.runner.busy_lock.release()


class MidReturnLoaderTests(unittest.TestCase):
    def test_default_plan_round_trips_through_the_loader(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "midreturn_profile.json"
            path.write_text(
                json.dumps(plan_to_dict(MidReturnMotionPlan()), indent=2), encoding="utf-8"
            )

            loaded = load_mid_return_motion_plan(path)

        self.assertEqual(loaded, MidReturnMotionPlan())

    def test_loader_rejects_unknown_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            path.write_text(json.dumps({"bogus_field": 1}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "unknown fields"):
                load_mid_return_motion_plan(path)

            legacy = Path(directory) / "legacy.json"
            legacy.write_text(json.dumps({"shake_count": 2}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown fields"):
                load_mid_return_motion_plan(legacy)

    def test_loader_rejects_retired_gap_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            # The retired gap-scan fields are unknown keys now.
            for name, payload in (
                ("select.json", {"gap_select": "nearest"}),
                ("retired.json", {"gap_conf": 0.5}),
                ("scan.json", {"scan_height_ratio": 0.5}),
                ("bias.json", {"y_bias_cm": 1.0}),
            ):
                path = Path(directory) / name
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "unknown fields"):
                    load_mid_return_motion_plan(path)

    def test_loader_validates_insert_positions(self):
        with tempfile.TemporaryDirectory() as directory:
            bad = Path(directory) / "bad.json"
            bad.write_text(json.dumps({"insert_z_m": float("nan")}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "insert_z_m"):
                load_mid_return_motion_plan(bad)

            ok = Path(directory) / "ok.json"
            ok.write_text(
                json.dumps(
                    {
                        "target_y_offset_cm": -3.5,
                        "insert_xy_offset_m": [0.02, 0.07],
                        "insert_z_m": 0.28,
                    }
                ),
                encoding="utf-8",
            )
            loaded = load_mid_return_motion_plan(ok)
            self.assertEqual(loaded.insert_xy_offset_m, (0.02, 0.07))
            self.assertEqual(loaded.insert_z_m, 0.28)

    def test_loader_validates_align_step_cm(self):
        with tempfile.TemporaryDirectory() as directory:
            bad = Path(directory) / "bad.json"
            bad.write_text(json.dumps({"align_step_cm": 21.0}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "align_step_cm"):
                load_mid_return_motion_plan(bad)

            ok = Path(directory) / "ok.json"
            ok.write_text(json.dumps({"align_step_cm": 1.2}), encoding="utf-8")
            self.assertEqual(load_mid_return_motion_plan(ok).align_step_cm, 1.2)

    def test_loader_validates_pre_insert_staging_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            retired = Path(directory) / "retired.json"
            retired.write_text(
                json.dumps({"pre_insert_offset_cm": [5.0, 0.0, 0.0]}), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "unknown fields"):
                load_mid_return_motion_plan(retired)

            bad_rod = Path(directory) / "bad_rod.json"
            bad_rod.write_text(json.dumps({"rod_putback_deg": 160.0}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "rod_putback_deg"):
                load_mid_return_motion_plan(bad_rod)

            ok = Path(directory) / "ok.json"
            ok.write_text(
                json.dumps(
                    {
                        "pre_insert_x_m": -0.3,
                        "pre_insert_x_max_m": -0.26,
                        "pre_insert_y_offset_cm": 1.0,
                        "pre_insert_z_offset_cm": 5.0,
                        "pre_insert_xy_offset_m": [0.25, 0.07],
                        "pre_insert_z_m": 0.35,
                        "pre_insert_rpy_deg": [100.0, 7.0, 90.0],
                        "push_xy_offset_m": [-0.03, 0.03],
                        "push_z_m": 0.30,
                        "push_rpy_deg": [0.0, 0.0, 0.0],
                    }
                ),
                encoding="utf-8",
            )
            loaded = load_mid_return_motion_plan(ok)
            self.assertEqual(loaded.pre_insert_xy_offset_m, (0.25, 0.07))
            self.assertEqual(loaded.pre_insert_z_m, 0.35)
            self.assertEqual(loaded.pre_insert_rpy_deg, (100.0, 7.0, 90.0))
            self.assertEqual(loaded.push_xy_offset_m, (-0.03, 0.03))
            self.assertEqual(loaded.push_z_m, 0.30)
            self.assertEqual(loaded.push_rpy_deg, (0.0, 0.0, 0.0))
            self.assertFalse(hasattr(loaded, "pre_insert_x_max_m"))

    def test_loader_rejects_malformed_triple(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            path.write_text(json.dumps({"pregrasp_offset_cm": [1.0, 2.0]}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "pregrasp_offset_cm"):
                load_mid_return_motion_plan(path)

    def test_loader_rejects_out_of_range_rod_angles(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            path.write_text(json.dumps({"rod_grasp_deg": -120.0}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "between -100.0 and 150.0"):
                load_mid_return_motion_plan(path)

            # The device limits are inclusive.
            ok = Path(directory) / "ok.json"
            ok.write_text(json.dumps({"rod_grasp_deg": 150.0}), encoding="utf-8")
            self.assertEqual(load_mid_return_motion_plan(ok).rod_grasp_deg, 150.0)


if __name__ == "__main__":
    unittest.main()
