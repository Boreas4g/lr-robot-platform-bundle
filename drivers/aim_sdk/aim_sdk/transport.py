"""Transport abstraction and PySerial implementation for RS485 Modbus RTU."""

from __future__ import annotations

from abc import ABC, abstractmethod
import threading
import time

from .exceptions import ResponseTimeout, TransportError


class FrameTransport(ABC):
    """A request/reply transport that exchanges one complete Modbus RTU frame."""

    @abstractmethod
    def transceive(self, request: bytes, timeout_s: float) -> bytes:
        """Send one RTU request and return its complete RTU response."""

    def close(self) -> None:
        """Release any resources held by this transport."""

    def send_broadcast(self, request: bytes) -> None:
        """Send a Modbus broadcast frame, which intentionally has no reply."""
        raise TransportError("this transport does not support Modbus broadcasts")


class SerialTransport(FrameTransport):
    """Thread-safe RTU transport backed by pyserial.

    The driver must provide automatic TX/RX direction control or an RS485
    adapter configured for it. The isolated bus in the manual is half-duplex.
    """

    def __init__(
        self,
        port: str,
        baudrate: int = 19_200,
        *,
        timeout_s: float = 0.2,
        serial_port: object | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self.default_timeout_s = timeout_s
        if serial_port is not None:
            self._serial = serial_port
            return
        try:
            import serial
        except ImportError as error:  # pragma: no cover - depends on environment
            raise TransportError("pyserial is required for SerialTransport") from error
        self._serial = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=timeout_s,
            write_timeout=timeout_s,
        )

    @property
    def baudrate(self) -> int:
        return int(self._serial.baudrate)

    @baudrate.setter
    def baudrate(self, value: int) -> None:
        self._serial.baudrate = value

    def transceive(self, request: bytes, timeout_s: float) -> bytes:
        with self._lock:
            try:
                self._serial.reset_input_buffer()
                self._serial.write(request)
                self._serial.flush()
                return self._read_rtu_frame(timeout_s)
            except ResponseTimeout:
                raise
            except Exception as error:  # pragma: no cover - hardware dependent
                raise TransportError("serial request failed") from error

    def send_broadcast(self, request: bytes) -> None:
        with self._lock:
            try:
                self._serial.reset_input_buffer()
                self._serial.write(request)
                self._serial.flush()
            except Exception as error:  # pragma: no cover - hardware dependent
                raise TransportError("serial broadcast failed") from error

    def _read_rtu_frame(self, timeout_s: float) -> bytes:
        deadline = time.monotonic() + timeout_s
        header = self._read_exactly(2, deadline)
        function = header[1]
        if function & 0x80:
            return header + self._read_exactly(3, deadline)
        if function == 0x03:
            byte_count = self._read_exactly(1, deadline)
            return header + byte_count + self._read_exactly(byte_count[0] + 2, deadline)
        # Standard write echoes and the vendor 0x7A response are normally 8
        # bytes total. An undocumented 0x7A variant can use raw_request().
        return header + self._read_exactly(6, deadline)

    def _read_exactly(self, size: int, deadline: float) -> bytes:
        data = bytearray()
        while len(data) < size and time.monotonic() < deadline:
            chunk = self._serial.read(size - len(data))
            if chunk:
                data.extend(chunk)
        if len(data) != size:
            raise ResponseTimeout(f"expected {size} serial bytes, received {len(data)}")
        return bytes(data)

    def close(self) -> None:
        with self._lock:
            if getattr(self, "_serial", None) is not None and self._serial.is_open:
                self._serial.close()
