#!/bin/bash
# 用法: compile_script.sh <python解释器> <脚本路径>
# 把单文件 Python 脚本编译为 <名字>_impl.so（- 转为 _），并在原路径留下 2 行加载器 .py
set -euo pipefail
PY="$1"; SCRIPT="$2"
DIR=$(dirname "$SCRIPT"); BASE=$(basename "$SCRIPT" .py); IMPL=$(echo "${BASE}_impl" | tr '-' '_')
WORK=/tmp/lr-protect-build/scripts-build/$BASE
SUDO=""; [ -w "$DIR" ] || SUDO="sudo"

rm -rf "$WORK"; mkdir -p "$WORK"
cp "$SCRIPT" "$WORK/$IMPL.py"
# 注入许可证校验（在 from __future__ 之后）
python3 - "$WORK/$IMPL.py" <<'EOF'
import sys
p = sys.argv[1]
lines = open(p, encoding="utf-8").read().splitlines(keepends=True)
if not any("lr_license_guard" in l for l in lines):
    at = 0
    for i, l in enumerate(lines):
        if l.startswith("from __future__ import"):
            at = i + 1
    lines.insert(at, "import lr_license_guard as _lrg; _lrg.require()\n")
    open(p, "w", encoding="utf-8").write("".join(lines))
print("已注入:", p)
EOF

cd "$WORK"
cat > _setup.py <<'EOF'
from setuptools import setup
from Cython.Build import cythonize
setup(name="_x", packages=[], ext_modules=cythonize("IMPLNAME.py", language_level=3,
      compiler_directives={"language_level": "3", "annotation_typing": False}),
      script_args=["build_ext", "--inplace", "-q"])
EOF
sed -i "s/IMPLNAME/$IMPL/" _setup.py
"$PY" _setup.py
SO=$(ls $IMPL.cpython-*.so)
strip --strip-unneeded "$SO" 2>/dev/null || true
$SUDO install -m 0644 "$SO" "$DIR/"
# 原脚本改写为加载器（保留原名与可执行权限）
$SUDO tee "$SCRIPT" >/dev/null <<EOF
#!/usr/bin/env python3
"""编译版加载器：逻辑在同目录 $IMPL 编译模块内"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from $IMPL import main
if __name__ == "__main__":
    raise SystemExit(main())
EOF
$SUDO chmod 0755 "$SCRIPT"
echo "完成: $SCRIPT -> $DIR/$SO"
