"""Small dependency-free Modbus RTU implementation used by the drive API."""

from __future__ import annotations

from dataclasses import dataclass

from .exceptions import CrcError, ModbusException, ProtocolError, ResponseTimeout
from .registers import MODBUS_READ_HOLDING, MODBUS_WRITE_MULTIPLE, MODBUS_WRITE_SINGLE
from .transport import FrameTransport


def crc16(data: bytes) -> int:
    """Return the standard Modbus RTU CRC-16 value."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def append_crc(payload: bytes) -> bytes:
    """Append Modbus CRC in wire order: low byte then high byte."""
    return payload + crc16(payload).to_bytes(2, "little")


def validate_crc(frame: bytes) -> bytes:
    """Validate a full RTU frame and return it without the CRC bytes."""
    if len(frame) < 4:
        raise ProtocolError("Modbus RTU frame is shorter than four bytes")
    payload, received = frame[:-2], int.from_bytes(frame[-2:], "little")
    expected = crc16(payload)
    if received != expected:
        raise CrcError(f"invalid CRC: received 0x{received:04X}, expected 0x{expected:04X}")
    return payload


def _u16(value: int) -> bytes:
    if not 0 <= value <= 0xFFFF:
        raise ValueError("register value must be in 0..65535")
    return value.to_bytes(2, "big")


@dataclass(slots=True)
class ModbusRtuClient:
    """Synchronous Modbus RTU client for a single half-duplex bus."""

    transport: FrameTransport
    timeout_s: float = 0.2
    retries: int = 1

    def read_holding(self, address: int, start: int, count: int) -> list[int]:
        if not 1 <= count <= 125:
            raise ValueError("Modbus read count must be in 1..125")
        response = self.request(address, MODBUS_READ_HOLDING, _u16(start) + _u16(count))
        if len(response) < 1 or response[0] != count * 2:
            raise ProtocolError("read response byte count does not match request")
        data = response[1:]
        if len(data) != count * 2:
            raise ProtocolError("read response is truncated")
        return [int.from_bytes(data[i : i + 2], "big") for i in range(0, len(data), 2)]

    def write_single(self, address: int, register: int, value: int) -> None:
        body = _u16(register) + _u16(value)
        response = self.request(address, MODBUS_WRITE_SINGLE, body)
        if response != body:
            raise ProtocolError("write-single response does not echo request")

    def write_multiple(self, address: int, start: int, values: list[int] | tuple[int, ...]) -> None:
        if not 1 <= len(values) <= 123:
            raise ValueError("Modbus write count must be in 1..123")
        data = b"".join(_u16(value) for value in values)
        body = _u16(start) + _u16(len(values)) + bytes((len(data),)) + data
        response = self.request(address, MODBUS_WRITE_MULTIPLE, body)
        expected = _u16(start) + _u16(len(values))
        if response != expected:
            raise ProtocolError("write-multiple response does not echo address/count")

    def broadcast_write_multiple(self, start: int, count: int, data: bytes) -> None:
        """Send a standard address-0 write-multiple broadcast without waiting.

        Modbus RTU broadcasts are deliberately silent. The manual uses this
        exact pattern for synchronized multi-axis absolute moves.
        """
        if not 1 <= count <= 123:
            raise ValueError("Modbus write count must be in 1..123")
        if len(data) != count * 2:
            raise ValueError("broadcast data length does not match register count")
        frame = append_crc(bytes((0, MODBUS_WRITE_MULTIPLE)) + _u16(start) + _u16(count) + bytes((len(data),)) + data)
        self.transport.send_broadcast(frame)

    def request(
        self,
        address: int,
        function: int,
        data: bytes = b"",
        *,
        response_function: int | None = None,
    ) -> bytes:
        if not 0 <= address <= 247:
            raise ValueError("Modbus device address must be in 0..247")
        if not 0 <= function <= 255:
            raise ValueError("function must be a byte")
        frame = append_crc(bytes((address, function)) + data)
        last_error: Exception | None = None
        for _ in range(self.retries + 1):
            try:
                response = self.transport.transceive(frame, self.timeout_s)
                payload = validate_crc(response)
                if len(payload) < 2:
                    raise ProtocolError("Modbus RTU reply has no address/function header")
                if payload[0] != address:
                    raise ProtocolError(f"reply address {payload[0]} does not match {address}")
                reply_function = payload[1]
                if reply_function == function | 0x80:
                    if len(payload) != 3:
                        raise ProtocolError("malformed Modbus exception response")
                    raise ModbusException(function, payload[2])
                expected_function = function if response_function is None else response_function
                if reply_function != expected_function:
                    raise ProtocolError(
                        f"reply function 0x{reply_function:02X} does not match 0x{expected_function:02X}"
                    )
                return payload[2:]
            except ResponseTimeout as error:
                last_error = error
        raise last_error or ResponseTimeout("drive did not respond")
