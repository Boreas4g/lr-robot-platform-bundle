"""识别后置校验：书脊倾斜判定 + 车辆外参定距居中对齐。

取书/还书/中位还书三种作业在每次视觉识别之后插入本步骤：
1. 倾斜判定——书脊四边形长边与画面竖直方向的夹角超过阈值（默认 60°）
   判定为不可执行，直接报错中止任务（机械臂尚未动作）；
2. 居中对齐——取书作业在当前 D435 深度和相机外参下，逐点计算候选抓取位置，
   用完整抓取姿态链的 IK 和关节限位余量生成舒适可达带；带外向中点移动，
   停车复扫确认进入留有边缘余量的带内即完成；异常换向或不收敛时中止。

倾斜角算法：四边形 4 角点按环绕序排列后取两条最长边，方向与竖直方向
夹角（atan2(|dx|, |dy|)）取平均，单位度（0°=竖直）。
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import replace
from typing import Any, Dict, Optional, Sequence, Tuple

from bookarm.domain.models.book import BookTarget, SpineTemplate
from bookarm.domain.models.pose import BasePose

log = logging.getLogger(__name__)

PolygonUv = Sequence[Sequence[float]]

# Bound IK sampling to a narrower screen-centre window even when the solver
# reports a much larger workspace. Each accepted sample also needs this much
# clearance from every arm-joint limit; the result is a comfortable operating
# range, not the arm's absolute mechanical envelope.
IK_CENTER_MAX_BAND_RATIO = 0.20
IK_CENTER_SAMPLE_COUNT = 21
IK_JOINT_COMFORT_MARGIN_RAD = 0.20
MAX_SINGLE_ALIGN_MOVE_M = 0.20
ALIGN_CENTER_TOLERANCE_RATIO = 0.005


def compute_spine_tilt_deg(polygon_uv: Optional[PolygonUv]) -> Optional[float]:
    """书脊倾斜角（与竖直方向夹角，0=竖直，90=水平）；无有效四边形返回 None。"""

    if polygon_uv is None:
        return None
    pts = [tuple(float(c) for c in point[:2]) for point in polygon_uv]
    if len(pts) != 4:
        return None
    cx = sum(p[0] for p in pts) / 4.0
    cy = sum(p[1] for p in pts) / 4.0
    # 按相对质心的极角排序得到环绕序（凸四边形）
    ordered = sorted(pts, key=lambda p: math.atan2(p[1] - cy, p[0] - cx))
    edges = [
        (ordered[(i + 1) % 4][0] - ordered[i][0], ordered[(i + 1) % 4][1] - ordered[i][1])
        for i in range(4)
    ]
    lengths = [math.hypot(*e) for e in edges]
    if min(lengths) <= 0:
        return None
    longest = sorted(range(4), key=lambda i: lengths[i])[-2:]
    tilts = []
    for i in longest:
        dx, dy = edges[i]
        tilts.append(math.degrees(math.atan2(abs(dx), abs(dy))))
    return sum(tilts) / len(tilts)


def center_x_ratio(target: BookTarget) -> Optional[float]:
    """目标书脊中心的水平归一化位置（0..1）；缺数据返回 None。"""

    if target.polygon_uv is None or not target.frame_width_px:
        return None
    cx = sum(float(p[0]) for p in target.polygon_uv) / len(target.polygon_uv)
    return cx / float(target.frame_width_px)


def check_spine_tilt(target: BookTarget, plan: Any) -> Optional[float]:
    """倾斜判定：超过 plan.spine_tilt_max_deg 抛 RuntimeError（不可执行）。

    返回倾斜角（°）或 None（无倾斜信息——兜底轴对齐识别）。"""

    max_deg = float(plan.spine_tilt_max_deg)
    tilt = compute_spine_tilt_deg(target.polygon_uv)
    if tilt is None:
        log.warning("书脊倾斜角不可用（识别兜底分支无倾斜信息）")
        if bool(plan.spine_tilt_fail_on_unknown):
            raise RuntimeError(
                "书脊倾斜角无法计算（识别结果无几何信息），按策略判定为不可执行；"
                "请检查目标书图像与书脊库模板"
            )
        return None
    if tilt > max_deg + 1e-6:  # 恰好等于阈值属可执行（浮点噪声容差）
        raise RuntimeError(
            "书脊倾斜 %.1f°，超过 %.1f° 上限，无法执行：书与书架倾斜过大，"
            "请人工检查书籍是否倒伏" % (tilt, max_deg)
        )
    return tilt


def take_book_grasp_poses(target: BookTarget, plan: Any) -> Dict[str, BasePose]:
    """Return the same four poses used by the take-book reachability check."""

    grasp_pose = target.grasp_pose
    fine_grasp = grasp_pose.offset_cm(
        plan.fine_grasp_offset_cm, rpy_deg=plan.fine_grasp_rpy_deg
    )
    return {
        "arm_pregrasp": grasp_pose.offset_cm(
            plan.pregrasp_offset_cm, rpy_deg=plan.grasp_rpy_deg
        ),
        "arm_approach": grasp_pose.offset_cm(
            plan.approach_offset_cm, rpy_deg=plan.grasp_rpy_deg
        ),
        "arm_fine_grasp": fine_grasp,
        "arm_post_grasp": fine_grasp.offset_cm(
            plan.post_grasp_offset_cm,
            rpy_offset_deg=plan.post_grasp_rpy_offset_deg,
        ),
    }


def _target_at_horizontal_ratio(target: BookTarget, ratio: float) -> Optional[BookTarget]:
    """Project the located grasp point horizontally on its measured depth plane."""

    if (
        target.pixel_uv is None
        or not target.frame_width_px
        or target.horizontal_pixel_to_base_m is None
    ):
        return None
    dx_px = float(ratio) * float(target.frame_width_px) - float(target.pixel_uv[0])
    delta = tuple(float(value) * dx_px for value in target.horizontal_pixel_to_base_m)

    def shifted(pose: BasePose) -> BasePose:
        return BasePose(
            pose.x_m + delta[0], pose.y_m + delta[1], pose.z_m + delta[2],
            pose.rx_rad, pose.ry_rad, pose.rz_rad,
        )

    return replace(target, raw_pose=shifted(target.raw_pose), grasp_pose=shifted(target.grasp_pose))


def _joint_clearance_error(arm: Any, joints: Any) -> Optional[str]:
    limits = getattr(getattr(arm, "config", None), "joint_limits", None)
    # Hardware-free test doubles may only model the IK port. The production
    # ArmService always has limits, so only it can claim the comfort margin.
    if not limits:
        return None
    values = getattr(joints, "values_rad", ())
    if len(values) < 6:
        return "IK 返回的关节角数量不足"
    clearances = []
    for joint_id, value in enumerate(values[:6], start=1):
        if joint_id not in limits:
            return "缺少第 %d 关节限位配置" % joint_id
        lower, upper = (float(limit) for limit in limits[joint_id])
        if not all(math.isfinite(v) for v in (float(value), lower, upper)):
            return "第 %d 关节角或限位不是有限数值" % joint_id
        clearances.append((min(float(value) - lower, upper - float(value)), joint_id))
    clearance, joint_id = min(clearances)
    if clearance < IK_JOINT_COMFORT_MARGIN_RAD:
        return "第 %d 关节距限位余量 %.3f rad，不足 %.2f rad" % (
            joint_id, clearance, IK_JOINT_COMFORT_MARGIN_RAD
        )
    return None


def _take_book_chain_is_comfortable(
    arm: Any, target: BookTarget, plan: Any
) -> Tuple[bool, Optional[str]]:
    check = getattr(arm, "check_pose_reachable_offworker", None)
    if not callable(check):
        check = arm.check_pose_reachable
    seed = plan.debug_joint
    try:
        for label, pose in take_book_grasp_poses(target, plan).items():
            seed = check(pose, seed, label=label)
            clearance_error = _joint_clearance_error(arm, seed)
            if clearance_error is not None:
                return False, "姿态 %s：%s" % (label, clearance_error)
    except (RuntimeError, ValueError) as error:
        return False, str(error)
    return True, None


def calculate_comfortable_center_band(
    target: BookTarget, plan: Any, arm: Any
) -> Tuple[Optional[Tuple[float, float]], Dict[str, Any]]:
    """Sample the configured centre window against the complete grasp IK chain.

    The returned interval is the contiguous comfortable run nearest the image
    centre, inset by one sample at any IK-failing boundary. ``None`` means the
    target lacks calibrated projection data or no stable run was found.
    """

    configured_band = float(getattr(plan, "align_center_band_ratio", 0.40))
    if not 0.05 <= configured_band <= 0.9:
        raise RuntimeError("align_center_band_ratio %.3f 非法（应 0.05~0.9）" % configured_band)
    band_ratio = min(configured_band, IK_CENTER_MAX_BAND_RATIO)
    lo = 0.5 - band_ratio / 2.0
    hi = 0.5 + band_ratio / 2.0
    count = max(3, int(IK_CENTER_SAMPLE_COUNT))
    samples = [lo + (hi - lo) * index / (count - 1) for index in range(count)]
    reachable = []
    first_ik_error: Optional[str] = None
    for ratio in samples:
        candidate = _target_at_horizontal_ratio(target, ratio)
        if candidate is None:
            return None, {
                "checked": False,
                "detail": "相机定位结果缺少水平像素到基座坐标映射，无法计算 IK 可达区",
                "sample_count": 0,
            }
        is_reachable, ik_error = _take_book_chain_is_comfortable(arm, candidate, plan)
        reachable.append(is_reachable)
        if first_ik_error is None and ik_error is not None:
            first_ik_error = ik_error

    runs = []
    start = None
    for index, is_reachable in enumerate(reachable + [False]):
        if is_reachable and start is None:
            start = index
        elif not is_reachable and start is not None:
            runs.append((start, index - 1))
            start = None
    if not runs:
        return None, {
            "checked": True,
            "detail": (
                "中心候选区内没有满足整条取书 IK 姿态链和关节余量的连续区域"
                if sum(reachable) > 0 or first_ik_error is None
                else "IK 候选未通过可达性或关节余量检查：%s" % first_ik_error
            ),
            "sample_count": count,
            "reachable_sample_count": sum(reachable),
        }

    center_index = count // 2
    selected = next(
        (run for run in runs if run[0] <= center_index <= run[1]),
        min(
            runs,
            key=lambda run: min(abs(samples[run[0]] - 0.5), abs(samples[run[1]] - 0.5)),
        ),
    )
    start, end = selected
    # Move one tested step inward when an IK-failing sample bounds the run.
    safe_start = start + 1 if start > 0 else start
    safe_end = end - 1 if end < count - 1 else end
    if safe_end <= safe_start:
        return None, {
            "checked": True,
            "detail": "IK 连续可达区域过窄，无法形成稳定居中带",
            "sample_count": count,
            "reachable_sample_count": sum(reachable),
        }
    result = (round(samples[safe_start], 4), round(samples[safe_end], 4))
    return result, {
        "checked": True,
        "detail": "按整条取书 IK 姿态链及关节余量计算",
        "sample_count": count,
        "reachable_sample_count": sum(reachable),
        "joint_comfort_margin_rad": IK_JOINT_COMFORT_MARGIN_RAD,
    }


def _center_tolerance_ratio(band: Tuple[float, float]) -> float:
    """Inset the acceptance band to retain clearance from its IK boundaries."""

    return min(ALIGN_CENTER_TOLERANCE_RATIO, max(0.0, (band[1] - band[0]) / 4.0))


def align_vehicle_to_center(
    vision: Any,
    template: SpineTemplate,
    target: BookTarget,
    vehicle: Any,
    plan: Any,
    *,
    arm: Any = None,
    engine: Any = None,
    task: Any = None,
) -> Tuple[BookTarget, Dict[str, Any]]:
    """里程计定距闭环：瞄准舒适带中点，停车复扫进入安全带内即完成。

    每次动车后重新拍照识别；返回（最终识别结果, 对齐详情）。
    """

    band = float(plan.align_center_band_ratio)
    if not 0.05 <= band <= 0.9:
        raise RuntimeError("align_center_band_ratio %.3f 非法（应 0.05~0.9）" % band)
    lo, hi = 0.5 - band / 2.0, 0.5 + band / 2.0
    max_moves = int(plan.align_max_moves)
    max_travel_m = float(plan.align_max_travel_m)
    settle_s = float(plan.align_settle_ms) / 1000.0
    sign = 1 if int(plan.align_direction_sign) >= 0 else -1
    # Validate the retained profile field so malformed old profiles still fail
    # clearly. It no longer limits each correction: that setting caused a
    # series of tiny moves. The chassis endpoint enforces the same 20 cm hard
    # limit, so one correction now uses the full extrinsic estimate up to it.
    legacy_step_cm = float(getattr(plan, "align_step_cm", 20.0))
    if not math.isfinite(legacy_step_cm) or not 0.1 <= legacy_step_cm <= 20.0:
        raise RuntimeError("align_step_cm %.2f 非法（兼容范围 0.1~20.0 cm）" % legacy_step_cm)
    move_distance = getattr(vehicle, "move_distance", None)

    moves = 0
    travel_m = 0.0
    move_details = []
    previous_direction: Optional[str] = None
    previous_band_error: Optional[float] = None
    while True:
        band_details: Dict[str, Any] = {}
        if arm is not None:
            if (
                target.horizontal_pixel_to_base_m is None
                and callable(getattr(arm, "check_pose_reachable_offworker", None))
            ):
                raise RuntimeError(
                    "车辆居中失败：D435 定位结果缺少横向基座映射，不能计算机械臂舒适可达区"
                )
            if target.horizontal_pixel_to_base_m is not None:
                reachable_band, band_details = calculate_comfortable_center_band(target, plan, arm)
                if reachable_band is None:
                    log.warning(
                        "Vehicle alignment has no comfortable band: capture=%s target=%s "
                        "fine_grasp_rpy_deg=%s post_grasp_offset_cm=%s "
                        "post_grasp_rpy_offset_deg=%s details=%s",
                        target.capture_id, target.grasp_pose.values(),
                        getattr(plan, "fine_grasp_rpy_deg", None),
                        getattr(plan, "post_grasp_offset_cm", None),
                        getattr(plan, "post_grasp_rpy_offset_deg", None), band_details,
                    )
                    raise RuntimeError(
                        "车辆居中失败：无法计算机械臂舒适可达区；%s"
                        % band_details.get("detail", "IK 范围不可用")
                    )
                lo, hi = reachable_band
        ratio = center_x_ratio(target)
        if ratio is None:
            if moves:
                raise RuntimeError("车辆对齐失败：动车后复扫缺少目标几何信息，禁止继续动车或抓取")
            log.warning("目标书居中位置不可用（缺多边形/帧宽），跳过车辆对齐")
            return target, {"aligned": False, "align_skipped": "no_geometry"}
        band_center = (lo + hi) / 2.0
        tolerance_ratio = _center_tolerance_ratio((lo, hi))
        center_error_ratio = ratio - band_center
        # The band is the safe operating range produced by the configured
        # profile/IK check.  Requiring a 0.5%-of-frame midpoint made the
        # controller chase normal vision noise: after a correction the target
        # could be a few pixels on the other side of 0.5 and the vehicle would
        # immediately reverse.  Keep a small margin at each band edge, then
        # accept every capture inside that stable interval.
        stable_lo = lo + tolerance_ratio
        stable_hi = hi - tolerance_ratio
        if stable_lo <= ratio <= stable_hi:
            return target, {
                "aligned": moves > 0,
                "align_moves": moves,
                "align_travel_m": round(travel_m, 4),
                "align_center_x_final": round(ratio, 4),
                "align_center_target_x_ratio": round(band_center, 4),
                "align_center_error_ratio": round(center_error_ratio, 4),
                "align_center_tolerance_ratio": round(tolerance_ratio, 4),
                "align_center_band": [round(lo, 4), round(hi, 4)],
                "align_acceptance_band": [round(stable_lo, 4), round(stable_hi, 4)],
                "align_completion_reason": "inside_comfort_band",
                "align_band_ik": bool(band_details.get("checked", False)),
                "align_reachable_samples": band_details.get("reachable_sample_count"),
                "align_move_details": move_details,
            }
        if moves >= max_moves:
            raise RuntimeError(
                "车辆对齐失败：%d 次定距移动后目标书仍未进入舒适区（当前 %.1f%%，舒适区 %.1f%%~%.1f%%）"
                % (moves, ratio * 100.0, stable_lo * 100.0, stable_hi * 100.0)
            )
        # 书在画面右侧（ratio>0.5）时相机需相对书架右移：方向由安装符号决定
        want_forward = (ratio > band_center) if sign > 0 else (ratio < band_center)
        direction = "forward" if want_forward else "backward"
        # A move has already stopped before the new capture is evaluated. Do
        # not drive back across the workspace when it overshot the whole safe
        # band or the estimated band jumped. Successful in-band captures have
        # returned above; this is an error, never permission to grasp.
        band_error = max(stable_lo - ratio, ratio - stable_hi, 0.0)
        if previous_direction is not None and direction != previous_direction:
            message = (
                "车辆对齐失败：复扫目标跨过舒适区，已停止反向追赶；"
                "当前 %.1f%%，舒适区 %.1f%%~%.1f%%，已移动 %.3f m；"
                "请检查视觉定位、相机外参和车辆移动方向"
                % (ratio * 100.0, stable_lo * 100.0, stable_hi * 100.0, travel_m)
            )
            log.warning(message)
            raise RuntimeError(message)
        if previous_band_error is not None and band_error >= previous_band_error - tolerance_ratio:
            message = (
                "车辆对齐失败：动车后目标偏差未明显减小，已停止继续纠偏；"
                "距舒适区偏差 %.1f%% → %.1f%%，已移动 %.3f m；"
                "请检查识别结果、相机外参和车辆移动方向"
                % (previous_band_error * 100.0, band_error * 100.0, travel_m)
            )
            log.warning(message)
            raise RuntimeError(message)
        # 识别结果中的每像素三维基座位移由 D435 深度、内参和当前 camera-to-base
        # 外参生成。取该向量长度得到沿已现场确认方向的距离，再受车端硬上限保护；
        # 底盘端以 /odom 反馈到达目标距离后停车。
        frame_width = int(target.frame_width_px or 0)
        if frame_width <= 0:
            raise RuntimeError("车辆对齐失败：缺少图像宽度，无法估算到舒适区中心的距离")
        offset_px = abs(ratio - band_center) * frame_width
        pixel_to_base = target.horizontal_pixel_to_base_m
        if pixel_to_base is None or len(pixel_to_base) < 3:
            raise RuntimeError(
                "车辆对齐失败：当前识别结果没有相机外参生成的像素到基座映射"
            )
        per_pixel_m = math.sqrt(sum(float(value) ** 2 for value in pixel_to_base[:3]))
        estimated_distance_m = offset_px * per_pixel_m
        if not math.isfinite(estimated_distance_m) or estimated_distance_m < 0.0025:
            raise RuntimeError(
                "车辆对齐失败：相机外参计算出的目标位移小于底盘定距分辨率"
            )
        requested_step_m = min(estimated_distance_m, MAX_SINGLE_ALIGN_MOVE_M)
        if travel_m + requested_step_m > max_travel_m:
            raise RuntimeError(
                "车辆对齐失败：累计行程将达 %.2f m 上限（已 %.3f m），请检查车位"
                % (max_travel_m, travel_m)
            )
        if not callable(move_distance):
            raise RuntimeError("车辆对齐失败：底盘客户端未提供里程计定距移动接口")
        if engine is not None and task is not None:
            engine.raise_if_cancelled(task)
        log.info(
            "车辆对齐第 %d 次：capture=%s 当前=%.4f 安全带=[%.4f, %.4f] "
            "目标=%.4f direction=%s request=%.4f m",
            moves + 1, target.capture_id, ratio, stable_lo, stable_hi,
            band_center, direction, requested_step_m,
        )
        move_result = move_distance(direction, requested_step_m)
        if not move_result.get("ok", False):
            raise RuntimeError(
                "车辆定距移动失败：%s" % move_result.get("error", "底盘未确认移动完成")
            )
        actual_step_m = abs(float(move_result.get("travelled_distance_m", requested_step_m)))
        travel_m += actual_step_m
        if travel_m > max_travel_m + 1e-9:
            raise RuntimeError(
                "车辆对齐失败：里程计确认累计行程 %.3f m，超过 %.2f m 安全上限"
                % (travel_m, max_travel_m)
            )
        move_details.append({
            "direction": direction,
            "center_x_before": round(ratio, 4),
            "acceptance_band": [round(stable_lo, 4), round(stable_hi, 4)],
            "offset_px": round(offset_px, 1),
            "estimated_distance_m": round(estimated_distance_m, 4),
            "requested_distance_m": round(requested_step_m, 4),
            "travelled_distance_m": round(actual_step_m, 4),
            "odom_error_m": round(
                float(move_result.get("error_m", requested_step_m - actual_step_m)), 4
            ),
            "duration_s": move_result.get("duration_s"),
        })
        previous_direction = direction
        previous_band_error = band_error
        moves += 1
        time.sleep(settle_s)
        if engine is not None and task is not None:
            engine.raise_if_cancelled(task)
        # 动车后重新识别：位姿与画面都变了
        target = vision.locate_book(template)
        tilt = compute_spine_tilt_deg(target.polygon_uv)
        if tilt is not None and tilt > float(plan.spine_tilt_max_deg) + 1e-6:
            raise RuntimeError(
                "对齐后重新识别发现书脊倾斜 %.1f°，超过 %.1f° 上限，无法执行："
                "请人工检查书籍是否倒伏" % (tilt, float(plan.spine_tilt_max_deg))
            )


def post_vision_check_align(
    vision: Any,
    template: SpineTemplate,
    context: Dict[str, Any],
    context_key: str,
    vehicle: Any,
    plan: Any,
    *,
    arm: Any = None,
    engine: Any = None,
    task: Any = None,
) -> Dict[str, Any]:
    """阶段动作入口：对 context[context_key] 中的识别结果做倾斜判定与居中对齐。

    对齐动过车时，context[context_key] 会被替换为对齐后的最新识别结果，
    下游阶段（可达性预检/夹取/插入）始终使用新位姿。
    """

    target = context.get(context_key)
    if not isinstance(target, BookTarget):
        raise RuntimeError("post-vision check requires a BookTarget in context[%r]" % context_key)
    tilt = check_spine_tilt(target, plan)
    details: Dict[str, Any] = {
        "spine_tilt_deg": None if tilt is None else round(tilt, 2),
        "spine_tilt_max_deg": float(plan.spine_tilt_max_deg),
    }
    if vehicle is None:
        # 未接车端对齐服务时仅做倾斜判定（测试/降级环境），不尝试动车
        log.warning("车辆对齐客户端未配置，仅执行书脊倾斜判定")
        details["aligned"] = False
        details["align_skipped"] = "no_vehicle_client"
        return details
    final_target, align_details = align_vehicle_to_center(
        vision, template, target, vehicle, plan, arm=arm, engine=engine, task=task
    )
    context[context_key] = final_target
    details.update(align_details)
    details["final_capture_id"] = final_target.capture_id
    return details
