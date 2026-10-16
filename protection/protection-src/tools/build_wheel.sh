#!/bin/bash
# 用法: build_wheel.sh <bookarm|aim_sdk> <源码目录> <wheel输出目录>
# 在临时副本中：打补丁(仅bookarm) → 注入许可证校验 → Cython编译 → 删.py → 构建wheel → 校验内容
set -euo pipefail
PKG="$1"; SRC="$2"; OUT="$3"
PY=/home/boreas/miniconda3/envs/bookarm/bin/python
WORK=/tmp/lr-protect-build/wheelsrc/$PKG
TOOLS=/home/boreas/lr-protection-build/tools

rm -rf "$WORK"; mkdir -p "$WORK" "$OUT"
rsync -a --exclude '__pycache__' --exclude '*.egg-info' --exclude 'tests' --exclude '.pytest_cache' "$SRC/" "$WORK/"

# 定位编译根：src 布局用 src/，平铺布局用仓库根
CYROOT="$WORK/src"
[ -d "$CYROOT" ] || CYROOT="$WORK"
# 注入路径相对编译根（注意：bookarm 的 __main__.py 稍后改名为 _main_impl.py）
INJECT=""
[ "$PKG" = bookarm ] && INJECT="--inject bookarm/service/_main_impl.py"

if [ "$PKG" = bookarm ]; then
  # 补丁：infer 动态加载支持编译版 .so（存在则优先；扩展模块初始化函数名须与文件名一致）
  "$PY" - "$WORK/src/bookarm/service/studio.py" <<'EOF'
import sys
p = sys.argv[1]
src = open(p, encoding="utf-8").read()
old = """    def _load_infer_module(self) -> Any:
        if self._infer_module is not None:
            return self._infer_module
        if not self._infer_path.is_file():"""
new = """    def _load_infer_module(self) -> Any:
        if self._infer_module is not None:
            return self._infer_module
        infer_path = self._infer_path
        if infer_path.suffix == ".py":
            so_matches = sorted(infer_path.parent.glob(infer_path.stem + ".cpython-*.so"))
            if so_matches:
                infer_path = so_matches[0]
        if not infer_path.is_file():"""
assert old in src, "studio.py 补丁锚点1未命中"
src = src.replace(old, new, 1)
seg = src.split('spec = importlib.util.spec_from_file_location("_bookarm_studio_infer", str(self._infer_path))', 1)
assert len(seg) == 2, "studio.py 补丁锚点2未命中"
src = seg[0] + 'spec = importlib.util.spec_from_file_location(infer_path.name.split(".")[0], str(infer_path))' + seg[1]
old3 = '缺失推理脚本：%s）"\n                % self._infer_path\n            )'
assert old3 in src, "studio.py 补丁锚点3未命中"
src = src.replace(old3, '缺失推理脚本：%s）"\n                % infer_path\n            )', 1)
open(p, "w", encoding="utf-8").write(src)
print("studio.py 补丁完成")
EOF
fi

# wheel 打包包含 .so（已有 package-data 表则插入一行，否则追加整表）
"$PY" - "$WORK/pyproject.toml" <<'EOF'
import sys
p = sys.argv[1]
lines = open(p, encoding="utf-8").read().splitlines(keepends=True)
header = "[tool.setuptools.package-data]"
if any(l.strip() == header for l in lines):
    idx = next(i for i, l in enumerate(lines) if l.strip() == header)
    lines.insert(idx + 1, '"*" = ["*.so"]\n')
else:
    lines += ["\n", header + "\n", '"*" = ["*.so"]\n']
open(p, "w", encoding="utf-8").write("".join(lines))
print("pyproject.toml 已加入 *.so 打包规则")
EOF

# Cython 编译（工具自动跳过 __init__.py），删除已编译 .py
rm -f "$OUT"/$PKG-*.whl
if [ "$PKG" = bookarm ]; then
  # python -m bookarm.service 需要源码版 __main__.py：编译体改名为 _main_impl，
  # 编译后写回加载器 __main__.py
  mv "$WORK/src/bookarm/service/__main__.py" "$WORK/src/bookarm/service/_main_impl.py"
fi
"$PY" "$TOOLS/cythonize_tree.py" "$CYROOT" $INJECT \
  --exclude '(^|/)(setup\.py|_lr_cython_setup\.py|__init__\.py)$|\.launch\.py$|__pycache__|(^|/)(test|tests|examples)/'
if [ "$PKG" = bookarm ]; then
  cat > "$WORK/src/bookarm/service/__main__.py" <<'EOF'
"""编译版加载器：逻辑在 bookarm.service._main_impl 编译模块内"""
from bookarm.service._main_impl import main

if __name__ == "__main__":
    main()
EOF
fi

# 构建 wheel（无隔离，用 env 内 setuptools）
cd "$WORK"
"$PY" -m pip wheel --no-build-isolation --no-deps -w "$OUT" . -q

# 校验 wheel 内容：除 __init__.py / __main__.py 加载器外不得有 .py，且必须有 .so
WHL=$(ls "$OUT"/$PKG-*.whl)
echo "== wheel 内容校验: $(basename "$WHL")"
"$PY" - "$WHL" <<'EOF'
import sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
pys = [n for n in z.namelist() if n.endswith(".py") and not n.endswith("__init__.py") and not n.endswith("__main__.py") and ".dist-info" not in n]
sos = [n for n in z.namelist() if n.endswith(".so")]
print("  .so 数量: %d" % len(sos))
if pys:
    print("  [错误] wheel 中仍有源码: %s" % pys[:5]); sys.exit(1)
if not sos:
    print("  [错误] wheel 中没有 .so"); sys.exit(1)
print("  通过：无源码 .py，.so 已打包")
EOF
