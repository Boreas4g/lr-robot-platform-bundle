# Hardware Commissioning Checklist

This procedure reduces risk during the first live test. It does not replace a
machine risk assessment, safety controller, guard interlock, or physical E-stop.

1. Confirm the drive model and supply voltage match the manual. Verify motor,
   power, protective earth, and mechanical assembly with power removed.
2. Keep the output shaft unloaded or disconnected from the production load.
   Ensure the accessible travel is safe for at least one full shaft turn.
3. Wire RS485 A to A and B to B. The manual's communication connector also
   requires its isolated 5V reference (`485_5V`) and common ground (`COM`) as
   appropriate for the controller's isolated interface.
4. Set the host port to 19200 baud, 8N1. Use the actual configured Modbus
   address, normally 1 for initial testing.
5. Start with feedback only:

   ```python
   with AimDrive.connect("COM3", address=1) as drive:
       print(drive.read_status())
   ```

6. Check `alarm` is zero. Resolve wiring, battery, overcurrent, stall, or
   overvoltage causes before issuing a move. The SDK intentionally does not
   pretend to reset alarms because the manual gives no reset register.
7. Explicitly enable Modbus control and servo output, then command a very
   small relative move such as 100 pulses. Verify physical direction and
   `read_absolute_position()`.
8. Configure the actual speed, acceleration, gear ratio, and limits. Persist
   settings only after validation via `save_parameters()`.
9. Validate the required homing method at low energy before production use.
   Mechanical homing deliberately stalls the motor; use a safe fixture.
10. For multi-axis broadcast control, validate every individual drive first,
    then verify addresses are consecutive `1..N` and test the group with low
    speeds/accelerations.
