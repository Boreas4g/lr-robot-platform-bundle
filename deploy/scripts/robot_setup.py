#!/usr/bin/env python3
"""Library robot appliance migration. No network activation during apply.

Only scan, export-baseline, init, plan and check are safe on a running robot.
apply is an installer for a stopped/new appliance; --start explicitly starts hardware.
"""
from __future__ import annotations

import argparse
import grp
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import pwd
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "LR-Web"
ROS = WEB / "external/Library_robot"
ARM = WEB / "external/lingzu-bookarm-py/bookarm"
ROLES = ("laser_port", "laser_back", "chassis_serial_port", "imu_port", "lift_port", "rodmotor")
CORE = ["lr-platform.service", "lr-control-api.service", "lr-web-static.service",
        "lr-host-start-agent.service", "lr-network-agent.service", "lr-robot-mapping-agent.service", "lr-xt369-usb.service"]
HARDWARE = ["lr-bookarm-can.service", "lr-bookarm-takeout.service", "lr-robot-runtime.service"]
RETIRED = ["lr-web-dev.service", "lr-bookarm-runtime.service", "lr-xt369p-battery.service",
           "lr-xt369p-rfcomm.service", "lr-robot-map-sync.timer", "lr-hotspot.service",
           "lr-station-discovery.service"]


class SetupError(Exception):
    pass


def run(argv, *, capture=False, check=True, **kwargs):
    result = subprocess.run([str(x) for x in argv], text=True,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None, **kwargs)
    if check and result.returncode:
        # Config-dependent subprocess output may contain credentials. Keep it out of errors.
        raise SetupError(f"命令失败（退出码 {result.returncode}）：{argv[0]}；请在本机检查，未输出私有配置。")
    return result


def yaml_module():
    try:
        import yaml
    except ImportError as exc:
        raise SetupError("缺少 python3-yaml；导出基线前先安装 sudo apt install python3-yaml") from exc
    return yaml


def read_yaml(path):
    return yaml_module().safe_load(Path(path).read_text())


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_private(path, content, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".lr-setup-")
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content.encode() if isinstance(content, str) else content)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def env_text(values):
    # Compatible with bash source, systemd EnvironmentFile and python-dotenv.
    return "".join(f"{key}={shlex.quote(str(value))}\n" for key, value in values.items())


def read_env(path):
    result = {}
    for line in Path(path).read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        tokens = shlex.split(value, comments=True)
        result[key.removeprefix("export ").strip()] = tokens[0] if tokens else ""
    return result


def udev_properties(path):
    result = run(["udevadm", "info", "--query=property", f"--name={path}"], capture=True, check=False)
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


def scan():
    devices = []
    for path in sorted(Path("/sys/class/tty").glob("tty*")):
        if not path.name.startswith(("ttyUSB", "ttyACM")):
            continue
        properties = udev_properties("/dev/" + path.name)
        devices.append({"device": "/dev/" + path.name,
                        **{key: properties.get(key, "") for key in
                           ("ID_VENDOR_ID", "ID_MODEL_ID", "ID_SERIAL_SHORT", "ID_PATH")},
                        "aliases": properties.get("DEVLINKS", "").split()})
    wifi = []
    for path in sorted(Path("/sys/class/net").glob("*")):
        if (path / "wireless").exists() or (path / "phy80211").exists():
            wifi.append({"interface": path.name, "mac": (path / "address").read_text().strip(),
                         "phy": (path / "phy80211").resolve().name})
    # Enumerate sysfs only: never open serial/CAN/video devices or send probe frames.
    cameras = set()
    for path in Path("/sys/bus/usb/devices").glob("*"):
        try:
            if (path / "idVendor").read_text().strip() == "8086" and "RealSense" in (path / "product").read_text():
                cameras.add((path / "serial").read_text().strip())
        except OSError:
            pass
    return {"serial_devices": devices, "wifi": wifi, "realsense_serials": sorted(cameras)}


def source_files():
    result = run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                 cwd=ROOT, capture=True, check=False)
    if result.returncode:
        # The handoff archive deliberately omits .git. Re-export only its
        # original approved source paths, never arbitrary files on the appliance.
        source_manifest = ROOT / ".local-deploy/migration-baseline/versions/source.json"
        if not source_manifest.is_file():
            raise SetupError("没有 Git 源文件清单或交付基线；请使用完整交付包导出")
        names = list(json.loads(source_manifest.read_text()))
    else:
        names = result.stdout.split("\0")
    files = {}
    for name in names:
        p = Path(name)
        if not name or p.parts[0] not in {"LR-Web", "drivers", "deploy", "xt369_linux", "docs", "README.md", ".gitignore"}:
            continue
        # Generated/runtime assets are deliberately excluded even if not yet ignored.
        if any(x in p.parts for x in ("dist", "node_modules", "recordings", "log", "build", "install", "data", "weights")) or any(x.startswith(".setup-previous-") for x in p.parts):
            continue
        if (p.name.startswith(".env") and not p.name.endswith(".example")) or p.suffix in {".key", ".pem", ".p12", ".pfx"}:
            continue
        file = ROOT / name
        if file.is_file() and not file.is_symlink() and file.suffix not in {".pdf", ".pyc"}:
            files[name] = digest(file)
    return files


def export_baseline(destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise SetupError("基线目录已存在；请用新目录导出，旧基线不会被覆盖。")
    destination.mkdir(parents=True, mode=0o700)
    provenance = {}

    def save(relative, data):
        write_private(destination / relative, data)

    def copy_file(source, relative):
        source = Path(source)
        if not source.is_file():
            raise SetupError(f"缺少基线文件：{source}")
        save(relative, source.read_bytes())
        provenance[relative] = str(source)

    gateway = read_yaml("/etc/lr-robot/edge-gateway.yaml")
    params = gateway["edge_gateway_node"]["ros__parameters"]
    # Strip identities, endpoints, keys and credentials from the exported gateway.
    for key in list(params):
        if key.startswith("mqtt_") or key in {"robot_id", "map_state_file", "map_registry_file", "bookarm_takeout_token"}:
            del params[key]
    save("robot/gateway.json", json_text(gateway))
    auto = read_yaml("/etc/lr-robot/auto-localization.yaml")
    save("robot/auto-localization.json", json_text(auto))
    registry = read_yaml("/etc/lr-robot/map-registry.yaml")
    maps = registry.get("maps", {})
    for map_id, entry in maps.items():
        if not re.fullmatch(r"MAP-[A-Za-z0-9_-]{1,80}", map_id):
            raise SetupError("地图 ID 不合法")
        original = Path(entry["yamlPath"])
        metadata = read_yaml(original)
        image = Path(metadata["image"])
        image = image if image.is_absolute() else original.parent / image
        copy_file(image, f"maps/{map_id}/map.pgm")
        metadata["image"] = "map.pgm"
        save(f"maps/{map_id}/map.yaml", yaml_module().safe_dump(metadata, allow_unicode=True))
        entry["yamlPath"] = f"maps/{map_id}/map.yaml"
    save("robot/map-registry.json", json_text(registry))
    # Export the configs actually read by the current takeout service, not stale private examples.
    config_env = read_env("/etc/lr-bookarm/bookarm.env")
    for name in ("camera", "lift", "rod", "arm"):
        source = ARM / f"config/devices/{name}.json"
        if config_env.get("LR_BOOKARM_CONFIG_DIR"):
            source = Path(config_env["LR_BOOKARM_CONFIG_DIR"]) / f"devices/{name}.json"
            copy_file(source, f"bookarm/devices/{name}.json")
            continue
        if name in {"arm", "rod"} or not source.is_file():
            python = Path("/home/boreas/miniconda3/envs/bookarm/bin/python")
            # Locate the configured interpreter on machines already installed by this tool.
            if (ROOT / ".venv-bookarm/bin/python").exists():
                python = ROOT / ".venv-bookarm/bin/python"
            config_env = read_env("/etc/lr-bookarm/bookarm.env")
            if config_env.get("LR_BOOKARM_CONFIG_DIR"):
                source = Path(config_env["LR_BOOKARM_CONFIG_DIR"]) / f"devices/{name}.json"
            else:
                module, cls = {"arm": ("arm", "ArmDeviceConfig"), "rod": ("rod", "RodDeviceConfig"),
                               "camera": ("camera", "D435BookSpineLocatorConfig"), "lift": ("lift", "LiftDeviceConfig")}[name]
                code = (f"from bookarm.devices.{module}.service import {cls}; "
                        "import json,dataclasses; " + f"print(json.dumps(dataclasses.asdict({cls}()),default=str))")
                result = run([python, "-c", code], capture=True, env={**os.environ, "PYTHONPATH": str(ARM / "src")})
                config = json.loads(result.stdout)
                for key in list(config):
                    if key.endswith(("_path", "_dir")):
                        config.pop(key)
                save(f"bookarm/devices/{name}.json", json_text(config))
                provenance[f"bookarm/devices/{name}.json"] = f"{cls} runtime defaults"
                continue
        copy_file(source, f"bookarm/devices/{name}.json")
    for name in ("book_stand_slots", "book_stand_pickup_slots", "camera_to_base"):
        if config_env.get("LR_BOOKARM_CONFIG_DIR"):
            candidates = [Path(config_env["LR_BOOKARM_CONFIG_DIR"]) / f"calibration/{name}.json"]
        elif name == "camera_to_base":
            candidates = [ARM / f"config/calibration/{name}.json", ARM / f"config/calibration/{name}.example.json"]
        else:
            candidates = [Path(f"/etc/lr-bookarm/config/calibration/{name}.json"), ARM / f"config/calibration/{name}.json"]
        copy_file(next((p for p in candidates if p.is_file()), candidates[0]), f"bookarm/calibration/{name}.json")
    inertia = (Path(config_env["LR_BOOKARM_CONFIG_DIR"]) / "calibration/arm_inertia.yaml" if config_env.get("LR_BOOKARM_CONFIG_DIR")
               else WEB / "external/lingzu-bookarm-py/resources/config/inertia_params.yaml")
    if not inertia.is_file():
        inertia = ARM / "config/calibration/arm_inertia.example.yaml"
    copy_file(inertia, "bookarm/calibration/arm_inertia.yaml")
    for name in ("take_profile", "return_profile", "midreturn_profile"):
        source = ARM / f"recordings/tuning/{name}.json"
        if source.exists():
            copy_file(source, f"tuning/{name}.json")
    for relative in ("src/car_ctrl/config/ddsm_hat_diff_drive.yaml", "src/lslidar_driver/params/lsx10_1.yaml",
                     "src/lslidar_driver/params/lsx10_2.yaml"):
        copy_file(ROS / relative, "ros/" + relative)
    weights = Path(config_env.get("LR_BOOKARM_YOLO_WEIGHTS") or WEB / "external/lingzu-bookarm-py/book_spine_inference_light/weights/best.pt")
    copy_file(weights, "assets/best.pt")
    battery = {"capacity_ah": None, "nominal_voltage_v": None, "serial": ""}
    state_path = Path("/var/lib/lr-platform/battery/state.sqlite3")
    if state_path.exists():
        import sqlite3
        with sqlite3.connect(state_path.as_uri() + "?mode=ro", uri=True) as connection:
            row = connection.execute("SELECT state FROM battery WHERE id=1").fetchone()
        if row:
            state = json.loads(row[0])
            battery.update(capacity_ah=state.get("capacityAh"), nominal_voltage_v=state.get("nominalVoltageV"))
    save("robot/battery.json", json_text(battery))
    # Capture full installed distributions, excluding editable/project-specific paths.
    for name, candidates in {
        "api": [ROOT / ".venv-api/bin/python", Path("/home/boreas/miniconda3/envs/lr-control-api/bin/python")],
        "bookarm": [ROOT / ".venv-bookarm/bin/python", Path("/home/boreas/miniconda3/envs/bookarm/bin/python")],
    }.items():
        python = next((p for p in candidates if p.exists()), None)
        if not python:
            raise SetupError(f"找不到现有 {name} Python 环境，不能生成可靠版本锁")
        code = ("import importlib.metadata as m,json,sys; "
                "print(json.dumps({'python':sys.version.split()[0], 'packages':"
                "{d.metadata['Name']:d.version for d in m.distributions() "
                "if d.metadata['Name'].lower().replace('_','-') not in ('bookarm','aim-sdk','lr-control-api','xt369-linux')}}))")
        info = json.loads(run([python, "-c", code], capture=True).stdout)
        save(f"versions/{name}.json", json_text(info))
        save(f"versions/{name}.txt", "".join(f"{k}=={v}\n" for k, v in sorted(info["packages"].items())))
    images = {}
    for service in ("postgres", "redis", "minio", "emqx"):
        ids = run(["docker", "ps", "-q", "--filter", f"label=com.docker.compose.service={service}"], capture=True).stdout.split()
        if len(ids) != 1:
            raise SetupError(f"需要恰好一个运行中的 {service} 容器来锁定镜像")
        image_id = run(["docker", "inspect", "--format", "{{.Image}}", ids[0]], capture=True).stdout.strip()
        meta = json.loads(run(["docker", "image", "inspect", image_id], capture=True).stdout)[0]
        if not meta.get("RepoDigests"):
            raise SetupError(f"{service} 镜像没有仓库摘要；请先为该镜像准备可拉取摘要")
        images[service] = meta["RepoDigests"][0]
    save("versions/images.json", json_text(images))
    node = run(["node", "--version"], capture=True).stdout.strip()
    save("versions/host.json", json_text({"node": node, "os": Path("/etc/os-release").read_text(), "architecture": os.uname().machine}))
    dpkg = run(["dpkg-query", "-W", "-f=${binary:Package}\t${Version}\n"], capture=True)
    save("versions/dpkg.tsv", dpkg.stdout)
    save("reference-hardware.json", json_text(scan()))
    save("provenance.json", json_text(provenance))
    save("versions/source.json", json_text(source_files()))
    hashes = {str(p.relative_to(destination)): digest(p) for p in destination.rglob("*") if p.is_file()}
    save("manifest.json", json_text({"schema": 1, "created_at": datetime.now(timezone.utc).isoformat(), "files": hashes}))
    print(f"基线已导出：{destination}\n包含依赖锁、镜像摘要、硬件参数、地图与权重；未导出证书、令牌、数据库或历史任务。")


def init_profile(path, baseline, robot_id):
    path = Path(path).resolve()
    if path.exists():
        raise SetupError("配置文件已存在，不覆盖")
    hw = scan()
    devices = {}
    for role in ROLES:
        found = next((d for d in hw["serial_devices"] if f"/dev/{role}" in d["aliases"]), {})
        devices[role] = {"vid": found.get("ID_VENDOR_ID", ""), "pid": found.get("ID_MODEL_ID", ""),
                         "serial": found.get("ID_SERIAL_SHORT", ""), "id_path": found.get("ID_PATH", "")}
    user = os.environ.get("SUDO_USER") or pwd.getpwuid(os.getuid()).pw_name
    gateway = json.loads((Path(baseline) / "robot/gateway.json").read_text())
    profile = {"schema": 1, "robot_id": robot_id, "robot_name": "图书馆机器人", "service_user": user,
               "baseline": str(Path(baseline).resolve()), "camera_serial": hw["realsense_serials"][0] if len(hw["realsense_serials"]) == 1 else "",
               "devices": devices, "camera": {}, "arm": {}, "lift": {}, "rod": {},
               "battery": json.loads((Path(baseline) / "robot/battery.json").read_text()),
               "hotspot": {"enabled": True, "interface": "", "mac": "", "ssid": "图书馆机器人",
                           "password": "12345678", "address": "192.168.4.1/24", "channel": 6},
               "bluetooth_name": "图书馆机器人", "operator_password": "123456",
               "active_map_id": gateway["edge_gateway_node"]["ros__parameters"].get("active_map_id", ""),
               "hardware_autostart": True, "calibration_reviewed": False, "map_site_reviewed": False,
               "site_start_confirmed": False}
    write_private(path, json_text(profile))
    print(f"新机器配置已生成：{path}\n请确认串口用途、相机、热点网卡、地图及标定，再运行 plan。scan 不会猜测前后雷达。")


def load_profile(path):
    path = Path(path).resolve()
    p = json.loads(path.read_text())
    p["baseline"] = str((path.parent / p["baseline"]).resolve())
    return p


def verify_baseline(baseline, verify_source=True):
    baseline = Path(baseline)
    manifest = json.loads((baseline / "manifest.json").read_text())
    if manifest.get("schema") != 1:
        raise SetupError("不支持的基线版本")
    for name, expected in manifest["files"].items():
        path = (baseline / name).resolve()
        if not path.is_relative_to(baseline.resolve()) or not path.is_file() or digest(path) != expected:
            raise SetupError(f"基线校验失败：{name}")
    if verify_source:
        expected = json.loads((baseline / "versions/source.json").read_text())
        changed = [name for name, checksum in expected.items() if not (ROOT / name).is_file() or digest(ROOT / name) != checksum]
        if changed:
            raise SetupError(f"项目代码与基线不同，共 {len(changed)} 项；第一项：{changed[0]}。请复制同一份完整源码或重新导出基线。")


def validate(p):
    if p.get("schema") != 1 or not re.fullmatch(r"LR-[A-Za-z0-9_-]+", p.get("robot_id", "")):
        raise SetupError("schema/robot_id 不合法")
    if not re.fullmatch(r"[a-z_][a-z0-9_-]*", p.get("service_user", "")) or p["service_user"] == "root":
        raise SetupError("service_user 必须是已有的普通 Linux 用户")
    try:
        if pwd.getpwnam(p["service_user"]).pw_uid == 0:
            raise SetupError("service_user 不能使用 UID 0")
    except KeyError as exc:
        raise SetupError("service_user 不存在，请先创建普通用户") from exc
    if not re.fullmatch(r"/[A-Za-z0-9_./+-]+", str(ROOT)):
        raise SetupError("项目目录请仅使用英文字母、数字、下划线、点、横杠或加号，避免 systemd 路径转义")
    if "\\u0000" in json.dumps(p):
        raise SetupError("配置含非法字符")
    for value in (p.get("robot_name", ""), p.get("bluetooth_name", ""), p.get("operator_password", "")):
        if not value or any(c in value for c in "\n\r\x00"):
            raise SetupError("名称/密码不能为空或含换行")
    if len(p["operator_password"]) < 6:
        raise SetupError("网站密码至少 6 位")
    battery = p["battery"]
    for key in ("capacity_ah", "nominal_voltage_v"):
        value = battery.get(key)
        if value is not None and (type(value) not in (float, int) or not 0 < value < 10000):
            raise SetupError("电池容量与标称电压必须为正数，未知时使用 null")
    if battery.get("serial") and not re.fullmatch(r"[A-Za-z0-9_.:-]+", battery["serial"]):
        raise SetupError("XT369 序列号格式不合法")
    hp = p["hotspot"]
    if hp["address"] != "192.168.4.1/24":
        raise SetupError("本交付固定热点地址 192.168.4.1/24")
    if hp["enabled"]:
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,15}", hp["interface"]):
            raise SetupError("请填写热点网卡接口名，可用 scan 查看")
        if hp.get("mac") and not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", hp["mac"]):
            raise SetupError("热点 MAC 格式错误")
        if not 1 <= len(hp["ssid"].encode()) <= 32 or hp["ssid"] != hp["ssid"].strip() or any(c in hp["ssid"] for c in "\n\r\t\\;"):
            raise SetupError("热点名称必须为 1–32 字节且不能含换行、反斜杠或分号")
        if not 8 <= len(hp["password"]) <= 63 or not hp["password"].isascii() or hp["password"] != hp["password"].strip() or any(c in hp["password"] for c in "\n\r\t\\;"):
            raise SetupError("WPA2 热点密码必须为 8–63 位 ASCII 字符；123456 仅可作网站密码")
        if not isinstance(hp["channel"], int) or hp["channel"] not in range(1, 12):
            raise SetupError("热点信道必须为 1–11")
    for key in ("hardware_autostart", "calibration_reviewed", "map_site_reviewed", "site_start_confirmed"):
        if type(p.get(key)) is not bool:
            raise SetupError(f"{key} 必须为 JSON 布尔值 true/false")
    if type(hp["enabled"]) is not bool:
        raise SetupError("hotspot.enabled 必须为 JSON 布尔值")
    if p["hardware_autostart"]:
        if not all(p.get(k) is True for k in ("calibration_reviewed", "map_site_reviewed", "site_start_confirmed")):
            raise SetupError("硬件自启前需在配置中确认 calibration_reviewed、map_site_reviewed、site_start_confirmed。详见迁移指南。")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", p.get("camera_serial", "")):
            raise SetupError("请填写新机器相机序列号")
        seen = set()
        for role in ROLES:
            d = p["devices"].get(role, {})
            if not all(re.fullmatch(r"[0-9a-fA-F]{4}", d.get(k, "")) for k in ("vid", "pid")):
                raise SetupError(f"{role} 缺少 USB VID/PID")
            if not d.get("serial") and not d.get("id_path"):
                raise SetupError(f"{role} 必须按唯一序列号或 USB 物理路径绑定")
            for key in ("serial", "id_path"):
                if d.get(key) and not re.fullmatch(r"[A-Za-z0-9_:.+/-]+", d[key]):
                    raise SetupError(f"{role} 的 {key} 不合法")
            selector = (d["vid"], d["pid"], "serial" if d.get("serial") else "id_path", d.get("serial") or d["id_path"])
            if selector in seen:
                raise SetupError("多个设备角色绑定了同一硬件，不能部署")
            seen.add(selector)
    for name in ("camera", "lift", "rod", "arm"):
        if not isinstance(p.get(name), dict):
            raise SetupError(f"{name} 必须是配置对象")
        baseline_fields = json.loads((Path(p["baseline"]) / f"bookarm/devices/{name}.json").read_text())
        if set(p[name]) - set(baseline_fields):
            raise SetupError(f"{name} 包含基线没有的字段，不能静默忽略")
    if "serial" in p["camera"]:
        raise SetupError("相机序列号只能在 camera_serial 配置，避免两处冲突")
    if p["arm"].get("backend", "socketcan") != "socketcan" or not re.fullmatch(r"can[0-9]+", p["arm"].get("can_interface", "can0")):
        raise SetupError("本安装器支持 socketcan 的 canN 接口")
    if p["arm"].get("can_bitrate", 1000000) not in (125000, 250000, 500000, 1000000):
        raise SetupError("CAN 波特率不合法")
    registry = json.loads((Path(p["baseline"]) / "robot/map-registry.json").read_text())
    if p["active_map_id"] not in registry["maps"]:
        raise SetupError("active_map_id 不在基线地图注册表中")


def service_group(p):
    return grp.getgrgid(pwd.getpwnam(p["service_user"]).pw_gid).gr_name


def check_hardware_bindings(p):
    """Compare selectors against sysfs only; never open or claim a device."""
    hw = scan()
    if p["hardware_autostart"]:
        if p["camera_serial"] not in hw["realsense_serials"]:
            raise SetupError("配置的 RealSense 相机未接入；用 scan 核对新机器序列号")
        for role in ROLES:
            d = p["devices"][role]
            key, value = ("ID_SERIAL_SHORT", d["serial"]) if d.get("serial") else ("ID_PATH", d["id_path"])
            matches = [item for item in hw["serial_devices"] if item.get("ID_VENDOR_ID", "").lower() == d["vid"].lower()
                       and item.get("ID_MODEL_ID", "").lower() == d["pid"].lower() and item.get(key) == value]
            if len(matches) != 1:
                raise SetupError(f"{role} 绑定未唯一匹配已接入设备；用 scan 核对 VID/PID、序列号及物理路径")
    if p["hotspot"]["enabled"]:
        h = p["hotspot"]
        device = next((item for item in hw["wifi"] if item["interface"] == h["interface"]), None)
        if not device or (h.get("mac") and h["mac"].lower() != device["mac"].lower()):
            raise SetupError("热点网卡不存在或 MAC 不匹配；必须填写新机器的实际无线网卡")
        if shutil.which("iw"):
            info = run(["iw", "phy", device["phy"], "info"], capture=True)
            modes = info.stdout.split("Supported interface modes:", 1)[-1].split("Band ", 1)[0]
            if not re.search(r"^\s*\* AP\s*$", modes, re.M):
                raise SetupError("所选无线网卡未声明支持 AP 热点模式")
            channel = re.search(r"\*\s+\d+(?:\.\d+)? MHz \[" + str(h["channel"]) + r"\]([^\n]*)", info.stdout)
            if not channel or any(flag in channel.group(1).lower() for flag in ("disabled", "no ir", "no-ir")):
                raise SetupError("所选热点信道不能广播；请核对无线网卡和国家/地区频段设置")
        if shutil.which("ip"):
            addresses = json.loads(run(["ip", "-j", "-4", "addr", "show"], capture=True).stdout)
            subnet = ipaddress.ip_network("192.168.4.0/24")
            for item in addresses:
                if item["ifname"] == h["interface"]:
                    continue
                for address in item.get("addr_info", []):
                    other = ipaddress.ip_network(f"{address['local']}/{address['prefixlen']}", strict=False)
                    if other.overlaps(subnet):
                        raise SetupError("另一网卡当前使用与 192.168.4.0/24 重叠的网络；请先规划独立上联网段")


def pack(baseline, destination):
    """Create a source + private baseline handoff, excluding live state and keys."""
    baseline, destination = Path(baseline).resolve(), Path(destination).resolve()
    verify_baseline(baseline)
    if destination.exists():
        raise SetupError("交付包已存在，不覆盖")
    destination.parent.mkdir(parents=True, exist_ok=True)
    sources = json.loads((baseline / "versions/source.json").read_text())
    with destination.open("xb") as stream:
        os.chmod(destination, 0o600)
        with tarfile.open(fileobj=stream, mode="w:gz", dereference=True) as archive:
            for name in sorted(sources):
                archive.add(ROOT / name, arcname=f"lr-robot-platform-bundle/{name}", recursive=False)
            for path in sorted(baseline.rglob("*")):
                if path.is_file():
                    archive.add(path, arcname=f"lr-robot-platform-bundle/.local-deploy/migration-baseline/{path.relative_to(baseline)}", recursive=False)
    checksum = digest(destination)
    write_private(str(destination) + ".sha256", f"{checksum}  {destination.name}\n")
    print(f"交付包：{destination}\nSHA256：{checksum}\n包含源码、版本锁、地图、标定和权重；不含当前机器身份凭据、数据库和运行状态。")


def enabled_units(p):
    return CORE + (HARDWARE if p["hardware_autostart"] else []) + ["lr-bluetooth.timer"]


def hotspot_keyfile(p, connection_uuid):
    h = p["hotspot"]
    mac = f"mac-address={h['mac']}\n" if h.get("mac") else ""
    return (f"[connection]\nid=lr-robot-hotspot\nuuid={connection_uuid}\ntype=wifi\ninterface-name={h['interface']}\n"
            "autoconnect=true\nautoconnect-priority=100\n\n[wifi]\nmode=ap\nband=bg\n"
            f"channel={h['channel']}\nssid={h['ssid']}\n{mac}\n[wifi-security]\nkey-mgmt=wpa-psk\n"
            f"proto=rsn;\npairwise=ccmp;\ngroup=ccmp;\npsk={h['password']}\n\n"
            "[ipv4]\nmethod=shared\naddress1=192.168.4.1/24\nnever-default=true\n\n[ipv6]\nmethod=disabled\n")


def udev_rules(p):
    lines = ["# Generated by deploy/robot-setup.sh; stable per-robot USB bindings."]
    for role in ROLES if p["hardware_autostart"] else ():
        d = p["devices"].get(role, {})
        if not d.get("vid"):
            continue
        selector = f'ATTRS{{serial}}=="{d["serial"]}"' if d.get("serial") else f'ENV{{ID_PATH}}=="{d["id_path"]}"'
        lines.append(f'SUBSYSTEM=="tty", ATTRS{{idVendor}}=="{d["vid"].lower()}", ATTRS{{idProduct}}=="{d["pid"].lower()}", '
                     f'{selector}, GROUP="dialout", MODE="0660", SYMLINK+="{role}"')
    lines.append(f'SUBSYSTEM=="hidraw", ATTRS{{idVendor}}=="0483", ATTRS{{idProduct}}=="5750", '
                 f'ATTRS{{product}}=="ATORCH XT369P*", GROUP="{service_group(p)}", MODE="0660"')
    lines.append('SUBSYSTEM=="usb", ATTR{idVendor}=="8086", ATTR{product}=="*RealSense*", GROUP="video", MODE="0660"')
    return "\n".join(lines) + "\n"


def render_units(p):
    user = p["service_user"]
    group = service_group(p)
    units = {}
    names = CORE + HARDWARE + ["lr-robot-mapping.service", "lr-bluetooth.service", "lr-bluetooth.timer"]
    for name in names:
        text = (ROOT / "deploy/systemd" / name).read_text()
        text = text.replace("/home/boreas/lr-robot-platform-bundle", str(ROOT))
        text = text.replace("User=boreas", f"User={user}").replace("Group=boreas", f"Group={group}")
        text = text.replace("/home/boreas/miniconda3/envs/lr-control-api/bin", str(ROOT / ".venv-api/bin"))
        text = text.replace("/usr/bin/node scripts/serve-static.cjs", "/opt/lr-node/bin/node scripts/serve-static.cjs")
        if name == "lr-control-api.service":
            text = text.replace("--host 0.0.0.0", "--host 127.0.0.1")
            text = text.replace("WorkingDirectory=", "EnvironmentFile=/etc/lr-platform/control-api.env\nWorkingDirectory=", 1)
        if name == "lr-xt369-usb.service":
            if p["battery"].get("serial"):
                text = text.replace("--state /var/lib/lr-platform/battery/state.sqlite3",
                                    "--state /var/lib/lr-platform/battery/state.sqlite3 --serial " + p["battery"]["serial"])
        if name == "lr-web-static.service":
            text = text.replace("Wants=network-online.target", "Wants=network-online.target\nRequires=lr-platform.service")
        if name == "lr-bookarm-takeout.service":
            text = text.replace("--pickup-slots-path /etc/lr-bookarm/config/calibration/book_stand_pickup_slots.json",
                                "--pickup-slots-path /etc/lr-bookarm/config/calibration/book_stand_pickup_slots.json "
                                "--camera-calibration /etc/lr-bookarm/config/calibration/camera_to_base.json "
                                "--arm-inertia-config /etc/lr-bookarm/config/calibration/arm_inertia.yaml")
            text = text.replace("[Service]", f"[Service]\nGroup={group}")
        if name == "lr-bookarm-can.service":
            channel = p["arm"].get("can_interface", "can0")
            rate = p["arm"].get("can_bitrate", 1000000)
            text = text.replace("can0", channel).replace(" 1000000", f" {rate}")
        if name == "lr-robot-runtime.service":
            text = text.replace("Wants=network-online.target", "Wants=network-online.target\nAfter=lr-platform.service")
        units[name] = text
    return units


def apply_profile(p, profile_path, *, install_deps, start):
    if os.geteuid() != 0:
        raise SetupError("apply 需要 sudo；plan/scan/check 不需要管理员权限")
    # Never reconfigure a live appliance, even when --start was supplied.
    for unit in CORE + HARDWARE + ["lr-robot-mapping.service", "lr-bookarm-runtime.service"]:
        if run(["systemctl", "is-active", "--quiet", unit], check=False, capture=True).returncode == 0:
            raise SetupError(f"{unit} 正在运行；本安装器用于新机器或现场已停机的迁移，未修改任何配置。")
    os_release = read_env("/etc/os-release")
    if os_release.get("ID") != "ubuntu" or os_release.get("VERSION_ID") != "24.04" or os.uname().machine != "x86_64":
        raise SetupError("当前基线安装器支持 Ubuntu 24.04 x86_64 / ROS 2 Jazzy；其他架构需要另建依赖基线")
    if Path("/etc/lr-platform/setup-secrets.json").exists():
        existing = json.loads(Path("/etc/lr-platform/setup-secrets.json").read_text())
        if existing["robot_id"] != p["robot_id"]:
            raise SetupError("已安装的机器人身份不同；拒绝覆盖")
    check_hardware_bindings(p)
    from robot_bootstrap import bootstrap
    bootstrap(p, install_deps=install_deps)
    baseline = Path(p["baseline"])
    account = pwd.getpwnam(p["service_user"])
    for directory in ("/var/lib/lr-platform", "/var/lib/lr-bookarm", "/var/lib/lr-robot"):
        Path(directory).mkdir(parents=True, exist_ok=True)
        os.chown(directory, 0, account.pw_gid)
        os.chmod(directory, 0o750)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = Path("/var/lib/lr-platform/setup-backups") / stamp
    backup.mkdir(parents=True, mode=0o700)

    def install(path, content, *, mode=0o640, owner=True):
        path = Path(path)
        missing = []
        parent = path.parent
        while not parent.exists():
            missing.append(parent)
            parent = parent.parent
        for parent in reversed(missing):
            parent.mkdir()
            os.chmod(parent, 0o750 if owner else 0o755)
            os.chown(parent, 0, account.pw_gid if owner else 0)
        if path.exists():
            previous = backup / str(path).lstrip("/")
            previous.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, previous)
            previous.chmod(0o600)
        write_private(path, content, mode)
        os.chown(path, 0, account.pw_gid if owner else 0)

    for directory in ("/etc/lr-platform", "/etc/lr-robot", "/etc/lr-bookarm"):
        Path(directory).mkdir(parents=True, exist_ok=True)
        os.chown(directory, 0, account.pw_gid)
        os.chmod(directory, 0o750)
    secrets_path = Path("/etc/lr-platform/setup-secrets.json")
    import secrets
    import uuid
    private = json.loads(secrets_path.read_text()) if secrets_path.exists() else {
        **{key: secrets.token_hex(24) for key in ("database", "minio", "dashboard", "cookie", "bookarm", "admin")},
        "station_id": "lr-station-" + str(uuid.uuid4()), "hotspot_uuid": str(uuid.uuid4()), "robot_id": p["robot_id"]}
    if private["robot_id"] != p["robot_id"]:
        raise SetupError("已安装的机器人身份不同；拒绝重用已有私钥或覆盖数据库身份")
    install(secrets_path, json_text(private), mode=0o600, owner=False)
    # This appliance includes its own control station. Issue unique station/robot credentials;
    # the existing PKI utility never exports the CA private key into robot runtime config.
    pki = Path("/var/lib/lr-platform/pki")
    pki_tool = WEB / "scripts/manage-fleet-pki.sh"
    def pki_command(*args):
        run(["bash", pki_tool, "--pki-dir", pki, *args], capture=True)
    if not (pki / "ca/ca.key").exists():
        pki_command("init-ca")
    if not (pki / "station/mqtt/server.crt").exists():
        pki_command("issue-station", "localhost", "127.0.0.1")
    if not (pki / f"robots/{p['robot_id']}/{p['robot_id']}.crt").exists():
        pki_command("issue-robot", p["robot_id"], p["robot_name"])
    pki_command("verify")
    pki_command("export-station", "/etc/lr-platform")
    pki_command("export-robot", p["robot_id"], "/etc/lr-robot")
    # The PKI exporter deliberately sets its destination to root-only mode.
    for directory in ("/etc/lr-platform", "/etc/lr-robot"):
        os.chown(directory, 0, account.pw_gid)
        os.chmod(directory, 0o750)
    station_credentials = read_env("/etc/lr-platform/platform-pki.env")
    robot_credentials = read_env("/etc/lr-robot/mqtt-credentials.env")
    for cert in Path("/etc/lr-platform/mqtt-certs").iterdir():
        # EMQX runs as UID 1000 in its container; its server key must be readable there.
        # Mount directory is root/service-group searchable, never exposed over HTTP.
        os.chown(cert, account.pw_uid, account.pw_gid)
        cert.chmod(0o644 if cert.suffix == ".crt" else 0o640)
    # Host user and EMQX container access are separated with a private container copy.
    broker_certs = Path("/var/lib/lr-platform/emqx-certs")
    broker_certs.mkdir(exist_ok=True)
    for name in ("ca.crt", "server.crt", "server.key"):
        target = broker_certs / name
        shutil.copy2(Path("/etc/lr-platform/mqtt-certs") / name, target)
        os.chown(target, 1000, 1000)
        target.chmod(0o600 if name.endswith(".key") else 0o644)
    os.chown(broker_certs, 1000, 1000)
    broker_certs.chmod(0o700)
    users = Path("/var/lib/lr-platform/emqx-users.csv")
    shutil.copy2("/etc/lr-platform/emqx-users.csv", users)
    os.chown(users, 1000, 1000)
    users.chmod(0o600)
    # Robot/client private material remains readable only by root and the service account group.
    for directory in (Path("/etc/lr-robot/mqtt"), Path("/etc/lr-platform/mqtt-certs")):
        os.chown(directory, 0, account.pw_gid)
        directory.chmod(0o750)
        for file in directory.iterdir():
            os.chown(file, 0, account.pw_gid)
            file.chmod(0o640)
    origin = "http://192.168.4.1:8000"
    platform = {"LR_PLATFORM_MODE": "production", "LR_PLATFORM_BUILD_ON_START": "false",
                "COMPOSE_PROJECT_NAME": "lr-robot-platform", "LR_POSTGRES_PASSWORD": private["database"],
                "LR_MINIO_ROOT_PASSWORD": private["minio"], "LR_EMQX_DASHBOARD_USERNAME": "lr-admin",
                "LR_EMQX_DASHBOARD_PASSWORD": private["dashboard"], "LR_EMQX_NODE_COOKIE": private["cookie"],
                "LR_MQTT_TLS_BIND_ADDRESS": "127.0.0.1", "LR_MQTT_CERTS_DIR": str(broker_certs),
                "LR_EMQX_BOOTSTRAP_USERS_FILE": str(users), "LR_STATION_URL": origin}
    images = json.loads((baseline / "versions/images.json").read_text())
    platform.update({f"LR_{key.upper()}_IMAGE": value for key, value in images.items()})
    # load-platform-env sources platform-pki.env last: keep mount paths consistent there too.
    station_credentials.update({"LR_MQTT_CERTS_DIR": str(broker_certs), "LR_EMQX_BOOTSTRAP_USERS_FILE": str(users)})
    install("/etc/lr-platform/platform-pki.env", env_text(station_credentials), mode=0o600, owner=False)
    install("/etc/lr-platform/platform.env", env_text(platform), mode=0o600, owner=False)
    api = {"LR_ENVIRONMENT": "production", "LR_AUTH_ENABLED": "true", "LR_SINGLE_OPERATOR": "false",
           "LR_STATION_ID": private["station_id"], "LR_STATION_NAME": p["robot_name"], "LR_STATION_URL": origin,
           "LR_CORS_ORIGINS": origin + ",http://localhost:8000,http://127.0.0.1:8000",
           "LR_STORAGE_BACKEND": "postgres", "LR_DATABASE_URL": f"postgresql+psycopg://library_robot:{private['database']}@127.0.0.1:5432/library_robot",
           "LR_REDIS_URL": "redis://127.0.0.1:6379/0", "LR_MQTT_URL": "mqtts://127.0.0.1:8883",
           "LR_MQTT_USERNAME": station_credentials["LR_MQTT_USERNAME"], "LR_MQTT_PASSWORD": station_credentials["LR_MQTT_PASSWORD"],
           "LR_MQTT_TLS_ENABLED": "true", "LR_REQUIRE_MQTT": "true", "LR_MQTT_CA_FILE": "/etc/lr-platform/mqtt-certs/ca.crt",
           "LR_MQTT_CLIENT_CERT_FILE": "/etc/lr-platform/mqtt-certs/control-api.crt",
           "LR_MQTT_CLIENT_KEY_FILE": "/etc/lr-platform/mqtt-certs/control-api.key",
           "LR_MAP_STORAGE_DIR": "/var/lib/lr-platform/maps", "LR_BATTERY_STATE_FILE": "/var/lib/lr-platform/battery/state.sqlite3",
           "LR_BATTERY_ROBOT_ID": p["robot_id"], "LR_ROBOT_AGENT_URL": "http://127.0.0.1:18090",
           "LR_HOST_START_AGENT_SOCKET": "/var/lib/lr-platform/host-start-agent/start-all.sock",
           "LR_NETWORK_AGENT_SOCKET": "/run/lr-network-agent/network.sock",
           "LR_BOOKARM_SOCKET_PATH": "/run/lr-bookarm/bookarm.sock", "LR_BOOKARM_TOKEN": private["bookarm"],
           "LR_ROBOT_ROOT": str(ROS), "LR_REGISTER_ROBOT_MAP_SCRIPT": str(ROS / "scripts/register-robot-map.sh")}
    install("/etc/lr-platform/control-api.env", env_text(api))
    arm_env = {"LR_BOOKARM_TOKEN": private["bookarm"], "LR_BOOKARM_PYTHON": str(ROOT / ".venv-bookarm/bin/python"),
               "LR_BOOKARM_CONFIG_DIR": "/etc/lr-bookarm/config", "LR_BOOKARM_ROOT": str(ARM),
               "LR_BOOKARM_INFERENCE_ROOT": str(WEB / "external/lingzu-bookarm-py/book_spine_inference_light"),
               "LR_BOOKARM_TASK_STORE_PATH": "/var/lib/lr-bookarm/runtime/bookarm-tasks.json",
               "LR_BOOKARM_HARDWARE_LOCK_PATH": "/var/lib/lr-bookarm/runtime/bookarm-hardware.lock",
               "LR_BOOKARM_YOLO_WEIGHTS": "/var/lib/lr-bookarm/models/best.pt"}
    install("/etc/lr-bookarm/bookarm.env", env_text(arm_env))
    gateway = json.loads((baseline / "robot/gateway.json").read_text())
    params = gateway["edge_gateway_node"]["ros__parameters"]
    home = Path(account.pw_dir)
    params.update({"robot_id": p["robot_id"], "mqtt_host": "127.0.0.1", "mqtt_port": 8883,
                   "mqtt_protocol_version": "3.1.1", "mqtt_tls_enabled": True,
                   "mqtt_ca_file": "/etc/lr-robot/mqtt/ca.crt",
                   "mqtt_client_cert_file": f"/etc/lr-robot/mqtt/{p['robot_id']}.crt",
                   "mqtt_client_key_file": f"/etc/lr-robot/mqtt/{p['robot_id']}.key",
                   **robot_credentials, "active_map_id": p["active_map_id"],
                   "map_registry_file": "/etc/lr-robot/map-registry.yaml",
                   "map_state_file": str(home / ".local/state/lr-robot/active_map.json"),
                   "bookarm_backend": "takeout", "bookarm_takeout_socket": "/run/lr-bookarm/bookarm.sock",
                   "bookarm_takeout_token": ""})
    if "allowed_map_ids" in params:
        params["allowed_map_ids"] = list(json.loads((baseline / "robot/map-registry.json").read_text())["maps"])
    bounds = json.loads((baseline / "robot/map-registry.json").read_text())["maps"][p["active_map_id"]]["bounds"]
    params.update({f"map_{axis}": bounds[key] for axis, key in
                  (("min_x", "minX"), ("max_x", "maxX"), ("min_y", "minY"), ("max_y", "maxY"))})
    install("/etc/lr-robot/edge-gateway.yaml", yaml_module().safe_dump(gateway, allow_unicode=True))
    auto = json.loads((baseline / "robot/auto-localization.json").read_text())
    for block in auto.values():
        if not isinstance(block, dict) or "ros__parameters" not in block:
            continue
        ap = block["ros__parameters"]
        ap.update({"active_map_id": p["active_map_id"], "map_registry_file": "/etc/lr-robot/map-registry.yaml"})
        ap.update({key: value for key, value in params.items() if key in {"map_min_x", "map_max_x", "map_min_y", "map_max_y"}})
        for key, value in list(ap.items()):
            if isinstance(value, str) and "/home/boreas/" in value:
                ap[key] = value.replace("/home/boreas/", str(home) + "/")
    install("/etc/lr-robot/auto-localization.yaml", yaml_module().safe_dump(auto, allow_unicode=True))
    install("/etc/lr-robot/runtime.env", env_text({"LR_GATEWAY_PARAMS_FILE": "/etc/lr-robot/edge-gateway.yaml",
            "LR_AUTO_LOCALIZATION_PARAMS_FILE": "/etc/lr-robot/auto-localization.yaml", "LR_ROS_AUTOMATIC_DISCOVERY_RANGE": "LOCALHOST",
            "LR_GATEWAY_BOOKARM_TOKEN": private["bookarm"]}))
    registry = json.loads((baseline / "robot/map-registry.json").read_text())
    for map_id, definition in registry["maps"].items():
        for name in ("map.yaml", "map.pgm"):
            install(f"/var/lib/lr-robot/maps/{map_id}/{name}", (baseline / f"maps/{map_id}/{name}").read_bytes(), mode=0o644)
        definition["yamlPath"] = f"/var/lib/lr-robot/maps/{map_id}/map.yaml"
    install("/etc/lr-robot/map-registry.yaml", yaml_module().safe_dump(registry))
    for path in ("/var/lib/lr-platform/battery", "/var/lib/lr-platform/maps", "/var/lib/lr-platform/host-start-agent",
                 "/var/lib/lr-bookarm/spine_studio", "/var/lib/lr-bookarm/runtime", "/var/lib/lr-bookarm/models",
                 "/var/lib/lr-robot", str(ARM / "recordings")):
        Path(path).mkdir(parents=True, exist_ok=True)
        os.chown(path, account.pw_uid, account.pw_gid)
        os.chmod(path, 0o750)
    install("/var/lib/lr-robot/mapping-marks.json", json_text({"version": 1, "marks": []}), mode=0o664)
    os.chown("/var/lib/lr-robot/mapping-marks.json", account.pw_uid, account.pw_gid)
    install("/var/lib/lr-bookarm/models/best.pt", (baseline / "assets/best.pt").read_bytes())
    for file in (baseline / "bookarm").rglob("*"):
        if not file.is_file():
            continue
        relative = file.relative_to(baseline / "bookarm")
        data = file.read_bytes()
        if relative.parts[0] == "devices":
            name = file.stem
            values = json.loads(data)
            values.update(p[name])
            if name == "camera":
                values["serial"] = p["camera_serial"]
            data = json_text(values)
        install(Path("/etc/lr-bookarm/config") / relative, data)
    calibration_dir = Path("/etc/lr-bookarm/config/calibration")
    calibration_dir.chmod(0o2770)
    for file in (baseline / "tuning").glob("*.json"):
        target = ARM / "recordings/tuning" / file.name
        install(target, file.read_bytes())
        os.chown(target, account.pw_uid, account.pw_gid)
        os.chown(target.parent, account.pw_uid, account.pw_gid)
    install("/etc/udev/rules.d/99-z-lr-robot.rules", udev_rules(p), mode=0o644, owner=False)
    for name, content in render_units(p).items():
        install(Path("/etc/systemd/system") / name, content, mode=0o644, owner=False)
    for file in (ROOT / "deploy/libexec").iterdir():
        if file.is_file():
            data = file.read_bytes()
            if file.name in {"lr-platform-start-all.sh", "lr-platform-restart-all.sh"}:
                data = data.replace(b"can0", p["arm"].get("can_interface", "can0").encode())
                data = data.replace(b"1000000", str(p["arm"].get("can_bitrate", 1000000)).encode())
            install(Path("/usr/local/libexec") / file.name, data, mode=0o755, owner=False)
    install("/etc/lr-platform/bluetooth.env", env_text({"LR_BLUETOOTH_NAME": p["bluetooth_name"]}))
    install("/etc/lr-platform/bookarm-start-policy.conf", "true\n" if p["hardware_autostart"] else "false\n", mode=0o660)
    sudoers = f"{p['service_user']} ALL=(root) NOPASSWD: /usr/bin/systemctl start lr-robot-runtime.service, /usr/bin/systemctl stop lr-robot-runtime.service, /usr/bin/systemctl restart lr-robot-runtime.service, /usr/bin/systemctl start lr-robot-mapping.service, /usr/bin/systemctl stop lr-robot-mapping.service, /usr/bin/systemctl start lr-bookarm-can.service, /usr/bin/systemctl start lr-bookarm-takeout.service, /usr/bin/systemctl start lr-xt369-usb.service, /usr/bin/systemctl start lr-robot-mapping-agent.service, /usr/bin/systemctl start lr-platform.service, /usr/bin/bash {ROS}/scripts/register-robot-map.sh *, {ROS}/scripts/register-robot-map.sh *\n"
    staged = backup / "sudoers-check"
    write_private(staged, sudoers, 0o440)
    run(["visudo", "-cf", staged], capture=True)
    install("/etc/sudoers.d/lr-robot", sudoers, mode=0o440, owner=False)
    if p["hotspot"]["enabled"]:
        install("/etc/NetworkManager/system-connections/lr-robot-hotspot.nmconnection",
                hotspot_keyfile(p, private["hotspot_uuid"]), mode=0o600, owner=False)
        run(["systemctl", "enable", "NetworkManager.service"], capture=True)
    run(["systemctl", "daemon-reload"])
    for unit in RETIRED:
        run(["systemctl", "disable", unit], check=False, capture=True)
    for unit in ["lr-robot-mapping.service"] + ([] if p["hardware_autostart"] else HARDWARE):
        run(["systemctl", "disable", unit], check=False, capture=True)
    run(["systemctl", "enable", *enabled_units(p)], capture=True)
    hostname = re.sub(r"[^a-z0-9-]+", "-", p["robot_id"].lower()).strip("-")[:58]
    run(["hostnamectl", "set-hostname", "lr-" + hostname], capture=True)
    run(["systemctl", "enable", "avahi-daemon.service"], capture=True)
    run(["udevadm", "control", "--reload-rules"])
    # Do not trigger devices, reload NM connections, rfkill Wi-Fi, restart networking or reboot.
    provision = ROOT / "deploy/scripts/robot_provision.py"
    env = {**os.environ, **{k: str(v) for k, v in platform.items()}}
    env.update(station_credentials)
    compose = ["docker", "compose", "-f", WEB / "infra/docker-compose/docker-compose.yml", "-f", WEB / "infra/docker-compose.production.yml"]
    run([*compose, "config", "--quiet"], env=env, capture=True)
    run([*compose, "up", "-d", "--no-build", "--pull", "never"], env=env)
    for _ in range(60):
        ready = run([*compose, "exec", "-T", "postgres", "pg_isready", "-U", "library_robot", "-d", "library_robot"], env=env, capture=True, check=False)
        if ready.returncode == 0:
            break
        time.sleep(1)
    else:
        raise SetupError("PostgreSQL 未就绪，未启动硬件")
    for _ in range(60):
        synced = run(["bash", pki_tool, "--pki-dir", pki, "sync-emqx", "all"], capture=True, check=False)
        if synced.returncode == 0:
            break
        time.sleep(1)
    else:
        raise SetupError("EMQX 账号同步失败，未启动硬件")
    # Provision DB while the API is stopped. Password travels in a private file, never argv.
    private_profile = backup / "profile.json"
    write_private(private_profile, json_text(p))
    run([ROOT / ".venv-api/bin/python", provision, private_profile], env={**os.environ, "PYTHONPATH": str(WEB / "apps/control-api")}, capture=True)
    install("/etc/lr-platform/setup-profile.json", json_text(p), mode=0o600, owner=False)
    install("/etc/lr-platform/setup-receipt.json", json_text({"created_at": stamp, "backup": str(backup),
            "profile_sha256": hashlib.sha256(json_text(p).encode()).hexdigest(), "baseline_sha256": digest(baseline / "manifest.json"),
            "enabled_units": enabled_units(p), "hotspot_pending_reboot": p["hotspot"]["enabled"]}), mode=0o600, owner=False)
    credentials = {"url": origin, "username": "operator", "password": p["operator_password"],
                   "admin_username": "admin", "admin_password": private["admin"]}
    install("/etc/lr-platform/access-credentials.json", json_text(credentials), mode=0o600, owner=False)
    if start:
        run(["systemctl", "start", *enabled_units(p)], capture=True)
    print(f"安装完成。备份：{backup}\n已设置开机自启：{', '.join(enabled_units(p))}\n"
          "热点将在下次开机加载；未切断或重连当前无线网络，也未自动重启电脑。\n"
          "账号文件：/etc/lr-platform/access-credentials.json（仅 root 可读）。")
    if not start:
        print("本次未启动导航/机械臂；现场具备启动条件后重启电脑，或重新执行 start 命令。")


def check(p):
    import urllib.request
    failures = []
    for unit in enabled_units(p):
        active = run(["systemctl", "is-active", unit], capture=True, check=False).stdout.strip()
        enabled = run(["systemctl", "is-enabled", unit], capture=True, check=False).stdout.strip()
        good = active == "active" and enabled == "enabled"
        print(f"{'OK' if good else 'FAIL'} {unit}: active={active}, enabled={enabled}")
        if not good:
            failures.append(unit)
    for url in ("http://127.0.0.1:8000/", "http://127.0.0.1:8080/health"):
        try:
            with urllib.request.urlopen(url, timeout=4) as response:
                body = response.read()
                good = response.status == 200
                if url.endswith("/health"):
                    health = json.loads(body)
                    good = good and health.get("status") == "ok"
            if not good:
                raise ValueError("状态未就绪")
            print("OK " + url)
        except Exception:
            print("FAIL " + url)
            failures.append(url)
    network = None
    try:
        import http.client
        import socket
        connection = http.client.HTTPConnection("localhost", timeout=10)
        connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.sock.settimeout(10)
        try:
            connection.sock.connect("/run/lr-network-agent/network.sock")
            connection.request("GET", "/status")
            response = connection.getresponse()
            network = json.loads(response.read())
            good = response.status == 200 and bool(network.get("local_url"))
        finally:
            connection.close()
    except Exception:
        good = False
    print(f"{'OK' if good else 'FAIL'} 网络代理与 Avahi 名称入口（只读）")
    if not good:
        failures.append("network-agent")
    if p["hardware_autostart"]:
        for role in ROLES:
            exists = Path("/dev", role).exists()
            print(f"{'OK' if exists else 'FAIL'} /dev/{role}")
            if not exists:
                failures.append(role)
        try:
            with urllib.request.urlopen("http://127.0.0.1:18091/status", timeout=4) as response:
                status = json.load(response)
            good = status.get("ok") is True and status.get("odom_available") is True
        except Exception:
            good = False
        print(f"{'OK' if good else 'FAIL'} 底盘定距服务 /odom 实时数据")
        if not good:
            failures.append("odometry")
        try:
            import http.client
            import socket
            token = read_env("/etc/lr-bookarm/bookarm.env")["LR_BOOKARM_TOKEN"]
            connection = http.client.HTTPConnection("localhost", timeout=4)
            connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            connection.sock.settimeout(4)
            try:
                connection.sock.connect("/run/lr-bookarm/bookarm.sock")
                connection.request("GET", "/api/v1/takeout/health", headers={"Authorization": "Bearer " + token})
                response = connection.getresponse()
                health = json.loads(response.read())
                good = response.status == 200 and health.get("started") is True and health.get("mode") == "real"
            finally:
                connection.close()
        except Exception:
            good = False
        print(f"{'OK' if good else 'FAIL'} BookArm 私有接口鉴权与真实硬件模式")
        if not good:
            failures.append("bookarm-health")
    try:
        import sqlite3
        path = Path("/var/lib/lr-platform/battery/state.sqlite3")
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
            row = connection.execute("SELECT state FROM battery WHERE id=1").fetchone()
        state = json.loads(row[0]) if row else {}
        last = state.get("last") or {}
        good = (not state.get("error") and last.get("bootId") == Path("/proc/sys/kernel/random/boot_id").read_text().strip()
                and 0 <= time.monotonic() - last.get("monotonic", 0) <= 5)
    except Exception:
        good = False
    print(f"{'OK' if good else 'FAIL'} XT369 USB 近 5 秒有效电量读数")
    if not good:
        failures.append("battery-data")
    if p["hotspot"]["enabled"]:
        device = next((d for d in (network or {}).get("devices", [])
                       if d["interface"] == p["hotspot"]["interface"]), {})
        good = bool(device.get("hotspots")) and (
            (device.get("mode") == "ap" and "192.168.4.1" in device.get("addresses", [])) or
            (device.get("mode") == "infrastructure" and bool(device.get("addresses"))))
        print(f"{'OK' if good else 'FAIL'} 固定热点配置与当前热点/Wi-Fi IPv4 连接")
        if not good:
            failures.append("hotspot")
    bluetooth = run(["bluetoothctl", "show"], capture=True, check=False)
    good = bluetooth.returncode == 0 and "Powered: yes" in bluetooth.stdout and f"Alias: {p['bluetooth_name']}" in bluetooth.stdout
    print(f"{'OK' if good else 'FAIL'} 蓝牙已开启且名称正确")
    if not good:
        failures.append("bluetooth")
    print("服务检查结束；进程在线不代表机械标定、定位、取还书动作已验收。")
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("scan", help="只读列出 USB、相机与网卡，不打开设备")
    export = sub.add_parser("export-baseline", help="从现有正常机器导出不含身份凭据的配置/版本基线")
    export.add_argument("--output", required=True)
    package = sub.add_parser("pack", help="生成源码、标定、地图、模型、依赖锁的一体交付包，不包含运行凭据和数据库")
    package.add_argument("--baseline", required=True)
    package.add_argument("--output", required=True)
    init = sub.add_parser("init", help="在新机器生成私有适配参数")
    init.add_argument("--profile", required=True)
    init.add_argument("--baseline", required=True)
    init.add_argument("--robot-id", required=True)
    for name in ("plan", "apply", "check", "start"):
        command = sub.add_parser(name)
        command.add_argument("--profile", default="/etc/lr-platform/setup-profile.json")
        if name == "apply":
            command.add_argument("--install-deps", action="store_true", help="安装系统依赖、Node、ROS、Python、构建前端和导航工作空间")
            command.add_argument("--start", action="store_true", help="配置完成后启动已确认的所有服务；不激活热点")
    args = parser.parse_args()
    if args.command == "scan":
        print(json_text(scan()), end="")
        return 0
    if args.command == "export-baseline":
        export_baseline(args.output)
        return 0
    if args.command == "pack":
        pack(args.baseline, args.output)
        return 0
    if args.command == "init":
        init_profile(args.profile, args.baseline, args.robot_id)
        return 0
    p = load_profile(args.profile)
    if args.command == "check":
        return check(p)
    verify_baseline(p["baseline"], verify_source=args.command in {"plan", "apply"})
    validate(p)
    if args.command == "plan":
        check_hardware_bindings(p)
        print(f"配置校验通过：{p['robot_id']} / {p['service_user']} / {ROOT}\n热点地址：http://192.168.4.1:8000\n"
              f"开机自启：{', '.join(enabled_units(p))}\n不会在安装时激活热点、断开 Wi-Fi 或自动重启。")
        return 0
    if args.command == "start":
        if os.geteuid() != 0 or not Path("/etc/lr-platform/setup-receipt.json").exists():
            raise SetupError("请先 sudo apply 完成安装")
        installed = json.loads(Path("/etc/lr-platform/setup-profile.json").read_text())
        if installed != p:
            raise SetupError("只能启动已经安装的配置，不能拿另一份配置绕过安装")
        run(["systemctl", "start", *enabled_units(p)], capture=True)
        print("服务启动指令已完成；请执行 check 并查看真实硬件遥测。热点连接仍需下次开机加载。")
        return 0
    apply_profile(p, args.profile, install_deps=args.install_deps, start=args.start)
    return 0


if __name__ == "__main__":
    sys.modules["robot_setup"] = sys.modules[__name__]
    os.umask(0o077)
    try:
        raise SystemExit(main())
    except (SetupError, OSError, ValueError, KeyError) as exc:
        # JSON decoder's message may include input fragments; do not dump configs.
        message = str(exc) if isinstance(exc, SetupError) else f"配置/文件错误（{type(exc).__name__}），请在本机检查输入与权限"
        print("错误：" + message, file=sys.stderr)
        raise SystemExit(1)
