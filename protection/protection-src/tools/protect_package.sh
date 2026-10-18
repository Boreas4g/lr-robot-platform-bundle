#!/bin/bash
# 用法: protect_package.sh <源包目录(lr-oneclick 明文)> <输出目录> <wheels目录>
# 把明文一键部署包转换为「受保护部署包」：
#   - ROS 4 个自研 Python 包 .py → .so（注入许可证校验，setup.py 加 package_data）
#   - control-api / 独立运维脚本 → .so（+加载器）
#   - aim_sdk/bookarm 源码删除，改由 wheels 目录的编译版 wheel 提供
#   - 新增 protection/（守护模块、CLI、vendor-tools）与 deploy.sh 的 license 阶段
# 前提：
#   1. wheels 目录已含 bookarm/aim_sdk 编译版 wheel（由 build_wheel.sh 生成）
#   2. protection-src/keys/ 已生成密钥对，且 lr_license_guard 已按公钥编译出
#      protection/lr_license_guard.cpython-{312,311}-*.so（可用 guard-build 步骤产出）
set -euo pipefail
SRC="$1"; OUT="$2"; WHEELS="$3"
B=/home/boreas/lr-protection-build
T=$B/protection-src/tools
GD=$B/guard-dist

[ -f "$WHEELS/bookarm-0.1.0-py3-none-any.whl" ] || { echo "缺少 bookarm wheel"; exit 1; }
[ -f "$WHEELS/aim_sdk-0.1.0-py3-none-any.whl" ] || { echo "缺少 aim_sdk wheel"; exit 1; }

echo "== 1/9 复制源包"
rm -rf "$OUT"; mkdir -p "$(dirname "$OUT")"
cp -a "$SRC" "$OUT"
C="$OUT/code"

echo "== 2/9 ROS 4 个 Python 包编译"
declare -A INJ
INJ[robot_decision]="robot_decision/auto_localization_node.py,robot_decision/bookarm_sdk_service.py,robot_decision/book_center_detector_node.py,robot_decision/book_shelf_fine_tune_node.py,robot_decision/cruise_node.py,robot_decision/edge_gateway_node.py,robot_decision/init_pose_node.py,robot_decision/point3_fine_tune_node.py,robot_decision/vehicle_nudge_node.py"
INJ[car_ctrl]="car_ctrl/car_odometry.py,car_ctrl/ddsm_hat_diff_drive_node.py,car_ctrl/ddsm_hat_motor_test_node.py,car_ctrl/imu_driver.py,car_ctrl/map_pose_recorder.py,car_ctrl/scan_odometry.py"
INJ[arm_aux_devices]="arm_aux_devices/lifttable.py,arm_aux_devices/turntable.py"
INJ[mobile_robot_voice_interaction]="mobile_robot_voice_interaction/speech_interaction.py,mobile_robot_voice_interaction/voice_cmd_reader.py"
for p in robot_decision car_ctrl arm_aux_devices mobile_robot_voice_interaction; do
  pkgdir="$C/Library_robot/src/$p"
  /usr/bin/python3 "$T/cythonize_tree.py" "$pkgdir" --inject "${INJ[$p]}" | tail -1
  # setup.py 加 package_data 让 .so 随 colcon 安装
  python3 - "$pkgdir/setup.py" <<'EOF'
import sys
p = sys.argv[1]
src = open(p, encoding="utf-8").read()
if "package_data" not in src:
    old = "    packages=find_packages(exclude=[\"test\"]),"
    assert old in src, "setup.py 锚点未命中: " + p
    src = src.replace(old, old + "\n    package_data={package_name: [\"*.so\"]},", 1)
    open(p, "w", encoding="utf-8").write(src)
print("setup.py 已加 package_data:", p)
EOF
done
rm -rf "$C"/Library_robot/src/{robot_decision,car_ctrl,arm_aux_devices,mobile_robot_voice_interaction}/test

echo "== 3/9 control-api 编译"
/home/boreas/miniconda3/envs/lr-control-api/bin/python "$T/cythonize_tree.py" \
  "$C/LR-Web/apps/control-api" --inject app/main.py \
  --exclude '(^|/)(setup\.py|_lr_cython_setup\.py|__init__\.py)$|\.launch\.py$|__pycache__|(^|/)(test|tests|examples)/' | tail -1
rm -rf "$C/LR-Web/apps/control-api/tests"

echo "== 4/8 独立脚本编译"
# sync-robot-maps/map-registry 原本从 src 树 import robot_decision；
# 受保护流程删除 src 后须改指 install 树 site-packages
python3 - "$C/Library_robot/scripts/sync-robot-maps.py" "$C/Library_robot/scripts/map-registry.py" <<'EOY'
import sys
for p in sys.argv[1:]:
    s = open(p, encoding="utf-8").read()
    old = 'sys.path.insert(0, str(WORKSPACE / "src" / "robot_decision"))'
    new = 'sys.path.insert(0, str(WORKSPACE / "install" / "robot_decision" / "lib" / "python3.12" / "site-packages"))'
    assert old in s, "sys.path 锚点未命中: " + p
    open(p, "w", encoding="utf-8").write(s.replace(old, new, 1))
    print("sys.path 补丁:", p)
EOY
bash "$T/compile_script.sh" /usr/bin/python3 "$C/Library_robot/scripts/mapping_agent.py" | tail -1
for f in auto_localize.py map-registry.py sync-robot-maps.py capture_imu_odom_diagnostics.py; do
  bash "$T/compile_script.sh" /usr/bin/python3 "$C/Library_robot/scripts/$f" | tail -1
done
rm -f "$C/Library_robot/scripts/test_mapping_agent.py"
bash "$T/compile_script.sh" /usr/bin/python3 "$C/LR-Web/scripts/lr-host-start-agent.py" | tail -1
bash "$T/compile_script.sh" /usr/bin/python3 "$C/LR-Web/scripts/lr-station-discovery.py" | tail -1

echo "== 5/8 wheels 取代 aim_sdk/bookarm 源码"
mkdir -p "$C/wheels"
cp "$WHEELS"/*.whl "$C/wheels/"
rm -rf "$C/aim_sdk"
rm -rf "$C/bookarm/src" "$C/bookarm/pyproject.toml" "$C/bookarm/tests" 2>/dev/null || true

echo "== 6/8 protection/ 目录"
P="$OUT/protection"
mkdir -p "$P/vendor-tools"
install -m 0644 "$GD/py312/lr_license_guard.cpython-312-x86_64-linux-gnu.so" "$P/"
install -m 0644 "$GD/py311/lr_license_guard.cpython-311-x86_64-linux-gnu.so" "$P/"
install -m 0755 /usr/local/bin/lr-license "$P/lr-license"
install -m 0644 "$B/protection-src/keygen.py" "$P/vendor-tools/"
install -m 0644 "$B/protection-src/ed25519py.py" "$P/vendor-tools/"
cat > "$P/vendor-tools/README.md" <<'EOF'
# 许可证签发工具（供应商专用，绝不随机器交付客户）

## 使用前
把许可证私钥 `license_private.key` 放到本目录。
**私钥只保存在完整备份中（protection-src/keys/），本目录默认不含私钥。
私钥泄露 = 任何人都能签发许可证，务必离线妥善保管。**

## 签发流程
1. 客户机部署后执行：`sudo lr-license code` 得到机器码（形如 LR1-XXXX-XXXX-XXXX）
2. 在供应商电脑（或任何安全机器）上：
   ```bash
   python3 keygen.py --key license_private.key --machine-code LR1-XXXX-XXXX-XXXX
   ```
   生成 license-LR1XXXXXXXXXXXX.lic
3. 许可证交给客户机：`sudo lr-license install <文件>`（或放到部署包 env/license.lic 后
   `bash deploy.sh --only license`）

许可证永久有效，仅绑定签发时的机器码（根盘序列号）。客户换硬盘/换机需重新签发。
EOF

echo "== 6.5/8 安装脚本补 impl .so"
python3 - "$C/LR-Web/scripts/install-host-start-agent.sh" "$C/LR-Web/scripts/install-control-station-appliance.sh" <<'EOF'
import sys
p1, p2 = sys.argv[1], sys.argv[2]
s = open(p1, encoding="utf-8").read()
old = 'install -o root -g root -m 0755 "$AGENT_SOURCE" "$AGENT_TARGET"\n'
assert old in s
s = s.replace(old, old + '# 编译版实现模块（加载器 .py 依赖同目录 impl .so）\ninstall -o root -g root -m 0644 "$ROOT_DIR/scripts/lr_host_start_agent_impl.cpython-312-x86_64-linux-gnu.so" /usr/local/libexec/\n', 1)
open(p1, "w", encoding="utf-8").write(s)
s = open(p2, encoding="utf-8").read()
old = 'install -m 0755 "$ROOT_DIR/scripts/lr-station-discovery.py" /usr/local/libexec/lr-station-discovery.py\n'
assert old in s
s = s.replace(old, old + 'install -m 0644 "$ROOT_DIR/scripts/lr_station_discovery_impl.cpython-312-x86_64-linux-gnu.so" /usr/local/libexec/\n', 1)
open(p2, "w", encoding="utf-8").write(s)
print("两个安装脚本已补 impl .so")
EOF

echo "== 7/8 deploy.sh 改造"
python3 - "$OUT/deploy.sh" <<'EOF'
import sys
p = sys.argv[1]
src = open(p, encoding="utf-8").read()

# 1) 头部用法：阶段列表加 license，11→12
src = src.replace(
    "# 阶段：preflight apt ros docker node code conda system build data enable",
    "# 阶段：preflight apt ros docker node code conda system license build data enable")

# 2) p_code：aim_sdk 改由 wheel 提供，删除其 rsync
old = '  run_as rsync -a "$PKG_DIR/code/aim_sdk/"                    "$LR_HOME/LR/lingzu-bookarm-py/aim_sdk/"\n'
assert old in src, "deploy.sh 锚点 p_code 未命中"
src = src.replace(old, "")

# 3) p_conda：editable 安装改为 wheel 安装
old = """  run_as "$CONDA_DIR/envs/bookarm/bin/pip" install --quiet \\
    -e "$LR_HOME/LR/lingzu-bookarm-py/aim_sdk" \\
    -e "$LR_HOME/project/lingzu_arm/lingzu-bookarm-py/bookarm"
"""
assert old in src, "deploy.sh 锚点 p_conda 未命中"
new = """  run_as "$CONDA_DIR/envs/bookarm/bin/pip" install --quiet \\
    "$PKG_DIR"/code/wheels/aim_sdk-0.1.0-py3-none-any.whl \\
    "$PKG_DIR"/code/wheels/bookarm-0.1.0-py3-none-any.whl
"""
src = src.replace(old, new, 1)

# 4) 新增 p_license，插在 p_system 之后；阶段计数 11→12
src = src.replace("# ---------------------------------------------------------------- build",
"""# ---------------------------------------------------------------- license
p_license() {
  log "阶段 9/12：许可证守护与机器码授权"
  local gd312="$PKG_DIR/protection/lr_license_guard.cpython-312-x86_64-linux-gnu.so"
  local gd311="$PKG_DIR/protection/lr_license_guard.cpython-311-x86_64-linux-gnu.so"
  [[ -f "$gd312" && -f "$gd311" ]] || die "包不完整：缺少 protection/ 守护模块"
  $SUDO install -m 0644 "$gd312" /usr/lib/python3/dist-packages/
  run_as install -m 0644 "$gd312" "$CONDA_DIR/envs/bookarm/lib/python3.12/site-packages/"
  run_as install -m 0644 "$gd311" "$CONDA_DIR/envs/lr-control-api/lib/python3.11/site-packages/"
  $SUDO install -m 0755 "$PKG_DIR/protection/lr-license" /usr/local/bin/lr-license
  run_as bash -c "echo 'import lr_license_guard;lr_license_guard.require()' > \\"$CONDA_DIR/envs/bookarm/lib/python3.12/site-packages/lr_license_guard_auto.pth\\""
  run_as bash -c "echo 'import lr_license_guard;lr_license_guard.require()' > \\"$CONDA_DIR/envs/lr-control-api/lib/python3.11/site-packages/lr_license_guard_auto.pth\\""
  if [[ -f "$PKG_DIR/env/license.lic" ]]; then
    $SUDO /usr/local/bin/lr-license install "$PKG_DIR/env/license.lic"
  else
    warn "未提供 env/license.lic，本机暂未授权。流程：sudo lr-license code 获取机器码 \\
      → 供应商 protection/vendor-tools/keygen.py 签发 → 许可证放入 env/license.lic \\
      → bash deploy.sh --only license"
  fi
}

# ---------------------------------------------------------------- build""", 1)
for a, b in [("阶段 1/11", "阶段 1/12"), ("阶段 2/11", "阶段 2/12"), ("阶段 3/11", "阶段 3/12"),
             ("阶段 4/11", "阶段 4/12"), ("阶段 5/11", "阶段 5/12"), ("阶段 6/11", "阶段 6/12"),
             ("阶段 7/11", "阶段 7/12"), ("阶段 8/11", "阶段 8/12"), ("阶段 9/11", "阶段 10/12"),
             ("阶段 10/11", "阶段 11/12"), ("阶段 11/11", "阶段 12/12")]:
    assert a in src, "deploy.sh 阶段计数锚点缺失: " + a
    src = src.replace(a, b)

# 5) main() 注册 license 阶段
old = "  should_run system    && p_system\n  should_run build     && p_build"
assert old in src, "deploy.sh 锚点 main 未命中"
src = src.replace(old, "  should_run system    && p_system\n  should_run license   && p_license\n  should_run build     && p_build", 1)

# 6) run_as 的 root 分支修复（sudo 运行时 $SUDO 为空导致 "-H 未找到命令"）
old_ra = "    $SUDO -H -u \\"$LR_USER\\" \\"$@\\""
assert old_ra in src, "run_as 锚点未命中"
src = src.replace(old_ra, "    sudo -H -u \\"$LR_USER\\" \\"$@\\"", 1)

# 7) p_system 补 libexec 运行文件安装
old_ps = """  $SUDO cp \\"$PKG_DIR\\"/system/systemd/lr-*.service /etc/systemd/system/
  $SUDO systemctl daemon-reload
"""
assert old_ps in src, "p_system 锚点未命中"
new_ps = """  $SUDO cp \\"$PKG_DIR\\"/system/systemd/lr-*.service /etc/systemd/system/
  $SUDO systemctl daemon-reload

  # lr-host-start-agent / lr-station-discovery 运行文件（编译版：加载器 .py + impl .so）
  $SUDO install -d -m 0755 /usr/local/libexec
  $SUDO install -m 0755 \\"$PKG_DIR/code/LR-Web/scripts/lr-host-start-agent.py\\" /usr/local/libexec/
  $SUDO install -m 0644 \\"$PKG_DIR\\"/code/LR-Web/scripts/lr_host_start_agent_impl.cpython-312-x86_64-linux-gnu.so /usr/local/libexec/
  $SUDO install -m 0755 \\"$PKG_DIR/code/LR-Web/scripts/lr-station-discovery.py\\" /usr/local/libexec/
  $SUDO install -m 0644 \\"$PKG_DIR\\"/code/LR-Web/scripts/lr_station_discovery_impl.cpython-312-x86_64-linux-gnu.so /usr/local/libexec/
  $SUDO install -m 0755 \\"$PKG_DIR/code/LR-Web/scripts/start-all.sh\\" /usr/local/libexec/lr-platform-start-all.sh
  $SUDO install -m 0755 \\"$PKG_DIR/code/LR-Web/scripts/restart-all.sh\\" /usr/local/libexec/lr-platform-restart-all.sh
"""
src = src.replace(old_ps, new_ps, 1)

open(p, "w", encoding="utf-8").write(src)
print("deploy.sh 改造完成")
EOF
bash -n "$OUT/deploy.sh" && echo "deploy.sh 语法检查通过"
echo "受保护部署包生成完毕: $OUT"
echo "[提醒] 请手工同步 README.zh-CN.md 保护版说明与《保护方案使用说明书》。"
