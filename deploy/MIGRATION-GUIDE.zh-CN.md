# 图书馆机器人：新车载电脑一键适配与部署

本指南用于把当前项目部署到**新组装机器人的车载电脑**。统一入口为项目根目录的 `deploy/robot-setup.sh`。填写一份机器配置后，一条 `apply --install-deps` 命令安装依赖、构建程序、生成本机配置和证书、初始化账号与地图、设置开机服务。现场确认完成后可加 `--start` 启动服务。

安装过程不激活热点、不重连 Wi-Fi、不触发 USB 重枚举、不自动重启电脑。热点配置保存到 NetworkManager，**下次开机生效**。`apply` 会拒绝在项目服务正在运行的机器人上覆盖安装；当前在用机器只执行 `scan`、`export-baseline`、`pack` 等只读/导出命令。

## 1. 哪些配置需要逐台适配

| 类别 | 新机器要核对的内容 | 本项目的配置位置/安装结果 |
| --- | --- | --- |
| 机器人身份 | 唯一 `robot_id`，例如 `LR-02`；展示名称 | 配置文件顶层；生成 `/etc/lr-robot/edge-gateway.yaml`、API 身份、独立 MQTT 凭据 |
| Linux 用户和目录 | 已存在的普通用户；项目实际目录；家目录 | `service_user`；脚本自动替换 systemd 的用户名、组、工作目录、解释器路径；目录使用英文字母、数字、下划线、点、横杠等普通路径字符 |
| RealSense 相机 | **新相机的序列号**、分辨率、深度尺寸、帧率 | `camera_serial` 和 `camera` 覆盖项；生成 `/etc/lr-bookarm/config/devices/camera.json` |
| 前、后雷达 | 各自 USB VID/PID、序列号；安装方向、雷达坐标系与外参 | `devices.laser_port`、`devices.laser_back`；基线 `ros/src/lslidar_driver/params/lsx10_*.yaml` 及 ROS 启动文件 |
| 底盘控制器 | USB 绑定、串口速率、轮径、轮距、电机 ID/方向、速度限制 | `devices.chassis_serial_port`；基线 `ros/src/car_ctrl/config/ddsm_hat_diff_drive.yaml` |
| IMU | USB 绑定、串口波特率、安装方向/坐标系 | `devices.imu_port`；ROS 底盘配置。没有唯一序列号时必须用**新电脑**的 `ID_PATH`，并固定插口 |
| 机械臂 CAN | 接口名、速率、关节 ID/方向、零点、限位、TCP、惯量、热保护 | `arm` 覆盖项；`/etc/lr-bookarm/config/devices/arm.json`、`calibration/arm_inertia.yaml`；默认 SocketCAN `can0`、1 Mbps |
| 升降台 | USB 绑定、总线地址、波特率、绝对参考位置、安装零点 | `devices.lift_port`、`lift`；`/etc/lr-bookarm/config/devices/lift.json` |
| 推杆 | USB 绑定、波特率、运动参数和机械行程 | `devices.rodmotor`、`rod`；`/etc/lr-bookarm/config/devices/rod.json`、动作 profile |
| 机械标定 | 相机到基座外参、取书槽位、还书槽位、机械臂惯量、取还书动作 profile | 基线 `bookarm/calibration/*`、`tuning/*`；生成 `/etc/lr-bookarm/config/calibration/*`，profile 写入项目 `recordings/tuning/` |
| XT369 USB 电量计 | 是否接入、USB 权限；多个电量计时指定序列号；电池容量和标称电压 | `battery.serial/capacity_ah/nominal_voltage_v`；生成 udev 权限及采集服务；电池状态在 `/var/lib/lr-platform/battery/` |
| 地图与定位 | 地图是否属于**实际现场**，有效 ID/边界、分辨率、原点；新机初始定位 | `active_map_id`；基线地图注册表、PGM/YAML、自动定位参数；不复制旧机的实时姿态和上次定位结果 |
| 热点 | 新电脑无线网卡名/MAC、AP 模式能力、SSID、密码、信道 | `hotspot.*`；`/etc/NetworkManager/system-connections/lr-robot-hotspot.nmconnection`；固定 `192.168.4.1/24`，共享模式提供 DHCP；开机自动连接优先级 `999` |
| 局域网 Wi-Fi | 现场 SSID、密码、允许设备互访；可选 DHCP 地址保留 | 安装后通过“系统 → 网络连接”配置，不复制旧机 Wi-Fi 密码；Avahi 提供页面显示的 `.local` 名称 |
| 蓝牙 | 适配器能否使用、对外名称 | `bluetooth_name`；`/etc/lr-platform/bluetooth.env`；timer 每 30 秒维持开启和可发现 |
| 网站登录和权限 | 用户密码、维护账号；对外入口 | `operator_password`；操作员仅开放**作业、地图与导航、系统**；维护管理员独立随机密码；入口统一 `8000`，不用 `8001` |
| 软件环境 | Ubuntu/CPU 架构、ROS、Node、Python 包、npm 锁、Docker 镜像 | 基线 `versions/*`；独立 Python venv；前端和 ROS 在新电脑重新构建 |
| 自动启动 | 服务依赖、硬件归属、建图与导航互斥 | 自动生成并启用 systemd 服务，见下一节 |
| 业务资料 | 图书、书脊模板、书架标注、任务模板、历史任务、日志 | **不属于通用部署基线**。新机器人默认新建业务数据；同一图书馆需要继承时，另做数据库、模板目录和文件存储备份/恢复，并核对机器人 ID 和现场绑定 |

### 可以统一，不能盲目复制的部分

- 相机设备配置和 ROS 参数优先从当前部署使用的文件导出；部分机械参数来自当前类默认值，缺少正式外参/惯量时会使用项目已有示例。`provenance.json` 记录各项来源。导出文件不证明当前连接硬件和机械标定已匹配，新机必须复核。
- 每台新机器人重新生成本站和本车的 MQTT/mTLS 证书、密码与 BookArm token；不共享旧机器的私钥和身份。数据库、MinIO、EMQX 维护密码随机生成。
- 不复制旧机的电量百分比、累计耗电、满电确认和实时姿态。新电池确认规格后，仍需在实际充满并拔掉充电器时重新做满电标定。
- 新机械总成的零点、相机位置、槽位和行程需要现场复核。软件能统一参数文件，无法用复制文件消除装配误差。
- 地点改变时需要相应现场地图，不能把实验室地图直接当作新图书馆地图。先用 `hardware_autostart=false` 部署软件，再通过已有地图/建图流程准备现场地图和定位；确认后从停机状态更新部署配置。

## 2. 开机启动的服务

| 服务 | 功能 | 策略 |
| --- | --- | --- |
| `docker.service`、`lr-platform.service` | PostgreSQL、Redis、MinIO、EMQX 基础设施 | 开机启动，使用本地已锁定镜像，日常启动不拉镜像 |
| `lr-control-api.service` | 控制 API | 开机启动，监听 `127.0.0.1:8080` |
| `lr-web-static.service` | 前端与接口代理 | 开机启动，监听 `0.0.0.0:8000` |
| `lr-host-start-agent.service` | 前端系统页的固定启动/重启命令代理 | 开机启动，私有 Unix socket |
| `lr-robot-mapping-agent.service` | 地图/建图管理代理 | 开机启动，仅本机 `127.0.0.1:18090` |
| `lr-xt369-usb.service` | XT369 USB 电量采样 | 开机启动，缺设备时重连；`check` 会区分“进程运行”和“真实读数在线” |
| `lr-bookarm-can.service`、`lr-bookarm-takeout.service` | CAN 与取/还书机械臂、相机、升降台、推杆 | `hardware_autostart=true` 且现场标定/启动条件确认后设为开机启动 |
| `lr-robot-runtime.service` | ROS 导航、底盘、雷达、IMU、Edge Gateway | 与上项同样受硬件自启选项控制，ROS 发现范围保持 `LOCALHOST` |
| `lr-bluetooth.timer` / `lr-bluetooth.service` | 蓝牙名称、开启、可发现 | timer 开机启动 |
| `NetworkManager.service` 和已保存热点连接 | 固定热点、DHCP | 开机默认加载优先级 `999` 的机器人热点，安装时不激活 |
| `lr-network-agent.service`、`avahi-daemon.service` | 受控 Wi-Fi 切换、名称发现 | 开机启动；代理启动本身不改变网络 |
| `lr-robot-mapping.service` | 实际 SLAM 建图模式 | **按需启动**，与导航模式互斥，不能一起开机运行 |

安装器不启用旧 `lr-web-dev`（8001）、旧机械臂运行时、旧 XT369 蓝牙采集、旧地图同步 timer、旧自定义热点服务。当前方案采用 USB 电量计、本机地图注册和 NetworkManager 热点。

`lr-station-discovery` 的现有实现要求 HTTPS 控制站地址，因此本交付的 `http://192.168.4.1:8000` 直连模式不启用它。用户通过固定网址访问，不依赖控制站自动发现。ROS、MQTT、BookArm 不对局域网开放。

## 3. 在正常旧机导出完整交付包

以下命令均在**项目根目录**执行。需要旧机已经正常运行、四个基础容器在线，且已有 `python3-yaml`。

```bash
sudo ./deploy/robot-setup.sh export-baseline \
  --output .local-deploy/migration-baseline

sudo ./deploy/robot-setup.sh pack \
  --baseline .local-deploy/migration-baseline \
  --output .local-deploy/library-robot-migration.tar.gz
```

交付包包含源码、相机/机械配置、已注册地图、识别模型、动作参数、依赖锁和镜像摘要。它不包含旧机器登录环境文件、数据库、CA 私钥和运行凭据。导出目录和压缩包默认私有权限；通过 U 盘或受控文件传输复制压缩包和同目录 `.sha256` 文件。如果普通用户需要读取，按实际账号调整这两个文件的所有者即可，不要把它们设为全员可读。

基线同时记录源码校验值。**导出以后改了源码，需要重新导出到一个新目录再打包**；旧基线和旧包不会被覆盖。

## 4. 在新车载电脑配置一次、执行一条安装命令

### 4.1 系统准备

本版安装器适用于 **Ubuntu 24.04 x86_64 / ROS 2 Jazzy**。先创建普通 Linux 用户，并让该电脑能联网下载依赖。建议有线网络安装；若未来要求热点和上网 Wi-Fi 同时工作，优先准备两块独立无线网卡，一块上网、一块专门开热点。

在存放交付包的目录校验并解压：

```bash
sha256sum -c library-robot-migration.tar.gz.sha256
tar -xzf library-robot-migration.tar.gz
cd lr-robot-platform-bundle
chmod +x deploy/robot-setup.sh
```

### 4.2 扫描并生成本机参数

```bash
./deploy/robot-setup.sh scan

./deploy/robot-setup.sh init \
  --baseline .local-deploy/migration-baseline \
  --profile .local-deploy/robot.json \
  --robot-id LR-02

nano .local-deploy/robot.json
```

`init` 会填入当前普通用户、唯一接入的 RealSense 序列号，以及已经存在且可识别的设备别名。新组装机器通常还没有别名，因此需要按扫描结果填写六个串口的实际用途。**不会根据 ttyUSB 编号猜测前后雷达或运动机构。**

每个 `devices` 项填写 `vid`、`pid`，再填写 `serial` 或 `id_path`。有唯一序列号时优先使用 `serial`；两者都有时以序列号为准。`scan` 展示的是只读设备属性，不会打开串口、相机、CAN 或发送控制帧。

无序列号的 IMU 等设备必须用新电脑的 `ID_PATH`。路径依赖物理 USB 插口，换电脑、换 HUB 或换插口后重新扫描并更新。不能把旧机器的物理路径原样照搬。

热点的 `interface` 必须填写实际无线接口名；建议同时填写对应 `mac`，防止绑错网卡。脚本检查 AP 能力、信道和其他网卡的网段冲突。普通密码和热点密码是两项：

| 项目 | 默认值 |
| --- | --- |
| 用户网站账号 | `operator` |
| 网站密码 `operator_password` | `123456` |
| 热点名称 `hotspot.ssid` | `图书馆机器人` |
| 热点密码 `hotspot.password` | `12345678`；WPA2 要求至少 8 位，不能使用 6 位网站密码 |
| 热点网关 | `192.168.4.1/24` |
| 用户访问网址 | `http://192.168.4.1:8000` |
| 蓝牙名称 | `图书馆机器人` |

相机/机械通用参数默认继承基线，顶层的 `camera`、`arm`、`lift`、`rod` 对象仅填写本机需要覆盖的字段。例如：

```json
{
  "camera": { "fps": 6 },
  "arm": { "can_interface": "can0", "can_bitrate": 1000000 },
  "lift": { "reference_absolute_position": -14931 },
  "rod": { "baudrate": 921600 }
}
```

这只是字段用法示例，不是新机器的标定结论。相机序列号统一写顶层 `camera_serial`，不能再放入 `camera` 覆盖项。完整字段示例见 `deploy/etc-templates/robot-profile.example.json`。

确认本机机械标定及地图属于实际现场后，才把 `calibration_reviewed`、`map_site_reviewed` 设为 `true`。`site_start_confirmed=true` 表示现场负责人已检查急停、清场、定位、限速和监护条件，并允许硬件在下一次开机/执行启动命令时启动。三个选项默认 `false`，用于防止未适配的新组装机器直接给运动机构上电。

仅先安装软件时，设置 `hardware_autostart=false`；此时导航和机械臂不设为开机自启。

### 4.3 预检和一键安装

```bash
./deploy/robot-setup.sh plan --profile .local-deploy/robot.json

sudo ./deploy/robot-setup.sh apply \
  --profile .local-deploy/robot.json \
  --install-deps
```

安装会完成：

1. 校验基线完整性和源码版本，检查配置及已接入设备是否匹配。
2. 安装系统依赖、ROS Jazzy、固定 Node 22 版本及 Docker Compose。
3. 为 API 和 BookArm 建立项目内独立 Python 环境，安装锁定版本和本地 XT369/升降台 SDK，执行依赖检查。
4. 按 `package-lock.json` 安装并构建前端，重新编译导航/决策 ROS 包及其本地依赖。
5. 生成本车配置、串口稳定别名和权限、独立证书、数据库和服务凭据。
6. 启动基础设施容器完成数据库初始化，创建真实机器人身份、操作员/维护账号，并导入基线地图；不生成假在线机器人或假定位。
7. 安装并启用对应开机服务、网络代理和 Avahi，保存固定 IP 热点配置；按机器人身份设置主机名供局域网发现。
8. 保存安装记录、私有配置快照、备份和账号文件。

默认安装**不会立即启动导航或机械臂**；已启用的硬件服务将在下一次开机启动。安装期间会启动 Docker 和基础容器用于初始化数据。全部配置已确认且现场允许立即启动时，使用同一命令加 `--start`：

```bash
sudo ./deploy/robot-setup.sh apply \
  --profile .local-deploy/robot.json \
  --install-deps --start
```

如果已经成功执行过 `apply`，直接启动已安装配置：

```bash
sudo ./deploy/robot-setup.sh start
```

`start` 只允许启动已安装的参数，不接受另一份未安装配置绕过适配流程。安装器和启动命令均不会激活热点；由现场人员选择合适时间重启电脑后，热点自动加载。单无线网卡切换为热点后，原上网 Wi-Fi 连接通常会被占用，远程维护连接可能消失，应提前安排本地接入。

`--install-deps` 控制是否执行系统包和 Node 的安装；即使省略，`apply` 仍会安装 Python/npm/ROS 项目依赖并构建。重复执行前要求项目服务已由现场人员停机；同一机器人身份的未完成安装可重试，凭据保留。普通用户密码会重新应用配置文件中的 `operator_password`。

## 5. 开机验收

重启后，手机或电脑连接“图书馆机器人”热点，浏览器打开：

```text
http://192.168.4.1:8000
```

使用 `operator / 123456` 登录（若配置已改密码，以配置为准）。局域网电脑也可访问 `http://车载电脑的局域网IP:8000`。

在车载电脑执行只读检查：

```bash
sudo ./deploy/robot-setup.sh check
```

检查项目包括服务开机启用及运行状态、前端、API 依赖健康、六个设备别名、底盘里程计、BookArm 私有接口鉴权与真实模式、XT369 最近有效读数、网络代理、热点配置和当前联网状态、蓝牙名称和开启状态。有一项失败就返回非零退出码。安装后尚未启动硬件或尚未重启加载热点时，相关检查失败是预期结果。

### 交付后连接图书馆 Wi-Fi

操作员登录热点入口后，在“系统 → 网络连接”选择目标 Wi-Fi、输入密码并切换；终端也切到目标网络，返回控制页点击“进入新网址”跳转到车载电脑取得的新 IP。`.local` 名称和路由器客户端列表中的新 IP 可作备用入口，使用 `8000` 端口登录后，在切换开始后约 5 分钟内确认保留。确认后 Wi-Fi 配置会持久保存；车载电脑重启后默认启动机器人热点，需要使用 Wi-Fi 时可从页面再次切换。未确认或连接失败会请求恢复原网络。固定热点入口为 `192.168.4.1`。单网卡不保证热点与 Wi-Fi 同时存在。

目标网络密码由现场用户输入，不纳入 Git 或通用基线。新机部署依赖包括 `python3-dbus`、`avahi-daemon`、`libnss-mdns`；`LR_NETWORK_AGENT_SOCKET` 指向 `/run/lr-network-agent/network.sock`。旧迁移包不会自动包含新代理，更新后需重新导出/打包。完整步骤见[用户指南](../docs/用户使用指南.md)和[网络部署说明](HOTSPOT-ACCESS.md)。

进程和接口在线不等于运动验收通过。首次运行还需要现场确认新机定位、地图对齐、底盘运动方向、限速、机械零点、取还书标定；动作验收通过正常前端流程完成。

维护管理员密码及操作员账号保存在：

```text
/etc/lr-platform/access-credentials.json
```

该文件仅 root 可读，不在控制台批量打印。其他安装结果：

| 路径 | 用途 |
| --- | --- |
| `/etc/lr-platform/setup-profile.json` | 已安装的本机适配参数，含用户密码，仅 root 可读 |
| `/etc/lr-platform/setup-receipt.json` | 安装时间、基线校验值、自启清单、备份位置 |
| `/etc/lr-platform/setup-secrets.json` | 本机持久凭据，仅 root 可读 |
| `/var/lib/lr-platform/setup-backups/<时间>/` | 本次覆盖前的文件备份和安装参数快照，仅 root 可读 |
| `/var/lib/lr-platform/pki/` | 本车载一体控制站自己的 PKI，不要复制给另一台机器人 |
| `/etc/lr-platform/control-api.env` | API 配置，root 和服务用户组可读 |
| `/etc/lr-bookarm/`、`/etc/lr-robot/` | 机械与 ROS 运行配置 |

备份供人工排查和恢复，不提供自动回滚或自动停止在用机器人。

## 6. 环境一致性的范围和限制

- 前端 npm 使用锁文件；Node 使用旧机导出的精确版本，并核对官方 SHA256；Python 包锁定旧机已安装版本；四个 Docker 镜像固定仓库摘要。源码、地图、权重、标定和依赖锁均带 SHA256 校验。
- Python 环境在新机用 Ubuntu 24.04 的系统 Python 3.12 重建，API/BookArm 分开 venv；不直接复制旧 conda 环境。当前旧机 API 是 Python 3.11、BookArm 是 3.12，因此**Python 小版本/系统补丁不会逐字节相同**；安装会用 `pip check` 和主要模块导入发现兼容问题，失败即退出。
- 系统 apt 包和 ROS 二进制按 Jazzy 仓库安装；导出的 `versions/dpkg.tsv` 用于对照，不承诺重装所有旧机桌面软件或锁死内核版本。不同 CPU 架构、系统发行版、CAN/相机型号需要建立对应基线，安装器会拒绝不支持的平台。
- 首次安装需要软件源、PyPI、Node 和镜像仓库可达；交付包不是完整离线软件仓库。日常启动不依赖下载镜像。要做完全离线交付，需要另备 apt 仓库、Python wheelhouse、npm 缓存及 Docker 镜像归档。
- 不修改新机防火墙策略；若现场已启用防火墙，需要确保热点及目标局域网允许入站 TCP 8000。不要对外开放 8080、18090、18091、ROS/DDS、MQTT 或机械臂控制口。
- 同一块 Wi-Fi 网卡是否支持热点和客户端并发取决于硬件/驱动能力。本脚本不创建并发虚拟无线接口；双网卡分别承担热点和上网更容易稳定交付。

## 7. 开发验证命令

这些检查只操作临时目录和模拟设备，不修改网络或真实硬件：

```bash
python3 -m unittest discover -s deploy/scripts -p 'test_*.py' -v
python3 -m py_compile deploy/scripts/robot_setup.py deploy/scripts/robot_bootstrap.py deploy/scripts/robot_provision.py
bash -n deploy/robot-setup.sh deploy/scripts/robot-bluetooth.sh
```

在已装 BookArm 依赖的 Python 环境中运行 `bookarm/tests/test_appliance_device_config.py`、`test_studio_service.py`、`test_studio_vision_wiring.py`。新机器完整安装、实际热点连接和运动功能仍需在新组装机器人上做现场集成验收。

API 的 `tests/conftest.py` 在测试收集阶段清除 `LR_*` 环境覆盖并禁用 `.env`，使用内存服务配置；测试期间禁止真实网络连接和宿主控制命令，车端地图注册默认关闭。需要验证这些接口时必须模拟代理、命令和设备，不能让自动测试使用现场控制 socket。
