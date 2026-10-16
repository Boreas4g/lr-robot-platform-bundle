"""Centimetre-based absolute-position control for the configured lift platform."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from .drive import AimDrive
from .registers import POSITION_TOLERANCE_PULSES


@dataclass(frozen=True, slots=True)
class LiftSpeedProfile:
    """Drive parameters assigned to one user-facing lift speed level."""

    target_speed_rpm: int
    acceleration_rpm_s: int


class LiftPlatform:
    """Control a lift using its calibrated height-to-absolute-position mapping.

    The calibration is fixed to 0 cm at absolute position 1 and 100000
    pulses for every 2.2 cm of lift travel. Heights are accepted from 0 cm
    through 170 cm inclusive. A target must be an integer pulse, so values
    between pulses are rounded to the nearest pulse with half values rounded up.
    """

    MIN_HEIGHT_CM = Decimal("0")
    MAX_HEIGHT_CM = Decimal("170")
    REFERENCE_HEIGHT_CM = MIN_HEIGHT_CM
    REFERENCE_ABSOLUTE_POSITION = 1
    PULSES_PER_TRAVEL = Decimal("100000")
    TRAVEL_CM = Decimal("2.2")
    DEFAULT_TIMEOUT_S = 45.0
    SPEED_PROFILES = {
        1: LiftSpeedProfile(target_speed_rpm=200, acceleration_rpm_s=400),
        2: LiftSpeedProfile(target_speed_rpm=400, acceleration_rpm_s=400),
        3: LiftSpeedProfile(target_speed_rpm=600, acceleration_rpm_s=600),
    }

    def __init__(self, drive: AimDrive, *, reference_absolute_position: int | None = None) -> None:
        self.drive = drive
        if reference_absolute_position is not None and not isinstance(reference_absolute_position, int):
            raise ValueError("reference absolute position must be an integer pulse count")
        self._reference_absolute_position = reference_absolute_position

    @property
    def reference_absolute_position(self) -> int:
        """Pulse count that reads as the calibrated minimum height (0 cm)."""

        return (
            self._reference_absolute_position
            if self._reference_absolute_position is not None
            else self.REFERENCE_ABSOLUTE_POSITION
        )

    def height_to_target_pulses(self, height_cm: Decimal | str | int | float) -> int:
        """Convert a calibrated height to a pulse target using this platform's zero reference."""

        base = self.height_to_absolute_position(height_cm)
        return base - self.REFERENCE_ABSOLUTE_POSITION + self.reference_absolute_position

    def pulses_to_height_cm(self, absolute_position: int) -> Decimal:
        """Convert a pulse feedback value to a calibrated height using this platform's zero reference."""

        if not isinstance(absolute_position, int):
            raise ValueError("absolute position must be an integer pulse count")
        return self.absolute_position_to_height(
            absolute_position - self.reference_absolute_position + self.REFERENCE_ABSOLUTE_POSITION
        )

    @classmethod
    def height_to_absolute_position(cls, height_cm: Decimal | str | int | float) -> int:
        """Convert a calibrated height in centimetres to an absolute pulse target."""
        height = cls._parse_height(height_cm)
        offset_pulses = (height - cls.REFERENCE_HEIGHT_CM) * cls.PULSES_PER_TRAVEL / cls.TRAVEL_CM
        return cls.REFERENCE_ABSOLUTE_POSITION + int(offset_pulses.to_integral_value(rounding=ROUND_HALF_UP))

    @classmethod
    def absolute_position_to_height(cls, absolute_position: int) -> Decimal:
        """Convert an absolute pulse feedback value to its calibrated height."""
        if not isinstance(absolute_position, int):
            raise ValueError("absolute position must be an integer pulse count")
        return cls.REFERENCE_HEIGHT_CM + (
            Decimal(absolute_position - cls.REFERENCE_ABSOLUTE_POSITION) * cls.TRAVEL_CM / cls.PULSES_PER_TRAVEL
        )

    @classmethod
    def speed_profile(cls, speed: int) -> LiftSpeedProfile:
        """Return the configured motion profile for speed level 1, 2, or 3."""
        if type(speed) is not int:
            raise ValueError("lift speed must be the integer 1, 2, or 3")
        try:
            return cls.SPEED_PROFILES[speed]
        except KeyError as error:
            raise ValueError("lift speed must be 1, 2, or 3") from error

    def move_to_height(
        self,
        height_cm: Decimal | str | int | float,
        speed: int,
        *,
        wait: bool = True,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        tolerance_pulses: int = POSITION_TOLERANCE_PULSES,
        check_ready: bool = True,
    ) -> int:
        """Apply a speed profile, then move to a target height and return its pulse target."""
        target = self.height_to_target_pulses(height_cm)
        profile = self.speed_profile(speed)
        self.drive.configure_motion(
            max_speed_rpm=profile.target_speed_rpm,
            acceleration_rpm_s=profile.acceleration_rpm_s,
        )
        self.drive.move_absolute(
            target,
            wait=wait,
            timeout_s=timeout_s,
            tolerance_pulses=tolerance_pulses,
            check_ready=check_ready,
        )
        return target

    def read_height_cm(self) -> Decimal:
        """Return the calibrated height represented by current absolute feedback."""
        return self.pulses_to_height_cm(self.drive.read_absolute_position())

    @classmethod
    def _parse_height(cls, height_cm: Decimal | str | int | float) -> Decimal:
        try:
            height = Decimal(str(height_cm))
        except (InvalidOperation, ValueError) as error:
            raise ValueError("lift height must be a finite number of centimetres") from error
        if not height.is_finite():
            raise ValueError("lift height must be a finite number of centimetres")
        if not cls.MIN_HEIGHT_CM <= height <= cls.MAX_HEIGHT_CM:
            raise ValueError(
                "lift height must be in the range %s..%s cm"
                % (cls.MIN_HEIGHT_CM, cls.MAX_HEIGHT_CM)
            )
        return height
