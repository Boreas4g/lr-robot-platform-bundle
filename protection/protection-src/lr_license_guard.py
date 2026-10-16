"""LR 图书馆机器人许可证守护模块（发布版本为 Cython 编译的 .so，无源码）。

- 机器码：根分区所在磁盘序列号 → SHA256(盐 ‖ 序列号) → LR1-XXXX-XXXX-XXXX
- 许可证：/etc/lr-license/license.lic（JSON），Ed25519 签名，验签公钥内嵌本模块
- require()：校验失败打印原因并 os._exit(1)（fail-closed）

本文件仅供内部构建使用，不得随产品交付。
"""
import base64
import binascii
import hashlib
import json
import os
import re
import subprocess
import sys

PRODUCT = "LR-LIBRARY-ROBOT"
LICENSE_PATH = "/etc/lr-license/license.lic"
_ENV_OVERRIDE = "LR_LICENSE_FILE"
_PUBLIC_KEY_HEX = "2270c8516eee2f20e333d7ffc7714ceb14f17fdb0eaecb4a719ccdaf902a2e4b"
_SALT = b"lr-license-v1\x00"

# ------------------------------------------------------------------ Ed25519 验签
_q = 2 ** 255 - 19
_l = 2 ** 252 + 27742317777372353535851937790883648493


def _expmod(b, e, m):
    r = 1
    b %= m
    while e:
        if e & 1:
            r = (r * b) % m
        b = (b * b) % m
        e >>= 1
    return r


def _inv(x):
    return _expmod(x, _q - 2, _q)


_d = (-121665 * _inv(121666)) % _q
_I = _expmod(2, (_q - 1) // 4, _q)


def _xrecover(y):
    xx = (y * y - 1) * _inv(_d * y * y + 1)
    x = _expmod(xx, (_q + 3) // 8, _q)
    if (x * x - xx) % _q != 0:
        x = (x * _I) % _q
    if x % 2 != 0:
        x = _q - x
    return x


_By = (4 * _inv(5)) % _q
_B = (_xrecover(_By) % _q, _By)


def _edwards(P, Q):
    x1, y1 = P
    x2, y2 = Q
    x3 = (x1 * y2 + x2 * y1) * _inv(1 + _d * x1 * x2 * y1 * y2)
    y3 = (y1 * y2 + x1 * x2) * _inv(1 - _d * x1 * x2 * y1 * y2)
    return (x3 % _q, y3 % _q)


def _scalarmult(P, e):
    Q = (0, 1)
    while e:
        if e & 1:
            Q = _edwards(Q, P)
        P = _edwards(P, P)
        e >>= 1
    return Q


def _decodepoint(s):
    if len(s) != 32:
        raise ValueError("bad point")
    y = int.from_bytes(s, "little") & ((1 << 255) - 1)
    sign = s[31] >> 7
    x = _xrecover(y)
    if (x & 1) != sign:
        x = _q - x
    if (-x * x + y * y - 1 - _d * x * x * y * y) % _q != 0:
        raise ValueError("not on curve")
    return (x, y)


def _ed_verify(sig, msg, pk):
    if len(sig) != 64 or len(pk) != 32:
        return False
    try:
        R = _decodepoint(sig[:32])
        A = _decodepoint(pk)
    except ValueError:
        return False
    S = int.from_bytes(sig[32:], "little")
    if S >= _l:
        return False
    h = int.from_bytes(hashlib.sha512(sig[:32] + pk + msg).digest(), "little")
    return _scalarmult(_B, S) == _edwards(R, _scalarmult(A, h))


# ------------------------------------------------------------------ 机器指纹
class LicenseError(Exception):
    pass


def _find_root_disk():
    try:
        out = subprocess.run(["findmnt", "-no", "SOURCE", "/"],
                             capture_output=True, text=True, timeout=5)
        src = out.stdout.strip().splitlines()[0] if out.stdout.strip() else ""
    except Exception:
        src = ""
    if not src:
        for cand in ("sda", "nvme0n1", "vda", "mmcblk0"):
            if os.path.exists("/sys/block/" + cand):
                return cand
        return None
    src = src.split("[")[0]
    name = os.path.basename(os.path.realpath(src))
    m = re.match(r"^(nvme\d+n\d+|mmcblk\d+|md\d+|loop\d+)p?\d*$", name)
    if m:
        return m.group(1)
    m = re.match(r"^([a-zA-Z]+)\d+$", name)
    if m:
        return m.group(1)
    return name


def _disk_serial(disk):
    try:
        out = subprocess.run(["lsblk", "-dno", "SERIAL", "/dev/" + disk],
                             capture_output=True, text=True, timeout=5)
        s = out.stdout.strip()
        if s:
            return s.splitlines()[0].strip()
    except Exception:
        pass
    for p in ("/sys/block/%s/device/serial" % disk, "/sys/block/%s/serial" % disk):
        try:
            with open(p) as f:
                s = f.read().strip()
            if s:
                return s
        except OSError:
            pass
    try:
        out = subprocess.run(["udevadm", "info", "--query=property",
                              "--name=/dev/" + disk],
                             capture_output=True, text=True, timeout=5).stdout
        val = {}
        for line in out.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                val[k] = v.strip()
        return val.get("ID_SERIAL_SHORT") or val.get("ID_SERIAL") or None
    except Exception:
        return None


def fingerprint():
    """返回 {'disk','serial','hash'}；失败抛 LicenseError"""
    disk = _find_root_disk()
    if not disk:
        raise LicenseError("无法确定根分区所在磁盘")
    serial = _disk_serial(disk)
    if not serial:
        raise LicenseError("无法读取磁盘 %s 的序列号" % disk)
    digest = hashlib.sha256(_SALT + serial.encode("utf-8")).hexdigest().upper()
    return {"disk": disk, "serial": serial, "hash": digest}


def machine_code():
    h = fingerprint()["hash"]
    return "LR1-%s-%s-%s" % (h[:4], h[4:8], h[8:12])


def signed_payload(product, code, issued_at):
    return ("%s|%s|%s" % (product, code, issued_at)).encode("utf-8")


# ------------------------------------------------------------------ 许可证校验
def _license_file(path=None):
    if path:
        return path
    env = os.environ.get(_ENV_OVERRIDE)
    return env if env else LICENSE_PATH


def check(path=None):
    """校验许可证。返回许可证 dict；失败抛 LicenseError。"""
    fp = _license_file(path)
    if not os.path.exists(fp):
        raise LicenseError("许可证文件不存在：%s" % fp)
    try:
        with open(fp) as f:
            lic = json.load(f)
    except (OSError, ValueError) as e:
        raise LicenseError("许可证文件无法解析：%s" % e)
    for k in ("product", "machine_code", "issued_at", "signature"):
        if k not in lic:
            raise LicenseError("许可证缺少字段：%s" % k)
    if lic["product"] != PRODUCT:
        raise LicenseError("许可证产品标识不符：%s" % lic["product"])
    local_code = machine_code()
    if lic["machine_code"] != local_code:
        raise LicenseError("机器码不匹配（本机 %s，许可证 %s）——软件未授权在本机运行"
                           % (local_code, lic["machine_code"]))
    try:
        sig = base64.b64decode(lic["signature"], validate=True)
    except binascii.Error:
        raise LicenseError("许可证签名格式非法")
    try:
        pk = bytes.fromhex(_PUBLIC_KEY_HEX)
    except ValueError:
        raise LicenseError("守护模块公钥损坏")
    msg = signed_payload(lic["product"], lic["machine_code"], lic["issued_at"])
    if not _ed_verify(sig, msg, pk):
        raise LicenseError("许可证签名校验失败（许可证被篡改或非官方签发）")
    return lic


def require(path=None):
    """入口校验：失败打印原因并立即终止进程。"""
    try:
        check(path)
    except LicenseError as e:
        sys.stderr.write("\n[lr-license] 许可证校验失败：%s\n"
                         "[lr-license] 请联系设备供应商获取本机许可证。\n\n" % e)
        sys.stderr.flush()
        os._exit(1)
    except Exception as e:  # 兜底：任何意外同样 fail-closed
        sys.stderr.write("\n[lr-license] 许可证校验异常（%s），拒绝运行。\n\n" % e)
        sys.stderr.flush()
        os._exit(1)


# ------------------------------------------------------------------ CLI
def _cmd_code():
    fp = fingerprint()
    print("产品：      %s" % PRODUCT)
    print("根盘设备：  /dev/%s" % fp["disk"])
    print("本机机器码：%s" % machine_code())


def _cmd_verify(path=None):
    try:
        lic = check(path)
    except LicenseError as e:
        print("[失败] %s" % e)
        return 1
    print("[通过] 许可证有效：机器码 %s，签发日期 %s" % (lic["machine_code"], lic["issued_at"]))
    return 0


def _cmd_info(path=None):
    fp = _license_file(path)
    if not os.path.exists(fp):
        print("许可证文件不存在：%s" % fp)
        return 1
    try:
        with open(fp) as f:
            lic = json.load(f)
        lic.pop("signature", None)
        print(json.dumps(lic, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as e:
        print("许可证文件无法解析：%s" % e)
        return 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print("用法：lr-license <命令> [参数]\n"
              "  code            显示本机机器码（用于向供应商申请许可证）\n"
              "  verify [文件]   校验许可证（默认 /etc/lr-license/license.lic）\n"
              "  info [文件]     显示许可证信息\n"
              "  install <文件>  安装许可证到 /etc/lr-license/（需 root）")
        return 0
    cmd = argv[0]
    if cmd == "code":
        _cmd_code()
        return 0
    if cmd == "verify":
        return _cmd_verify(argv[1] if len(argv) > 1 else None)
    if cmd == "info":
        return _cmd_info(argv[1] if len(argv) > 1 else None)
    if cmd == "install":
        if len(argv) < 2:
            print("用法：lr-license install <许可证文件>")
            return 2
        import shutil
        os.makedirs(os.path.dirname(LICENSE_PATH), exist_ok=True)
        # 先验签再安装，防止装错文件
        rc = _cmd_verify(argv[1])
        if rc != 0:
            print("拒绝安装：许可证未通过校验")
            return 1
        shutil.copyfile(argv[1], LICENSE_PATH)
        os.chmod(LICENSE_PATH, 0o640)
        print("已安装到 %s" % LICENSE_PATH)
        return 0
    print("未知命令：%s（--help 查看用法）" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main())
