# 本机部署记录

> **2026-10-24 网络连接功能**：已构建并部署“系统 → 网络连接”，安装、启用并启动 `lr-network-agent.service`，通过私有 Unix socket 控制 NetworkManager。前端和 API 已重启加载新版，普通操作员登录后可查看当前 Wi-Fi、缓存网络列表、名称入口和切回热点入口。Avahi 名称为 `lr-control.local`；跨网络切换后“进入新网址”按钮优先跳转目标网卡新 IPv4 地址，并保留 `.local` 名称入口。
>
> 本次没有提交真实 Wi-Fi 切换请求、重启 NetworkManager 或改变热点配置。部署前后 `wlo1` 均连接 `LR_5G`，IPv4 均为 `192.168.3.22`；API 健康检查为 ok，PostgreSQL/MQTT connected，机器人 idle。旧的排队和暂停记录未改动；它们不会单独阻止网络切换，仍在执行的任务或机器人活动状态会阻止。真实切换、自动恢复和冷启动重连仍需现场验收。
>
> **2026-10-24 切换请求排查**：现场两次请求均在 API 返回 `409`，NetworkManager 没有收到切换命令。原因是历史排队/暂停任务被当作仍在执行；现改为只拦截执行中任务及机器人忙碌/导航/手动控制/建图状态。目标网卡取得地址后，“进入新网址”按钮优先使用新 IPv4。前端错误提示会保持显示，明确标示未受理请求。
>
> **2026-10-24 开机网络默认值**：`lr-network-agent.service` 已启用开机启动。NetworkManager 固定热点配置改为 `autoconnect=yes`、优先级 `999`；已保存的 Wi-Fi 在切换确认后仍会保留并可用，但优先级为 `998`，重启后默认启动机器人热点。修改未切断当前 LR_5G 连接；下次重启后验证热点广播。
>
> 验证：前端 201 项测试通过；API 全量 306 项测试通过，后续新增校验后的网络 API 专项 14 项通过；部署/代理 49 项测试通过；生产代理集成测试、TypeScript、构建和新页面 antd 检查通过。手机/平板/桌面的模拟切换表单和交接流程验证通过。全仓库 lint 仍因既有 vendored/ROS 构建目录与断裂符号链接报错；本次新增 API 的 Ruff 检查通过。用户指南 Markdown、PDF、热点说明和迁移指南同步更新。
>
> 上线后已通过真实手机/桌面视口的登录、网络状态/缓存列表/热点入口和无横向溢出检查；机器人、书籍、地图、图像、电池与两路 WebSocket 正常，操作员调试访问仍为 403。`lr-control.local` 本机解析到 `192.168.3.22`。网络变更端点始终未调用。

> **2026-10-23 增补**：本项目现已启用登录，普通操作账号只能使用作业、地图与导航、系统功能；调试中心菜单、直接页面和对应 API 均由服务端限制。热点与访客接入的当前状态、启动方式和验收步骤见[热点与访客访问](HOTSPOT-ACCESS.md)。

> **2026-10-20 增补**：当前主机没有 root/sudo、Docker 及本 bundle 的
> `lr-*` systemd 单元，控制站改为用户态部署（PostgreSQL/Redis/Mosquitto
> 解包运行、uvicorn + node 静态站点）。操作说明、端口与测试结果见
> [deploy/local/README.md](local/README.md)。下文 2026-10-16 的
> systemd/Docker 部署记录保留作为历史参考。

2026-10-16：将本机控制站前端与 control-api 从 `/home/boreas/LR-Web`
切换到 `/home/boreas/lr-robot-platform-bundle/LR-Web`。

2026-10-21：统一部署工作区到当前项目目录。前端、control-api、
ROS 2、BookArm、书脊识别模型、systemd 单元及启动脚本都从该项目读取。

## 访问与服务

- 本机网页：<http://localhost:8000>
- 本次部署时的局域网地址：<http://192.168.3.22:8000>
- API 文档：<http://localhost:8080/docs>
- 健康检查：<http://localhost:8000/health>
- 登录账号由管理员提供；操作员初始密码保存在本机权限为 0600 的 `.local-deploy/hotspot-access.txt`，不纳入 Git。

所有 `lr-*` 服务继续由 systemd 管理，保留原有开机启动及失败重启设置。
控制站的本地覆盖文件为：

```text
/etc/systemd/system/lr-web-static.service.d/90-local-bundle.conf
/etc/systemd/system/lr-control-api.service.d/90-local-bundle.conf
```

前端统一由 `lr-web-static.service` 提供 `:8000`，本机与局域网均访问此端口。`lr-web-dev.service` 已停用并取消开机启动，`8001` 不再作为服务入口。

前端使用当前目录的 `dist/` 和 `scripts/serve-static.cjs`，API 使用当前目录的
`apps/control-api/app/`，Python 环境沿用
`/home/boreas/miniconda3/envs/lr-control-api`。

## 配置和数据衔接

私有 `.env` 已复制到 `LR-Web/apps/control-api/.env`，权限为 0600，受 Git
忽略规则保护。数据库、MQTT 证书、BookArm Unix socket 和宿主启动代理沿用
原有配置。健康检查显示 PostgreSQL、MQTT connected；Redis 会话缓存仍使用
原有 memory 模式。

现有地图、业务文件已迁入 `LR-Web/apps/control-api/data/`；BookArm 任务历史和书脊
识别模型也已迁入当前项目对应目录。旧工作区保留为回滚副本，确认新路径运行稳定前不要删除。

ROS 导航、机械臂、建图代理、地图注册、XT369 电池服务、平台启动及发现服务的
systemd 配置均指向当前项目。API 服务通过 `LR_ROBOT_ROOT` 指向 ROS 工作区
`/home/boreas/lr-robot-platform-bundle/LR-Web/external/Library_robot`。
地图注册脚本通过 `LR_REGISTER_ROBOT_MAP_SCRIPT` 指向本机 sudoers 已授权的
`/home/boreas/lr-robot-platform-bundle/LR-Web/external/Library_robot/scripts/register-robot-map.sh`。

配置已写入，但本次没有重启导航、建图代理或机械臂服务，因此已运行的进程仍从旧工作区
执行。现场负责人确认急停、清场、定位、限速和监护条件后，再安排服务切换和在线验收。

## 更新与查看日志

在当前项目根目录执行：

```bash
cd LR-Web
ELECTRON_SKIP_BINARY_DOWNLOAD=1 HUSKY=0 npm ci --no-audit --no-fund
UMI_ENV=production NODE_ENV=production NODE_OPTIONS=--max-old-space-size=2048 RAYON_NUM_THREADS=2 npm run build
sudo systemctl restart lr-control-api.service lr-web-static.service
curl --fail http://127.0.0.1:8000/health
```

构建显式设置 `UMI_ENV=production`，使实时 WebSocket 使用网页同源代理。
安装时跳过 Electron 二进制下载；本次部署的是 Web 服务。

```bash
systemctl status lr-web-static.service lr-control-api.service --no-pager
journalctl -u lr-web-static.service -u lr-control-api.service -n 100 --no-pager
```

## 验证和回滚

已通过生产构建、68 项相关后端测试，以及地图注册配置调整后的 8 项回归测试。
切换后验证了首页及静态资源、API 文档、当前用户、底盘参数读取、2 张地图预览、
BookArm 健康接口和 WebSocket 机器人快照。原有 1 台机器人、602 条任务、
2 张地图的 ID 列表与切换前一致。没有执行机器人运动或取还书动作测试。

备份目录：

```text
/home/boreas/lr-robot-platform-bundle/.local-deploy/20261016-212756/
```

其中保存了原服务单元、私有环境配置、PostgreSQL dump、业务文件归档和核对基线。
`.local-deploy/` 已加入 Git 忽略规则，目录仅当前用户可访问。

恢复原前后端服务路径：

```bash
bash /home/boreas/lr-robot-platform-bundle/.local-deploy/20261016-212756/rollback-services.sh
```

该脚本只撤销本次 systemd 路径覆盖并重启前后端，不自动回灌数据库或业务文件。

## XT369 电池采集扩展

2026-10-16 新增 lr-xt369-usb.service（USB 采集、开机自启），使用独立持久化数据库。
配置为用户确认的 24V/20Ah，电量以紧凑图标和数字显示在“智巡一号”名称后面，
每秒更新。仅保留电量显示和满电校准；当前接线下充电器绕过 XT369，
电量估算仅适用于校准后的纯放电过程。
详见 [XT369-INTEGRATION.md](XT369-INTEGRATION.md)。
