"""In-memory Modbus RTU simulator for development without servo hardware."""

from __future__ import annotations

from dataclasses import dataclass, field

from .exceptions import ResponseTimeout
from .modbus import append_crc, validate_crc
from .models import join_i32, split_i32
from .registers import (
    MODBUS_READ_HOLDING,
    MODBUS_WRITE_MULTIPLE,
    MODBUS_WRITE_SINGLE,
    VENDOR_INCREMENTAL_MOVE,
    VENDOR_INCREMENTAL_MOVE_RESPONSE,
    Register,
)
from .transport import FrameTransport


@dataclass(slots=True)
class SimulatedAimDevice:
    """A deterministic register-level subset of a YZ-AIM drive.

    It immediately completes moves and does not model mechanics, inertia,
    homing sensors, or power cycling. Its purpose is protocol/API testing.
    """

    address: int = 1
    registers: list[int] = field(default_factory=lambda: [0] * 0x1A)

    def __post_init__(self) -> None:
        self.registers[Register.ELECTRONIC_GEAR_DENOMINATOR] = 1
        self.registers[Register.SAVE_PARAMETERS] = 2

    @property
    def absolute_position(self) -> int:
        return join_i32(
            self.registers[Register.ABSOLUTE_POSITION_LOW],
            self.registers[Register.ABSOLUTE_POSITION_HIGH],
        )

    @absolute_position.setter
    def absolute_position(self, value: int) -> None:
        low, high = split_i32(value)
        self.registers[Register.ABSOLUTE_POSITION_LOW] = low
        self.registers[Register.ABSOLUTE_POSITION_HIGH] = high

    def handle(self, payload: bytes) -> bytes | None:
        """Handle a CRC-stripped RTU request and return a CRC-stripped reply."""
        address, function, data = payload[0], payload[1], payload[2:]
        if address not in (0, self.address):
            return None
        is_broadcast = address == 0
        if function == MODBUS_READ_HOLDING:
            if is_broadcast:
                return None
            start = int.from_bytes(data[:2], "big")
            count = int.from_bytes(data[2:4], "big")
            if start + count > len(self.registers):
                return bytes((self.address, function | 0x80, 0x02))
            encoded = b"".join(value.to_bytes(2, "big") for value in self.registers[start : start + count])
            return bytes((self.address, function, len(encoded))) + encoded
        if function == MODBUS_WRITE_SINGLE:
            register = int.from_bytes(data[:2], "big")
            value = int.from_bytes(data[2:4], "big")
            self._write(register, [value])
            return None if is_broadcast else bytes((self.address, function)) + data[:4]
        if function == MODBUS_WRITE_MULTIPLE:
            start = int.from_bytes(data[:2], "big")
            count = int.from_bytes(data[2:4], "big")
            byte_count = data[4]
            raw_values = data[5 : 5 + byte_count]
            if byte_count != count * 2 or len(raw_values) != byte_count:
                return bytes((self.address, function | 0x80, 0x03))
            values = [int.from_bytes(raw_values[index : index + 2], "big") for index in range(0, byte_count, 2)]
            if is_broadcast and start == Register.ABSOLUTE_POSITION_LOW and count % 4 == 0:
                # The manual assigns each 4-register record to address 1, 2,
                # etc. The records are not one contiguous register write in a
                # single device.
                axis_index = self.address - 1
                offset = axis_index * 4
                if offset + 4 <= len(values):
                    _window = values[offset : offset + 4]
                    position_low, position_high, speed, acceleration = _window
                    self.registers[Register.TARGET_SPEED] = speed
                    self.registers[Register.ACCELERATION] = acceleration
                    self.absolute_position = join_i32(position_low, position_high)
                return None
            self._write(start, values)
            return None if is_broadcast else bytes((self.address, function)) + data[:4]
        if function == VENDOR_INCREMENTAL_MOVE:
            delta = int.from_bytes(data[:4], "big", signed=True)
            self.absolute_position += delta
            return None if is_broadcast else bytes((self.address, VENDOR_INCREMENTAL_MOVE_RESPONSE)) + data[:4]
        return bytes((self.address, function | 0x80, 0x01))

    def _write(self, start: int, values: list[int]) -> None:
        if start + len(values) > len(self.registers):
            return
        for index, value in enumerate(values):
            self.registers[start + index] = value
        if start == Register.SAVE_PARAMETERS and values and values[0] == 1:
            # Complete immediately; real hardware may retain value 1 briefly.
            self.registers[Register.SAVE_PARAMETERS] = 2
        if start <= Register.TARGET_POSITION_LOW and start + len(values) >= Register.TARGET_POSITION_HIGH + 1:
            low = self.registers[Register.TARGET_POSITION_LOW]
            high = self.registers[Register.TARGET_POSITION_HIGH]
            self.absolute_position += join_i32(low, high)
        if start <= Register.ABSOLUTE_POSITION_LOW and start + len(values) >= Register.ABSOLUTE_POSITION_HIGH + 1:
            low = self.registers[Register.ABSOLUTE_POSITION_LOW]
            high = self.registers[Register.ABSOLUTE_POSITION_HIGH]
            # Communication-mode zero is the manual's special clear command.
            if low == 0 and high == 0 and self.registers[Register.ELECTRONIC_GEAR_NUMERATOR] == 0:
                self.absolute_position = 0


class SimulatedTransport(FrameTransport):
    """A shared virtual RS485 bus for one or more :class:`SimulatedAimDevice`."""

    def __init__(self, *devices: SimulatedAimDevice) -> None:
        self.devices = {device.address: device for device in devices}
        self.requests: list[bytes] = []
        self.closed = False

    def transceive(self, request: bytes, timeout_s: float) -> bytes:
        timeout_s = None
        self.requests.append(request)
        payload = validate_crc(request)
        address = payload[0]
        device = self.devices.get(address)
        if device is None:
            raise ResponseTimeout(f"simulated address {address} did not respond")
        response = device.handle(payload)
        if response is None:
            raise ResponseTimeout("broadcast has no Modbus response")
        return append_crc(response)

    def send_broadcast(self, request: bytes) -> None:
        self.requests.append(request)
        payload = validate_crc(request)
        if payload[0] != 0:
            raise ValueError("simulated broadcast must use address zero")
        for device in self.devices.values():
            device.handle(payload)

    def close(self) -> None:
        self.closed = True
