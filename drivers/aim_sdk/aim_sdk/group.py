"""Broadcast-synchronized multi-axis commands documented by YZ-AIM."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .drive import AimDrive
from .models import split_i32
from .registers import Register


@dataclass(frozen=True, slots=True)
class AxisMove:
    """One record in a YZ-AIM broadcast absolute-motion frame."""

    position: int
    speed_rpm: int
    acceleration_rpm_s: int

    def validate(self) -> None:
        split_i32(self.position)
        if not 0 <= self.speed_rpm <= 3000:
            raise ValueError("axis speed must be in 0..3000 RPM")
        if not 0 <= self.acceleration_rpm_s <= 60098:
            raise ValueError("axis acceleration must be in 0..60098 RPM/s")


class AimDriveGroup:
    """A shared-RS485 group controlled by the manual's address-0 broadcast.

    The manual associates the first 8-byte record with device address 1, the
    second with device address 2, and so on. Therefore device addresses must
    be consecutive, beginning at 1, and an omitted axis cannot be skipped.
    """

    def __init__(self, drives: Iterable[AimDrive]) -> None:
        self.drives = tuple(drives)
        if not self.drives:
            raise ValueError("a drive group needs at least one drive")
        first_client = self.drives[0].client
        first_transport = first_client.transport
        if any(drive.client.transport is not first_transport for drive in self.drives):
            raise ValueError("all group drives must share one RS485 transport")
        addresses = tuple(drive.address for drive in self.drives)
        if addresses != tuple(range(1, len(self.drives) + 1)):
            raise ValueError("broadcast axes must have consecutive addresses 1..N in axis order")
        self.client = first_client

    def move_absolute_sync(self, moves: Iterable[AxisMove]) -> None:
        """Broadcast simultaneous absolute position, speed, and acceleration.

        This is the manual's `0x10`, address `0x00`, register `0x16` frame.
        Broadcast does not have a reply, so every axis must be checked before
        the command is sent.
        """
        entries = tuple(moves)
        if len(entries) != len(self.drives):
            raise ValueError("one AxisMove is required for each group drive")
        for drive, move in zip(self.drives, entries, strict=True):
            move.validate()
            drive.assert_motion_ready()
        data = bytearray()
        for move in entries:
            low, high = split_i32(move.position)
            data.extend(low.to_bytes(2, "big"))
            data.extend(high.to_bytes(2, "big"))
            data.extend(move.speed_rpm.to_bytes(2, "big"))
            data.extend(move.acceleration_rpm_s.to_bytes(2, "big"))
        self.client.broadcast_write_multiple(Register.ABSOLUTE_POSITION_LOW, len(entries) * 4, bytes(data))

    def disable_outputs(self) -> None:
        """Disable each individual axis; not synchronized by the manual."""
        for drive in self.drives:
            drive.disable_output()

    def assert_all_ready(self) -> None:
        """Validate every axis before an operation that cannot be replied to."""
        for drive in self.drives:
            drive.assert_motion_ready()
