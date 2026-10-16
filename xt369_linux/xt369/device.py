"""Linux hidraw backend using only Python's standard library.

Passive by default; optional fixed vendor polling request only.
No arbitrary output/feature commands, resets, or calibration.
Device enumeration reads sysfs metadata; it never reads unrelated HID input.
"""
from dataclasses import asdict, dataclass
import errno
import math
import os
from pathlib import Path
import select
import stat

from .protocol import HIDRAW_MEASUREMENT_QUERY, Measurement, parse_report

OBSERVED_PC_IDS = (0x0483, 0x5750)


def report_descriptor(info: 'DeviceInfo') -> bytes:
    return (Path('/sys/class/hidraw') / Path(info.path).name /
            'device/report_descriptor').read_bytes()


def compatible_report_layout(descriptor: bytes) -> bool:
    """Accept HID descriptor variants with the same unnumbered 64-byte I/O.

    This checks report structure, not an exact firmware descriptor byte string.
    It deliberately rejects Report IDs, non-vendor pages and other I/O sizes.
    """
    size = count = usage_page = 0
    input_bits = output_bits = 0
    collections = 0
    stack = []
    index = 0
    try:
        while index < len(descriptor):
            prefix = descriptor[index]
            index += 1
            if prefix == 0xfe:  # long item: unsupported for this layout check
                return False
            length = (0, 1, 2, 4)[prefix & 3]
            value = int.from_bytes(descriptor[index:index + length], 'little')
            if index + length > len(descriptor):
                return False
            index += length
            item_type = (prefix >> 2) & 3
            tag = (prefix >> 4) & 15
            if item_type == 3:
                return False
            if item_type == 1:  # global item
                if tag == 0:
                    usage_page = value
                elif tag == 7:
                    size = value
                elif tag == 8:  # Report ID present: hidraw write shape differs
                    return False
                elif tag == 9:
                    count = value
                elif tag == 10:
                    stack.append((size, count, usage_page))
                elif tag == 11:
                    size, count, usage_page = stack.pop()
            elif item_type == 0 and tag == 10:
                if length != 1:
                    return False
                collections += 1
            elif item_type == 0 and tag == 12:
                if length != 0 or collections <= 0:
                    return False
                collections -= 1
            elif item_type == 0 and tag in (8, 9):
                if (collections <= 0 or not 0xff00 <= usage_page <= 0xffff or
                        size <= 0 or count <= 0 or length == 0 or value & 1):
                    return False
                if tag == 8:
                    input_bits += size * count
                else:
                    output_bits += size * count
    except (IndexError, OverflowError):
        return False
    return input_bits == output_bits == 512 and collections == 0 and not stack


@dataclass(frozen=True)
class DeviceInfo:
    path: str
    vendor_id: int
    product_id: int
    name: str
    manufacturer: str
    product: str
    serial: str
    usb_port: str
    interface: str
    bus: int

    @property
    def named_xt369(self) -> bool:
        return "XT369" in (self.name + " " + self.product).upper()

    @property
    def candidate(self) -> bool:
        return self.bus == 3 and (self.named_xt369 or
                                  (self.vendor_id, self.product_id) == OBSERVED_PC_IDS)

    def to_dict(self) -> dict:
        return {**asdict(self), "vendor_id": f"{self.vendor_id:04x}",
                "product_id": f"{self.product_id:04x}",
                "candidate": self.candidate, "name_matches": self.named_xt369}


def _read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def enumerate_devices(sys_class: Path = Path("/sys/class/hidraw"),
                      dev_root: Path = Path("/dev")) -> list[DeviceInfo]:
    devices = []
    for node in sorted(sys_class.glob("hidraw*")):
        hid = (node / "device").resolve()
        props = dict(line.split("=", 1) for line in _read(hid / "uevent").splitlines() if "=" in line)
        try:
            bus, vid, pid = (int(v, 16) for v in props["HID_ID"].split(":"))
        except (KeyError, ValueError):
            continue
        usb = next((p for p in hid.parents if (p / "idVendor").exists()), None)
        interface = next((_read(p / "bInterfaceNumber") for p in hid.parents
                          if (p / "bInterfaceNumber").exists()), "")
        devices.append(DeviceInfo(
            path=str(dev_root / node.name), vendor_id=vid, product_id=pid, bus=bus,
            name=props.get("HID_NAME", ""),
            manufacturer=_read(usb / "manufacturer") if usb else "",
            product=_read(usb / "product") if usb else "",
            serial=(_read(usb / "serial") if usb else "") or props.get("HID_UNIQ", ""),
            usb_port=usb.name if usb else "", interface=interface,
        ))
    return devices


class DeviceNotFound(RuntimeError):
    pass


class AmbiguousDevice(RuntimeError):
    pass


def select_device(devices: list[DeviceInfo], *, path: str | None = None,
                  serial: str | None = None, previous: DeviceInfo | None = None) -> DeviceInfo:
    candidates = [d for d in devices if d.candidate]
    if previous is not None:
        candidates = [d for d in candidates if
                      (d.vendor_id, d.product_id, d.interface) ==
                      (previous.vendor_id, previous.product_id, previous.interface) and
                      (d.serial == previous.serial if previous.serial else
                       bool(previous.usb_port) and d.usb_port == previous.usb_port)]
    elif path:
        candidates = [d for d in candidates if os.path.realpath(d.path) == os.path.realpath(path)]
    else:
        # STM32's generic IDs can belong to other devices. Auto-open only by name.
        candidates = [d for d in candidates if d.named_xt369]
    if serial is not None:
        candidates = [d for d in candidates if d.serial == serial]
    if not candidates:
        raise DeviceNotFound("未找到匹配的 XT369。运行 python3 -m xt369 list 查看连接与选择条件。")
    if len(candidates) != 1:
        raise AmbiguousDevice("发现多个匹配设备/接口，请用 --device 指定：" +
                              ", ".join(d.path for d in candidates))
    return candidates[0]


class XT369Device:
    """One connection. Callers handle disconnects with close/connect explicitly.

    read_measurement returns None on timeout and raises ProtocolError for unknown
    reports. It never returns a stale previous measurement.
    """
    def __init__(self, path: str | None = None, *, serial: str | None = None,
                 poll: bool = False):
        self.path, self.serial = path, serial
        self.poll = poll
        self.info: DeviceInfo | None = None
        self._fd: int | None = None

    def connect(self) -> DeviceInfo:
        self.close()
        info = select_device(enumerate_devices(), path=self.path, serial=self.serial, previous=self.info)
        if self.poll:
            if (not info.named_xt369 or info.bus != 3 or
                    (info.vendor_id, info.product_id) != OBSERVED_PC_IDS):
                raise ValueError('主动查询仅支持型号名匹配且 VID/PID 为 0483:5750 的 XT369')
            if not compatible_report_layout(report_descriptor(info)):
                raise ValueError('不支持此 HID 描述符：需要已适配的 64 字节无编号 XT369 报告')
        access = os.O_RDWR if self.poll else os.O_RDONLY
        flags = access | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW
        fd = os.open(info.path, flags)
        try:
            if not stat.S_ISCHR(os.fstat(fd).st_mode):
                raise OSError("目标不是字符设备")
        except BaseException:
            os.close(fd)
            raise
        self._fd, self.info = fd, info
        return info

    def request_measurement(self) -> bytes:
        """Send only the vendor normal-state query. Call at most once per second.

        A successful write confirms transport acceptance, not a measurement.
        """
        if not self.poll:
            raise RuntimeError('底层设备未启用查询；使用 XT369Reader 或设置 poll=True')
        if self._fd is None:
            raise RuntimeError('请先 connect()')
        sent = os.write(self._fd, HIDRAW_MEASUREMENT_QUERY)
        if sent != len(HIDRAW_MEASUREMENT_QUERY):
            raise OSError(errno.EIO, f'查询报告写入不完整：{sent}/65 字节；不拼接重发')
        return HIDRAW_MEASUREMENT_QUERY

    def read_report(self, timeout: float = 1.0) -> bytes | None:
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("timeout 必须是非负有限数字")
        if self._fd is None:
            raise RuntimeError("请先 connect()")
        ready, _, _ = select.select([self._fd], [], [], timeout)
        if not ready:
            return None
        try:
            report = os.read(self._fd, 4096)
        except BlockingIOError:
            return None
        if not report:
            raise OSError(errno.ENODEV, "设备已断开")
        return report

    def read_measurement(self, timeout: float = 1.0) -> Measurement | None:
        report = self.read_report(timeout)
        return None if report is None else parse_report(report)

    def close(self) -> None:
        if self._fd is not None:
            fd, self._fd = self._fd, None
            os.close(fd)

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.close()
