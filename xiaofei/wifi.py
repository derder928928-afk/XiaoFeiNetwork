"""Wi-Fi：用 netsh wlan 扫描/连接（纯 subprocess，避免 wlanapi ABI 风险）。
解析函数为纯函数，兼容中英文 Windows 标签，便于离线测试。"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

CREATE_NO_WINDOW = 0x08000000


@dataclass(frozen=True)
class WifiNetwork:
    ssid: str
    signal: int
    secure: bool
    profile_name: str = ""


def _netsh(args: list[str], timeout: float = 20.0) -> str:
    try:
        proc = subprocess.run(["netsh", "wlan", *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout,
                              creationflags=CREATE_NO_WINDOW, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout or ""


# 中文/英文标签都可能出现；用值特征匹配更稳。
_SSID_LINE = re.compile(r"^\s*(?:SSID|网络名)\s*(?:\d+\s*)?[：:]\s*(.+?)\s*$", re.IGNORECASE)
_SIGNAL_LINE = re.compile(r"(?:Signal|信号)\s*[：:]\s*(\d+)\s*%?", re.IGNORECASE)
_AUTH_LINE = re.compile(r"(?:Authentication|身份验证)\s*[：:]\s*(.+?)\s*$", re.IGNORECASE)
_STATE_LINE = re.compile(r"(?:State|状态)\s*[：:]\s*(.+?)\s*$", re.IGNORECASE)
_PROFILE_LINE = re.compile(r"(?:Profile|配置文件|名称)\s*[：:]\s*(.+?)\s*$", re.IGNORECASE)


def current_ssid(text: str | None = None) -> str | None:
    if text is None:
        text = _netsh(["show", "interfaces"])
    state = _STATE_LINE.search(text or "")
    if state and ("disconnected" in state.group(1).lower() or "断开" in state.group(1)):
        return None
    for line in (text or "").splitlines():
        stripped = line.strip()
        # 只认纯 "SSID :"（排除 BSSID）
        m = re.match(r"^\s*SSID\s*[：:]\s*(.+?)\s*$", line, re.IGNORECASE)
        if m and not re.match(r"^\s*BSSID", line, re.IGNORECASE):
            return m.group(1)
    return None


def parse_networks(text: str) -> list[WifiNetwork]:
    networks: list[WifiNetwork] = []
    current: str | None = None
    signal = 0
    secure = False
    flush = lambda: (current is not None and networks.append(WifiNetwork(current, signal, secure)))
    for line in (text or "").splitlines():
        m = re.match(r"^\s*SSID\s*\d+\s*[：:]\s*(.+?)\s*$", line, re.IGNORECASE)
        if m:
            flush()
            current, signal, secure = m.group(1), 0, False
            continue
        if current is None:
            continue
        sm = _SIGNAL_LINE.search(line)
        if sm:
            signal = int(sm.group(1))
        am = _AUTH_LINE.search(line)
        if am:
            auth = am.group(1).strip().lower()
            secure = not (auth in ("open", "无", "未加密", "none", "开放") or "open" in auth or "无" in auth or "开放" in auth)
    flush()
    return networks


def scan(preferred: str | None = None) -> list[WifiNetwork]:
    return parse_networks(_netsh(["show", "networks"]))


def _profile_exists(ssid: str) -> bool:
    text = _netsh(["show", "profiles", f"name={ssid}"])
    return bool(text) and "does not exist" not in text.lower() and "不存在" not in text


def open_profile_xml(ssid: str) -> str:
    from xml.sax.saxutils import escape
    hex_ssid = ssid.encode("utf-8").hex().upper()
    return (
        '<?xml version="1.0"?>\n'
        '<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">\n'
        f"  <name>{escape(ssid)}</name>\n"
        f"  <SSIDConfig><SSID><hex>{hex_ssid}</hex><name>{escape(ssid)}</name></SSID></SSIDConfig>\n"
        "  <connectionType>ESS</connectionType><connectionMode>manual</connectionMode>\n"
        "  <MSM><security><authEncryption><authentication>open</authentication>"
        "<encryption>none</encryption><useOneX>false</useOneX></authEncryption></security></MSM>\n"
        "</WLANProfile>\n"
    )


def _ensure_open_profile(ssid: str) -> None:
    if _profile_exists(ssid):
        return
    import os
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".xml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(open_profile_xml(ssid))
        _netsh(["add", "profile", f"filename={path}", "use=yes", "overwrite=no"])
    finally:
        if os.path.exists(path):
            os.remove(path)


def connect(ssid: str, use_saved: bool) -> None:
    if not use_saved:
        _ensure_open_profile(ssid)
    _netsh(["connect", f"ssid={ssid}", f"name={ssid}"])


def wait_connected(ssid: str, attempts: int = 25, delay: float = 1.0) -> bool:
    import time
    for _ in range(attempts):
        time.sleep(delay)
        if current_ssid() == ssid:
            return True
    return False
