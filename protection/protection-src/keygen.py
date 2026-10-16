#!/usr/bin/env python3
"""LR 许可证签发工具（供应商侧）。

用法：
  python3 keygen.py --key license_private.key --machine-code LR1-XXXX-XXXX-XXXX \
      [--date 2026-10-13] [--out license.lic]

机器码由客户机在交付/部署后运行 `lr-license code` 获得。
许可证文件交给客户机执行 `sudo lr-license install license.lic` 即完成授权。
"""
import argparse
import base64
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ed25519py import publickey, sign  # noqa: E402

PRODUCT = "LR-LIBRARY-ROBOT"


def main():
    ap = argparse.ArgumentParser(description="LR 许可证签发工具")
    ap.add_argument("--key", required=True, help="私钥文件（hex，来自 gen_keys.py）")
    ap.add_argument("--machine-code", required=True, help="客户机机器码 LR1-XXXX-XXXX-XXXX")
    ap.add_argument("--date", default=datetime.date.today().isoformat(), help="签发日期")
    ap.add_argument("--out", default=None, help="输出许可证文件路径")
    args = ap.parse_args()

    code = args.machine_code.strip().upper()
    if not code.startswith("LR1-") or len(code) != 18:
        ap.error("机器码格式应为 LR1-XXXX-XXXX-XXXX，实际：%s" % args.machine_code)

    with open(args.key) as f:
        seed = bytes.fromhex(f.read().strip())
    if len(seed) != 32:
        ap.error("私钥长度非法（应为 32 字节 hex）")
    pk = publickey(seed)

    payload = ("%s|%s|%s" % (PRODUCT, code, args.date)).encode("utf-8")
    sig = sign(payload, seed, pk)

    lic = {
        "product": PRODUCT,
        "machine_code": code,
        "issued_at": args.date,
        "signature": base64.b64encode(sig).decode("ascii"),
    }
    out = args.out or ("license-%s.lic" % code.replace("-", ""))
    with open(out, "w") as f:
        json.dump(lic, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.chmod(out, 0o600)
    print("已签发：%s" % out)
    print("  机器码：%s  签发日期：%s" % (code, args.date))
    print("  公钥指纹：%s" % pk.hex()[:16])
    return 0


if __name__ == "__main__":
    sys.exit(main())
