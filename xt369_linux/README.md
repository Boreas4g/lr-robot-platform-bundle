# XT369 Linux 接口

Python 3.10+，Linux USB HID 电压/电流采集接口，运行时只依赖 Python 标准库。输入是已连接且供电正常的 XT369 硬件；输出为 `Measurement` 对象，或与仪表采集显示相同的文本行。默认自动查询，无需调用方构造报文。

安装后调用：

```python
from xt369 import XT369Reader, format_measurement

with XT369Reader() as meter:
    for measurement in meter:
        print(format_measurement(measurement))
```

跨语言调用：

```bash
python3 -m xt369 list
python3 -m xt369 read
python3 -m xt369 read --format json
```

安装：`python3 -m pip install .`，或将构建好的 wheel 安装到调用程序使用的 Python 环境。安装后也可运行 `xt369 read`。在源目录中无需安装即可导入和运行。

完整约定、参数、错误处理、多设备选择、权限和集成示例见 [接口说明](docs/API.md)。默认文本输出格式如下（格式示例）：

```text
2026-10-16T08:23:34.342+00:00  电压=23.987572 V  电流=0.016611 A  计算功率=0.398458 W
```

支持范围：已在 XT369P V2.0.3 验证的 USB HID 查询/测量协议。不绑定用户名、目录、序列号或 hidraw 编号。不同协议、蓝牙 SPP 和 Windows/macOS 不在本接口支持范围内。
