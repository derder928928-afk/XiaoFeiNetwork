"""本地配置存储：JSON + Windows DPAPI（当前用户）加密密码，与 C# LocalStore 行为一致。"""
from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
import tempfile
from dataclasses import replace

from .model import CampusProfile


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _crypt32():
    return ctypes.windll.crypt32


def _kernel32():
    return ctypes.windll.kernel32


def _blob_from(data: bytes) -> "_DATA_BLOB":
    buf = ctypes.create_string_buffer(data, len(data))
    blob = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    # keep buf referenced by the blob's memory until copied
    blob._buffer = buf  # type: ignore[attr-defined]
    return blob


def protect(plain: str) -> str:
    if not plain:
        return ""
    inp = _blob_from(plain.encode("utf-8"))
    out = _DATA_BLOB()
    if not _crypt32().CryptProtectData(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("DPAPI 加密失败")
    try:
        data = ctypes.string_at(out.pbData, out.cbData)
    finally:
        _kernel32().LocalFree(out.pbData)
    return base64.b64encode(data).decode("ascii")


def unprotect(token: str) -> str:
    if not token:
        return ""
    raw = base64.b64decode(token)
    inp = _blob_from(raw)
    out = _DATA_BLOB()
    if not _crypt32().CryptUnprotectData(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("DPAPI 解密失败（可能更换了 Windows 用户）")
    try:
        data = ctypes.string_at(out.pbData, out.cbData)
    finally:
        _kernel32().LocalFree(out.pbData)
    return data.decode("utf-8")


def app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_dir() -> str:
    custom = os.environ.get("XIAOFEI_DATA_DIR")
    if custom and custom.strip():
        return os.path.abspath(custom.strip())
    local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
    preferred = os.path.join(local, "XiaoFeiNetwork")
    try:
        os.makedirs(preferred, exist_ok=True)
        return preferred
    except OSError:
        fallback = os.path.join(app_dir(), "XiaoFeiNetwork-data")
        os.makedirs(fallback, exist_ok=True)
        return fallback


class LocalStore:
    @property
    def file_path(self) -> str:
        return os.path.join(data_dir(), "configuration.json")

    def load(self) -> tuple[CampusProfile, str]:
        path = self.file_path
        if not os.path.exists(path):
            return (CampusProfile(), "")
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        profile = CampusProfile.from_dict(data.get("profile", {}))
        profile.validate()
        password = unprotect(data.get("protectedPassword", ""))
        return (profile, password)

    def save(self, profile: CampusProfile, password: str) -> None:
        profile.validate()
        directory = data_dir()
        os.makedirs(directory, exist_ok=True)
        payload = {"profile": profile.to_dict(), "protectedPassword": protect(password)}
        fd, tmp = tempfile.mkstemp(dir=directory, prefix="configuration-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self.file_path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
