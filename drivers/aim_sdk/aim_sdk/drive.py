"""High-level control API for one YZ-AIM servo drive."""

from __future__ import annotations

from contextlib import AbstractContextManager
import time
from typing import Iterator

from .exceptions import DriveAlarmError, ProtocolError, SafetyInterlockError, UnsupportedOperationError
from .modbus import ModbusRtuClient
from .models import (
    AlarmCode,
    BaudRate,
    DriveStatus,
    MotionConfiguration,
    SpecialFunction,
    join_i32,
    signed_i16,
    split_i32,
    unsigned_i16,
)
from .registers import (
    DEFAULT_BAUDRATE,
    ENCODER_PULSES_PER_REVOLUTION,
    MODBUS_WRITE_MULTIPLE,
    POSITION_TOLERANCE_PULSES,
    VENDOR_CHANGE_ADDRESS,
    VENDOR_INCREMENTAL_MOVE,
    VENDOR_INCREMENTAL_MOVE_RESPONSE,
    Register,
)
from .transport import FrameTransport, SerialTransport


class AimDrive(AbstractContextManager["AimDrive"]):
    """Control one addressable YZ-AIM drive on an RS485 Modbus RTU bus.

    The SDK deliberately does not turn on the output while connecting. Call
    :meth:`enable_modbus` and :meth:`enable_output` after verifying the
    mechanics and software limits.
    """

    pulses_per_revolution = ENCODER_PULSES_PER_REVOLUTION
    position_tolerance_pulses = POSITION_TOLERANCE_PULSES

    def __init__(self, client: ModbusRtuClient, address: int = 1) -> None:
        if not 1 <= address <= 247:
            raise ValueError("drive address must be in 1..247; address 0 is broadcast only")
        self.client = client
        self.address = address

    @classmethod
    def connect(
        cls,
        port: str,
        *,
        address: int = 1,
        baudrate: int = DEFAULT_BAUDRATE,
        timeout_s: float = 0.2,
        retries: int = 1,
    ) -> "AimDrive":
        """Open a physical 8N1 serial port and return a drive handle."""
        transport = SerialTransport(port, baudrate, timeout_s=timeout_s)
        return cls(ModbusRtuClient(transport, timeout_s=timeout_s, retries=retries), address)

    @classmethod
    def from_transport(
        cls,
        transport: FrameTransport,
        *,
        address: int = 1,
        timeout_s: float = 0.2,
        retries: int = 1,
    ) -> "AimDrive":
        """Create a drive from a physical, test, or simulated transport."""
        return cls(ModbusRtuClient(transport, timeout_s=timeout_s, retries=retries), address)

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying transport. This does not disable motor output."""
        self.client.transport.close()

    # Generic documented register access ---------------------------------
    def read_register(self, register: Register | int) -> int:
        """Read one 16-bit holding register without unit conversion."""
        return self.read_registers(register, 1)[0]

    def read_registers(self, start: Register | int, count: int) -> list[int]:
        """Read consecutive 16-bit holding registers without unit conversion."""
        return self.client.read_holding(self.address, int(start), count)

    def write_register(self, register: Register | int, value: int) -> None:
        """Write one 16-bit holding register without unit conversion."""
        self.client.write_single(self.address, int(register), value)

    def write_registers(self, start: Register | int, values: list[int] | tuple[int, ...]) -> None:
        """Write consecutive holding registers without unit conversion."""
        self.client.write_multiple(self.address, int(start), values)

    # Connection and output ------------------------------------------------
    def enable_modbus(self) -> None:
        """Enable communication control (register 0x00 = 1).

        When enabled, external pulse input is inactive as stated in the
        manual. This call does not enable the motor output.
        """
        self.write_register(Register.MODBUS_ENABLE, 1)

    def disable_modbus(self) -> None:
        """Disable Modbus control (register 0x00 = 0)."""
        self.write_register(Register.MODBUS_ENABLE, 0)

    def enable_output(self) -> None:
        """Enable servo output (register 0x01 = 1)."""
        self.write_register(Register.OUTPUT_ENABLE, 1)

    def disable_output(self) -> None:
        """Disable servo output (register 0x01 = 0)."""
        self.write_register(Register.OUTPUT_ENABLE, 0)

    def is_modbus_enabled(self) -> bool:
        return bool(self.read_register(Register.MODBUS_ENABLE))

    def is_output_enabled(self) -> bool:
        return bool(self.read_register(Register.OUTPUT_ENABLE))

    # Motion configuration -------------------------------------------------
    def set_target_speed(self, rpm: int) -> None:
        """Set target speed or the position-mode maximum speed, in RPM."""
        if not 0 <= rpm <= 3000:
            raise ValueError("target speed must be in 0..3000 RPM")
        self.write_register(Register.TARGET_SPEED, rpm)

    def set_acceleration(self, rpm_per_second: int) -> None:
        """Set acceleration in RPM/s (the manual permits 0..60098)."""
        if not 0 <= rpm_per_second <= 60098:
            raise ValueError("acceleration must be in 0..60098 RPM/s")
        self.write_register(Register.ACCELERATION, rpm_per_second)

    def set_weak_field_angle_raw(self, value: int) -> None:
        """Set register 0x04 exactly; its documented units are inconsistent."""
        if not 0 <= value <= 306:
            raise ValueError("weak-field raw value must be in 0..306")
        self.write_register(Register.WEAK_FIELD_ANGLE, value)

    def set_speed_kp(self, value: float) -> None:
        """Set the documented speed-loop gain (raw value represents 0.0..10.0)."""
        raw = round(value * 1000)
        if not 0 <= raw <= 10000:
            raise ValueError("speed KP must be in 0.0..10.0")
        self.write_register(Register.SPEED_KP, raw)

    def set_speed_integral_ms(self, milliseconds: int) -> None:
        """Set speed-loop integral time in milliseconds (2..2000)."""
        if not 2 <= milliseconds <= 2000:
            raise ValueError("speed integral time must be in 2..2000 ms")
        self.write_register(Register.SPEED_INTEGRAL_MS, milliseconds)

    def set_position_kp(self, value: int) -> None:
        """Set position-loop proportional gain (60..30000)."""
        if not 60 <= value <= 30000:
            raise ValueError("position KP must be in 60..30000")
        self.write_register(Register.POSITION_KP, value)

    def set_speed_feedforward(self, volts_per_krpm: float) -> None:
        """Set speed feedforward in V/KRPM, represented as raw value / 327."""
        raw = round(volts_per_krpm * 327)
        if not 0 <= raw <= 0xFFFF:
            raise ValueError("speed feedforward is outside the representable range")
        self.write_register(Register.SPEED_FEEDFORWARD, raw)

    def set_direction_polarity(self, clockwise_when_dir_active: bool) -> None:
        """Configure whether active external DIR denotes clockwise rotation."""
        self.write_register(Register.DIRECTION_POLARITY, int(clockwise_when_dir_active))

    def set_electronic_gear(self, numerator: int, denominator: int) -> None:
        """Set the 16-bit electronic gear ratio used by external pulse control."""
        if not 0 <= numerator <= 65535:
            raise ValueError("electronic gear numerator must be in 0..65535")
        if not 1 <= denominator <= 65535:
            raise ValueError("electronic gear denominator must be in 1..65535")
        self.write_registers(Register.ELECTRONIC_GEAR_NUMERATOR, [numerator, denominator])

    def configure_motion(
        self,
        *,
        max_speed_rpm: int,
        acceleration_rpm_s: int,
        position_kp: int | None = None,
        speed_kp: float | None = None,
        speed_integral_ms: int | None = None,
        speed_feedforward_v_per_krpm: float | None = None,
    ) -> MotionConfiguration:
        """Apply documented motion settings and return the applied configuration."""
        self.set_target_speed(max_speed_rpm)
        self.set_acceleration(acceleration_rpm_s)
        if position_kp is not None:
            self.set_position_kp(position_kp)
        if speed_kp is not None:
            self.set_speed_kp(speed_kp)
        if speed_integral_ms is not None:
            self.set_speed_integral_ms(speed_integral_ms)
        if speed_feedforward_v_per_krpm is not None:
            self.set_speed_feedforward(speed_feedforward_v_per_krpm)
        return MotionConfiguration(
            max_speed_rpm=max_speed_rpm,
            acceleration_rpm_s=acceleration_rpm_s,
            position_kp=position_kp,
            speed_kp=speed_kp,
            speed_integral_ms=speed_integral_ms,
            speed_feedforward_v_per_krpm=speed_feedforward_v_per_krpm,
        )

    # Position control -----------------------------------------------------
    def move_relative(self, pulses: int, *, check_ready: bool = True) -> None:
        """Move by a signed pulse count via the manual's 0x10/0x0C example.

        The register table calls 0x0C and 0x0D read-only, but page 15 of the
        manual explicitly writes them using function 0x10. This method follows
        that worked example.
        """
        if check_ready:
            self.assert_motion_ready()
        low, high = split_i32(pulses)
        self.write_registers(Register.TARGET_POSITION_LOW, [low, high])

    def move_relative_vendor(self, pulses: int, *, check_ready: bool = True) -> None:
        """Move by a signed pulse count with vendor function 0x78.

        Unlike register writes, the manual specifies this command's data as a
        conventional big-endian signed 32-bit integer and its reply function
        as `0x7B`.
        """
        if check_ready:
            self.assert_motion_ready()
        if not -(1 << 31) <= pulses <= (1 << 31) - 1:
            raise ValueError("position must fit in a signed 32-bit integer")
        reply = self.client.request(
            self.address,
            VENDOR_INCREMENTAL_MOVE,
            (pulses & 0xFFFF_FFFF).to_bytes(4, "big"),
            response_function=VENDOR_INCREMENTAL_MOVE_RESPONSE,
        )
        if len(reply) != 4:
            raise ProtocolError("vendor incremental-move response must contain four data bytes")

    def move_absolute(
        self,
        pulses: int,
        *,
        wait: bool = False,
        timeout_s: float = 10.0,
        tolerance_pulses: int = POSITION_TOLERANCE_PULSES,
        allow_zero_clear: bool = False,
        check_ready: bool = True,
    ) -> None:
        """Move to an absolute position established by zeroing or homing.

        With electronic gear numerator zero, the manual assigns a special
        clear-position meaning to target zero. To prevent accidental clearing,
        use :meth:`clear_absolute_position` instead, or explicitly pass
        `allow_zero_clear=True`.
        """
        if pulses == 0 and not allow_zero_clear and self.electronic_gear_numerator() == 0:
            raise SafetyInterlockError(
                "absolute target zero clears position in communication mode; use clear_absolute_position()"
            )
        if check_ready:
            self.assert_motion_ready()
        low, high = split_i32(pulses)
        self.write_registers(Register.ABSOLUTE_POSITION_LOW, [low, high])
        if wait:
            self.wait_until_at_position(pulses, timeout_s=timeout_s, tolerance_pulses=tolerance_pulses)

    def move_to_origin(self, *, wait: bool = False, timeout_s: float = 10.0) -> None:
        """Move to the manual's communication-mode origin command (position 1)."""
        if self.electronic_gear_numerator() != 0:
            raise SafetyInterlockError(
                "the manual's position-1 origin command requires electronic gear numerator = 0"
            )
        self.move_absolute(1, wait=wait, timeout_s=timeout_s)

    def read_absolute_position(self) -> int:
        """Return the signed 32-bit absolute position in encoder pulses."""
        low, high = self.read_registers(Register.ABSOLUTE_POSITION_LOW, 2)
        return join_i32(low, high)

    def read_target_position(self) -> int:
        """Read the signed 32-bit target/relative command register pair."""
        low, high = self.read_registers(Register.TARGET_POSITION_LOW, 2)
        return join_i32(low, high)

    def clear_absolute_position(self, *, acknowledge: bool = False) -> None:
        """Clear the absolute position using the manual's special sequence.

        This only works when the electronic gear numerator is zero. It changes
        the coordinate system and therefore requires `acknowledge=True`.
        """
        if not acknowledge:
            raise SafetyInterlockError("clearing position needs acknowledge=True")
        if self.electronic_gear_numerator() != 0:
            raise SafetyInterlockError(
                "the manual requires electronic gear numerator = 0 before clearing absolute position"
            )
        self.write_registers(Register.ABSOLUTE_POSITION_LOW, [0, 0])

    def emergency_stop(self) -> None:
        """Execute the manual's software emergency-stop sequence.

        It writes electronic gear numerator zero, then relative target zero.
        This stops queued communication-mode pulses but is not a replacement
        for an independent, safety-rated physical E-stop.
        """
        self.write_register(Register.ELECTRONIC_GEAR_NUMERATOR, 0)
        self.write_registers(Register.TARGET_POSITION_LOW, [0, 0])

    def wait_until_at_position(
        self,
        position: int,
        *,
        timeout_s: float = 10.0,
        tolerance_pulses: int = POSITION_TOLERANCE_PULSES,
        poll_interval_s: float = 0.02,
    ) -> int:
        """Poll absolute feedback until it is within the requested tolerance."""
        if tolerance_pulses < 0:
            raise ValueError("tolerance must be non-negative")
        deadline = time.monotonic() + timeout_s
        while True:
            actual = self.read_absolute_position()
            if abs(actual - position) <= tolerance_pulses:
                return actual
            if time.monotonic() >= deadline:
                raise TimeoutError(f"position did not reach {position}; latest feedback was {actual}")
            time.sleep(poll_interval_s)

    # Status and alarms ----------------------------------------------------
    def read_alarm(self) -> AlarmCode | int:
        """Read the raw documented alarm code as an enum when known."""
        return AlarmCode.from_register(self.read_register(Register.ALARM_CODE))

    def read_status(self) -> DriveStatus:
        """Read all documented live feedback and control state in one block."""
        values = self.read_registers(Register.MODBUS_ENABLE, 0x1A)
        raw = {Register(index): value for index, value in enumerate(values)}
        low = raw[Register.ABSOLUTE_POSITION_LOW]
        high = raw[Register.ABSOLUTE_POSITION_HIGH]
        return DriveStatus(
            absolute_position=join_i32(low, high),
            speed_rpm=signed_i16(raw[Register.CURRENT_SPEED]) / 10,
            current_a=raw[Register.SYSTEM_CURRENT] / 2000,
            voltage_v=raw[Register.SYSTEM_VOLTAGE] / 327,
            temperature_c=raw[Register.SYSTEM_TEMPERATURE],
            pwm_percent=signed_i16(raw[Register.SYSTEM_PWM]) / 327.67,
            alarm=AlarmCode.from_register(raw[Register.ALARM_CODE]),
            output_enabled=bool(raw[Register.OUTPUT_ENABLE]),
            modbus_enabled=bool(raw[Register.MODBUS_ENABLE]),
        )

    def assert_motion_ready(self) -> None:
        """Refuse a command if Modbus/output are disabled or an alarm is active."""
        status = self.read_status()
        if not status.modbus_enabled:
            raise SafetyInterlockError("Modbus control is disabled; call enable_modbus()")
        if not status.output_enabled:
            raise SafetyInterlockError("servo output is disabled; call enable_output()")
        if status.alarm != AlarmCode.NONE:
            raise DriveAlarmError(f"drive alarm is active: {status.alarm!r}")

    def monitor(self, *, interval_s: float = 0.1) -> Iterator[DriveStatus]:
        """Yield periodic status snapshots until the caller stops iteration."""
        if interval_s <= 0:
            raise ValueError("monitor interval must be positive")
        while True:
            yield self.read_status()
            time.sleep(interval_s)

    # Homing and special operating modes ----------------------------------
    def set_special_function(self, value: SpecialFunction | int, *, save: bool = False) -> None:
        """Set register 0x19 and optionally persist it across a power cycle."""
        raw = int(value)
        if not 0 <= raw <= 32768:
            raise ValueError("special-function value must be in the manual's 0..32768 range")
        self.write_register(Register.SPECIAL_FUNCTION, raw)
        if save:
            self.save_parameters()

    def home_mechanical(self, *, to_encoder_zero: bool = False, save: bool = False) -> None:
        """Start documented mechanical stall homing, optionally to encoder Z."""
        function = (
            SpecialFunction.MECHANICAL_HOME_TO_ENCODER_ZERO
            if to_encoder_zero
            else SpecialFunction.MECHANICAL_HOME_PLUS_36_DEGREES
        )
        self.set_special_function(function, save=save)

    def home_switch(self, *, save: bool = False) -> None:
        """Start homing using an external home switch wired to EN input."""
        self.set_special_function(SpecialFunction.HOME_SWITCH_ON_ENABLE_INPUT, save=save)

    def set_zout_simulated_home_mode(self, *, save: bool = False) -> None:
        """Enable the manual's ZOUT simulated-home mode (requires pulse wiring)."""
        self.set_special_function(SpecialFunction.ZOUT_SIMULATED_HOME, save=save)

    def set_encoder_follow_mode(self, *, save: bool = False) -> None:
        """Enable external encoder-follow mode; pulse inputs become encoder inputs."""
        self.set_special_function(SpecialFunction.ENCODER_FOLLOW, save=save)

    def set_pwm_speed_mode(self, *, save: bool = False) -> None:
        """Enable PWM duty-cycle speed mode (manual: 10-90% = 0-1000 RPM)."""
        self.set_special_function(SpecialFunction.PWM_SPEED, save=save)

    def set_pulse_direction_mode(self, *, save: bool = False) -> None:
        """Enable the default external pulse-plus-direction mode."""
        self.set_special_function(SpecialFunction.PULSE_DIRECTION, save=save)

    def set_powerup_angle(self, encoder_pulses: int, *, save: bool = True) -> None:
        """Configure power-up motion to a single-turn absolute angle.

        The manual accepts 10..32768, corresponding to 0..360 degrees via
        `pulses * 360 / 32768`.
        """
        if not 10 <= encoder_pulses <= ENCODER_PULSES_PER_REVOLUTION:
            raise ValueError("power-up angle must be in 10..32768 encoder pulses")
        self.set_special_function(encoder_pulses, save=save)

    # Persistence and vendor-specific configuration ----------------------
    def save_parameters(self, *, wait: bool = True, timeout_s: float = 2.0) -> None:
        """Request parameter persistence through register 0x14.

        The manual specifies 0 = not saved, 1 = saving, 2 = saved. Some drive
        versions may reply with 1 until the next cycle, so waiting is optional.
        """
        self.write_register(Register.SAVE_PARAMETERS, 1)
        if not wait:
            return
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.read_register(Register.SAVE_PARAMETERS) == 2:
                return
            time.sleep(0.02)
        raise TimeoutError("parameter save did not reach the documented complete state")

    def configure_baud_rate(self, baud_rate: BaudRate | int) -> BaudRate:
        """Write the manual's four-step baud-rate configuration sequence.

        Power-cycle the drive after this call, then set the host serial port to
        the returned baud rate before communicating again. Do not call
        :meth:`save_parameters`; the manual says this setting is internal.
        """
        baud = BaudRate(baud_rate)
        self.enable_modbus()
        self.set_acceleration(baud.manual_acceleration_value)
        self.set_weak_field_angle_raw(129)
        self.write_register(Register.MODBUS_ENABLE, 506)
        return baud

    def set_host_baud_rate(self, baud_rate: BaudRate | int) -> None:
        """Change a SerialTransport's host baud rate after drive power cycling."""
        transport = self.client.transport
        if not isinstance(transport, SerialTransport):
            raise UnsupportedOperationError("host baud-rate change requires SerialTransport")
        transport.baudrate = int(BaudRate(baud_rate))

    def raw_change_address(self, request_data: bytes, *, response_function: int = VENDOR_CHANGE_ADDRESS) -> bytes:
        """Send function 0x7A with caller-supplied data.

        The manual names 0x7A as address modification but provides no payload
        layout, so this method intentionally cannot guess one. Use it only
        with a frame definition supplied by the manufacturer.
        """
        if not request_data:
            raise UnsupportedOperationError(
                "the supplied manual omits the 0x7A address-change payload; provide manufacturer frame bytes"
            )
        return self.client.request(
            self.address,
            VENDOR_CHANGE_ADDRESS,
            request_data,
            response_function=response_function,
        )

    def electronic_gear_numerator(self) -> int:
        """Read register 0x0A, including its documented communication-mode zero."""
        return self.read_register(Register.ELECTRONIC_GEAR_NUMERATOR)

    def electronic_gear_denominator(self) -> int:
        """Read register 0x0B."""
        return self.read_register(Register.ELECTRONIC_GEAR_DENOMINATOR)

    def set_stationary_max_output_raw(self, value: int) -> None:
        """Set register 0x18 exactly; its ones digit encodes stall timing."""
        if not 0 <= value <= 609:
            raise ValueError("stationary maximum output raw value must be in 0..609")
        self.write_register(Register.STATIONARY_MAX_OUTPUT, value)

    def read_stationary_max_output_raw(self) -> int:
        """Read register 0x18 without interpreting its packed stall-timer digit."""
        return self.read_register(Register.STATIONARY_MAX_OUTPUT)

    def set_current_speed_raw(self, signed_tenth_rpm: int) -> None:
        """Write raw signed speed only if a firmware mode explicitly permits it.

        The manual marks 0x10 as read-only. Prefer :meth:`set_target_speed`.
        This method is intentionally absent to prevent a misleading API.
        """
        signed_tenth_rpm = None
        raise UnsupportedOperationError("current-speed register 0x10 is read-only in the manual")
