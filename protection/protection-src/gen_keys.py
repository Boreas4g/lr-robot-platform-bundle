#!/usr/bin/env python3
"""生成 LR 许可证 Ed25519 密钥对（只在密钥轮换/初始化时运行）。

私钥 -> keys/license_private.key（hex，chmod 600）—— 只存备份，绝不交付！
公钥 -> keys/license_public.key（hex）—— 内嵌进 lr_license_guard.py

注意：轮换密钥后必须用新公钥重编 lr_license_guard .so 并部署到各机器，
再用新私钥重新签发各机许可证。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ed25519py import publickey  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
KEYS = os.path.join(HERE, "keys")


def main():
    os.makedirs(KEYS, exist_ok=True)
    priv_path = os.path.join(KEYS, "license_private.key")
    pub_path = os.path.join(KEYS, "license_public.key")
    if os.path.exists(priv_path):
        print("私钥已存在，覆盖会作废已签发的全部许可证！文件：%s" % priv_path)
        if input("确认重新生成？输入 YES 继续：") != "YES":
            print("已取消")
            return 1
    seed = os.urandom(32)
    pk = publickey(seed)
    with open(priv_path, "w") as f:
        f.write(seed.hex() + "\n")
    os.chmod(priv_path, 0o600)
    with open(pub_path, "w") as f:
        f.write(pk.hex() + "\n")
    os.chmod(pub_path, 0o644)
    print("私钥：%s（妥善保管，只存备份！）" % priv_path)
    print("公钥：%s" % pub_path)
    print("公钥 hex：%s" % pk.hex())
    return 0


if __name__ == "__main__":
    sys.exit(main())
