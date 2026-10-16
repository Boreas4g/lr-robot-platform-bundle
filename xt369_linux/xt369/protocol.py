"""XT369P measured-data frame parser.

Evidence: parser VA 0x42c440, measurement branch 0x42c530, scale
constant float32 at VA 0x477008 = 1_000_000. This branch checks no
EE FF trailer. Header recognition is NOT a checksum.
"""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import struct
import time

HEADER = bytes.fromhex("aa 40 62 05")
REPORT_SIZE = 64

# DcTester.exe normal-state timer: 0x4108d0 -> 0x403e10.
# Windows libusb transmits all 64 bytes, including 0x55. Linux hidraw
# needs an EXTRA leading zero selector for the unnumbered report.
MEASUREMENT_QUERY_PAYLOAD = bytes.fromhex('55 05 22 05 0b 00 8c ee ff') + bytes(55)
HIDRAW_MEASUREMENT_QUERY = b'\x00' + MEASUREMENT_QUERY_PAYLOAD


class ProtocolError(ValueError):
    """Unknown, truncated, or unsupported report; never use cached values."""


@dataclass(frozen=True)
class Measurement:
    received_at: str
    received_monotonic: float
    voltage_v: float
    current_a: float
    power_w_calculated: float
    raw_voltage: int
    raw_current: int
    raw_report_hex: str
    report_id: int | None
    protocol: str = "xt369p-aa406205"
    validation: str = "header-and-length-only"

    def to_dict(self) -> dict:
        return asdict(self)


def parse_report(report: bytes, *, received_at: str | None = None,
                 received_monotonic: float | None = None) -> Measurement:
    """Parse one complete HID report (not an arbitrary serial byte stream).

    Accept 64 bytes starting AA, or exactly 65 with a descriptor-defined
    report-ID byte followed by AA. The latter is a transport adaptation,
    not a claim that this firmware uses a particular input report ID.
    The numeric resolution of the encoding is not instrument accuracy.
    """
    report = bytes(report)
    report_id = None
    frame = report
    if len(report) == 65 and report[1:5] == HEADER:
        report_id, frame = report[0], report[1:]
    if len(frame) != REPORT_SIZE:
        raise ProtocolError(f"需要完整的 64 字节测量帧，收到 {len(report)} 字节")
    if frame[:4] != HEADER:
        raise ProtocolError(f"未知测量帧头 {frame[:4].hex(' ')}")
    raw_voltage, raw_current = struct.unpack_from("<II", frame, 8)
    voltage, current = raw_voltage / 1_000_000, raw_current / 1_000_000
    return Measurement(
        received_at=received_at or datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        received_monotonic=time.monotonic() if received_monotonic is None else received_monotonic,
        voltage_v=voltage, current_a=current, power_w_calculated=voltage * current,
        raw_voltage=raw_voltage, raw_current=raw_current,
        raw_report_hex=report.hex(" "), report_id=report_id,
    )
