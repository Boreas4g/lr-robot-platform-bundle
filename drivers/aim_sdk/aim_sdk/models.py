"""Public data types and unit conversions for the YZ-AIM protocol."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class BaudRate(IntEnum):
    """Baud rates selectable through the manual's special configuration flow."""

    BPS_9600 = 9600
    BPS_19200 = 19200
    BPS_38400 = 38400
    BPS_115200 = 115200

    @property
    def manual_acceleration_value(self) -> int:
        return {
            BaudRate.BPS_9600: 800,
            BaudRate.BPS_19200: 801,
            BaudRate.BPS_38400: 802,
            BaudRate.BPS_115200: 803,
        }[self]


class AlarmCode(IntEnum):
    """Alarm codes explicitly documented by YZ-AIM v2.56."""

    NONE = 0x00
    BATTERY_POWER_LOSS = 0x10
    OVERCURRENT = 0x12
    STALL = 0x14
    OVERVOLTAGE = 0x15

    @classmethod
    def from_register(cls, value: int) -> "AlarmCode | int":
        try:
            return cls(value)
        except ValueError:
            return value


class SpecialFunction(IntEnum):
    """Operating modes and homing values written to register 0x19."""

    PULSE_DIRECTION = 0
    MECHANICAL_HOME_PLUS_36_DEGREES = 1
    ENCODER_FOLLOW = 2
    PWM_SPEED = 3
    MECHANICAL_HOME_TO_ENCODER_ZERO = 4
    ZOUT_SIMULATED_HOME = 5
    HOME_SWITCH_ON_ENABLE_INPUT = 8


@dataclass(frozen=True, slots=True)
class DriveStatus:
    """Scaled real-time feedback collected from documented status registers."""

    absolute_position: int
    speed_rpm: float
    current_a: float
    voltage_v: float
    temperature_c: int
    pwm_percent: float
    alarm: AlarmCode | int
    output_enabled: bool
    modbus_enabled: bool


@dataclass(frozen=True, slots=True)
class MotionConfiguration:
    """Core motion settings in physical units where the manual defines units."""

    max_speed_rpm: int
    acceleration_rpm_s: int
    position_kp: int | None = None
    speed_kp: float | None = None
    speed_integral_ms: int | None = None
    speed_feedforward_v_per_krpm: float | None = None


def join_i32(low_word: int, high_word: int) -> int:
    """Join vendor low/high 16-bit words into a signed 32-bit integer."""
    value = (high_word << 16) | low_word
    return value - 0x1_0000_0000 if value & 0x8000_0000 else value


def split_i32(value: int) -> tuple[int, int]:
    """Split a signed 32-bit value into vendor low/high 16-bit words."""
    if not -(1 << 31) <= value <= (1 << 31) - 1:
        raise ValueError("position must fit in a signed 32-bit integer")
    unsigned = value & 0xFFFF_FFFF
    return unsigned & 0xFFFF, unsigned >> 16


def signed_i16(value: int) -> int:
    """Interpret an unsigned Modbus register as a signed 16-bit value."""
    return value - 0x1_0000 if value & 0x8000 else value


def unsigned_i16(value: int) -> int:
    """Encode a signed 16-bit integer as a Modbus register."""
    if not -(1 << 15) <= value <= (1 << 15) - 1:
        raise ValueError("value must fit in a signed 16-bit integer")
    return value & 0xFFFF
