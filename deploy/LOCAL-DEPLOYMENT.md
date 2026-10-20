# 本机部署记录

> **2026-10-20 增补**：当前主机没有 root/sudo、Docker 及本 bundle 的
> `lr-*` systemd 单元，控制站改为用户态部署（PostgreSQL/Redis/Mosquitto
> 解包运行、uvicorn + node 静态站点）。操作说明、端口与测试结果见
> [deploy/local/README.md](local/README.md)。下文 2026-10-16 的
> systemd/Docker 部署记录保留作为历史参考。

2026-10-16：将本机控制站前端与 control-api 从 `/home/boreas/LR-Web`
切换到 `/home/boreas/lr-robot-platform-bundle/LR-Web`。

## 访问与服务

- 本机网页：<http://localhost:8000>
- 本次部署时的局域网地址：<http://192.168.3.22:8000>
- API 文档：<http://localhost:8080/docs>
- 健康检查：<http://localhost:8000/health>
- 沿用现有免登录操作员模式。

`lr-web-static.service` 和 `lr-control-api.service` 继续由 systemd 管理，
保留开机启动及失败重启设置。新增的路径覆盖文件为：

```text
/etc/systemd/system/lr-web-static.service.d/90-local-bundle.conf
/etc/systemd/system/lr-control-api.service.d/90-local-bundle.conf
```

前端使用当前目录的 `dist/` 和 `scripts/serve-static.cjs`，API 使用当前目录的
`apps/control-api/app/`，Python 环境沿用
`/home/boreas/miniconda3/envs/lr-control-api`。

## 配置和数据衔接

私有 `.env` 已复制到 `LR-Web/apps/control-api/.env`，权限为 0600，受 Git
忽略规则保护。数据库、MQTT 证书、BookArm Unix socket 和宿主启动代理沿用
原有配置。健康检查显示 PostgreSQL、MQTT connected；Redis 会话缓存仍使用
原有 memory 模式。

`LR-Web/apps/control-api/data` 链接到
`/home/boreas/LR-Web/apps/control-api/data`，继续使用现有地图和业务文件。
**旧目录仍承载这些数据和车端运行环境，请保留。**

本次切换范围为控制站前端与 API。ROS 导航、机械臂、建图代理、Docker
基础设施、平台启动及发现服务继续使用原有部署。
API 服务通过 `LR_ROBOT_ROOT` 指向实际运行的 ROS 工作区
`/home/boreas/LR-Web/external/Library_robot`。
地图注册脚本通过 `LR_REGISTER_ROBOT_MAP_SCRIPT` 指向本机 sudoers 已授权的
`/home/boreas/LR/Library_robot/scripts/register-robot-map.sh`。

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
