# 私有配置文件清单（未纳入本备份）

按项目安全规则（`/home/boreas/LR/AGENTS.md`、`Library_robot/AGENTS.md`：
「不得将私钥、MQTT 密码、证书或 /etc/lr-robot/ 私有配置提交到 Git」），
下列**线上私有配置与凭据一律未纳入**本备份与 Git 仓库。恢复系统时需从本机
原位置或加密备份渠道获取。

## /etc/lr-bookarm/

| 文件 | 用途（来源：引用它的公开代码） |
| --- | --- |
| `bookarm.env` | BookArm Bearer token（`LR_BOOKARM_TOKEN`），被 `lr-bookarm-takeout.service`、`lr-web-static.service`、libexec 启动脚本引用 |

## /etc/lr-robot/

| 文件/目录 | 用途 |
| --- | --- |
| `runtime.env` | 车端运行时变量：选择私有 Gateway 参数文件（`LR_GATEWAY_PARAMS_FILE` 等），见 `Library_robot/scripts/start-robot-runtime.sh` |
| `bookarm.env` | BookArm 本机服务 token |
| `edge-gateway.yaml` | Edge Gateway 私有参数（MQTT/mTLS 接入） |
| `auto-localization.yaml` | 自动定位私有参数 |
| `map-registry.yaml` / `map-sync.yaml` | 地图注册表 / 地图同步（mTLS）配置 |
| `xt369p-battery.yaml` | 电池遥测串口配置 |
| `mqtt/` | 车端 MQTT mTLS 客户端证书与私钥 |
| `staging/`、`backups/`、大量 `*.bak` | 配置历史快照 |

## /etc/lr-platform/

| 文件/目录 | 用途 |
| --- | --- |
| `platform.env` | 控制站平台环境变量（被 `lr-platform.service` → `start-platform.sh` 引用） |
| `platform-pki.env` | 平台 PKI 参数 |
| `discovery.json` | 局域网发现广播配置（`lr-station-discovery.service`） |
| `cruise-points.yaml` | 巡航点位 |
| `client-ca.crt` / `mqtt-certs/` / `web-certs/` | mTLS CA、MQTT 服务端与 Web 证书私钥 |
| `emqx-users.csv` | EMQX 账号 |
| `bookarm-start-policy.conf` | BookArm 启动策略 |

## 其他已排除的敏感/密钥材料

- `LR-Web/apps/control-api/.env`（control-api 真实环境变量；模板见同目录 `.env.example`）
- `protection/protection-src/keys/`（Ed25519 许可证签名私钥，本机位于 `~/lr-protection-build/protection-src/keys/`）
- `~/lr-protection-build/license.lic`（本机已签发许可证）
- `~/lr-backup-stage/`（2026-10-13 旧一键备份暂存，内含上述多类凭据与私钥，整体未纳入）
