# XT369 USB 电量接入

原接口包位于项目根目录 xt369_linux/，使用其标准库 USB HID 实现，未改动原包。
当前电池参数为用户确认的 24 V、20 Ah；仪表为 ATORCH XT369P V2.0.3，
VID/PID 0483:5750，序列号 949016。

## 测量与计算

接线：电池 → XT369 → 用电设备，USB 接电脑；充电器直接接电池。
协议提供电压、无符号负载电流，不提供 SOC，也不能测量绕过仪表的充电电流。
只发送原包固定测量查询，不发送任何硬件控制指令。

在电池已充满、拔下充电器并人工确认校准后，按以下公式估算纯放电过程：

- 消耗 Ah = Σ((I前+I后)/2 × Δt/3600)。
- SOC = clamp(100 × (20 − 消耗Ah) / 20, 0, 100)。

数字显示到 0.1% 是显示精度，不代表实际准确度；容量老化、温度、初始基准、
自放电及未经过仪表的负载均会影响结果。不用瞬时电压猜测百分比。
重新充电后，旧估算不再适用，需实际充满并断开充电器后再次校准。
本功能不再提供充电状态或手动充电标记，无法自动发现充电行为。

## 界面

只在运行总览“机器人与设备”的“智巡一号”（LR-01）名称后显示小型电池和数字。
图标区间为 0% 空、(0,25]% 一格、(25,50]% 两格、(50,75]% 三格、(75,100]% 四格。
>50% 绿色、(25,50]% 黄色、≤25% 红色。离线或无有效校准基准时显示「—」。
点击图标可确认满电校准；校准要求设备在线，确认电池已充满且已拔下充电器。
无独立大卡片、顶栏入口、充电闪电、手动充电操作或电池详情面板。

## 服务与维护

XT369 → lr-xt369-usb.service → SQLite → FastAPI → WebSocket → 前端。

- 每秒采集，单实例锁；读取失败关闭句柄，每 3 秒重连，按序列号寻找仪表。
- /var/lib/lr-platform/battery/state.sqlite3 事务保存累计值，目录权限 0700。
- 仅同一设备、同次系统启动且间隔不超过 5 秒才积分；长断线标记漏计。
- 无有效样本超过 5 秒时不显示旧百分比。服务重启不自动清零或重设满电。
- 旧版手动充电字段在读取时移除；旧的失效基准保持失效，等待人工满电校准。
- 采集和 API 使用同一 Python 环境，安装本地 wheel：
  xt369_linux/dist/xt369_linux-1.0.0-py3-none-any.whl。
- udev 规则：deploy/udev/70-lr-xt369.rules；采集服务：deploy/systemd/lr-xt369-usb.service。
- API 配置 LR_BATTERY_STATE_FILE 为上述数据库路径；LR_BATTERY_ROBOT_ID 默认 LR-01。

保留的接口：

- GET /api/v1/power/battery：电量与采集诊断快照。
- WS /api/v1/realtime/battery：每秒 battery.updated，沿用项目鉴权。
- PUT /api/v1/power/battery/config：管理员设置 capacityAh、nominalVoltageV。
- POST /api/v1/power/battery/calibrate-full：管理员确认，confirmFull=true、confirmUnplugged=true。

检查服务：systemctl status lr-xt369-usb --no-pager
日志：journalctl -u lr-xt369-usb -n 50 --no-pager
数据：curl --fail http://127.0.0.1:8000/api/v1/power/battery

## 验证

后端覆盖积分、持久化、失联、旧状态迁移、参数校验及校准确认；前端覆盖四格
边界、数字精度、离线隐藏、未知电量和机器人绑定。生产构建及应用 src/config
范围 TypeScript 检查通过。仓库独立 cloudflare-worker 示例缺少 data 文件的
原有类型错误不在本次修改范围。
