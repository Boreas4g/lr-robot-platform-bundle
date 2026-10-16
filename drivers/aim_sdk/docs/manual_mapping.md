# YZ-AIM v2.56 Manual Mapping

This SDK is derived from the supplied `YZ-AIM_v2.56` manual. Register names
below retain the manual's terminology. All addresses are zero-based Modbus
holding-register addresses.

## Communication

- Transport: isolated RS485, Modbus RTU.
- Factory serial format: 19200 baud, 8 data bits, no parity, one stop bit.
- Documented standard functions: `0x03` read holding registers, `0x06` write
  one register, `0x10` write registers.
- Documented vendor functions: `0x78` relative 32-bit pulse motion, response
  `0x7B`; `0x7A` address modification (payload absent from the manual).

`AimDrive` sends standard RTU CRC-16 in Modbus wire order: low CRC byte first.

## Register API

| Address | Manual name | SDK interface | Scaling / notes |
| --- | --- | --- | --- |
| `0x00` | Modbus enable | `enable_modbus`, `disable_modbus` | `0` / `1`; Modbus enables communication control and disables external pulse input. |
| `0x01` | Driver output enable | `enable_output`, `disable_output` | `0` / `1`. |
| `0x02` | Motor target speed | `set_target_speed` | RPM; max speed in position mode. |
| `0x03` | Motor acceleration | `set_acceleration` | RPM/s; `60000+` has special feedforward semantics documented by the vendor. |
| `0x04` | Weak-field angle | `set_weak_field_angle_raw` | The manual gives inconsistent units; exposed raw. Used as `129` in baud configuration. |
| `0x05` | Speed-loop proportional | `set_speed_kp` | raw / 1000, range 0.0 to 10.0. Low digit also affects pulse input polarity. |
| `0x06` | Speed-loop integral time | `set_speed_integral_ms` | milliseconds, 2 to 2000. |
| `0x07` | Position-loop proportional | `set_position_kp` | range 60 to 30000. Low digit also affects alarm-output polarity. |
| `0x08` | Speed feedforward | `set_speed_feedforward` | raw / 327 V/KRPM. |
| `0x09` | DIR polarity | `set_direction_polarity` | `0` / `1`. |
| `0x0A` | Electronic gear numerator | `set_electronic_gear` | `0` carries special communication-mode meanings. |
| `0x0B` | Electronic gear denominator | `set_electronic_gear` | 1 to 65535. |
| `0x0C-0x0D` | Target position | `move_relative`, `read_target_position` | signed 32-bit low word then high word. Table says read-only; page-15 example writes them with `0x10`. |
| `0x0E` | Alarm code | `read_alarm`, `read_status` | Known codes: `0x10` battery, `0x12` overcurrent, `0x14` stall, `0x15` overvoltage. |
| `0x0F` | System current | `read_status` | raw / 2000 A. |
| `0x10` | Current speed | `read_status` | signed raw / 10 RPM. |
| `0x11` | System voltage | `read_status` | raw / 327 V. |
| `0x12` | System temperature | `read_status` | degrees Celsius. |
| `0x13` | Output PWM | `read_status` | signed raw, approximately percentage = raw / 327.67. |
| `0x14` | Save flag | `save_parameters` | write 1; read 2 when completed. |
| `0x15` | Device address | `read_register(Register.DEVICE_ADDRESS)` | read-only in the table. |
| `0x16-0x17` | Absolute position | `move_absolute`, `read_absolute_position` | signed 32-bit low word then high word. |
| `0x18` | Stationary max output | `set_stationary_max_output_raw` | packed vendor field: tens/hundreds control output, ones digit stall time. |
| `0x19` | Special function | homing/mode helpers | See mode table below. |

## Position conventions and coordinate safety

All high-level position arguments are encoder pulses. A shaft turn is 32768
pulses. Positive direction follows the configured drive polarity.

The manual's position examples transfer a 32-bit value as a low 16-bit
register, then a high 16-bit register. `aim_sdk` follows that ordering and
handles two's-complement negative positions.

After powering up, clearing absolute position, or completing a homing method,
the vendor defines that reference as coordinate zero. Page 15 says that when
the electronic gear numerator is zero, writing absolute position zero clears
the coordinate system; therefore `move_absolute(0)` is blocked by default.
Use `clear_absolute_position(acknowledge=True)` only after you have evaluated
the mechanical consequence. The manual's move-to-origin example sends
absolute position `1`, not zero; use `move_to_origin()`.

The manual recommends comparing feedback with a `+/-2` pulse tolerance before
starting the next action. `move_absolute(..., wait=True)` uses that default.

## Special function values (`0x19`)

| Value | SDK method | Meaning |
| --- | --- | --- |
| `0` | `set_pulse_direction_mode` | Pulse plus direction (default). |
| `1` | `home_mechanical()` | Reverse to mechanical stall then advance 36 degrees. |
| `2` | `set_encoder_follow_mode` | Encoder-follow mode using pulse inputs. |
| `3` | `set_pwm_speed_mode` | 10% to 90% input duty corresponds to 0 to 1000 RPM. |
| `4` | `home_mechanical(to_encoder_zero=True)` | Mechanical stall then advance to encoder Z. |
| `5` | `set_zout_simulated_home_mode` | ZOUT assisted simulated homing; requires the manual's pulse wiring. |
| `8` | `home_switch()` | Home switch on EN input. |
| `10-32768` | `set_powerup_angle` | On startup, turn to the given single-turn absolute angle; degrees = value * 360 / 32768. |

These operations can be persisted with `save=True`. Test them unloaded and
with physical travel limits; the mechanical homing procedure intentionally
commands a stall.

## Motion commands

```python
# Relative movement by a signed pulse count, using page-15 0x10 example.
drive.move_relative(+32768)

# Alternative documented vendor command, function 0x78.
drive.move_relative_vendor(-32768)

# Absolute target in the active coordinate system.
drive.move_absolute(65536, wait=True)

# Read feedback through 0x03 starting at 0x16, two registers.
position = drive.read_absolute_position()
```

For simultaneous motion, all drives must share an RS485 transport and use
addresses 1 through N without gaps. `AimDriveGroup.move_absolute_sync()` sends
the documented address-0 `0x10` broadcast with an 8-byte record per axis:
32-bit position, 16-bit speed, then 16-bit acceleration. Broadcast commands
have no reply, so check alarms and output state before sending them.

## Baud-rate configuration

`configure_baud_rate()` uses the manual's four-frame sequence:

1. Modbus enable = 1
2. Acceleration = `800` (9600), `801` (19200), `802` (38400), or `803` (115200)
3. Weak-field-angle raw = 129
4. Modbus enable = 506

Power-cycle the drive after configuration, then call `set_host_baud_rate()` on
a physical serial transport. The manual specifically says not to save this
sequence using register `0x14`.

## Deliberate limitations

- The manual labels function `0x7A` “change device address,” but it does not
  give a data layout, example frame, or response frame. `raw_change_address()`
  requires manufacturer-provided request bytes instead of inventing a command.
- The manual lists no alarm-clear/reset command. The SDK reports alarms and
  blocks default motion commands; recovery must use the vendor-approved power
  or wiring procedure.
- RS485 has no safety integrity. `emergency_stop()` is the vendor's
  communication-mode stop sequence, not an E-stop. Use independently wired,
  safety-rated hardware for hazardous machines.
