"""Public Python API for live XT369 voltage/current acquisition on Linux."""
import time
import math
from collections.abc import Iterator

from .device import DeviceInfo, XT369Device
from .protocol import Measurement, parse_report


def format_measurement(measurement: Measurement) -> str:
    """Format a measurement like the former terminal reader output."""
    return (f"{measurement.received_at}  电压={measurement.voltage_v:.6f} V  "
            f"电流={measurement.current_a:.6f} A  "
            f"计算功率={measurement.power_w_calculated:.6f} W")


class XT369Reader:
    """Context-managed, actively-polled reader for a connected Linux XT369.

    Args:
        path: Optional hidraw path, for example ``/dev/hidraw7``.
        serial: Optional USB serial to select one of multiple meters.
        poll_interval: Minimum delay between the vendor query requests.
        report_timeout: Maximum time a single ``read`` call waits for a frame.

    Reads are on demand. Each poll sends only the fixed normal-measurement
    request used by the supplied PC application. Unknown input reports are
    rejected; timeouts return ``None`` and never repeat an old measurement.
    """

    def __init__(self, path: str | None = None, *, serial: str | None = None,
                 poll_interval: float = 1.0, report_timeout: float = 1.5):
        if not math.isfinite(poll_interval) or poll_interval < 1:
            raise ValueError("poll_interval must be finite and at least 1 second")
        if not math.isfinite(report_timeout) or report_timeout <= 0:
            raise ValueError("report_timeout must be finite and greater than zero")
        self.poll_interval = float(poll_interval)
        self.report_timeout = float(report_timeout)
        self._device = XT369Device(path, serial=serial, poll=True)
        self._next_poll = 0.0
        self._connected = False

    @property
    def device_info(self) -> DeviceInfo | None:
        """Selected USB/HID device metadata, or ``None`` before connect."""
        return self._device.info

    def connect(self) -> DeviceInfo:
        """Open the selected XT369 HID device for its fixed query/read flow."""
        self._connected = False
        info = self._device.connect()
        self._connected = True
        self._next_poll = 0.0
        return info

    def read(self, timeout: float | None = None) -> Measurement | None:
        """Return one new measurement, or ``None`` if the wait times out.

        ``timeout`` defaults to ``report_timeout``. A caller may pass a larger
        timeout to tolerate slower firmware. Timeout must be positive/finite.
        """
        if timeout is None:
            timeout = self.report_timeout
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive and finite")
        if not self._connected:
            raise RuntimeError("call connect() or use the reader as a context manager")

        deadline = time.monotonic() + timeout
        while True:
            now = time.monotonic()
            if now >= deadline:
                return None
            if now >= self._next_poll:
                self._device.request_measurement()
                self._next_poll = time.monotonic() + self.poll_interval

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            wait = min(remaining, max(0.0, self._next_poll - time.monotonic()))
            report = self._device.read_report(wait)
            if report is None:
                if time.monotonic() >= deadline:
                    return None
                continue
            return parse_report(report)

    def __iter__(self) -> Iterator[Measurement]:
        """Yield measurements; raise TimeoutError on silence. Break to stop."""
        while True:
            measurement = self.read()
            if measurement is None:
                raise TimeoutError("XT369 did not return a measurement within report_timeout")
            yield measurement

    def close(self) -> None:
        """Close the HID handle; safe to call more than once."""
        self._connected = False
        self._device.close()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.close()
