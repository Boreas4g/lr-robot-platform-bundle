# XT369 Linux 接口说明（v1.0.0）

## 用途与运行要求

输入为通过 USB 数据线连接到 Linux、且测量侧正常供电的 XT369。接口自动按周期发起查询，返回收到的电压、电流和由 V×A 计算的功率。运行环境为 Python 3.10+，仅依赖标准库，不需要串口波特率、第三方 HID 库或 Windows 上位机。

支持已在 XT369P V2.0.3 上验证的协议：USB VID/PID `0483:5750`、名称包含 XT369、厂商自定义 Usage Page、输入/输出均为 64 字节且无 Report ID 的 HID 报告结构，输入帧头 `AA 40 62 05`。同系列设备可按上述身份和报告结构进行连接，仍需使用相同的查询及测量协议；未验证的新型号或不同描述符/协议不会自动猜测适配。字段仅检查帧长与帧头，不声称校验了未知的 CRC。电压/电流保留仪表原值，不自动校准或扣除空载偏移。

硬件测量线路为“直流电源 → XT369 测量输入 → 测量输出 → 用电设备”，电脑通过独立 USB 数据口通信。接口不能判断物理接线或供电是否正确。

## 安装和权限

在项目根目录执行 `python3 -m pip install .`，或者安装交付目录 `dist/` 中的 `.whl` 包。无网络安装 wheel 可使用 `python3 -m pip install --no-deps /path/to/xt369_linux-1.0.0-py3-none-any.whl`。调用者使用安装了该包的 Python 环境；源目录内也可直接运行。

Linux 用户需对所选 `/dev/hidrawX` 有读写权限（读取测量需要先发送查询）。权限不足会抛 `PermissionError`。可由部署方配置 udev，为匹配的 VID/PID、产品名和可选序列号授权；桌面可用 `TAG+="uaccess"`，服务进程应使用专用组和 `MODE="0660"`。实际产品名/序列号通过 `python3 -m xt369 list` 查询，不建议给所有 HID 设备开放权限。

源目录内临时以管理员运行可用 `sudo /usr/bin/python3 -m xt369 read`。安装到虚拟环境时，应使用该环境的解释器，而不是假设系统 Python 也安装了接口。

## Python 主接口

```python
XT369Reader(path=None, *, serial=None, poll_interval=1.0, report_timeout=1.5)
```

| 参数 | 类型 / 默认值 | 说明 |
|---|---|---|
| `path` | `str \| None` / `None` | 可选 `/dev/hidrawX` 路径。默认自动识别。 |
| `serial` | `str \| None` / `None` | 可选 USB 序列号，用于多设备选择。与 path 同时给出时必须都匹配。 |
| `poll_interval` | `float` / `1.0` | 查询间隔，必须有限且 ≥1 秒。可降低查询频率，不保证更高刷新率。 |
| `report_timeout` | `float` / `1.5` | 单次 read 默认等待时间，必须为正有限数。查询间隔调大时建议同步调大此值。 |

默认自动选择名称匹配的单台设备；发现多台/多个匹配接口时抛 `AmbiguousDevice`，不任意选择。可分别创建 Reader，以序列号或接口路径区分。名称缺失、只有通用 VID/PID 的设备不允许主动采集。接口不硬编码本机序列号、用户目录或 USB 端口。描述符按报告结构检查，不要求与某台仪表的描述符逐字节一致；结构相同不代表未知固件的业务协议必然相同。

| 方法 / 属性 | 返回 | 行为 |
|---|---|---|
| `connect()` | `DeviceInfo` | 选择设备并打开，启动查询调度；首次查询在 read 时发送。重复调用会关闭旧连接后重新打开。 |
| `read(timeout=None)` | `Measurement \| None` | 等待一条新收到的有效测量；超时返回 None。timeout 必须为正有限数。 |
| `device_info` | `DeviceInfo \| None` | 当前或最近一次成功连接的元信息；关闭后可用于查阅，不代表设备仍在线。 |
| `close()` | `None` | 释放设备句柄，可重复调用。关闭后 read 抛 RuntimeError。 |
| `with XT369Reader() as meter` | Reader | 进入时连接，离开时关闭，包括异常退出。 |
| `for measurement in meter` | `Measurement` 迭代流 | 连续读取；超时抛 TimeoutError，断线/协议错误向调用方传播。break 后退出 with 释放句柄。 |
| `format_measurement(m)` | `str` | 输出规定文本，不带换行。 |

read 是阻塞的，内部自动调度固定查询；每个实例应由单一线程顺序调用。不同设备使用不同实例。不启动后台线程、不安装服务、不写日志、不打印内容；关闭、重试和输出去向由调用者控制。未知帧抛 ProtocolError，不以缓存或零值填补。

返回的是新收到的报告，设备内部测量发生的时刻未知；长时间暂停调用时，内核中可能已有待读报告，不保证是最新一次查询的对应回应。需要连续更新时持续 read/迭代。timeout 约束接收等待和循环调度，系统设备打开/写入耗时取决于 Linux 驱动，非硬实时接口。

## 返回数据

`Measurement` 为不可变 dataclass，`to_dict()` 返回可被 `json.dumps` 编码的字典。

| 字段 | 类型 | 含义 |
|---|---|---|
| `received_at` | str | 主机接收时间，UTC ISO 8601，毫秒精度，带 `+00:00`。 |
| `received_monotonic` | float | 主机单调时钟秒数，供同机计算间隔。 |
| `voltage_v` | float | 电压，V。 |
| `current_a` | float | 电流，A。按当前协议无符号值解码，不承诺反向电流支持。 |
| `power_w_calculated` | float | `voltage_v * current_a`，W，非仪表原生功率字段。 |
| `raw_voltage`, `raw_current` | int | 原始整数，分别除以 1,000,000 得到 V/A。 |
| `raw_report_hex` | str | 接收到的原始报告十六进制，便于调用方诊断。 |
| `report_id` | int 或 None | 若输入带报告编号则保留；当前适配设备为 None。 |
| `protocol` | str | `xt369p-aa406205`。 |
| `validation` | str | `header-and-length-only`，表示检查范围。 |

文本格式固定为：`时间戳␠␠电压=六位小数 V␠␠电流=六位小数 A␠␠计算功率=六位小数 W`。六位小数是输出格式，不代表仪表测量精度。

## 调用示例

连续输出与原终端相同的文本：

```python
from xt369 import XT369Reader, format_measurement

with XT369Reader() as meter:
    for measurement in meter:
        print(format_measurement(measurement), flush=True)
```

将结构化数据传给其他模块：

```python
from xt369 import XT369Reader

with XT369Reader(serial="实际设备序列号") as meter:
    result = meter.read(timeout=2.0)
    if result is None:
        raise TimeoutError("XT369 未返回数据")
    payload = result.to_dict()
    # 调用方使用 payload 或 result.voltage_v / result.current_a
```

GUI/异步服务中请把阻塞读取放到专用工作线程；不要在事件循环主线程直接持续 read。需要暂停/退出时等待本次有界读取结束，再由该工作线程 close，避免另一线程正在 read 时关闭句柄。

## 异常与重连

| 异常 | 含义 / 调用方处理 |
|---|---|
| `DeviceNotFound` | 未发现符合选择条件的设备，检查连接后重试 connect。 |
| `AmbiguousDevice` | 多设备或多接口，传 serial/path 缩小范围。 |
| `PermissionError` | 设备权限不足，配置部署用户权限。 |
| `OSError` | USB 断开、读写失败等，关闭后由调用方按退避策略重新 connect。 |
| `ProtocolError` | 收到不支持的测量帧。保留异常并确认协议；不应作为有效读数使用。 |
| `ValueError` | 参数无效或不支持设备描述符，修正配置或新增明确适配。 |
| `RuntimeError` | 未连接或已关闭时 read，先 connect。 |
| `TimeoutError` | 迭代接口等待超时；显式 read 对应情况返回 None。 |

接口不隐藏断线、不无限自动重试。连接成功后会记住 VID/PID、接口和身份；再次 connect 优先按原序列号识别，即便 hidraw 编号改变。无序列号时按原 USB 物理端口识别，换物理端口需新建 Reader。多个设备序列号相同时可能仍需显式接口路径，重连匹配有歧义时会报错。恢复失败不能把上一条读数当成当前值。

## 命令行 / 跨语言进程接口

```bash
python3 -m xt369 list
python3 -m xt369 read
python3 -m xt369 read --serial 实际序列号 --format json
python3 -m xt369 read --device /dev/hidrawX --duration 30
```

`read` 默认主动查询及文本输出，无需 --poll（接受该旧选项作为兼容）。可选 `--timeout`、`--poll-interval` 与 Python 参数含义相同。stdout 只输出测量行，json 模式为一行一个 JSON 对象，立即刷新；错误写 stderr。其他语言应分别消费 stdout/stderr 并检查退出状态。单独 list 输出 JSON 候选数组，通用 ID 候选不等于主动模式可用设备。

退出码：0 正常完成；2 设备/权限/配置/协议错误；3 等待超时或有限时长内没有测量；130 用户 Ctrl+C。有限时长结束时若此前已有测量则成功。默认持续运行，收到错误即退出，重启策略由宿主程序负责。旧的 capture、replay、doctor、raw-log 调试入口已移除。

## 模块边界

公共业务入口为 `XT369Reader`、`Measurement`、`format_measurement` 及异常类型。底层 `XT369Device`、`enumerate_devices`、`parse_report` 仍可用于高级集成；底层 Device 不负责定时查询，普通业务使用 Reader 即可。

v1 的文本字段和单位保持固定；建议跨语言解析 JSON 而非中文文本，允许未来字典新增字段。首次调用其他固件应确认相同协议和描述符；不通过放宽校验来承诺适配所有名为 XT369 的硬件。单个设备应由一个采集进程管理，再将数据分发给多个消费者。
