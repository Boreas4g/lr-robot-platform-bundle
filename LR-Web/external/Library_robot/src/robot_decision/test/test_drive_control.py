import pytest

from robot_decision.drive_control import (
    ACKERMANN,
    DIFFERENTIAL,
    constrain_ackermann_velocity,
    control_mode,
)


def test_control_mode_defaults_to_differential_for_legacy_commands() -> None:
    assert control_mode({}) == DIFFERENTIAL
    assert control_mode({"controlMode": ACKERMANN}) == ACKERMANN
    with pytest.raises(ValueError):
        control_mode({"controlMode": "unknown"})


def test_ackermann_turn_adds_linear_speed_and_enforces_one_metre_radius() -> None:
    linear, angular = constrain_ackermann_velocity(0.0, 0.8)

    assert linear == pytest.approx(0.08)
    assert angular == pytest.approx(0.08)
    assert abs(linear / angular) == pytest.approx(1.0)


def test_ackermann_reverse_turn_preserves_direction() -> None:
    linear, angular = constrain_ackermann_velocity(-0.2, -0.5)

    assert linear == pytest.approx(-0.2)
    assert angular == pytest.approx(-0.2)


def test_stop_and_straight_motion_are_not_changed() -> None:
    assert constrain_ackermann_velocity(0.0, 0.0) == (0.0, 0.0)
    assert constrain_ackermann_velocity(0.2, 0.0) == (0.2, 0.0)
