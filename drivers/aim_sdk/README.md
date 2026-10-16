# aim_sdk

`aim_sdk` 是用于控制 YZ-AIM 一体化伺服电机的 Python SDK，基于产品手册
`YZ-AIM_v2.56` 中定义的隔离 RS485 / Modbus RTU 通讯协议实现。

## 功能范围

SDK 覆盖手册中给出明确通讯格式的功能：

- Modbus 寄存器读写、CRC 校验、超时和重试处理。
- 驱动器和 Modbus 使能、运行参数设置与参数保存。
- 相对定位、绝对定位、当前位置读取、到位等待与软件急停。
- 电流、转速、电压、温度、PWM、使能状态和报警代码读取。
- 自动找机械原点、编码器零点、原点开关、编码器跟随、PWM 调速和脉冲方向模式。
- 多轴 RS485 广播同步绝对定位。
- 波特率设置流程和无硬件仿真器。

手册将功能码 `0x7A` 标注为“修改设备地址”，但未给出请求/应答帧格式；SDK 不会猜测
该命令，只提供需要厂家帧定义的 `raw_change_address()` 接口。手册也没有提供软件清除
报警的指令，因此 SDK 不会虚构报警复位功能。

## 安装

在项目目录执行：

```bash
python -m pip install -e .
```

也可以安装开发依赖以运行测试：

```bash
python -m pip install -e ".[dev]"
```

物理电机通讯需要 `pyserial`，它已在项目依赖中声明。按手册连接 RS485 A/B、隔离
5V 和公共地后，将示例中的 `/dev/lift_port` 替换为实际串口。

## 快速开始

```python
from aim_sdk import AimDrive

with AimDrive.connect("/dev/lift_port", address=1) as motor:
    # 连接后不会自动使能，需由应用明确确认后开启。
    motor.enable_modbus()
    motor.enable_output()

    motor.configure_motion(max_speed_rpm=800, acceleration_rpm_s=5000)
    motor.move_absolute(32_768, wait=True)

    print("当前位置:", motor.read_absolute_position())
    print("实时状态:", motor.read_status())
```

15 位编码器每圈为 `32768` 脉冲，因此上述命令使电机移动到绝对坐标的一圈位置。

## 常用控制示例

```python
# 相对正转一圈；负数代表反向。
motor.move_relative(32_768)

# 以厂商的 0x78 专用功能码执行相对运动。
motor.move_relative_vendor(-32_768)

# 绝对定位，并等待反馈进入 +/-10 脉冲容差。
motor.move_absolute(65_536, wait=True)

# 读取报警与实时反馈。
status = motor.read_status()
print(status.alarm, status.speed_rpm, status.voltage_v)

# 将当前绝对坐标清零；这是改变坐标系的操作，必须显式确认。
motor.clear_absolute_position(acknowledge=True)

# 保存已验证的参数。
motor.save_parameters()
```

## 升降台位置控制

`LiftPlatform` 针对已标定的升降台提供以厘米为单位的绝对定位：绝对脉冲 `1`
对应高度 `54 cm`，每移动 `2.2 cm` 对应 `100000` 脉冲。可控制范围是
`54` 到 `120 cm`（含端点）。目标位置只能是整数脉冲，SDK 使用十进制计算并将
无法整除的结果四舍五入到最近脉冲。

```python
from aim_sdk import AimDrive, LiftPlatform

with AimDrive.connect("/dev/lift_port", address=1) as motor:
    motor.enable_modbus()
    motor.enable_output()
    lift = LiftPlatform(motor)

    # 速度档位：1 = 200 RPM / 400 RPM/s；2 = 400 / 400；3 = 600 / 600。
    target_pulses = lift.move_to_height("80.0", speed=2)
    print(target_pulses, lift.read_height_cm())
```

`move_to_height()` 每次都会先设置对应档位的目标速度和加速度，再发送绝对位置。
默认等待反馈到位（`+/-10` 脉冲），等待超时为 45 秒，覆盖最低速档的全行程移动；
不需要等待时传入 `wait=False`。

## 通讯默认值

- 协议：Modbus RTU。
- 接口：RS485。
- 默认串口参数：`19200, 8N1`。
- 编码器分辨率：单圈 `32768` 脉冲。
- 位置数据：有符号 32 位，低 16 位寄存器在前、高 16 位寄存器在后；每个寄存器遵循
  Modbus 大端字节序。

## 多轴同步控制

多轴同步功能要求各电机位于同一条 RS485 总线，地址连续为 `1` 到 `N`。SDK 会使用
手册定义的地址 `0` 广播和功能码 `0x10`，一次发送每轴的位置、速度和加速度。

```python
from aim_sdk import AimDrive, AimDriveGroup, AxisMove
from aim_sdk.transport import SerialTransport

transport = SerialTransport("/dev/lift_port")
axis_1 = AimDrive.from_transport(transport, address=1)
axis_2 = AimDrive.from_transport(transport, address=2)

for axis in (axis_1, axis_2):
    axis.enable_modbus()
    axis.enable_output()

group = AimDriveGroup([axis_1, axis_2])
group.move_absolute_sync([
    AxisMove(position=32_768, speed_rpm=500, acceleration_rpm_s=3000),
    AxisMove(position=65_536, speed_rpm=700, acceleration_rpm_s=4000),
])
```

广播命令没有应答，SDK 会先检查各轴的报警和使能状态；仍应在低速、低加速度下先完成
机械验证。

## 安全说明

- 连接 SDK 不会自动使能输出，必须明确调用 `enable_modbus()` 和 `enable_output()`。
- 当电子齿轮分子为 `0` 时，手册规定向绝对位置写入 `0` 有清零含义。因此
  `move_absolute(0)` 默认会被拦截；请使用带确认参数的
  `clear_absolute_position(acknowledge=True)`。
- `emergency_stop()` 实现的是手册中的通讯急停流程，不能替代独立的、符合安全等级的
  物理急停回路。
- 自动找机械原点会使电机堵转。请在空载、低能量、行程安全的条件下验证。
- 首次上机前请阅读 [硬件验收清单](docs/hardware_acceptance.md)；完整寄存器和功能映射
  见 [手册映射说明](docs/manual_mapping.md)。

## 示例和测试

- 无硬件运行示例：`python examples/simulated_demo.py`
- 单轴物理电机示例：[examples/single_axis.py](examples/single_axis.py)
- 多轴同步示例：[examples/multi_axis.py](examples/multi_axis.py)
- 执行测试：`python -m unittest discover -s tests -v`

## 桌面控制界面

项目内置中文桌面 GUI，可通过以下任一方式启动：

```bash
python -m aim_sdk.gui
# 或在安装后：
aim-sdk-gui
```

界面包含三个页面：

- **连接与使能**：扫描或输入串口、设置波特率/设备地址/超时，连接后独立启用
  Modbus 控制和伺服输出，并显示连接、报警、位置与转速。
- **RS485 Modbus RTU 通讯控制**：运动参数、绝对/相对定位、状态自动刷新、回零、
  软件急停、位置清零、寄存器读写和带确认机制的原始 Modbus 请求。
- **升降台调试**：按厘米输入 `54` 至 `120` 的目标高度，预览对应的绝对脉冲，
  选择速度档位并执行确认后的升降台绝对定位，同时显示换算后的当前高度。

GUI 的串口访问在后台顺序执行，避免状态轮询和运动命令抢占同一条 RS485 总线。关闭
窗口或点击“断开并失能”时，程序会先尝试失能伺服输出再关闭串口。
