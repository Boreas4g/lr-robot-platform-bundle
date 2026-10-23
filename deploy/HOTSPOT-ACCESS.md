# 热点、局域网与访客访问

更新：2026-10-24。操作员可使用作业、地图与导航、系统；调试中心的页面和 API 仍受维护角色限制。操作步骤及 PDF 来源见[用户使用指南](../docs/用户使用指南.md)。

## 两种接入方式

| 模式 | 终端连接的网络 | 网页入口 |
| --- | --- | --- |
| 车载热点 | 图书馆机器人，默认密码 `12345678` | `http://192.168.4.1:8000` |
| 图书馆 Wi-Fi | 与车载电脑相同、允许设备互访的局域网 | `http://机器人当前IP:8000`，或页面显示的 .local 名称 |

网站操作员默认 `operator / 123456`；网站密码与 Wi-Fi 密码是两项。API 重启或会话满 24 小时后需重新登录。不同 IP/主机名属于不同浏览器来源，切换入口后也需登录。完整本机维护凭据位于 `.local-deploy/hotspot-access.txt`，不得提交 Git。

用户已反馈热点接入、登录和控制页面正常。本次开发验证时保留维护连接 LR_5G，没有激活或断开 Wi-Fi。当前地址只代表当时的路由器分配结果；不要把 192.168.3.22 写死为交付地址。实时状态在“系统 → 网络连接”查看。

## 网页切换流程

1. 确认机器人停止，没有执行中的作业、导航、手动控制或建图。历史排队、暂停记录不会单独阻止切换。
2. 登录 8000 端口控制台，打开“系统 → 网络连接”，选择网卡和 Wi-Fi。热点模式只显示缓存网络，避免主动扫描打断现有终端；未列出的网络可手动添加。
3. 输入目标密码，先保存名称入口，例如本机 `http://lr-control.local:8000/system/network`，并准备通过路由器查询 IP 的备用办法。
4. 勾选提示后确认。服务先返回任务，再延迟约 5 秒切换，单网卡热点会暂时消失。
5. 终端连接目标 Wi-Fi，点击页面“进入新网址”（优先跳转机器人在目标网络取得的新 IPv4 地址，`.local` 名称作备用），用原账号重新登录，在“系统 → 网络连接”点击“确认保留此连接”。只有经目标网卡的新地址访问才允许确认。提交被拒绝时页面会保留并显示原因，不会把旧排队/暂停记录误报成切换成功。
6. 从切换开始约 5 分钟未确认，或约 45 秒未获得 IPv4 地址，系统请求恢复原连接；NetworkManager 自身的检查点在代理故障时也保留超时恢复能力。以页面倒计时和结果为准。

确认后保存目标 Wi-Fi 及密码，当前可继续使用该网络。重启后默认优先启动已配置的 192.168.4.1/24 机器人热点；如需再次使用 Wi-Fi，从“系统 → 网络连接”切换。其他 Wi-Fi 配置仍保留。现场应保留有线或本地维护办法。

支持开放网络、WPA/WPA2-PSK 和 WPA3-SAE 个人网络；不处理企业 802.1X、网页认证或绕过访客隔离。名称发现依赖 Avahi/mDNS、终端和路由器支持；名称解析失败时使用路由器客户端列表中的 IP。建议管理员配置 DHCP 地址保留。功能不提供跨互联网控制。

## 服务与权限

```text
浏览器 :8000 /system/network
  → serve-static.cjs 同源代理（覆盖 X-LR-Local-Address）
  → control-api /api/v1/system/network（登录及角色验证）
  → /run/lr-network-agent/network.sock（root:服务用户组，0660）
  → lr-network-agent.service → NetworkManager D-Bus
```

API 以普通服务用户运行；网络代理提供固定的状态、扫描、连接、确认操作，不开放 shell 或任意命令。密码仅经请求体和本机 D-Bus 传递，不进入命令行、返回值、会话存储和应用日志。临时新连接先留在内存，确认后持久化；失败时恢复原网络并删除本次临时连接。

代理源码：`deploy/libexec/lr-network-agent.py`；单元：`deploy/systemd/lr-network-agent.service`；API 配置：`LR_NETWORK_AGENT_SOCKET=/run/lr-network-agent/network.sock`。代理启动和状态读取不改变网络，安装脚本不主动切换无线连接。

接口：`GET /api/v1/system/network`；`POST .../scan`、`POST .../connect`、`POST .../confirm`。全部要求网站登录，角色限系统管理员、维护人员和图书馆操作员。连接接口检查机器人任务状态。确认必须走 8000 生产代理，直接访问 8080 或普通 Umi 开发代理不属于受支持的交接入口。

新机适配脚本安装 python3-dbus、NetworkManager、Avahi 和 mDNS 解析支持，启用代理，按机器人身份设置主机名。见[迁移指南](MIGRATION-GUIDE.zh-CN.md)。不要对正在运行的机器人执行完整迁移 apply。

已安装机器的维护升级，在作业停止后执行（单元的 Group 必须改为实际 API 服务用户组）：

```bash
sudo install -D -o root -g root -m 0755 deploy/libexec/lr-network-agent.py /usr/local/libexec/lr-network-agent.py
sudo install -o root -g root -m 0644 deploy/systemd/lr-network-agent.service /etc/systemd/system/lr-network-agent.service
sudo systemctl daemon-reload
sudo systemctl enable --now lr-network-agent.service avahi-daemon.service
# 按 LOCAL-DEPLOYMENT.md 构建前端后，重启前后端加载新版本。
sudo systemctl restart lr-control-api.service lr-web-static.service
```

前提为系统已有 python3-dbus 和 Avahi；安装依赖时不得允许包管理器重启当前网络。上面的代理启动不激活任何 Wi-Fi。切勿为测试运行 nmcli connection up、重启 NetworkManager 或启停当前热点。

## 只读检查与问题定位

```bash
systemctl is-active lr-network-agent.service lr-control-api.service lr-web-static.service avahi-daemon.service
systemctl is-enabled lr-network-agent.service
curl --fail --unix-socket /run/lr-network-agent/network.sock http://localhost/status
curl --fail http://127.0.0.1:8000/health
nmcli -f DEVICE,TYPE,STATE,CONNECTION device status
journalctl -u lr-network-agent.service -n 50 --no-pager
```

- 页面报 503：检查代理、/usr/bin/python3 的 dbus 模块、socket 服务组是否与 API 用户匹配。
- 显示恢复未完成：不要连发切换请求；等待 NetworkManager 检查点超时，现场检查后再重启代理清理状态。
- 新 IP 可登录但不能确认：用目标网卡地址的 8000 入口，避免 localhost、另一块网卡或直接 8080。
- 切换后原 IP 不能访问：使用名称入口或查路由器 DHCP 客户端列表。
- 服务正常但终端打不开：确认同网段可互访、访客隔离、TCP 8000；不要对外开放后端、ROS/DDS、MQTT 或机械臂端口。

## 热点与蓝牙限制

固定热点由 NetworkManager 的 AP 连接管理，IPv4 共享模式地址为 192.168.4.1/24。只保存配置不会立即广播热点。网页仅列出该网卡已存在且地址正确的 AP 配置；不改变热点名称和密码。

单网卡并发取决于硬件、驱动和信道，当前功能采用模式切换。需要热点与上联 Wi-Fi 长期同时存在时，建议两块独立网卡。历史 lr-hotspot.service / robot-hotspot.py 使用 hostapd，不能与 NetworkManager 在同一网卡同时运行；网页模块管理 NetworkManager 接口，迁移安装器默认停用旧热点服务。

Bluetooth 身份发现和配对由 lr-bluetooth.timer 维持，名称为“图书馆机器人”，不承担网页网络共享。热点密码不是蓝牙配对码。

## 验证范围

自动测试模拟连接与恢复动作，涵盖权限、校验、幂等、错误密码、无 DHCP、超时恢复、错误入口拒绝确认及保存失败恢复；不连接或断开现场 Wi-Fi。真实跨网络切换、终端重连及冷启动重连仍需现场使用者在可恢复的条件下验收，不能用单元测试代替无线硬件验收。
