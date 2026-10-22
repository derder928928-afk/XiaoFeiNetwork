"""上网认证控制器：QWebEngineView 承载学校认证页，注入脚本自动填写/提交并核验结果。
移植自 PortalController.cs 的状态机（generation 防串扰、FillAsync 重试、ObserveAuthentication）。"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import QObject, QTimer, Signal, Slot, QUrl

from .model import CampusProfile
from .portal_script import build_script, bootstrap_script

DISCOVER_URL = "http://www.msftconnecttest.com/redirect"


class PortalController(QObject):
    status = Signal(str)
    submitted = Signal()
    address_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # QtWebEngine 延迟导入：缺少 Addons 时降级为占位控件，不影响主窗口构建
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            self.view = QWebEngineView(parent)
            self._webengine = True
        except Exception:
            from PySide6.QtWidgets import QLabel
            self.view = QLabel("认证页需要 QtWebEngine（PySide6-Addons）", parent)
            self.view.setAlignment(Qt.AlignCenter)
            self._webengine = False
        self.view.urlChanged.connect(lambda *_: self.address_changed.emit())
        self.view.loadFinished.connect(self._on_load_finished)
        self.generation = 0
        self.profile: CampusProfile | None = None
        self.password = ""
        self.finished = False
        self.is_active = False
        self.requires_interaction = False
        self.internet_confirmed = False
        self.auth_confirmed = False
        self._deadline: datetime | None = None
        self._attempt = 0
        self._filling = False
        self._fill_timer = QTimer(self)
        self._fill_timer.setInterval(150)
        self._fill_timer.timeout.connect(self._fill_step)
        self._obs_timer = QTimer(self)
        self._obs_timer.setInterval(500)
        self._obs_timer.timeout.connect(self._observe_step)

    # ---- 生命周期 ----
    def open(self, profile: CampusProfile, password: str, discover: bool = False) -> None:
        if not self._webengine:
            self.status.emit("缺少 QtWebEngine 组件，无法打开认证页。请安装 PySide6-Addons。")
            return
        self.stop(clear=False)
        self.generation += 1
        if discover:
            self.profile = replace(profile, portal_url=DISCOVER_URL, username="", auto_submit=False)
            self.password = ""
        else:
            self.profile = profile
            self.password = password
        self.finished = False
        self.auth_confirmed = False
        self.internet_confirmed = False
        self.requires_interaction = not profile.auto_submit
        self.is_active = True
        self._attempt = 0
        self._filling = False
        self._install_bootstrap(CampusProfile.origin(self.profile.portal_url) or "")
        self.view.load(QUrl(self.profile.portal_url))
        self.status.emit("正在探测认证地址，请确认学校页面后使用当前地址。" if discover else "正在打开校园认证页…")

    def stop(self, clear: bool = True) -> None:
        self.generation += 1
        self.profile = None
        self.password = ""
        self.finished = False
        self.is_active = False
        self.requires_interaction = False
        self._deadline = None
        self._fill_timer.stop()
        self._obs_timer.stop()
        try:
            self.view.stop()
            if clear:
                self.view.load(QUrl("about:blank"))
        except Exception:
            pass

    def confirm_internet(self) -> None:
        self.internet_confirmed = True
        self.requires_interaction = False
        self.finished = True
        self._deadline = None
        self.password = ""
        self.status.emit("已经连接成功")

    def report_unavailable(self) -> None:
        self.internet_confirmed = False
        self.status.emit("未连接网络")

    @property
    def is_authenticating(self) -> bool:
        return self._deadline is not None or (not self.finished and not self.requires_interaction)

    @property
    def address(self) -> str:
        try:
            s = self.view.url().toString()
            return "" if s == "about:blank" else s
        except Exception:
            return ""

    def _install_bootstrap(self, origin: str) -> None:
        from PySide6.QtWebEngineCore import QWebEngineScript
        page = self.view.page()
        page.scripts().clear()
        script = QWebEngineScript()
        script.setName("campus-bootstrap")
        script.setSourceCode(bootstrap_script(origin))
        script.setInjectionPoint(QWebEngineScript.DocumentCreation)
        script.setWorldId(QWebEngineScript.MainWorld)
        script.setRunsOnSubFrames(False)
        page.scripts().insert(script)

    # ---- 自动填写状态机 ----
    @Slot(bool)
    def _on_load_finished(self, ok: bool) -> None:
        if not self.is_active or self.finished:
            return
        self._attempt = 0
        self._filling = True
        self._fill_step()

    def _run_script(self, code: str, callback) -> None:
        try:
            self.view.page().runJavaScript(code, callback)
        except Exception as exc:
            callback(f"error:{exc}")

    def _fill_step(self) -> None:
        if not self.is_active or self.finished or self.profile is None:
            self._fill_timer.stop()
            return
        if self._attempt > 80:
            self._fill_timer.stop()
            self.requires_interaction = True
            self.status.emit("未识别登录表单，请手动登录或设置 CSS 选择器。")
            return
        self._attempt += 1
        prof = self.profile
        if prof.username == "" or self.password == "":
            self._fill_timer.stop()
            self.requires_interaction = True
            self.status.emit("请在设置中填写上网账号密码，或直接在网页中手动登录。")
            return
        code = build_script(prof, self.password)
        self._run_script(code, self._on_fill_result)

    def _on_fill_result(self, result) -> None:
        if not self.is_active or self.finished or self.profile is None:
            return
        status = result if isinstance(result, str) else "unknown"
        if status == "authenticated":
            self._confirm_authentication(); return
        if status == "authentication-rejected":
            self._fill_timer.stop(); self.requires_interaction = True; self.finished = True; self.password = ""
            self.status.emit("学校返回登录失败，请查看网页提示并检查账号、密码和服务选项。"); return
        if status in ("submitted", "already-submitted"):
            self._fill_timer.stop(); self.finished = True; self.password = ""; self.requires_interaction = True
            self._deadline = datetime.now(timezone.utc) + timedelta(seconds=30)
            self.status.emit("已触发登录，正在核验学校返回结果和已登录页面…")
            self.submitted.emit(); self._start_observe(); return
        if status in ("waiting-submit", "waiting-ready", "missing-submit", "missing-service",
                      "missing-fields", "waiting-agreement"):
            return  # 继续下一次 _fill_step
        if status == "filled":
            self._fill_timer.stop(); self.requires_interaction = True; self.finished = True; self.password = ""
            self.status.emit("账号密码已填写，请在网页中手动点击登录。"); return
        if status == "submission-unconfirmed":
            self._fill_timer.stop(); self.requires_interaction = True; self.finished = True; self.password = ""
            self.status.emit("学校登录函数未完成提交，请查看网页提示，补充信息后重试。"); return
        if status == "agreement-required":
            self._fill_timer.stop(); self.requires_interaction = True; self.finished = True; self.password = ""
            self.status.emit("网页必选勾选项尚未确认，请在认证页完成协议阅读或手动勾选后重试。"); return
        if status == "manual-required":
            self._fill_timer.stop(); self.requires_interaction = True; self.finished = True; self.password = ""
            self.status.emit("学校要求验证码或运营商信息，请在认证页补充。"); return
        if status == "invalid-selector":
            self._fill_timer.stop(); self.requires_interaction = True
            self.status.emit("CSS 选择器无效，请修改高级设置。"); return
        if status == "wrong-origin":
            self._fill_timer.stop(); self.requires_interaction = True
            self.status.emit("认证地址不匹配，已阻止填写。"); return
        if status == "not-submitted" or status == "awaiting-authentication":
            return
        # unknown → 保持重试
        return

    def _confirm_authentication(self) -> None:
        if self.auth_confirmed:
            return
        self.auth_confirmed = True
        self._deadline = None
        self.finished = True
        self.password = ""
        self.requires_interaction = False
        self._obs_timer.stop()
        self._fill_timer.stop()
        if not self.internet_confirmed:
            self.status.emit("学校已确认登录成功，正在检查实际联网状态。")
        self.submitted.emit()

    # ---- 提交后核验 ----
    def _start_observe(self) -> None:
        self._obs_timer.start()

    def _observe_step(self) -> None:
        if not self.is_active or self.profile is None or self._deadline is None:
            self._obs_timer.stop()
            return
        prof = self.profile
        origin = CampusProfile.origin(prof.portal_url)
        if CampusProfile.origin(self.address) == origin:
            code = build_script(prof, "", status_only=True)
            self._run_script(code, self._on_observe_result)
        else:
            self._check_deadline()

    def _on_observe_result(self, result) -> None:
        if self._deadline is None:
            self._obs_timer.stop(); return
        status = result if isinstance(result, str) else ""
        if status == "authenticated":
            self._confirm_authentication(); return
        if status == "authentication-rejected":
            self._obs_timer.stop(); self._deadline = None; self.requires_interaction = True
            self.status.emit("学校返回登录失败，请查看网页提示并检查账号、密码和服务选项。"); return
        self._check_deadline()

    def _check_deadline(self) -> None:
        if self._deadline and datetime.now(timezone.utc) >= self._deadline:
            self._obs_timer.stop(); self._deadline = None; self.requires_interaction = True
            self.status.emit("30 秒内未确认已登录页面或学校成功结果，正在复查联网状态；仍未联网时请查看网页提示后重试。")
            self.submitted.emit()
