"""纯 Python AES 解密（GCM 与 CBC，只做解密，够解客户端登录态用）。

为什么不用第三方库：整套工具要能在一个干净的 Python 上直接跑，不额外 pip 安装。
实现只用标准库，正确性由 tests/test_aesgcm.py 里的 NIST 向量兜住。
"""
from __future__ import annotations

SBOX = bytes.fromhex(
    "637c777bf26b6fc53001672bfed7ab76ca82c97dfa5947f0add4a2af9ca472c0"
    "b7fd9326363ff7cc34a5e5f171d8311504c723c31896059a071280e2eb27b275"
    "09832c1a1b6e5aa0523bd6b329e32f8453d100ed20fcb15b6acbbe394a4c58cf"
    "d0efaafb434d338545f9027f503c9fa851a3408f929d38f5bcb6da2110fff3d2"
    "cd0c13ec5f974417c4a77e3d645d197360814fdc222a908846eeb814de5e0bdb"
    "e0323a0a4906245cc2d3ac629195e479e7c8376d8dd54ea96c56f4ea657aae08"
    "ba78252e1ca6b4c6e8dd741f4bbd8b8a703eb5664803f60e613557b986c11d9e"
    "e1f8981169d98e949b1e87e9ce5528df8ca1890dbfe6426841992d0fb054bb16"
)

# 逆 S 盒：解密用（由 SBOX 反推，避免手抄出错）
_INV = [0] * 256
for _i, _v in enumerate(SBOX):
    _INV[_v] = _i
INV_SBOX = bytes(_INV)
del _i, _v

RCON = (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36)


def _xtime(a: int) -> int:
    a <<= 1
    return (a ^ 0x11B) & 0xFF if a & 0x100 else a


def _expand_key(key: bytes):
    """AES-128（16 字节）或 AES-256（32 字节）密钥扩展。"""
    if len(key) not in (16, 32):
        raise ValueError("只支持 AES-128 / AES-256（16 或 32 字节密钥）")
    nk, nr = len(key) // 4, (10 if len(key) == 16 else 14)
    words = [list(key[i * 4:i * 4 + 4]) for i in range(nk)]
    for i in range(nk, 4 * (nr + 1)):
        temp = list(words[i - 1])
        if i % nk == 0:
            temp = temp[1:] + temp[:1]
            temp = [SBOX[b] for b in temp]
            temp[0] ^= RCON[i // nk - 1]
        elif i % nk == 4:
            temp = [SBOX[b] for b in temp]
        words.append([words[i - nk][j] ^ temp[j] for j in range(4)])
    return [sum(words[r * 4:r * 4 + 4], []) for r in range(nr + 1)], nr


def _encrypt_block(block: bytes, round_keys, nr: int) -> bytes:
    s = [block[i] ^ round_keys[0][i] for i in range(16)]
    for rnd in range(1, nr + 1):
        s = [SBOX[b] for b in s]
        # ShiftRows：第 r 行左移 r 位（状态按列存，索引 = 4*列 + 行）
        shifted = [0] * 16
        for r in range(4):
            for c in range(4):
                shifted[4 * c + r] = s[4 * ((c + r) % 4) + r]
        s = shifted
        if rnd != nr:
            for c in range(4):
                a0, a1, a2, a3 = s[c * 4:c * 4 + 4]
                t = a0 ^ a1 ^ a2 ^ a3
                s[c * 4 + 0] = a0 ^ t ^ _xtime(a0 ^ a1)
                s[c * 4 + 1] = a1 ^ t ^ _xtime(a1 ^ a2)
                s[c * 4 + 2] = a2 ^ t ^ _xtime(a2 ^ a3)
                s[c * 4 + 3] = a3 ^ t ^ _xtime(a3 ^ a0)
        s = [s[i] ^ round_keys[rnd][i] for i in range(16)]
    return bytes(s)


def _decrypt_block(block: bytes, round_keys, nr: int) -> bytes:
    s = [block[i] ^ round_keys[nr][i] for i in range(16)]
    for rnd in range(nr - 1, -1, -1):
        # InvShiftRows：第 r 行右移 r 位
        shifted = [0] * 16
        for r in range(4):
            for c in range(4):
                shifted[4 * ((c + r) % 4) + r] = s[4 * c + r]
        s = [INV_SBOX[b] for b in shifted]
        s = [s[i] ^ round_keys[rnd][i] for i in range(16)]
        if rnd != 0:
            for c in range(4):
                a0, a1, a2, a3 = s[c * 4:c * 4 + 4]
                # InvMixColumns（0e/0b/0d/09）
                s[c * 4 + 0] = _gmul(a0, 14) ^ _gmul(a1, 11) ^ _gmul(a2, 13) ^ _gmul(a3, 9)
                s[c * 4 + 1] = _gmul(a0, 9) ^ _gmul(a1, 14) ^ _gmul(a2, 11) ^ _gmul(a3, 13)
                s[c * 4 + 2] = _gmul(a0, 13) ^ _gmul(a1, 9) ^ _gmul(a2, 14) ^ _gmul(a3, 11)
                s[c * 4 + 3] = _gmul(a0, 11) ^ _gmul(a1, 13) ^ _gmul(a2, 9) ^ _gmul(a3, 14)
    return bytes(s)


def _gmul(a: int, b: int) -> int:
    """GF(2^8) 乘法（AES 多项式 0x11B）。"""
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        hi = a & 0x80
        a = (a << 1) & 0xFF
        if hi:
            a ^= 0x1B
        b >>= 1
    return p


def cbc_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    """AES-CBC 解密（无填充处理，长度必须是 16 的倍数）。"""
    if len(iv) != 16:
        raise ValueError("IV 必须是 16 字节")
    if len(data) % 16:
        raise ValueError("密文长度必须是 16 的倍数")
    round_keys, nr = _expand_key(key)
    prev = iv
    out = bytearray()
    for offset in range(0, len(data), 16):
        block = data[offset:offset + 16]
        plain = _decrypt_block(block, round_keys, nr)
        out += bytes(a ^ b for a, b in zip(plain, prev))
        prev = block
    return bytes(out)


def _gf_mul(x: int, y: int) -> int:
    z, v = 0, y
    for i in range(127, -1, -1):
        if (x >> i) & 1:
            z ^= v
        v = (v >> 1) ^ (0xE1 << 120) if v & 1 else v >> 1
    return z


def _ghash(h: int, data: bytes) -> int:
    y = 0
    for i in range(0, len(data), 16):
        block = int.from_bytes(data[i:i + 16].ljust(16, b"\x00"), "big")
        y = _gf_mul(y ^ block, h)
    return y


def gcm_decrypt(key: bytes, nonce: bytes, ciphertext: bytes, tag: bytes, aad: bytes = b"") -> bytes:
    """解密并校验 tag；tag 不符直接抛 ValueError（说明密钥不对或数据被改）。"""
    round_keys, nr = _expand_key(key)
    h = int.from_bytes(_encrypt_block(b"\x00" * 16, round_keys, nr), "big")
    j0 = nonce + (1).to_bytes(4, "big")
    lengths = len(aad).to_bytes(8, "big") + (len(ciphertext) * 8).to_bytes(8, "big")

    def pad(raw: bytes) -> bytes:
        return raw + b"\x00" * ((-len(raw)) % 16)

    mask = _ghash(h, pad(aad) + pad(ciphertext) + lengths)
    expected = bytes(a ^ b for a, b in zip(_encrypt_block(j0, round_keys, nr), mask.to_bytes(16, "big")))
    if expected != tag:
        raise ValueError("GCM tag 校验失败")

    out = bytearray()
    for idx, offset in enumerate(range(0, len(ciphertext), 16), start=2):
        keystream = _encrypt_block(nonce + idx.to_bytes(4, "big"), round_keys, nr)
        out += bytes(a ^ b for a, b in zip(ciphertext[offset:offset + 16], keystream))
    return bytes(out)
