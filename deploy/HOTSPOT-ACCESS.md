# 热点与访客访问

## 交付目标

车载电脑自己提供 Wi-Fi 局域网。开机后，用户用手机或电脑连接“图书馆机器人”，输入热点密码 `12345678`，在浏览器访问固定地址 `http://192.168.4.1:8000`，以 `operator` / `123456` 登录。无需进入车载电脑桌面，也不依赖现场路由器或互联网。公开功能为作业、地图与导航、系统。

当前 `LR_5G` 仅用于维护联网，并非最终用户接入方案。现阶段不切换该网络；热点是否广播须以实际启用和客户端验收为准。

## 当前状态

- Web 前端和 control-api 已从当前项目目录运行，网页入口为 `8000`，`8001` 已停用。
- 本机网页为 <http://localhost:8000>；连接当前局域网时可访问 <http://192.168.3.22:8000>。
- 登录已开启。普通账号只显示作业、地图与导航、系统；调试中心的页面路由、控制 API 和 BookArm 代理均有服务端权限校验。
- 操作员账号为 `operator`，密码已按用户要求改为 `123456`，新密码登录成功、旧密码被拒绝。完整维护凭据保存在 `.local-deploy/hotspot-access.txt`（0600，目录 0700），不提交到 Git。API 服务重启或会话满 24 小时后需要重新登录。
- Bluetooth 开机常开，广播名称为“图书馆机器人”，保持可发现、可配对。已安装的 `lr-bluetooth.timer` 每 30 秒恢复这些设置。
- Wi-Fi 热点的服务 `lr-hotspot.service` 已安装，但目前已停止并禁用开机启动，避免中断现有无线网络；车载热点尚未广播。
- 系统另有 NetworkManager 的 `Hotspot` 配置（SSID 同为“图书馆机器人”）。已将此未启用的配置固定为 `192.168.4.1/24`、2.4 GHz 信道 6，保持 `autoconnect=no`。修改保存配置不会开启热点，也不代表客户端接入已经验收；不要在当前无线维护连接下直接激活它，否则会占用 `wlo1` 并中断 `LR_5G`。排查“连接热点后地址打不开”时，先确认实际启用的是哪种热点，以及客户端取得的 IP 和网关；仅保存配置不会产生 `192.168.4.1` 地址。

## 热点硬件限制

车载电脑当前只有一块 Intel Wi-Fi 网卡。它正在连接 5 GHz 的 `LR_5G`，而本机无线监管配置禁止该频段作为热点发射；这块网卡也不能在保持当前连接的同时将热点切到另一个信道。已验证 NetworkManager 的并发连接会因该限制启动失败。

当前保持 `LR_5G` 连接。脚本不包含断开网络、关闭 Wi-Fi 或改变默认路由的命令。两种交付模式都要求目标无线芯片没有已连接接口和已分配 IP；占用时直接拒绝启动。热点不会自动转发局域网或互联网流量。

### 方案 A：车载网卡专用于本地热点

这是无需上联 Wi-Fi 的车载独立运行模式，不强制增加第二块网卡。已准备配置示例 `deploy/etc-templates/hotspot-standalone.env.example`，尚未安装到系统。

该模式必须在现场安排切换或已有验证通过的备用维护网络时实施：预先确保 `wlo1` 不再被 NetworkManager 用于连接其他 Wi-Fi，将它保留给本地 AP；再部署 standalone 配置并启用热点服务。开机后不能让上联自动连接抢占这块无线芯片。此准备会改变现有联网方式，本次未执行。

当前只允许做只读检查：

```bash
LR_HOTSPOT_MODE=standalone LR_WIFI_STATION=wlo1 python3 deploy/scripts/robot-hotspot.py --check
```

如果当前仍连接 `LR_5G`，检查应拒绝启动并报告网卡正在使用；这不是热点故障，也不会自动断网。独立模式的广播、DHCP、重启自启尚未经过现场验收。

### 方案 B：保留上联，另一块网卡提供热点

这是当前需要保持 `LR_5G` 不断开时的并行部署方案。程序会校验物理无线芯片，而不是只比较接口名称。默认模式为 `isolated`。

没有第二块独立网卡时，isolated 模式启动前检查会直接拒绝运行，不会操作当前网络。增加网卡后，将服务的 `LR_WIFI_STATION` 指向新接口，并配置 `/etc/lr-platform/hotspot.env`：

```text
LR_WIFI_STATION=<USB-Wi-Fi-interface>
LR_UPSTREAM_WIFI=wlo1
LR_HOTSPOT_MODE=isolated
```

可先用只读检查确认网卡条件（把占位符替换为新接口名）：

```bash
LR_WIFI_STATION=<USB-Wi-Fi-interface> python3 deploy/scripts/robot-hotspot.py --check
```

检查通过后再启用服务，并检查热点广播和前端。此时只会在独立网卡上建立 `lr-ap0`，不会断开上联或调整系统默认路由：

```bash
sudo systemctl enable --now lr-hotspot.service
systemctl status lr-hotspot.service --no-pager
sudo hostapd_cli -p /run/lr-hotspot/hostapd -i lr-ap0 status
ip -4 address show lr-ap0
curl --fail http://192.168.4.1:8000/health
```

成功后，手机或电脑连接 SSID `图书馆机器人`，输入 Wi-Fi 密码 `12345678`，在浏览器打开 <http://192.168.4.1:8000>，再使用操作员网站账号登录。热点提供本地 DHCP 和 `robot.lan` 名称，不提供互联网出口。也可用 `http://robot.lan:8000`。

## Bluetooth

Bluetooth 当前用于广播身份、发现和配对。它不提供网络共享或网页入口；网页访问使用现有局域网或未来的 Wi-Fi 热点。已启用 `bluetooth.service` 和 `lr-bluetooth.timer`；定时器调用一次性的 `lr-bluetooth.service`，该服务执行完显示 inactive 属于正常现象。`12345678` 是 Wi-Fi 热点密码，Bluetooth 配对使用系统配对流程。

检查状态：

```bash
systemctl is-enabled lr-hotspot.service lr-bluetooth.timer
systemctl is-active lr-hotspot.service lr-bluetooth.timer bluetooth.service
journalctl -u lr-hotspot.service -u lr-bluetooth.service -n 50 --no-pager
```

登录页、三个公开模块及手机布局已部署。已复测 1440 px 桌面、360 px 手机竖屏和 844 px 横屏，9 个公开页面无整页横向溢出、脚本错误或业务 HTTP 错误。真实运行服务的地图图片、机器人和电池 WebSocket、登录退出及调试拒绝均验证通过；24 项权限测试、代理集成测试、TypeScript 检查均已通过。此前全量 201 项前端测试及 97 项相关 API 测试已通过。热点两种模式的防断网检查另有自动化测试。实际热点广播、手机 DHCP 接入与冷启动，需要在现场网络切换完成或独立网卡接入后验收。未执行机器人运动、取还书或导航动作。
