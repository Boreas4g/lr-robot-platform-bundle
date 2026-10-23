"""Dependency installation for robot_setup (never imported by scan/check)."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import tarfile
import tempfile
import urllib.request

from robot_setup import ROOT, WEB, ROS, ARM, SetupError, run, write_private


@contextmanager
def no_service_restarts():
    """Do not let package postinst scripts start/restart networking during setup."""
    policy = Path("/usr/sbin/policy-rc.d")
    previous = policy.read_bytes() if policy.exists() else None
    previous_mode = policy.stat().st_mode & 0o777 if policy.exists() else None
    if policy.is_symlink():
        raise SetupError("policy-rc.d 是符号链接，请由管理员先配置软件包安装期间禁止自动重启服务")
    write_private(policy, "#!/bin/sh\nexit 101\n", 0o755)
    try:
        yield
    finally:
        if previous is None:
            policy.unlink()
        else:
            write_private(policy, previous, previous_mode)


def download(url, destination):
    with urllib.request.urlopen(url, timeout=90) as response:
        write_private(destination, response.read())


def install_node(version):
    if not re.fullmatch(r"v22\.\d+\.\d+", version):
        raise SetupError("基线 Node 版本必须是 v22.x.x")
    node = Path("/opt/lr-node/bin/node")
    if node.exists() and run([node, "--version"], capture=True).stdout.strip() == version:
        return
    with tempfile.TemporaryDirectory(prefix="lr-node-") as directory:
        directory = Path(directory)
        filename = f"node-{version}-linux-x64.tar.xz"
        base = f"https://nodejs.org/dist/{version}/"
        download(base + "SHASUMS256.txt", directory / "checksums")
        download(base + filename, directory / filename)
        checksums = dict((line.split()[1], line.split()[0]) for line in (directory / "checksums").read_text().splitlines())
        if hashlib.sha256((directory / filename).read_bytes()).hexdigest() != checksums.get(filename):
            raise SetupError("Node 官方分发包 SHA256 校验失败")
        with tarfile.open(directory / filename) as archive:
            archive.extractall(directory, filter="data")
        target = Path("/opt") / f"lr-node-{version}"
        if target.exists():
            raise SetupError(f"Node 目标目录已经存在但不完整：{target}")
        shutil.move(str(directory / f"node-{version}-linux-x64"), target)
        link = Path("/opt/lr-node")
        if link.exists() and not link.is_symlink():
            raise SetupError("/opt/lr-node 已存在且不是符号链接")
        link.unlink(missing_ok=True)
        link.symlink_to(target)


def bootstrap(p, *, install_deps):
    baseline = Path(p["baseline"])
    account = pwd.getpwnam(p["service_user"])
    node_version = json.loads((baseline / "versions/host.json").read_text())["node"]
    # Code is built as the normal service user. The private baseline can be root-owned;
    # installer copies only required build inputs into the project first.
    env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive", "NEEDRESTART_MODE": "l"}
    if install_deps:
        with no_service_restarts():
            run(["apt-get", "update"], env=env)
            run(["apt-get", "install", "-y", "ca-certificates", "curl", "gnupg", "git", "build-essential",
                 "cmake", "pkg-config", "python3-venv", "python3-dev", "python3-pip", "python3-yaml",
                 "python3-serial", "python3-paho-mqtt", "python3-websockets", "python3-numpy", "python3-scipy",
                 "network-manager", "python3-dbus", "avahi-daemon", "libnss-mdns", "bluez", "rfkill", "iw", "dnsmasq-base", "iproute2", "can-utils",
                 "docker.io", "docker-compose-v2", "sudo", "jq", "openssl", "libgl1", "libglib2.0-0", "libpcap-dev"], env=env)
            if not Path("/opt/ros/jazzy/setup.bash").exists():
                key = Path("/usr/share/keyrings/lr-ros-archive-keyring.asc")
                download("https://raw.githubusercontent.com/ros/rosdistro/master/ros.key", key)
                key.chmod(0o644)
                write_private("/etc/apt/sources.list.d/lr-ros2.list",
                              "deb [arch=amd64 signed-by=/usr/share/keyrings/lr-ros-archive-keyring.asc] "
                              "http://packages.ros.org/ros2/ubuntu noble main\n", 0o644)
                run(["apt-get", "update"], env=env)
            run(["apt-get", "install", "-y", "ros-jazzy-ros-base", "ros-jazzy-navigation2", "ros-jazzy-nav2-bringup",
                 "ros-jazzy-slam-toolbox", "ros-jazzy-rviz2", "python3-colcon-common-extensions", "python3-rosdep"], env=env)
        install_node(node_version)
    for command in ("docker", "colcon", "rosdep", "udevadm", "visudo", "iw", "nmcli"):
        if not shutil.which(command):
            raise SetupError(f"缺少 {command}，请加 --install-deps")
    if not Path("/opt/ros/jazzy/setup.bash").exists() or not Path("/opt/lr-node/bin/node").exists():
        raise SetupError("缺少 ROS Jazzy 或固定 Node 环境，请加 --install-deps")
    compose_version = run(["docker", "compose", "version", "--short"], capture=True).stdout.strip().lstrip("v")
    match = re.match(r"(\d+)\.(\d+)\.(\d+)", compose_version)
    if not match or tuple(map(int, match.groups())) < (2, 24, 4):
        raise SetupError("Docker Compose 需要 >= 2.24.4，支持生产配置的 !override")
    run(["usermod", "-a", "-G", "dialout,video,plugdev", p["service_user"]])
    run(["systemctl", "enable", "docker.service"], capture=True)
    run(["systemctl", "start", "docker.service"], capture=True)
    # Pull only baseline digests; daily boot subsequently uses --pull never.
    for image in json.loads((baseline / "versions/images.json").read_text()).values():
        if run(["docker", "image", "inspect", image], capture=True, check=False).returncode:
            run(["docker", "pull", image])
    build_env = {"HOME": account.pw_dir, "PATH": "/opt/lr-node/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                 "LANG": "C.UTF-8", "HUSKY": "0", "ELECTRON_SKIP_BINARY_DOWNLOAD": "1"}

    def as_user(argv, **kwargs):
        return run(["runuser", "-u", p["service_user"], "--", "env", *[f"{k}={v}" for k, v in build_env.items()], *argv], **kwargs)

    if not os.access(ROOT, os.W_OK):
        raise SetupError("项目目录不可写")
    # Give only the copied project tree to its owner, not the user's entire home or /etc.
    run(["chown", "-R", f"{account.pw_uid}:{account.pw_gid}", ROOT])
    for name in ("api", "bookarm"):
        venv = ROOT / f".venv-{name}"
        if not venv.exists():
            as_user(["/usr/bin/python3", "-m", "venv", venv])
        py = venv / "bin/python"
        # Copy version lock to user-readable private directory; original baseline remains private.
        lock = ROOT / ".local-deploy" / f"{name}-requirements.lock"
        write_private(lock, (baseline / f"versions/{name}.txt").read_bytes())
        os.chown(lock.parent, account.pw_uid, account.pw_gid)
        os.chown(lock, account.pw_uid, account.pw_gid)
        as_user([py, "-m", "pip", "install", "--extra-index-url", "https://download.pytorch.org/whl/cpu", "-r", lock])
        projects = [ROOT / "xt369_linux", WEB / "apps/control-api"] if name == "api" else [ROOT / "drivers/aim_sdk", ARM]
        for project in projects:
            as_user([py, "-m", "pip", "install", "--no-deps", "--no-build-isolation", "-e", project])
        as_user([py, "-m", "pip", "check"])
        modules = "import fastapi,uvicorn,psycopg,redis,paho.mqtt.client,xt369" if name == "api" else (
            "import fastapi,uvicorn,serial,pyrealsense2,pinocchio,cv2,ultralytics; import bookarm.service.composition")
        as_user([py, "-c", modules])
    as_user(["/opt/lr-node/bin/npm", "ci", "--no-audit", "--no-fund"], cwd=WEB)
    as_user(["/opt/lr-node/bin/npm", "run", "build"], cwd=WEB)
    # Rebuild against each new host rather than copying embedded /home/boreas paths in install/.
    for file in (baseline / "ros").rglob("*"):
        if file.is_file():
            target = ROS / file.relative_to(baseline / "ros")
            write_private(target, file.read_bytes(), 0o644)
            os.chown(target, account.pw_uid, account.pw_gid)
    if not Path("/etc/ros/rosdep/sources.list.d/20-default.list").exists():
        run(["rosdep", "init"])
    as_user(["rosdep", "update", "--rosdistro", "jazzy"])
    # rosdep resolves selected application packages and their local dependencies, not
    # unrelated voice/experimental stacks that are not part of the appliance runtime.
    packages = ["mobile_robot_nav_bringup", "robot_decision"]
    paths = as_user(["colcon", "list", "--packages-up-to", *packages, "--paths-only"], cwd=ROS, capture=True).stdout.splitlines()
    if not paths:
        raise SetupError("未找到 ROS 运行包")
    with no_service_restarts():
        run(["rosdep", "install", "--rosdistro", "jazzy", "--from-paths", *[ROS / path for path in paths],
             "--ignore-src", "-r", "-y"], env=env)
    for name in ("build", "install", "log"):
        directory = ROS / name
        if directory.exists():
            # Preserve previous generated state in-place for diagnosis. Do not delete maps/configs.
            archived = ROS / f".setup-previous-{name}-{__import__('time').time_ns()}"
            directory.rename(archived)
    script = 'source /opt/ros/jazzy/setup.bash && exec colcon build --symlink-install --packages-up-to mobile_robot_nav_bringup robot_decision --parallel-workers 2'
    as_user(["bash", "-c", script], cwd=ROS)
    # Executable bits can be lost when a project is copied through FAT/NTFS media.
    for directory in (ROOT / "deploy", WEB / "scripts", ROS / "scripts", ARM / "scripts"):
        for file in directory.rglob("*.sh"):
            file.chmod(file.stat().st_mode | 0o111)
    (ROS / "scripts/mapping_agent.py").chmod(0o755)
