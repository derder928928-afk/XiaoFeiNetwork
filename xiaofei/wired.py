"""有线认证：PPPoE(rasdial)/802.1X(netsh)/学校客户端，复用 Windows 已存配置与凭据。"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

from .model import CampusProfile


@dataclass(frozen=True)
class BroadbandEntry:
    name: str
    phonebook_path: str


def _has_control(text: str) -> bool:
    return any(ord(ch) < 32 or ord(ch) == 127 for ch in text)


def _tasklist_has(image_name: str) -> bool:
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/NH"],
                             capture_output=True, text=True, timeout=10,
                             creationflags=0x08000000).stdout
    except Exception:
        return False
    return image_name.lower() in (out or "").lower()


def parse_phonebook(text: str, file: str) -> list[BroadbandEntry]:
    result: list[BroadbandEntry] = []
    name: str | None = None
    broadband = False

    def add():
        if broadband and name and name.strip():
            result.append(BroadbandEntry(name, file))

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            add()
            name = line[1:-1]
            broadband = False
        elif name is not None:
            pair = line.split("=", 1)
            if len(pair) == 2 and pair[0].strip().lower() == "type":
                # RASET_Broadband = 5；绝不用同名 VPN/模拟拨号条目。
                broadband = pair[1].strip() == "5"
    add()
    return result


def _pbk_paths() -> list[str]:
    paths = []
    for env in ("APPDATA", "PROGRAMDATA"):
        base = os.environ.get(env)
        if base:
            paths.append(os.path.join(base, "Microsoft", "Network", "Connections", "Pbk", "rasphone.pbk"))
    return paths


def read_broadband_entries() -> list[BroadbandEntry]:
    entries: list[BroadbandEntry] = []
    for file in _pbk_paths():
        try:
            if os.path.isfile(file):
                with open(file, "r", encoding="utf-8", errors="ignore") as fh:
                    entries.extend(parse_phonebook(fh.read(), file))
        except OSError:
            pass
    seen: dict[str, BroadbandEntry] = {}
    for entry in entries:  # APPDATA 在前，优先当前用户条目
        seen.setdefault(entry.name.lower(), entry)
    return list(seen.values())


def build_command(profile: CampusProfile, interface_name: str,
                  entries: list[BroadbandEntry], system_dir: str) -> tuple[str, list[str]]:
    if not profile.is_wired or not profile.uses_system_authentication:
        raise RuntimeError("当前配置未选择有线系统认证。")
    if profile.wired_auth == "pppoe":
        entry = next((e for e in entries if e.name.lower() == profile.broadband_name.lower()), None)
        if entry is None:
            raise RuntimeError("未找到该 PPPoE 宽带连接。请先在 Windows 创建宽带连接、保存账号密码，再选择对应连接名称。")
        if entry.name.startswith("/") or _has_control(entry.name):
            raise RuntimeError("宽带连接名称无效，请在 Windows 中重新命名该连接。")
        return (os.path.join(system_dir, "rasdial.exe"), [entry.name, "/PHONEBOOK:" + entry.phonebook_path])
    if profile.wired_auth == "dot1x":
        if not interface_name.strip():
            raise RuntimeError("请先选择需要认证的以太网接口。")
        return (os.path.join(system_dir, "netsh.exe"), ["lan", "reconnect", "interface=" + interface_name])
    raise RuntimeError("专用客户端通过已选程序启动。")


def _run(cmd: str, args: list[str], timeout: float = 60.0) -> int:
    creationflags = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run([cmd, *args], capture_output=True, timeout=timeout,
                          creationflags=creationflags, stdin=subprocess.DEVNULL)
    return proc.returncode


def connect(profile: CampusProfile, interface_name: str) -> str:
    """返回状态文案；失败抛异常。账号密码绝不进命令行/日志/UI。"""
    if profile.wired_auth == "client":
        file = profile.authentication_client
        if not os.path.isabs(file) or not file.lower().endswith(".exe") or not os.path.isfile(file):
            raise RuntimeError("请先选择学校已安装的认证客户端 EXE 文件。")
        image = os.path.basename(file)
        if _tasklist_has(image):
            return "检测到同名认证客户端，请先检查其窗口并完成登录。"
        os.startfile(file)  # noqa: S606 - 启动用户选定的学校客户端
        return "学校认证客户端已打开，请在客户端内完成登录；助手将继续检查联网状态。"

    system_dir = os.environ.get("SystemRoot", r"C:\\Windows") + "\\System32"
    cmd, args = build_command(profile, interface_name, read_broadband_entries(), system_dir)
    code = _run(cmd, args)
    if code != 0:
        if profile.wired_auth == "pppoe":
            raise RuntimeError(f"Windows PPPoE 拨号失败（错误码 {code}）。请检查系统保存的账号密码、网线及宽带连接设置。")
        raise RuntimeError(f"Windows 802.1X 认证请求失败（错误码 {code}）。请检查以太网认证配置、Wired AutoConfig 服务和运行权限。")
    return ("Windows 拨号已完成，正在检查实际联网状态。" if profile.wired_auth == "pppoe"
            else "已向所选以太网接口发起 802.1X 认证，正在检查实际联网状态。")
