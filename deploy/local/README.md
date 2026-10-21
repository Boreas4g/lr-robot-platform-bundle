# 本机无 root 部署（控制站）

2026-10-20 在 `boreas@boreas`（Ubuntu 24.04）上完成的控制站部署记录。
本机没有 root/sudo、没有 Docker，也没有为本 bundle 安装的 `lr-*` systemd
单元，因此采用**用户态**运行全部组件。2026-10-21 已接入 IMU、前后雷达与
底盘（串口只读通信/驱动测试通过）；机械臂仍未接入，BookArm 继续用 `--fake`。

## 部署内容

| 组件 | 地址/路径 | 说明 |
| --- | --- | --- |
| 前端静态站点 | <http://127.0.0.1:8000>（局域网 <http://192.168.3.53:8000>） | `LR-Web/dist/`（生产构建），`scripts/serve-static.cjs` 托管并反代 |
| 中心 API | <http://127.0.0.1:8080> · `/docs` | FastAPI `apps/control-api`，PostgreSQL + Redis + MQTT 全连接 |
| PostgreSQL | `127.0.0.1:55432` | 从 Ubuntu `.deb` 解包到 `.local-stack/root`，非 5432 |
| Redis | `127.0.0.1:56379` | 同上，会话/幂等/机器人控制锁 |
| Mosquitto | `127.0.0.1:51883` | 同上，命令下发与遥测接收 |
| BookArm（可选） | `.local-stack/run/bookarm/bookarm.sock` | `--fake` 无硬件模拟服务；由 `start-bookarm-fake.sh` 单独启动 |
| Python 环境 | `LR-Web/.venv` | control-api、bookarm、aim_sdk、pytest 等 |
| ROS 测试叠加 | `.local-stack/ros-overlay` | `nav2_msgs`、`diagnostic_updater`（仅为测试/构建） |
| 运行数据 | `LR-Web/apps/control-api/data/` | 地图、电池 SQLite；已被 Git 忽略 |
| 日志 | `.local-stack/logs/` | PostgreSQL/Redis/Mosquitto/API/静态站点 |

`.local-stack/` 与 `LR-Web/.venv`、`node_modules`、`dist` 都不进 Git。

## 首次配置

```bash
cd /home/boreas/lr-robot-platform-bundle
bash deploy/local/bootstrap.sh
```

`bootstrap.sh` 可重复执行，只补齐缺失项：

1. `apt-get download` 并 `dpkg-deb -x` 解包 PostgreSQL 16、Redis 7、Mosquitto 2
   及其运行库到 `.local-stack/root`（无需 root，不改系统包）。
2. 解包 `nav2_msgs` / `diagnostic_updater` 到 ROS 叠加目录。
3. 创建 `LR-Web/.venv`，安装 `control-api[dev]`、`bookarm[service,test]`、
   `aim_sdk`、`pin`（机械臂逆解）、OpenCV 等。
4. `npm ci` + 生产构建 `dist/`。
5. 生成 `LR-Web/apps/control-api/.env`（权限 0600，已在 Git 忽略）。

PyPI 默认使用清华镜像；可用 `LR_PIP_INDEX_URL` 覆盖。

## 启停

```bash
bash deploy/local/start-local.sh   # 基础设施 + API + 静态站点，幂等
bash deploy/local/status-local.sh  # 端口、进程和 /health
bash deploy/local/stop-local.sh    # 停止全部

# 无硬件联调：同时启动 BookArm --fake 模拟服务（CAN/相机/升降均不接触）
LR_BOOKARM_FAKE=true bash deploy/local/start-local.sh
# 只启动模拟 BookArm（不重启动其它服务）
bash deploy/local/start-bookarm-fake.sh
```

冷启动约 3 秒。API 与环境变量由 `deploy/local/env.sh` 统一导出，
`chassis_params.py`、`map_register.py` 这类直接读 `os.environ` 的模块与
pydantic `.env` 配置保持一致。

本机重启后不会自动启动（没有 systemd 用户单元）；需要时手动执行
`start-local.sh`。

## 前端「一键启动」

生产版 `scripts/start-all.sh` 会操作 systemd/Docker；本机没有这些组件，直接点击
总览页「一键启动」会显示 robot-runtime、mapping-agent、platform-web 失败。
现已在 `LR-Web/apps/control-api/.env` 设置：

```text
LR_HOST_START_ALL_SCRIPT=.../deploy/local/start-all-local.sh
```

该适配脚本启动用户态控制站，并向页面返回：

- `bookarm-conflict` / `platform-web` / `bookarm-service`：OK
- `can0` / `robot-runtime` / `mapping-agent`：SKIPPED（车端硬件运行时需现场授权后单独启动）

因此页面会显示启动完成，但明确列出被跳过的车端模块；这不代表 Nav2/机械臂运行时
已启动。`重启全部` 仍使用生产版 `restart-all.sh`，本机暂未适配。

## 桌面一键启动

桌面已放置可双击的启动器：

```text
~/Desktop/启动图书馆机器人.desktop
  └─ Exec: deploy/local/desktop-start.sh
       ├─ LR_BOOKARM_FAKE=true start-local.sh（全部服务）
       ├─ 成功后系统通知并自动打开 http://localhost:8000
       └─ 失败时弹窗提示，日志在 .local-stack/logs/desktop-start.log
```

启动器已 `chmod +x` 并设置 `metadata::trusted=true`（Ubuntu GNOME 无需再点
“允许启动”）。冷启动约 3 秒；服务已在运行时重复点击只会重新打开网页。
文件管理器或终端里也可直接运行：

```bash
bash deploy/local/desktop-start.sh
```

> 启动器固定带 `LR_BOOKARM_FAKE=true`，即无硬件演示模式。接真实机械臂时
> 请改用终端命令并去掉该变量，同时恢复真实 BookArm socket。

## 配置要点

`LR-Web/apps/control-api/.env` 与模板
`deploy/etc-templates/`、`apps/control-api/.env.example` 的差异：

- 基础设施改用用户态端口 `55432/56379/51883`；
- `LR_ROBOT_ROOT` 指向本 bundle 的
  `LR-Web/external/Library_robot`（车端源码镜像），供底盘参数页读取；
- `LR_REGISTER_ROBOT_MAP_SCRIPT` 指向 bundle 内的车端地图注册脚本；
- `LR_VEHICLE_MAP_REGISTER_ENABLED=false`：本机没有 `/var/lib/lr-robot/maps`，
  导入地图只进控制站，不写车端地图库；
- `LR_CRUISE_POINTS_ENABLED=false`：未部署“已批准的巡航点副本”，
  “同步巡航点”接口按设计返回 422；
- `LR_AUTH_ENABLED=false`：沿用交付默认的免登录单操作员模式。
  接入局域网共享前必须改为 `true` 并更换默认密码。
- `LR_BOOKARM_SOCKET_PATH` 与静态站点的 `LR_BOOKARM_SOCKET` 都指向
  `.local-stack/run/bookarm/bookarm.sock`；真实车端部署需改回
  `/run/lr-bookarm/bookarm.sock`。
- `.env` 中带空格的值（站点名）使用双引号，`env.sh` 用 `set -a` 加载。

> BookArm 的 `--fake` 模式只用于无硬件联调/演示：它会模拟取还书流程并在
> `/api/v1/takeout/health` 返回 `{"mode":"fake"}`。接入真实机械臂前必须停掉
> 该服务并改用硬件模式，避免把模拟状态当成真实设备状态。


## 已验证（2026-10-20）

| 范围 | 命令 | 结果 |
| --- | --- | --- |
| 控制站端到端 | `LR-Web/.venv/bin/python deploy/local/smoke-test.py` | **15/15** 通过 |
| 取书→中位还书流程 | `LR-Web/.venv/bin/python deploy/local/workflow-test.py`（需 fake BookArm） | **5/5** 通过（模板→机器人上线→取书→还书） |
| 后端单元/回归 | 见下方“后端测试命令” | **271 passed** |
| 前端 Vitest | `cd LR-Web && npx vitest run` | **200 passed**（24 文件） |
| 前端类型检查 | `npm run tsc`（业务代码） | 通过；`cloudflare-worker/` 有 9 个既存错误 |
| 前端 Biome | `npx biome lint src config tests scripts …` | 通过（仅 warning/info） |
| 桌面端启动器 | `npm run desktop:test` | **7 passed** |
| bookarm（机械臂/视觉） | `cd …/bookarm && pytest` | **495 passed** |
| aim_sdk（升降台） | `cd drivers/aim_sdk && pytest` | **17 passed, 3 failed**（旧行程标定断言，见下） |
| ROS `robot_decision` | `PYTHONPATH=src/robot_decision:… pytest test` | **154 passed** |
| ROS `car_ctrl` | `PYTHONPATH=src/car_ctrl:… pytest test` | **13 passed** |
| 建图代理 | `…/Library_robot/scripts/test_mapping_agent.py` | **14 passed** |
| ROS 构建 | `colcon build`（8 个包） | car_ctrl、robot_decision、arm_aux_devices、voice、explore_lite_msgs、dual_laser_merger、lslidar_msgs、lslidar_driver；`ros2 pkg executables` 可列出各节点 |

后端测试会读取 `apps/control-api/.env`（部署用 PostgreSQL/本地站点标识），
直接跑 pytest 会连到本机部署库并因站点名断言失败。请用内存模式并重置测试
期望值：

```bash
cd LR-Web/apps/control-api
env LR_STORAGE_BACKEND=memory LR_DATABASE_URL= LR_REDIS_URL= LR_MQTT_URL= \
    LR_BOOKARM_SOCKET_PATH= LR_STATION_NAME="LR 控制站" \
    LR_STATION_ID=development-station \
    LR_ROBOT_ROOT="$PWD/../../external/Library_robot" \
    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
    ../../.venv/bin/python -m pytest -q
```

冒烟测试覆盖：静态站点与 SPA 回退、`/health` 反代、PostgreSQL/Redis/MQTT
依赖状态、登录、地图导入与预览、标注增改查、书籍增改查、压测模板、底盘参数、
电池快照、BookArm 启动策略、MQTT 命令下发、幂等键去重、遥测入站、
WebSocket `robots.snapshot` / `robot.updated` / 电池每秒推送、重启后数据持久化；
启动 fake BookArm 时还会验证控制站健康轮询与 `--fake` 服务连通。

## 硬件诊断（2026-10-21）

新硬件已通过 USB HUB 接入，`99-robot-serial.rules` 已按实际序列号更新并安装：

| 设备 | 别名 | 序列号 / USB 路径 | 协议 |
| --- | --- | --- | --- |
| 前雷达 | `/dev/laser_port` → `ttyACM1` | `5C98184123` | LSLIDAR N10_P，460800 |
| 后雷达 | `/dev/laser_back` → `ttyACM0` | `5C98184650` | LSLIDAR N10_P，460800 |
| 底盘 | `/dev/chassis_serial_port` → `ttyACM2` | `5B90176754` | DDSM115 RS485，115200 |
| IMU | `/dev/imu_port` → `ttyUSB0` | CH340，USB 路径 `...-0:2.2` | WIT 0x55 帧，9600 |

只读探针（不发送任何运动命令）：

```bash
python3 deploy/local/hardware-probe.py
```

2026-10-21 结果：

- 前/后雷达：各约 **10 Hz** 扫描（`/scan_f`、`/scan_b`），原始包率约 328 包/s，
  5 秒内 CRC 错误 0–1 个，测距约 0.14–5.8 m；
- 底盘：DDSM115 **4/4 电机**返回有效反馈帧，模式 `0x02`，轮速 0；探针只发
  `0x74` 反馈查询，未发转速命令；
- IMU：串口和 `/imu/data_raw` 正常（约 10 Hz），加速度约 `(0, 0, +9.8) m/s²`，
  角度正常。静止时 `0x52` 三轴为 0；手动转动 180 秒采样实测角速度峰值
  x=2.08、y=2.81、z=35.95 °/s（非零帧 70/1804），说明陀螺仪可用。
  静止为零是该模块的静态零速输出/死区，**不是芯片故障**；之前配置里的故障结论已纠正。
  低速转动响应仍需在后续运动验收时确认，`car_odometry` 继续使用 IMU 角速度；
- 未做底盘运动测试。按车端安全规则，运动验收需要现场负责人明确授权、急停可用、
  运动范围清场并完成定位/限速检查。

## 硬件未连接时的行为（历史）

- 不会启动 `lr-robot-runtime`、Nav2、雷达、机械臂、XT369 采集等车端进程；
- 机器人列表使用 API 的演示种子数据（LR-01），遥测可通过 MQTT 注入并持久化；
- 未启动 fake BookArm 时 `/bookarm-api/*` 返回 500（Unix socket 不存在），前端按“机械臂服务不可达”降级；启动 fake 后接口与取还书流程可用，但健康状态来自模拟设备；
- 电池接口返回 `offline`，来源为 XT369 USB；
- 底盘参数 64 项中 59 项可读写，5 项 `finetune.*` 标记“当前车端版本不支持”。

## 已知问题（与本次部署无关）

1. `drivers/aim_sdk` 的 `test_lift_platform.py` 仍按旧的 54cm 零点/100000
   脉冲每 2.2cm 断言，而当前实现是 0cm 零点、0–170cm 行程；属于测试未随
   标定更新，3 项失败不影响控制站。
2. `npm run tsc` 对 `cloudflare-worker/` 报缺少 `src/data/*` 模块，该目录是
   独立 Cloudflare 示例，不参与控制站构建。
3. `mobile_robot_nav_bringup`、`mobile_robot_cartographer_bringup` 需要
   `explore_lite`/Nav2/Cartographer 二进制包；本机 ROS Jazzy 是基础安装，
   未安装 Nav2 全栈，因此未构建这两个“仅安装 launch/config”的包。
4. Biome 会扫描 `LR-Web/.venv` 里 pip 自带的 JS 并报错；对业务目录
   `src config tests scripts` 检查是通过的。若要 `npm run lint` 整体通过，
   可把 `**/.venv` 加入 `biome.json` 的 `files.includes` 忽略列表。
