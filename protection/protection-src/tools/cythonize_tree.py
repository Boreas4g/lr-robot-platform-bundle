#!/usr/bin/env python3
"""把一个目录树里的 .py 批量编译为同名 .so（Cython），并清理源码。

用法（用目标解释器运行）：
  python3 cythonize_tree.py DIR [--inject rel/a.py,rel/b.py] \
      [--exclude REGEX] [--keep-py] [--no-strip]

行为：
  1. 收集 DIR 下所有 .py（默认排除 setup.py / __init__.py / *.launch.py / __pycache__ / test·tests 目录）
  2. 对 --inject 列出的相对路径文件，在 from __future__ 块之后注入许可证校验调用
  3. 批量 cythonize 编译（annotation_typing=False，纯 Python 语义）；
     批量失败则逐文件隔离编译，失败文件保留 .py 并告警
  4. 清理已编译的 .py（除非 --keep-py）、.c、__pycache__、build 目录与临时 setup
  5. strip .so 符号
退出码：0=全部成功；3=有文件编译失败（已保留 .py）
"""
import argparse
import os
import re
import shutil
import subprocess
import sys

INJECT_LINE = "import lr_license_guard as _lrg; _lrg.require()\n"
DEFAULT_EXCLUDE = r"(^|/)(setup\.py|_lr_cython_setup\.py|__init__\.py)$|\.launch\.py$|__pycache__|(^|/)(test|tests)/"


def collect(root, exclude_re):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root)
            if exclude_re.search(rel):
                continue
            out.append(full)
    return sorted(out)


def inject(root, rel_files):
    for rel in rel_files:
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            print("[注入] 警告：文件不存在，跳过：%s" % rel)
            continue
        with open(path, encoding="utf-8") as f:
            src = f.read()
        if "lr_license_guard" in src:
            print("[注入] 已存在，跳过：%s" % rel)
            continue
        lines = src.splitlines(keepends=True)
        # from __future__ import 必须保持在前，注入点放在其最后一行之后
        insert_at = 0
        for i, line in enumerate(lines):
            if line.startswith("from __future__ import"):
                insert_at = i + 1
        lines.insert(insert_at, INJECT_LINE)
        with open(path, "w", encoding="utf-8") as f:
            f.write("".join(lines))
        print("[注入] %s（插入于第 %d 行后）" % (rel, insert_at))


def run_setup(root, files):
    setup_path = os.path.join(root, "_lr_cython_setup.py")
    file_list = ",\n        ".join("r'%s'" % os.path.relpath(f, root) for f in files)
    with open(setup_path, "w") as f:
        f.write(
            "from setuptools import setup\n"
            "from Cython.Build import cythonize\n"
            "setup(name='_lr_cython_build', packages=[], ext_modules=cythonize([\n"
            "        %s\n"
            "    ], language_level=3, compiler_directives={'language_level': '3', 'annotation_typing': False}),\n"
            "    script_args=['build_ext', '--inplace', '-q'])\n" % file_list
        )
    try:
        proc = subprocess.run([sys.executable, "_lr_cython_setup.py"], cwd=root,
                              capture_output=True, text=True)
        return proc.returncode, proc.stderr
    finally:
        if os.path.exists(setup_path):
            os.remove(setup_path)


def so_for(py_path):
    base = py_path[:-3]
    d = os.path.dirname(py_path)
    stem = os.path.basename(base)
    for fn in os.listdir(d or "."):
        if fn.startswith(stem + ".") and fn.endswith(".so"):
            return os.path.join(d, fn)
    return None


def cleanup(root, keep_py, compiled):
    removed = 0
    compiled = set(os.path.abspath(f) for f in compiled)
    for dirpath, dirnames, filenames in os.walk(root):
        for fn in list(filenames):
            full = os.path.join(dirpath, fn)
            if fn.endswith(".c"):
                os.remove(full)
                removed += 1
            elif (fn.endswith(".py") and not keep_py
                  and os.path.abspath(full) in compiled
                  and so_for(full) is not None):
                os.remove(full)
                removed += 1
        if "__pycache__" in dirnames:
            shutil.rmtree(os.path.join(dirpath, "__pycache__"), ignore_errors=True)
            dirnames.remove("__pycache__")
    bdir = os.path.join(root, "build")
    if os.path.isdir(bdir):
        shutil.rmtree(bdir, ignore_errors=True)
    return removed


def strip_sos(root):
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if fn.endswith(".so"):
                subprocess.run(["strip", "--strip-unneeded",
                                os.path.join(dirpath, fn)],
                               capture_output=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--inject", default="", help="逗号分隔的相对路径列表")
    ap.add_argument("--exclude", default=DEFAULT_EXCLUDE)
    ap.add_argument("--keep-py", action="store_true")
    ap.add_argument("--no-strip", action="store_true")
    args = ap.parse_args()

    root = os.path.abspath(args.dir)
    exclude_re = re.compile(args.exclude)
    files = collect(root, exclude_re)
    if not files:
        print("没有需要编译的 .py 文件")
        return 0
    print("共 %d 个 .py 待编译" % len(files))

    if args.inject:
        inject(root, [s for s in args.inject.split(",") if s])

    rc, err = run_setup(root, files)
    failed = []
    if rc == 0:
        missing = [f for f in files if so_for(f) is None]
        failed = missing
    else:
        print("[警告] 批量编译失败，转为逐文件隔离编译…")
        for f in files:
            rc1, err1 = run_setup(root, [f])
            if rc1 != 0 or so_for(f) is None:
                failed.append(f)
                tail = "\n".join((err1 or "").splitlines()[-5:])
                print("[失败] %s\n%s" % (os.path.relpath(f, root), tail))

    succeeded = [f for f in files if f not in failed]
    removed = cleanup(root, args.keep_py, succeeded)
    if not args.no_strip:
        strip_sos(root)

    print("编译完成：成功 %d，失败 %d，清理源码文件 %d"
          % (len(files) - len(failed), len(failed), removed))
    for f in failed:
        print("  [保留明文] %s" % os.path.relpath(f, root))
    return 3 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
