"""离线自检：复刻 C# Program.cs 的关键逻辑断言（不依赖 GUI / 网络）。"""
import json
import os
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xiaofei.model import CampusProfile, AutoPolicy, PortalRecovery, InternetStatus
from xiaofei import portal_script

checks = 0
def ok(cond, msg):
    global checks
    checks += 1
    assert cond, "FAIL: " + msg

p = CampusProfile()
p.validate()
ok(p.ssid == "JXIT-5G", "默认 SSID 为 JXIT-5G")
ok(p.portal_url == "", "认证地址默认为空")
ok(not p.automatic, "默认不自动连接")
ok(p.connection_label == "Wi-Fi", "无线连接标签")

ok(CampusProfile.origin("http://192.0.2.1/eportal/") == "http://192.0.2.1", "origin 去路径")
ok(CampusProfile.origin("https://Example.COM:8443/x") == "https://example.com:8443", "origin 小写+端口")
ok(CampusProfile.origin("http://a.com:80") == "http://a.com", "省略默认 http 端口")
ok(CampusProfile.origin("https://a.com:443") == "https://a.com", "省略默认 https 端口")
ok(CampusProfile.origin("https://user:secret@example.com") is None, "拒绝含账号密码")
ok(CampusProfile.origin("javascript:alert(1)") is None, "拒绝非 http")
ok(CampusProfile.origin("not a url") is None, "拒绝乱填")

def invalid(profile):
    try:
        profile.validate()
    except ValueError:
        return True
    return False
ok(invalid(replace(p, portal_url="javascript:alert(1)")), "非法认证地址被拒")
ok(invalid(replace(p, portal_url="https://user:pw@e.com")), "含凭据地址被拒")
ok(not invalid(replace(p, portal_url="")), "空地址合法（自动探测）")
ok(invalid(replace(p, ssid="x" * 40)), "SSID 超长被拒")
wired = replace(p, ssid="", wired_auth="pppoe")
ok(invalid(wired), "pppoe 缺宽带名被拒")

now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
pol = AutoPolicy()
ok(pol.should_join(True, "JXIT-5G", "Home", ["JXIT-5G"], False, now), "可见目标可连")
ok(not pol.should_join(True, "JXIT-5G", None, ["JXIT-5G-fake"], False, now), "精确匹配 SSID")
ok(not pol.should_join(False, "JXIT-5G", None, ["JXIT-5G"], False, now), "暂停不连")
ok(not pol.should_join(True, "JXIT-5G", "JXIT-5G", ["JXIT-5G"], False, now), "已连不重连")
ok(not pol.should_join(True, "JXIT-5G", None, ["JXIT-5G"], True, now), "忙时不连")
pol.begin(now)
ok(not pol.should_join(True, "JXIT-5G", None, ["JXIT-5G"], False, now + timedelta(seconds=59)), "60s 冷却")
ok(pol.should_join(True, "JXIT-5G", None, ["JXIT-5G"], False, now + timedelta(seconds=61)), "60s 后重试")
pol.reset()
ok(pol.should_join(True, "JXIT-5G", None, ["JXIT-5G"], False, now), "reset 立即允许")

rec = PortalRecovery()
ok(rec.should_authenticate(True, True, now), "首次可认证")
rec.begin(now); rec.observe(InternetStatus.UNAVAILABLE)
ok(rec.retry_delay == timedelta(seconds=60), "第1次退避 60s")
rec.begin(now); rec.observe(InternetStatus.UNAVAILABLE)
ok(rec.retry_delay == timedelta(seconds=120), "第2次退避 120s")
for _ in range(6):
    rec.begin(now); rec.observe(InternetStatus.UNAVAILABLE)
ok(rec.retry_delay == timedelta(seconds=300), "退避封顶 300s")
rec.observe(InternetStatus.ONLINE)
ok(rec.attempts == 0 and rec.failures == 0, "联网成功即复位")

prof = CampusProfile(username="acct", portal_url="http://192.0.2.1/eportal/")
secret = "test'\\\"\n</script>"
script = portal_script.build_script(replace(prof, service_option=secret), secret)
ok("/*CAMPUS_CONFIG*/" not in script, "配置占位符已替换")
ok("/*CAMPUS_AGREEMENTS*/" not in script, "协议占位符已替换")
ok("__campusAgreementAttempts" in script, "协议脚本已注入")
start = script.index("const cfg = ") + len("const cfg = ")
cfg = json.loads(script[start:script.index(";", start)])
ok(cfg["origin"] == "http://192.0.2.1", "config.origin")
ok(cfg["password"] == secret, "config.password 原样还原")
ok(cfg["serviceOption"] == secret, "config.serviceOption 原样还原")
ok(cfg["confirmSubmit"] is True and cfg["submit"] is True, "confirmSubmit/submit")
ok(cfg["statusOnly"] is False, "statusOnly 默认 False")

status = portal_script.build_script(prof, "", status_only=True)
s2 = status.index("const cfg = ") + len("const cfg = ")
cfg2 = json.loads(status[s2:status.index(";", s2)])
ok(cfg2["statusOnly"] is True, "statusOnly 模式")

boot = portal_script.bootstrap_script("http://192.0.2.1")
ok("/*CAMPUS_ORIGIN*/" not in boot, "bootstrap origin 已替换")
ok('"http://192.0.2.1"' in boot, "bootstrap 含 origin 字面量")

print(f"ALL CHECKS PASSED: {checks}")
