import threading

import pytest

from car_ctrl.ddsm_hat_diff_drive_node import (
    DDSM115Rs485Bus,
    DDSMHatDiffDriveNode,
    MotorFeedback,
    attach_crc,
    int16_to_bytes,
)


class _Logger:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def info(self, message: str) -> None:
        self.messages.append(message)


def _feedback_frame() -> bytes:
    current_high, current_low = int16_to_bytes(-2000)
    rpm_high, rpm_low = int16_to_bytes(-12)
    return attach_crc(
        bytes([1, 0x02, current_high, current_low, rpm_high, rpm_low, 52, 0, 0x0A])
    )


def test_feedback_parser_retains_current_error_and_extended_temperature() -> None:
    bus = DDSM115Rs485Bus.__new__(DDSM115Rs485Bus)
    frame = _feedback_frame()

    feedback = bus.parse_feedback(frame, 1)

    assert feedback is not None
    assert feedback.motor_id == 1
    assert feedback.rpm == -12.0
    assert feedback.current_a == pytest.approx(-2000 * 8.0 / 32767.0)
    assert feedback.error_code == 0x0A
    assert feedback.temperature_c is None

    extended = bus.parse_feedback(frame, 1, extended_feedback=True)
    assert extended is not None
    assert extended.temperature_c == 52.0


def test_feedback_log_reports_command_current_and_decoded_errors(monkeypatch) -> None:
    node = DDSMHatDiffDriveNode.__new__(DDSMHatDiffDriveNode)
    node.motor_ids = [1, 2, 3, 4]
    node.feedback_timeout = 0.5
    node._command_lock = threading.Lock()
    node._last_commanded_rpms = {1: -22, 2: 22, 3: -22, 4: 22}
    node._feedback_lock = threading.Lock()
    node._feedback_rpms = [None, None, None, None]
    node._feedback_currents = [None, None, None, None]
    node._feedback_errors = [None, None, None, None]
    node._feedback_temperatures = [None, None, None, None]
    node._feedback_times = [0.0, 0.0, 0.0, 0.0]
    logger = _Logger()
    node.get_logger = lambda: logger
    monkeypatch.setattr("car_ctrl.ddsm_hat_diff_drive_node.time.monotonic", lambda: 10.0)

    node._apply_feedback(
        [
            MotorFeedback(1, -1.0, 1.25, 0x08, 55.0),
            MotorFeedback(2, 22.0, -0.5, 0x00),
        ]
    )
    node._log_feedback_snapshot()

    assert node._feedback_currents == [1.25, -0.5, None, None]
    assert len(logger.messages) == 4
    assert "指令RPM：-22" in logger.messages[0]
    assert "实际RPM：-1.0" in logger.messages[0]
    assert "电流A：1.250" in logger.messages[0]
    assert "温度C：55" in logger.messages[0]
    assert "错误码：0x08(堵转)" in logger.messages[0]
    assert "实际RPM：22.0" in logger.messages[1]
    assert "电流A：-0.500" in logger.messages[1]
    assert "温度C：未提供" in logger.messages[1]
    assert "错误码：0x00" in logger.messages[1]
    assert "实际RPM：无反馈" in logger.messages[2]

    logger.messages.clear()
    node._last_commanded_rpms = {motor_id: 0 for motor_id in node.motor_ids}
    node._log_feedback_snapshot()
    assert logger.messages == []
