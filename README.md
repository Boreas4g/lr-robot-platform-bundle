# LR 图书馆机器人平台 — 全系统代码备份

采集于 2026-10-16，来源机器为本机器人车载电脑兼控制站（boreas 主机）。
本仓库整合该平台**全部功能代码与相关数据文件**，对应线上 13 个 `lr-*` systemd
服务所涉及的全部代码路径。

## 系统架构与代码分布

```
浏览器 ──> :8000  lr-web-static.service    LR-Web/scripts/serve-static.cjs（静态托管 dist/ + 反代）
              ├─ /api,/health ──> :8080  lr-control-api.service   LR-Web/apps/control-api/（FastAPI）
              └─ /bookarm-api  ──> unix socket  lr-bookarm-takeout.service
                                                        LR-Web/external/lingzu-bookarm-py/bookarm/
lr-platform.service（oneshot）──> LR-Web/scripts/start-platform.sh（PG/Redis/MinIO/EMQX 基础设施）
lr-robot-runtime.service    ──> Library_robot/scripts/start-robot-runtime.sh
                                 └─ ROS2：底盘驱动→双雷达→Nav2/AMCL→自动定位→Edge Gateway(MQTT↔ROS)
lr-robot-mapping(-agent).service ──> 手动建图栈 + 建图 HTTP 代理(127.0.0.1:18090)
lr-robot-map-sync.service/timer ──> 地图 mTLS 同步
lr-bookarm-can.service ──> can0 @1Mbps 初始化
lr-xt369p-battery/-rfcomm.service ──> 电池遥测 / 蓝牙 SPP
lr-host-start-agent.service ──> root 启动代理（/usr/local/libexec/）
lr-station-discovery.service ──> 局域网发现广播
```

## 目录内容

| 路径 | 内容 | 来源 |
| --- | --- | --- |
| `LR-Web/` | **控制站主仓库完整工作树**：前端源码 `src/`、构建产物 `dist/`（:8000 托管的数据）、`apps/control-api/`（FastAPI :8080）、`apps/edge-gateway/`、`external/lingzu-bookarm-py/`（**机械臂服务 + D435 书脊视觉识别 + 标定数据**）、`external/Library_robot/`（**ROS2 车端源码镜像：car_ctrl 底盘电机驱动、robot_decision 边缘网关/决策、nav2_minimal_bringup 导航、dual_laser_merger 雷达合并、cartographer 建图、语音交互、realsense/lslidar 驱动、地图**）、`external/rod-motor-firmware/`（ESP32 杆电机固件）、`scripts/` 运维脚本、`desktop/` 桌面端、`cloudflare-worker/`、`infra/`、`contracts/`、`docs/` | `/home/boreas/project/LR/LR-Web` |
| `drivers/aim_sdk/` | YZ-AIM 一体化伺服电机 Python SDK（RS485/Modbus，升降台驱动，bookarm 硬件依赖，未被 vendor 进任何仓库） | `/home/boreas/LR/lingzu-bookarm-py/aim_sdk` |
| `drivers/rf2o_laser_odometry/` | 激光雷达 2D 里程计 ROS2 包（含本机未提交的 `/scan_f` 话题适配） | `/home/boreas/rf2o_laser_odometry` |
| `drivers/robot_4wd_dds115_base_controller/` | 4WD DDSM115 轮毂电机 RS485 控制器（ROS1 版，含本机测试脚本） | `/home/boreas/robot_4wd_dds115_base_controller` |
| `protection/protection-src/` | 许可证保护工具链源码（Ed25519 签名守护、Cython 打包工具；**不含密钥**） | `/home/boreas/lr-protection-build/protection-src` |
| `deploy/systemd/` | 全部 14 个 `lr-*` systemd 单元（含 timer） | `/etc/systemd/system/` |
| `deploy/libexec/` | root 侧安装的运行脚本（启动代理、平台拉起、发现广播等） | `/usr/local/libexec/lr-*` |
| `deploy/etc-templates/` | 私有配置**脱敏模板**与排除清单 `PRIVATE-CONFIGS.md` | 自制 |
| `misc/` | 本机散置脚本与固件（电机保持、升降串口、RealSense 配置、USB2CAN 固件 bin） | `/home/boreas/` |

## 排除项（有意为之）

**安全排除（项目 AGENTS.md 硬性规则：私钥/MQTT 密码/证书//etc/lr-robot 私有配置不得进 Git）**：
详见 `deploy/etc-templates/PRIVATE-CONFIGS.md`。包括 `/etc/lr-robot/`、`/etc/lr-platform/`、
`/etc/lr-bookarm/` 的真实配置与证书、`apps/control-api/.env`、许可证私钥、`~/lr-backup-stage/`。

**可重建产物排除**：`node_modules/`（`package-lock.json` 可重现）、ROS `build/ install/ log/`、
`__pycache__/`、`src/.umi*`、`.turbopack/`、各目录 `.git/`。

**重复/历史副本排除**（现行代码已在本备份内）：
`~/LR/Library_robot/`（live 工作区，源码与 `LR-Web/external/Library_robot/` 逐字节一致，仅多编译产物）、
`~/realsense_ros/`（上游干净克隆 realsenseai/realsense-ros @4.57.7，源码已 vendor 进 ROS 工作区）、
`~/project/lingzu_arm/`（bookarm 退役快照，落后 5 个提交）、`~/project/rod-motor-firmware/`（与 external 逐字节一致）、
`LR-Web/lr-oneclick-deploy-20261008.tar.gz`（410M 旧部署归档，含凭据）。

## 本机当前部署（2026-10-20）

本机没有 root/sudo、Docker，也没有本 bundle 的 `lr-*` systemd 单元；控制站已按
用户态方式运行：

- 网页：<http://localhost:8000>（局域网 <http://192.168.3.53:8000>）
- API 文档：<http://localhost:8080/docs>

配置、端口、启停与测试命令见 [deploy/local/README.md](deploy/local/README.md)。
机器人硬件未连接，BookArm 可选用 `--fake` 模拟联调。

## 恢复要点

1. 依赖：Node.js ≥22、Python（conda env `lr-control-api`）、ROS 2 Jazzy、Docker（PG/Redis/MinIO/EMQX）。
2. 控制站：`cd LR-Web && npm ci && npm run build`（或直接用 `dist/`）；
   control-api 按 `apps/control-api/README.md` 建环境并依据 `.env.example` 补 `.env`。
3. 车端：`colcon build` ROS 工作区；按 `deploy/etc-templates/` 补齐 `/etc` 私有配置与证书。
4. systemd：参照 `deploy/systemd/` 单元与 `deploy/libexec/` 脚本恢复服务。
