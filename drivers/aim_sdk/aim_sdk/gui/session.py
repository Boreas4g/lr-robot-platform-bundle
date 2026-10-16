"""State holder used by the GUI to own exactly one physical drive session."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, TypeVar

from ..drive import AimDrive
from ..exceptions import AimError


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ConnectionSettings:
    """Serial settings exposed by the connection page."""

    port: str
    address: int = 1
    baudrate: int = 19_200
    timeout_s: float = 0.2
    retries: int = 1

    def validate(self) -> None:
        if not self.port.strip():
            raise ValueError("请选择或输入串口名称，例如 /dev/lift_port")
        if not 1 <= self.address <= 247:
            raise ValueError("设备地址必须在 1 到 247 之间")
        if self.baudrate not in (9600, 19_200, 38_400, 115_200):
            raise ValueError("波特率必须是 9600、19200、38400 或 115200")
        if not 0.05 <= self.timeout_s <= 10:
            raise ValueError("超时时间必须在 0.05 到 10 秒之间")
        if not 0 <= self.retries <= 10:
            raise ValueError("重试次数必须在 0 到 10 之间")


class DriveSession:
    """Own a drive connection for the lifetime of the desktop application.

    The GUI executes all session calls through one background worker, ensuring
    serial frames from polling and command actions cannot interleave.
    """

    def __init__(self) -> None:
        self._drive: AimDrive | None = None
        self._settings: ConnectionSettings | None = None

    @property
    def connected(self) -> bool:
        return self._drive is not None

    @property
    def settings(self) -> ConnectionSettings | None:
        return self._settings

    def connect(self, settings: ConnectionSettings) -> AimDrive:
        """Open a new serial connection, closing the previous one if present."""
        settings.validate()
        self.disconnect(disable_output=True)
        self._drive = AimDrive.connect(
            settings.port.strip(),
            address=settings.address,
            baudrate=settings.baudrate,
            timeout_s=settings.timeout_s,
            retries=settings.retries,
        )
        self._settings = settings
        return self._drive

    def attach(self, drive: AimDrive, settings: ConnectionSettings | None = None) -> None:
        """Attach a drive for tests or for an already-open custom transport."""
        self.disconnect(disable_output=False)
        self._drive = drive
        self._settings = settings

    def disconnect(self, *, disable_output: bool = True) -> None:
        """Safely release the current connection.

        Output disable is attempted before closing, but closing still proceeds
        if the bus no longer responds.
        """
        drive, self._drive = self._drive, None
        self._settings = None
        if drive is None:
            return
        try:
            if disable_output:
                drive.disable_output()
        finally:
            drive.close()

    def require_drive(self) -> AimDrive:
        """Return the active drive or raise a user-facing connection error."""
        if self._drive is None:
            raise AimError("尚未连接电机，请先在“连接与使能”页面连接串口")
        return self._drive

    def call(self, operation: Callable[[AimDrive], T]) -> T:
        """Run one operation against the active drive."""
        return operation(self.require_drive())
