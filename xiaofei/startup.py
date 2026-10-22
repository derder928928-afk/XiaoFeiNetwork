"""开机自启：HKCU\\...\\Run 值 XiaoFeiNetwork.Windows，与 C# StartupRegistration 一致。"""
from __future__ import annotations

import winreg

VALUE_NAME = "XiaoFeiNetwork.Windows"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


class StartupRegistration:
    def __init__(self, executable_path: str, key_path: str = RUN_KEY) -> None:
        self.executable_path = executable_path
        self.key_path = key_path

    @property
    def command(self) -> str:
        return f'"{self.executable_path}" --startup'

    def is_enabled(self) -> bool:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.key_path) as key:
                value, _ = winreg.QueryValueEx(key, VALUE_NAME)
        except OSError:
            return False
        return isinstance(value, str) and value.lower() == self.command.lower()

    def set_enabled(self, enabled: bool) -> None:
        if enabled:
            if len(self.command) > 260 or '"' in self.executable_path:
                raise RuntimeError("安装路径太长或包含无效字符，无法设置开机自启。请安装到较短的路径。")
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.key_path, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, self.command)
        else:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.key_path, 0, winreg.KEY_SET_VALUE) as key:
                    winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
        if self.is_enabled() != enabled:
            raise OSError("启动项未能保存，请检查 Windows 权限。")
