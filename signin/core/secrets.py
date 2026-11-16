"""从本机客户端里读「已经登录过」的凭证（Windows DPAPI + Chromium v10 加密）。

设计原则：用户只做一件事——在自己的客户端/网页里登录一次。
剩下的读凭证、解密、刷新，全部由这里完成，配置里不再出现「令牌 / Cookie」这类输入框。

支持的两种存储：
1. 客户端自己写的 v10 密文（`v10` + 12 字节 nonce + 密文 + 16 字节 tag）
   → 主密钥在 `<应用目录>/Local State` 的 `os_crypt.encrypted_key`，先用 DPAPI 解出，
     再用 AES-256-GCM 解内容。
2. VS Code 内核应用的 `state.vscdb`（ItemTable 里的 `secret://...`）
   → 值可能是 TEXT 形式的 `{"type":"Buffer","data":[...]}`，解码后再按上面第 1 条解。
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import shutil
import sqlite3
import tempfile
from ctypes import wintypes
from pathlib import Path

from .aesgcm import gcm_decrypt

_ENV_ROOTS = ("APPDATA", "LOCALAPPDATA")


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _unprotect(data: bytes) -> bytes:
    """调 Windows DPAPI 解开一段本机加密数据（跨机器/换用户就解不开，这是正常的）。"""
    if os.name != "nt":
        raise RuntimeError("DPAPI 只在 Windows 上可用")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    blob_in = DATA_BLOB(len(data), ctypes.cast(ctypes.c_char_p(data), ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    if not crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None, 0,
                                      ctypes.byref(blob_out)):
        raise RuntimeError(f"DPAPI 解密失败（错误码 {ctypes.get_last_error()}）")
    out = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    kernel32.LocalFree(blob_out.pbData)
    return out


def app_dir(names) -> Path | None:
    """在 %APPDATA% / %LOCALAPPDATA% 下按名字（不区分大小写）找应用目录。"""
    if isinstance(names, str):
        names = (names,)
    wanted = {n.lower() for n in names}
    for var in _ENV_ROOTS:
        root = os.environ.get(var)
        if not root or not os.path.isdir(root):
            continue
        try:
            for entry in os.listdir(root):
                if entry.lower() in wanted:
                    return Path(root) / entry
        except OSError:
            continue
    return None


def master_key(profile_dir: Path) -> bytes | None:
    """从 `Local State` 里取主密钥（DPAPI 解一层，得到 32 字节 AES 密钥）。"""
    state_file = Path(profile_dir) / "Local State"
    if not state_file.exists():
        return None
    try:
        doc = json.loads(state_file.read_text(encoding="utf-8"))
        raw = base64.b64decode(doc.get("os_crypt", {}).get("encrypted_key", ""))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not raw:
        return None
    try:
        return _unprotect(raw[5:] if raw[:5] == b"DPAPI" else raw)
    except RuntimeError:
        return None


def decrypt_blob(key: bytes | None, blob: bytes) -> bytes:
    """解一段 v10/v11 密文；不是 Chromium 密文时退回 DPAPI。"""
    if blob[:3] in (b"v10", b"v11"):
        if not key:
            raise RuntimeError("缺少主密钥，无法解 v10 密文")
        return gcm_decrypt(key, blob[3:15], blob[15:-16], blob[-16:])
    return _unprotect(blob)


def read_encrypted_json(path: Path, key: bytes | None):
    raw = Path(path).read_bytes()
    return json.loads(decrypt_blob(key, raw).decode("utf-8"))


def _payload_of(value) -> bytes:
    """把 ItemTable 的原始值还原成字节（TEXT / BLOB 两种存储都兼容）。"""
    data = value if isinstance(value, (bytes, bytearray)) else str(value).encode("utf-8")
    try:
        obj = json.loads(data.decode("utf-8"))
        if isinstance(obj, dict) and isinstance(obj.get("data"), (list, dict)):
            payload = obj["data"]
            if isinstance(payload, dict):
                payload = payload.get("data", [])
            return bytes(payload)
    except (ValueError, TypeError, json.JSONDecodeError):
        pass
    return bytes(data)


def read_vscdb_secret(profile_dir: Path, needle: str) -> dict | None:
    """在 state.vscdb 里找键名含 needle 的 secret，解出来当 JSON 返回。"""
    db = Path(profile_dir) / "User" / "globalStorage" / "state.vscdb"
    if not db.exists():
        return None
    key = master_key(profile_dir)
    tmp = Path(tempfile.gettempdir()) / f"signin_vscdb_{abs(hash(str(db)))}.db"
    try:
        shutil.copy2(db, tmp)
        con = sqlite3.connect(tmp)
        try:
            rows = con.execute("select key, value from ItemTable").fetchall()
        finally:
            con.close()
    except (OSError, sqlite3.Error):
        return None
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass

    for name, value in rows:
        if needle.lower() not in str(name).lower():
            continue
        payload = _payload_of(value)
        for attempt in ("auto", "dpapi"):
            try:
                plain = (decrypt_blob(key, payload) if attempt == "auto" else _unprotect(payload))
            except (RuntimeError, ValueError):
                continue
            try:
                doc = json.loads(plain.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(doc, dict):
                return doc
    return None
