"""Exceptions raised by the YZ-AIM SDK."""


class AimError(Exception):
    """Base class for all SDK errors."""


class TransportError(AimError):
    """Serial transport could not send or receive a complete frame."""


class ResponseTimeout(TransportError):
    """The drive did not reply before the configured timeout."""


class ProtocolError(AimError):
    """A reply was malformed or did not match the request."""


class CrcError(ProtocolError):
    """A Modbus RTU frame has an invalid CRC."""


class ModbusException(ProtocolError):
    """The drive returned a Modbus exception response."""

    def __init__(self, function: int, code: int):
        self.function = function
        self.code = code
        super().__init__(f"Modbus exception 0x{code:02X} for function 0x{function:02X}")


class DriveAlarmError(AimError):
    """Motion was blocked because the drive reports an alarm."""


class SafetyInterlockError(AimError):
    """A dangerous manual-specific operation needs explicit acknowledgement."""


class UnsupportedOperationError(AimError):
    """The manual names a capability but does not define its wire protocol."""
