"""联网检测：用 TCP 连接探测（比 ICMP 更稳、无需管理员），语义等价于 C# 的 ping baidu。"""
from __future__ import annotations

import socket

from .model import InternetStatus

PROBE_HOST = "www.baidu.com"
PROBE_PORT = 80


def probe(host: str = PROBE_HOST, port: int = PROBE_PORT, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def to_status(online: bool) -> InternetStatus:
    return InternetStatus.ONLINE if online else InternetStatus.UNAVAILABLE


def check() -> InternetStatus:
    return to_status(probe())
