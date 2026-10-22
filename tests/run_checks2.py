"""离线自检 2：wifi 解析 / wired phonebook / store(DPAPI) / startup 命令串。"""
import os
import sys
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xiaofei import wifi, wired, store, startup
from xiaofei.model import CampusProfile

checks = 0
def ok(c, m):
    global checks; checks += 1; assert c, "FAIL: " + m

en = """Name : Wi-Fi
State : connected
SSID : JXIT-5G
BSSID : aa:bb:cc:dd:ee:ff

    SSID 1 : JXIT-5G
    Network type      : Infrastructure
    Authentication    : open
    Encryption        : None
    BSSID 1 : aa:bb:cc:dd:ee:ff
        Signal        : 87%

    SSID 2 : ChinaNet-5G
    Network type      : Infrastructure
    Authentication    : WPA2-Personal
    Encryption        : CCMP
    BSSID 1 : 11:22:33:44:55:66
        Signal        : 55%
"""
ok(wifi.current_ssid(en) == "JXIT-5G", "英文 current_ssid")
nets = wifi.parse_networks(en)
ok([n.ssid for n in nets] == ["JXIT-5G", "ChinaNet-5G"], "英文网络名")
ok(nets[0].secure is False and nets[0].signal == 87, "英文 open/信号")
ok(nets[1].secure is True and nets[1].signal == 55, "英文 WPA2/信号")

zh = """名称 : WLAN
状态 : 已连接
SSID : JXIT-5G

    SSID 1 : JXIT-5G
    网络类型 : 基础结构
    身份验证 : 开放
    加密       : 无
        信号 : 90%

    SSID 2 : eduroam
    网络类型 : 基础结构
    身份验证 : WPA2-企业
    加密       : CCMP
        信号 : 40%
"""
ok(wifi.current_ssid(zh) == "JXIT-5G", "中文 current_ssid")
zn = wifi.parse_networks(zh)
ok([n.ssid for n in zn] == ["JXIT-5G", "eduroam"], "中文网络名")
ok(zn[0].secure is False and zn[0].signal == 90, "中文 开放/信号")
ok(zn[1].secure is True, "中文 企业=加密")

ok(wifi.current_ssid("State : disconnected\nSSID :") is None, "断开时无 current_ssid")

xml = wifi.open_profile_xml("JXIT-5G")
ok("<authentication>open</authentication>" in xml and "manual" in xml, "open profile xml")
ok("4A5849542D3547" in xml, "SSID hex 正确")

pbk = """[JXIT-PPPoE]
Type=5
ServerName=x

[SomeVPN]
Type=2
"""
entries = wired.parse_phonebook(pbk, "C:\\pbk\\rasphone.pbk")
ok([e.name for e in entries] == ["JXIT-PPPoE"], "只识别 Type=5 宽带")

prof = replace(CampusProfile(), ssid="", wired_auth="pppoe", broadband_name="JXIT-PPPoE")
cmd, args = wired.build_command(prof, "", entries, "C:\\Windows\\System32")
ok(cmd.endswith("rasdial.exe") and args[0] == "JXIT-PPPoE", "pppoe 命令")
d1 = replace(CampusProfile(), ssid="", wired_auth="dot1x")
cmd2, args2 = wired.build_command(d1, "以太网", entries, "C:\\Windows\\System32")
ok(cmd2.endswith("netsh.exe") and "interface=以太网" in args2, "dot1x 命令")

token = store.protect("我的密码123")
ok(store.unprotect(token) == "我的密码123", "DPAPI roundtrip")
ok(store.protect("") == "" and store.unprotect("") == "", "空密码")

s = startup.StartupRegistration(r"C:\Apps\小飞网络助手\小飞网络助手.exe")
ok(s.command == '"C:\\Apps\\小飞网络助手\\小飞网络助手.exe" --startup', "startup 命令串")
ok(startup.VALUE_NAME == "XiaoFeiNetwork.Windows", "startup 值名")

print(f"ALL CHECKS2 PASSED: {checks}")
