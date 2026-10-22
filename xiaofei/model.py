"""核心模型与策略：与 C# Core.cs 行为一致（CampusProfile / AutoPolicy / PortalRecovery）。"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

DEFAULT_SSID = "JXIT-5G"


class InternetStatus(enum.Enum):
    ONLINE = "online"
    UNAVAILABLE = "unavailable"


def _has_control(text: str) -> bool:
    return any(ord(ch) < 32 or ord(ch) == 127 for ch in text)


@dataclass(frozen=True)
class CampusProfile:
    ssid: str = DEFAULT_SSID
    wired_auth: str = "web"          # web | pppoe | dot1x | client
    ethernet_name: str = ""
    broadband_name: str = ""
    authentication_client: str = ""
    use_saved_wifi_profile: bool = False
    portal_enabled: bool = True
    portal_url: str = ""
    username: str = ""
    service_option: str = ""
    user_selector: str = ""
    password_selector: str = ""
    submit_selector: str = ""
    auto_submit: bool = True
    automatic: bool = False

    @property
    def is_wired(self) -> bool:
        return not self.ssid.strip()

    @property
    def uses_system_authentication(self) -> bool:
        return self.is_wired and self.wired_auth != "web"

    @property
    def uses_web_portal(self) -> bool:
        return self.portal_enabled and not self.uses_system_authentication

    @property
    def connection_label(self) -> str:
        if not self.is_wired:
            return "Wi-Fi"
        return {
            "pppoe": "有线 · PPPoE 拨号",
            "dot1x": "有线 · 802.1X",
            "client": "有线 · 专用客户端",
        }.get(self.wired_auth, "有线 · 网页认证")

    @staticmethod
    def origin(address: str) -> str | None:
        """返回 scheme://host[:port] 小写；非 http/https、缺主机、含账号密码则 None。"""
        try:
            parts = urlsplit(address)
        except ValueError:
            return None
        scheme = parts.scheme.lower()
        if scheme not in ("http", "https"):
            return None
        if not parts.hostname:
            return None
        if parts.username is not None or parts.password is not None:
            return None
        host = parts.hostname.lower()
        try:
            port = parts.port
        except ValueError:
            return None
        netloc = host if port is None else f"{host}:{port}"
        # 省略默认端口，与 .NET GetLeftPart(Authority) 一致
        if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
            netloc = host
        return f"{scheme}://{netloc}"

    def validate(self) -> None:
        if not self.is_wired and len(self.ssid.encode("utf-8")) > 32:
            raise ValueError("Wi-Fi 名称最多为 32 字节；有线模式请留空。")
        if self.wired_auth not in ("web", "pppoe", "dot1x", "client"):
            raise ValueError("请选择有效的有线认证方式。")
        if self.is_wired and self.wired_auth == "pppoe" and (
            not self.broadband_name.strip() or _has_control(self.broadband_name)
        ):
            raise ValueError("请填写或选择 Windows 中已配置的 PPPoE 宽带连接名称。")
        if self.is_wired and self.wired_auth == "client" and (
            not self.authentication_client.strip()
            or not self.authentication_client.lower().endswith(".exe")
        ):
            raise ValueError("请先选择学校认证客户端的 EXE 文件。")
        if _has_control(self.ethernet_name):
            raise ValueError("以太网接口名称无效。")
        # 认证地址留空是合法的：连接校园网后自动探测；只有填了才校验。
        if self.uses_web_portal and self.portal_url.strip() and CampusProfile.origin(self.portal_url) is None:
            raise ValueError("请输入 http:// 或 https:// 开头的认证地址，不能在地址中包含账号密码。")

    def to_dict(self) -> dict:
        return {
            "ssid": self.ssid, "wiredAuth": self.wired_auth, "ethernetName": self.ethernet_name,
            "broadbandName": self.broadband_name, "authenticationClient": self.authentication_client,
            "useSavedWifiProfile": self.use_saved_wifi_profile, "portalEnabled": self.portal_enabled,
            "portalUrl": self.portal_url, "username": self.username, "serviceOption": self.service_option,
            "userSelector": self.user_selector, "passwordSelector": self.password_selector,
            "submitSelector": self.submit_selector, "autoSubmit": self.auto_submit, "automatic": self.automatic,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CampusProfile":
        return cls(
            ssid=data.get("ssid", DEFAULT_SSID),
            wired_auth=data.get("wiredAuth", "web"),
            ethernet_name=data.get("ethernetName", ""),
            broadband_name=data.get("broadbandName", ""),
            authentication_client=data.get("authenticationClient", ""),
            use_saved_wifi_profile=bool(data.get("useSavedWifiProfile", False)),
            portal_enabled=bool(data.get("portalEnabled", True)),
            portal_url=data.get("portalUrl", ""),
            username=data.get("username", ""),
            service_option=data.get("serviceOption", ""),
            user_selector=data.get("userSelector", ""),
            password_selector=data.get("passwordSelector", ""),
            submit_selector=data.get("submitSelector", ""),
            auto_submit=bool(data.get("autoSubmit", True)),
            automatic=bool(data.get("automatic", False)),
        )


class AutoPolicy:
    def __init__(self) -> None:
        self.last_attempt: datetime = datetime.min.replace(tzinfo=timezone.utc)

    def should_join(self, enabled: bool, target: str, current: str | None,
                    visible, busy: bool, now: datetime) -> bool:
        visible = list(visible)
        return (enabled and len(target) > 0 and current != target and target in visible
                and not busy and (now - self.last_attempt) >= timedelta(seconds=60))

    def should_prepare_wired(self, enabled: bool, needed: bool, busy: bool, now: datetime) -> bool:
        return enabled and needed and not busy and (now - self.last_attempt) >= timedelta(seconds=60)

    def begin(self, now: datetime) -> None:
        self.last_attempt = now

    def reset(self) -> None:
        self.last_attempt = datetime.min.replace(tzinfo=timezone.utc)


class PortalRecovery:
    def __init__(self) -> None:
        self.failures = 0
        self.attempts = 0
        self.last_attempt: datetime = datetime.min.replace(tzinfo=timezone.utc)
        self.state: InternetStatus = InternetStatus.UNAVAILABLE

    @property
    def retry_delay(self) -> timedelta:
        exponent = max(0, self.attempts - 1)
        return timedelta(seconds=min(300, 60 * (2 ** exponent)))

    def observe(self, result: InternetStatus) -> None:
        if result == InternetStatus.ONLINE:
            self.reset()
        else:
            self.failures = min(2, self.failures + 1)
        self.state = result

    def should_authenticate(self, enabled: bool, portal_enabled: bool, now: datetime) -> bool:
        base = (enabled and portal_enabled and self.state != InternetStatus.ONLINE
                and ((self.attempts == 0 and self.failures == 0) or self.failures >= 1)
                and (now - self.last_attempt) >= self.retry_delay)
        return base

    def begin(self, now: datetime) -> None:
        self.last_attempt = now
        self.attempts = min(4, self.attempts + 1)

    def reset(self) -> None:
        self.failures = 0
        self.attempts = 0
        self.last_attempt = datetime.min.replace(tzinfo=timezone.utc)
        self.state = InternetStatus.UNAVAILABLE
