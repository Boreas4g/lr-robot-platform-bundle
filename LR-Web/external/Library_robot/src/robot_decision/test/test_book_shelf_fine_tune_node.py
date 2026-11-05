import math
from types import SimpleNamespace

import pytest

from robot_decision.book_shelf_fine_tune_node import (
    BookShelfFineTuneNode,
    _clamp,
    _normalize_angle,
    _quaternion_to_yaw,
)


def _set_heading_defaults(node) -> None:
    node.shelf_heading_kp = 3.0
    node.shelf_heading_kd = 0.4
    node.shelf_heading_deadband_rad = math.radians(3.0)
    node.shelf_heading_max_error_rad = math.radians(10.0)
    node.shelf_heading_max_error_rate_rad_s = 1.0
    node.shelf_heading_min_turning_radius_m = 1.0


def _x_control_node(x_error: float, yaw_error: float, speed: float = 0.05):
    node = BookShelfFineTuneNode.__new__(BookShelfFineTuneNode)
    node._abort_requested = SimpleNamespace(is_set=lambda: False)
    node._target_errors = lambda *_args: (x_error, 0.0, yaw_error)
    node.x_tolerance = 0.05
    node.k_x = 1.0
    node.max_linear_speed = 0.05
    node.max_angular_speed = 0.12
    node._shelf_move_speed_override = speed
    node._shelf_heading_guidance_enabled = True
    _set_heading_defaults(node)
    return node


def _run_x_once(node, monkeypatch):
    messages = []
    node._velocity_publisher = SimpleNamespace(publish=lambda message: messages.append(message))
    monkeypatch.setattr(
        "robot_decision.book_shelf_fine_tune_node.time.monotonic",
        lambda: 0.0 if not messages else 1.0,
    )
    monkeypatch.setattr("robot_decision.book_shelf_fine_tune_node.time.sleep", lambda _period: None)
    success, _message = node._tune_x(0.0, 0.0, 0.0, deadline=1.0, period=0.1)
    assert success is False
    assert len(messages) == 1
    return messages[0]


def test_clamp_limits_magnitude_and_preserves_sign() -> None:
    assert _clamp(0.1, 0.2) == pytest.approx(0.1)
    assert _clamp(-0.1, 0.2) == pytest.approx(-0.1)
    assert _clamp(0.5, 0.2) == pytest.approx(0.2)
    assert _clamp(-0.5, 0.2) == pytest.approx(-0.2)


def test_quaternion_to_yaw_uses_the_standard_z_axis_formula() -> None:
    yaw = _quaternion_to_yaw(0.0, 0.0, math.sin(math.pi / 4), math.cos(math.pi / 4))

    assert yaw == pytest.approx(math.pi / 2)


def test_normalize_angle_wraps_to_signed_pi() -> None:
    assert _normalize_angle(3 * math.pi) == pytest.approx(math.pi)


def test_target_errors_follow_the_base_frame_while_the_base_rotates() -> None:
    node = BookShelfFineTuneNode.__new__(BookShelfFineTuneNode)
    node._current_pose = lambda: (0.0, 0.1, math.pi / 2)

    x_error, y_error, yaw_error = node._target_errors(0.0, 0.0, 0.0)

    # Facing +y with the target 0.1 m behind: the offset sits entirely in the
    # base-frame x component, the same convention the patrol fine tune uses.
    assert x_error == pytest.approx(-0.1)
    assert y_error == pytest.approx(0.0)
    assert yaw_error == pytest.approx(-math.pi / 2)


def test_ackermann_yaw_command_uses_a_one_metre_arc() -> None:
    node = BookShelfFineTuneNode.__new__(BookShelfFineTuneNode)
    node._control_mode = "ackermann"
    node.k_yaw = 1.0
    node.max_angular_speed = 0.2
    node.max_linear_speed = 0.05

    command = node._yaw_command(0.5)

    assert command.linear.x == pytest.approx(0.05)
    assert command.angular.z == pytest.approx(0.05)


def test_differential_yaw_command_keeps_zero_linear_speed() -> None:
    node = BookShelfFineTuneNode.__new__(BookShelfFineTuneNode)
    node._control_mode = "differential"
    node.k_yaw = 1.0
    node.max_angular_speed = 0.2
    node.max_linear_speed = 0.05

    command = node._yaw_command(0.1)

    assert command.linear.x == 0.0
    assert command.angular.z == pytest.approx(0.1)


def test_x_only_shelf_move_never_runs_lateral_or_yaw_stages() -> None:
    node = BookShelfFineTuneNode.__new__(BookShelfFineTuneNode)
    parameters = {
        "control_mode": "differential",
        "x_only": True,
        "shelf_move_speed_mps": 0.08,
        "shelf_move_x_tolerance_m": float("nan"),
    }
    node.get_parameter = lambda name: SimpleNamespace(value=parameters[name])
    node.get_logger = lambda: SimpleNamespace(info=lambda _message: None)
    node.timeout_sec = 10.0
    node.stage_timeout_sec = 10.0
    node.control_rate_hz = 8.0
    node.x_tolerance = 0.05
    calls = []
    node._tune_x = lambda *_args: calls.append("x") or (True, "x aligned")
    node._tune_y = lambda *_args: pytest.fail("shelf_move must not run the y stage")
    node._tune_yaw = lambda *_args: pytest.fail("shelf_move must not run the yaw stage")
    node._target_errors = lambda *_args: (0.01, 0.5, 1.0)
    node._publish_stop = lambda: None

    success, message = node._run_fine_tune(0.0, 0.0, 0.0, "CMD-SHELF")

    assert success is True
    assert message.startswith("shelf move complete")
    assert calls == ["x"]


def test_x_only_shelf_move_uses_command_x_tolerance_for_final_check() -> None:
    node = BookShelfFineTuneNode.__new__(BookShelfFineTuneNode)
    parameters = {
        "control_mode": "differential",
        "x_only": True,
        "shelf_move_speed_mps": float("nan"),
        "shelf_move_x_tolerance_m": 0.02,
    }
    node.get_parameter = lambda name: SimpleNamespace(value=parameters[name])
    node.get_logger = lambda: SimpleNamespace(info=lambda _message: None)
    node.timeout_sec = 10.0
    node.stage_timeout_sec = 10.0
    node.control_rate_hz = 8.0
    node.x_tolerance = 0.05
    node._tune_x = lambda *_args: (True, "x aligned")
    node._target_errors = lambda *_args: (0.03, 0.0, 0.0)
    node._publish_stop = lambda: None

    success, message = node._run_fine_tune(0.0, 0.0, 0.0, "CMD-SHELF")

    assert success is False
    assert "final tolerance check failed" in message


def test_normal_fine_tune_still_runs_all_stages() -> None:
    node = BookShelfFineTuneNode.__new__(BookShelfFineTuneNode)
    parameters = {"control_mode": "differential", "x_only": False}
    node.get_parameter = lambda name: SimpleNamespace(value=parameters[name])
    node.get_logger = lambda: SimpleNamespace(info=lambda _message: None)
    node.timeout_sec = 10.0
    node.stage_timeout_sec = 10.0
    node.control_rate_hz = 8.0
    node.x_tolerance = 0.05
    node.y_tolerance = 0.05
    node.yaw_tolerance = 0.05
    calls = []
    for stage in ("x", "y", "yaw"):
        setattr(
            node,
            f"_tune_{stage}",
            lambda *_args, stage=stage: calls.append(stage) or (True, "aligned"),
        )
    node._target_errors = lambda *_args: (0.01, 0.01, 0.01)
    node._publish_stop = lambda: None

    success, _message = node._run_fine_tune(0.0, 0.0, 0.0, "CMD-FINE")

    assert success is True
    assert calls == ["x", "y", "yaw"]


@pytest.mark.parametrize("speed", [0.0, 0.08, 0.5])
def test_shelf_move_uses_manual_speed_without_changing_fine_tune_limit(
    monkeypatch, speed
) -> None:
    node = BookShelfFineTuneNode.__new__(BookShelfFineTuneNode)
    node._abort_requested = SimpleNamespace(is_set=lambda: False)
    node._target_errors = lambda *_args: (1.0, 0.0, 0.0)
    node.x_tolerance = 0.05
    node.k_x = 1.0
    node.max_linear_speed = 0.05
    node._shelf_move_speed_override = speed
    node._shelf_heading_guidance_enabled = True
    _set_heading_defaults(node)
    messages = []
    node._velocity_publisher = SimpleNamespace(publish=lambda message: messages.append(message))
    monkeypatch.setattr(
        "robot_decision.book_shelf_fine_tune_node.time.monotonic",
        lambda: 0.0 if not messages else 1.0,
    )
    monkeypatch.setattr("robot_decision.book_shelf_fine_tune_node.time.sleep", lambda _period: None)

    success, _message = node._tune_x(0.0, 0.0, 0.0, deadline=1.0, period=0.1)

    assert success is False
    assert len(messages) == 1
    assert messages[0].linear.x == pytest.approx(speed)
    assert messages[0].linear.y == 0.0
    assert messages[0].angular.z == 0.0
    assert node.max_linear_speed == 0.05


def test_shelf_heading_guidance_stops_inside_three_degree_deadband(monkeypatch) -> None:
    command = _run_x_once(
        _x_control_node(1.0, math.radians(2.0), speed=0.5), monkeypatch
    )

    assert command.angular.z == 0.0


def test_shelf_heading_guidance_uses_proportional_control(monkeypatch) -> None:
    node = _x_control_node(1.0, math.radians(6.0), speed=0.5)
    node.shelf_heading_kp = 0.5

    command = _run_x_once(node, monkeypatch)

    assert command.angular.z == pytest.approx(0.5 * math.radians(6.0))


def test_shelf_heading_guidance_enforces_one_metre_radius_forward_and_reverse(
    monkeypatch,
) -> None:
    for speed in (0.05, -0.05):
        command = _run_x_once(
            _x_control_node(
                math.copysign(1.0, speed), math.radians(8.0), speed=abs(speed)
            ),
            monkeypatch,
        )

        assert command.linear.x == pytest.approx(speed)
        assert command.angular.z == pytest.approx(0.05)
        assert abs(command.linear.x / command.angular.z) >= 1.0


def test_shelf_heading_guidance_does_not_turn_without_linear_motion(monkeypatch) -> None:
    command = _run_x_once(
        _x_control_node(1.0, math.radians(10.0), speed=0.0), monkeypatch
    )

    assert command.linear.x == 0.0
    assert command.angular.z == 0.0


def test_shelf_heading_guidance_clamps_error_to_ten_degrees(monkeypatch) -> None:
    node = _x_control_node(1.0, math.radians(90.0), speed=0.5)
    node.shelf_heading_kp = 0.1

    command = _run_x_once(node, monkeypatch)

    assert command.angular.z == pytest.approx(0.1 * math.radians(10.0))


def test_shelf_move_arrival_does_not_require_heading_alignment() -> None:
    node = _x_control_node(0.01, math.radians(30.0))
    node._velocity_publisher = SimpleNamespace(
        publish=lambda _message: pytest.fail("arrival must not publish another command")
    )

    success, message = node._tune_x(0.0, 0.0, 0.0, deadline=float("inf"), period=0.1)

    assert success is True
    assert message == "x aligned"


def test_normal_fine_tune_x_stage_does_not_use_shelf_heading_guidance(monkeypatch) -> None:
    node = _x_control_node(1.0, math.radians(5.0), speed=0.5)
    del node._shelf_heading_guidance_enabled

    command = _run_x_once(node, monkeypatch)

    assert command.angular.z == 0.0
