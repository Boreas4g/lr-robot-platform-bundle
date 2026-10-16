"""Ed25519（RFC 8032）最小实现 —— 公域参考公式，迭代循环版本。

仅供 LR 许可证系统内部使用：gen_keys.py / keygen.py 依赖本模块。
验签侧代码已内嵌进 lr_license_guard.py（自包含，不依赖本文件）。
"""
import hashlib

_b = 256
_q = 2 ** 255 - 19
_l = 2 ** 252 + 27742317777372353535851937790883648493


def _sha512(m):
    return hashlib.sha512(m).digest()


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
_Bx = _xrecover(_By)
_B = (_Bx % _q, _By % _q)


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


def _encodeint(y):
    return y.to_bytes(32, "little")


def _encodepoint(P):
    x, y = P
    enc = bytearray(y.to_bytes(32, "little"))
    enc[31] |= (x & 1) << 7
    return bytes(enc)


def _decodeint(s):
    return int.from_bytes(s, "little")


def _decodepoint(s):
    if len(s) != 32:
        raise ValueError("bad point length")
    y = int.from_bytes(s, "little") & ((1 << 255) - 1)
    sign = s[31] >> 7
    x = _xrecover(y)
    if (x & 1) != sign:
        x = _q - x
    P = (x, y)
    if not _isoncurve(P):
        raise ValueError("point not on curve")
    return P


def _isoncurve(P):
    x, y = P
    return (-x * x + y * y - 1 - _d * x * x * y * y) % _q == 0


def _hint(m):
    return int.from_bytes(_sha512(m), "little")


def _clamp_scalar(h):
    a = bytearray(h[:32])
    a[0] &= 248
    a[31] &= 63
    a[31] |= 64
    return int.from_bytes(a, "little")


def publickey(seed):
    """seed: 32 字节私钥种子 -> 32 字节公钥"""
    if len(seed) != 32:
        raise ValueError("seed 必须为 32 字节")
    a = _clamp_scalar(_sha512(seed))
    return _encodepoint(_scalarmult(_B, a))


def sign(msg, seed, pk):
    """对 msg（bytes）签名，返回 64 字节签名"""
    h = _sha512(seed)
    a = _clamp_scalar(h)
    r = _hint(h[32:64] + msg)
    R = _scalarmult(_B, r)
    S = (r + _hint(_encodepoint(R) + pk + msg) * a) % _l
    return _encodepoint(R) + _encodeint(S)


def verify(sig, msg, pk):
    """验签：sig 64 字节，pk 32 字节，返回 bool"""
    if len(sig) != 64 or len(pk) != 32:
        return False
    try:
        R = _decodepoint(sig[:32])
        A = _decodepoint(pk)
    except ValueError:
        return False
    S = _decodeint(sig[32:])
    if S >= _l:
        return False
    h = _hint(sig[:32] + pk + msg)
    return _scalarmult(_B, S) == _edwards(R, _scalarmult(A, h))
