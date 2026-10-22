"""小飞网络助手 · 江西科技学院版 —— PySide6 原生界面 + 状态机（移植 MainForm.cs）。"""
from __future__ import annotations

import json
import os
import sys
import threading
from dataclasses import replace
from datetime import datetime, timezone

from PySide6.QtCore import Qt, QObject, QTimer, Signal, Slot, QUrl
from PySide6.QtGui import QIcon, QPainter, QColor
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QLineEdit,
    QComboBox, QStackedWidget, QScrollArea, QFrame, QSystemTrayIcon, QMenu, QCheckBox,
    QFileDialog, QSizePolicy)

from . import wifi, wired, connectivity, theme
from .model import CampusProfile, AutoPolicy, PortalRecovery, InternetStatus
from .portal import PortalController
from .startup import StartupRegistration
from .store import LocalStore, app_dir
from . import __version__, APP_NAME, EDITION, AUTHOR, DEFAULT_SSID


def _now():
    return datetime.now(timezone.utc)


class Switch(QCheckBox):
    """自绘开关（复用 QCheckBox 语义）。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setMinimumSize(40, 22)
        self.toggled.connect(lambda *_: self.update())

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height(); r = h / 2
        track = QColor(theme.ACCENT_2) if self.isChecked() else QColor("#cbd6e1")
        if not self.isEnabled():
            track.setAlpha(120)
        p.setPen(Qt.NoPen); p.setBrush(track); p.drawRoundedRect(0, 0, w, h, r, r)
        d = h - 6; x = w - d - 3 if self.isChecked() else 3
        p.setBrush(QColor("#ffffff")); p.drawEllipse(x, 3, d, d)


class Worker(QObject):
    """后台线程执行阻塞调用（netsh / 子进程），结果回调到 GUI 线程。"""
    finished = Signal(int, str, object)

    def __init__(self):
        super().__init__()
        self._cbs: dict[int, object] = {}
        self._n = 0
        self.finished.connect(self._dispatch)

    def submit(self, fn, cb, *a):
        self._n += 1; tok = self._n; self._cbs[tok] = cb

        def run():
            try:
                self.finished.emit(tok, "ok", fn(*a))
            except Exception as e:  # noqa: BLE001
                self.finished.emit(tok, "err", e)
        threading.Thread(target=run, daemon=True).start()

    @Slot(int, str, object)
    def _dispatch(self, tok, kind, value):
        cb = self._cbs.pop(tok, None)
        if cb:
            cb(kind, value)


class MainWindow(QMainWindow):
    def __init__(self, start_in_tray: bool = False, verify_path: str | None = None):
        super().__init__()
        self.verify_path = verify_path
        self.setWindowTitle(APP_NAME)
        self.resize(1200, 800); self.setMinimumSize(996, 720)
        try:
            self.setWindowIcon(QIcon(theme.resource_path("app.ico")))
        except Exception:
            pass

        self.store = LocalStore()
        self.saved = CampusProfile()
        self.saved_password = ""
        self.policy = AutoPolicy()
        self.recovery = PortalRecovery()
        self.startup = StartupRegistration(app_exe())
        self.current_ssid: str | None = None
        self.networks: list = []
        self.online: bool | None = None
        self.busy = self.joining = self.checking = self.permission_needed = False
        self.status = "准备就绪"
        self.last_scan = ""
        self.generation = 0
        self._wifi_mode = "open"
        self._wired_auth = "web"
        self._last_wifi_ssid = DEFAULT_SSID

        self.worker = Worker()
        self.portal = PortalController()
        self.portal.status.connect(self._set_status)
        self.portal.submitted.connect(lambda: QTimer.singleShot(1000, lambda: self._check_internet_async(False)))
        self.portal.address_changed.connect(self._push_state)

        self._build_ui()
        try:
            self.saved, self.saved_password = self.store.load()
            self.load_profile_to_ui()
        except Exception as e:  # noqa: BLE001
            self._set_status("无法读取配置，请重新填写并保存：" + str(e))

        self.timer = QTimer(self); self.timer.setInterval(20000)
        self.timer.timeout.connect(lambda: self.refresh(scan=(self.current_ssid != self.saved.ssid)))
        self.timer.start()
        self._build_tray()

        if start_in_tray:
            self.hide()
        if verify_path:
            QTimer.singleShot(3500, self._run_verify)
        else:
            QTimer.singleShot(300, lambda: self.refresh(scan=True))

    # ---------------- UI ----------------
    def _build_ui(self):
        root = QWidget(); self.setCentralWidget(root)
        outer = QVBoxLayout(root); outer.setContentsMargins(0, 0, 0, 0)
        self.backdrop = QFrame(); self.backdrop.setObjectName("backdrop")
        outer.addWidget(self.backdrop)
        body = QHBoxLayout(self.backdrop); body.setContentsMargins(0, 0, 0, 0); body.setSpacing(0)

        side = QFrame(); side.setObjectName("sidebar"); side.setFixedWidth(236)
        sl = QVBoxLayout(side); sl.setContentsMargins(20, 22, 18, 18); sl.setSpacing(10)
        brand = QHBoxLayout(); brand.setSpacing(10)
        av = QLabel(); av.setObjectName("brandAvatar"); av.setFixedSize(44, 44)
        bt = QVBoxLayout(); bt.setSpacing(2)
        nm = QLabel(APP_NAME); nm.setObjectName("brandName")
        cap = QLabel("XIAO FEI · JXIT"); cap.setObjectName("brandCaption")
        bt.addWidget(nm); bt.addWidget(cap)
        brand.addWidget(av); brand.addLayout(bt); brand.addStretch(1)
        sl.addLayout(brand)
        ed = QLabel(EDITION); ed.setObjectName("edition")
        sl.addWidget(ed, alignment=Qt.AlignLeft)
        sl.addSpacing(10)

        self.nav_buttons: dict[str, QPushButton] = {}
        for key, text in [("dashboard", "连接状态"), ("settings", "校园网设置"), ("portal", "上网认证")]:
            b = QPushButton("  " + text); b.setProperty("class", "nav")
            b.clicked.connect(lambda _=0, k=key: self.navigate(k))
            sl.addWidget(b); self.nav_buttons[key] = b
        sl.addStretch(1)
        author = QLabel(AUTHOR); author.setObjectName("author")
        lic = QLabel(f"© 2026 {AUTHOR}"); lic.setObjectName("author")
        sl.addWidget(author); sl.addWidget(lic)
        body.addWidget(side)

        main = QVBoxLayout(); main.setContentsMargins(0, 0, 0, 0); main.setSpacing(0)
        head = QHBoxLayout(); head.setContentsMargins(30, 22, 28, 8)
        col = QVBoxLayout(); col.setSpacing(4)
        self.title = QLabel("网络概览"); self.title.setObjectName("pageTitle")
        self.subtitle = QLabel(f"{DEFAULT_SSID} 校园网，到校自动连。"); self.subtitle.setObjectName("pageSub")
        col.addWidget(self.title); col.addWidget(self.subtitle)
        head.addLayout(col); head.addStretch(1)
        tag = QLabel("🐻 自嘲熊陪你连网"); tag.setObjectName("headTag")
        head.addWidget(tag, alignment=Qt.AlignBottom)
        main.addLayout(head)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._page_dashboard())
        self.stack.addWidget(self._page_settings())
        self.stack.addWidget(self._page_portal())
        main.addWidget(self.stack, 1)

        footer = QFrame(); footer.setObjectName("footer"); footer.setFixedHeight(40)
        fl = QHBoxLayout(footer); fl.setContentsMargins(28, 0, 28, 0)
        self.dot = QLabel(); self.dot.setFixedSize(8, 8)
        self.status_label = QLabel(self.status); self.status_label.setObjectName("statusText")
        ver = QLabel(f"v{__version__} · {EDITION}"); ver.setObjectName("version")
        fl.addWidget(self.dot); fl.addWidget(self.status_label, 1); fl.addWidget(ver)
        main.addWidget(footer)

        holder = QWidget(); holder.setLayout(main); body.addWidget(holder, 1)
        self._apply_wallpaper()
        self.navigate("dashboard")

    def _apply_wallpaper(self):
        url = theme.resource_path("wallpaper.jpg").replace("\\", "/")
        self.backdrop.setStyleSheet(
            "#backdrop{border-image: url(\"%s\") 0 0 0 0 stretch stretch;}" % url)

    def _card(self):
        c = QFrame(); c.setProperty("class", "card")
        lay = QVBoxLayout(c); lay.setContentsMargins(16, 15, 16, 15); lay.setSpacing(6)
        return c, lay

    def _page_dashboard(self):
        page = QWidget(); v = QVBoxLayout(page); v.setContentsMargins(30, 4, 30, 16)
        wrap = QVBoxLayout(); wrap.setSpacing(12)

        hero, hl = self._card(); row = QHBoxLayout()
        icon = QLabel("📶"); icon.setStyleSheet("font-size:26px;")
        info = QVBoxLayout()
        self.hero_title = QLabel("正在读取 Wi-Fi 状态"); self.hero_title.setObjectName("heroTitle")
        self.hero_target = QLabel(f"目标校园网  {DEFAULT_SSID}"); self.hero_target.setObjectName("heroTarget")
        info.addWidget(self.hero_title); info.addWidget(self.hero_target)
        b_connect = QPushButton("立即连接"); b_connect.setProperty("class", "primary"); b_connect.clicked.connect(self.manual_connect)
        b_edit = QPushButton("修改配置"); b_edit.clicked.connect(lambda: self.navigate("settings"))
        acts = QVBoxLayout(); acts.addWidget(b_connect); acts.addWidget(b_edit)
        row.addWidget(icon); row.addLayout(info); row.addStretch(1); row.addLayout(acts)
        hl.addLayout(row); wrap.addWidget(hero)

        bear = QLabel("🐻 连不上先怪熊，再怪自己。"); bear.setObjectName("bearLine"); wrap.addWidget(bear)

        auto, al = self._card(); ar = QHBoxLayout()
        at = QVBoxLayout(); at.addWidget(QLabel("自动连接与认证"))
        self.auto_desc = QLabel(f"发现 {DEFAULT_SSID} 后连接，并使用已保存账号登录。"); self.auto_desc.setObjectName("desc")
        at.addWidget(self.auto_desc)
        self.sw_auto = Switch(); self.sw_auto.toggled.connect(self.set_automatic)
        ar.addLayout(at); ar.addStretch(1); ar.addWidget(self.sw_auto); al.addLayout(ar); wrap.addWidget(auto)

        self.perm_card, _ = self._card(); pr = QHBoxLayout()
        pr.addWidget(QLabel("🛰  允许读取附近 Wi-Fi")); pr.addStretch(1)
        b_loc = QPushButton("授权定位"); b_loc.setProperty("class", "primary"); b_loc.clicked.connect(lambda: self._open("ms-settings:privacy-location"))
        pr.addWidget(b_loc); self.perm_card.layout().addLayout(pr); self.perm_card.setVisible(False); wrap.addWidget(self.perm_card)

        grid = QHBoxLayout(); grid.setSpacing(12)
        for text, slot in [("校园网设置\n账号、认证方式", lambda: self.navigate("settings")),
                           ("上网认证\n打开学校登录页", lambda: self.open_portal()),
                           ("检查上网状态\n探测是否在线", lambda: self.check_internet(False))]:
            b = QPushButton(text); b.setProperty("class", "quick"); b.clicked.connect(slot); b.setMinimumHeight(74)
            grid.addWidget(b)
        wrap.addLayout(grid)

        tip, tl = self._card(); tl.addWidget(QLabel("使用提示"))
        d = QLabel(f"点「校园网设置」填写学号密码并保存；连接 {DEFAULT_SSID} 后到「上网认证」点「探测认证地址」自动获取学校页面。账号密码只保存在本机。")
        d.setObjectName("desc"); d.setWordWrap(True); tl.addWidget(d); wrap.addWidget(tip)
        wrap.addStretch(1)

        container = QWidget(); container.setLayout(wrap)
        sa = QScrollArea(); sa.setWidgetResizable(True); sa.setWidget(container)
        v.addWidget(sa); return page

    def _page_settings(self):
        page = QWidget(); v = QVBoxLayout(page); v.setContentsMargins(30, 4, 30, 16)
        wrap = QVBoxLayout(); wrap.setSpacing(12)

        c1, l1 = self._card(); r1 = QHBoxLayout()
        t1 = QVBoxLayout(); t1.addWidget(QLabel("开机自启"))
        self.startup_desc = QLabel("登录 Windows 后在托盘运行，自动连接按已保存设置执行。"); self.startup_desc.setObjectName("desc"); t1.addWidget(self.startup_desc)
        self.sw_startup = Switch(); self.sw_startup.setEnabled(False); self.sw_startup.toggled.connect(self.set_startup)
        r1.addLayout(t1); r1.addStretch(1); r1.addWidget(self.sw_startup); l1.addLayout(r1); wrap.addWidget(c1)

        c2, l2 = self._card(); l2.addWidget(QLabel("连接方式"))
        seg = QHBoxLayout()
        self.b_wifi = QPushButton("Wi-Fi 无线网络"); self.b_wired = QPushButton("有线网络（以太网）")
        for b, m in [(self.b_wifi, "wifi"), (self.b_wired, "wired")]:
            b.setCheckable(True); b.clicked.connect(lambda _=0, mm=m: self.select_connection(mm)); seg.addWidget(b)
        self.b_wifi.setChecked(True); l2.addLayout(seg)
        self.conn_note = QLabel("修改连接方式后请点击保存。"); self.conn_note.setObjectName("note"); l2.addWidget(self.conn_note); wrap.addWidget(c2)

        self.ssid_card, l3 = self._card()
        l3.addWidget(QLabel("校园 Wi-Fi 名称（有线模式留空）"))
        self.e_ssid = QLineEdit(DEFAULT_SSID); self.e_ssid.setMaxLength(32); self.e_ssid.textChanged.connect(self._mode_from_ssid); l3.addWidget(self.e_ssid)
        self.join_help = QLabel(f"{DEFAULT_SSID} 默认按开放网络处理；学号和密码在下方网页认证中填写。"); self.join_help.setObjectName("note"); self.join_help.setWordWrap(True); l3.addWidget(self.join_help)
        wrap.addWidget(self.ssid_card)

        self.wifi_mode_card, l4 = self._card(); l4.addWidget(QLabel("认证方式"))
        seg2 = QHBoxLayout()
        self.b_open = QPushButton("开放网络"); self.b_saved = QPushButton("使用 Windows 已保存的配置")
        for b, m in [(self.b_open, "open"), (self.b_saved, "saved")]:
            b.setCheckable(True); b.clicked.connect(lambda _=0, mm=m: self.set_wifi_mode(mm)); seg2.addWidget(b)
        self.b_open.setChecked(True); l4.addLayout(seg2); wrap.addWidget(self.wifi_mode_card)

        self.wired_card, wl = self._card(); wl.addWidget(QLabel("有线认证方式"))
        self.cb_wired = QComboBox(); self.cb_wired.addItems(["网页认证", "PPPoE 宽带拨号", "802.1X 系统认证", "学校专用客户端"])
        self.cb_wired.currentIndexChanged.connect(self._wired_auth_changed); wl.addWidget(self.cb_wired)
        self.e_eth = QLineEdit(); self.e_eth.setPlaceholderText("以太网接口（留空自动）"); wl.addWidget(self.e_eth)
        self.e_broad = QLineEdit(); self.e_broad.setPlaceholderText("Windows 宽带连接名称"); wl.addWidget(self.e_broad)
        self.e_client = QLineEdit(); self.e_client.setPlaceholderText("学校认证客户端 EXE"); self.e_client.setReadOnly(True); wl.addWidget(self.e_client)
        b_pick = QPushButton("选择认证客户端"); b_pick.clicked.connect(self.pick_client); wl.addWidget(b_pick)
        self.wired_card.setVisible(False); wrap.addWidget(self.wired_card)

        self.portal_card, pc = self._card(); pr2 = QHBoxLayout()
        pv = QVBoxLayout(); pv.addWidget(QLabel("连接后进行网页认证"))
        pd = QLabel("连上校园网后自动打开学校认证页。"); pd.setObjectName("desc"); pv.addWidget(pd)
        self.sw_portal = Switch()
        pr2.addLayout(pv); pr2.addStretch(1); pr2.addWidget(self.sw_portal); pc.addLayout(pr2)

        self.portal_fields = QWidget(); pfl = QVBoxLayout(self.portal_fields); pfl.setContentsMargins(0, 6, 0, 0); pfl.setSpacing(8)
        pfl.addWidget(QLabel("认证页面地址"))
        self.e_url = QLineEdit(); self.e_url.setPlaceholderText(f"连接 {DEFAULT_SSID} 后点「探测认证地址」自动获取"); pfl.addWidget(self.e_url)
        fr = QHBoxLayout(); self.e_user = QLineEdit(); self.e_user.setPlaceholderText("输入账号")
        self.e_pass = QLineEdit(); self.e_pass.setPlaceholderText("输入上网密码"); self.e_pass.setEchoMode(QLineEdit.Password)
        fu = QVBoxLayout(); fu.addWidget(QLabel("学号 / 上网账号")); fu.addWidget(self.e_user)
        fp = QVBoxLayout(); fp.addWidget(QLabel("上网密码")); fp.addWidget(self.e_pass)
        fr.addLayout(fu); fr.addLayout(fp); pfl.addLayout(fr)
        pfl.addWidget(QLabel("服务选项（可留空）"))
        self.e_service = QLineEdit(); self.e_service.setPlaceholderText("例如：联通接入服务"); pfl.addWidget(self.e_service)
        self.cb_autosubmit = QCheckBox("自动填写后点击登录"); self.cb_autosubmit.setChecked(True); pfl.addWidget(self.cb_autosubmit)
        self.adv = QWidget(); advl = QVBoxLayout(self.adv); advl.setContentsMargins(0, 4, 0, 0); advl.setSpacing(6)
        for label, attr in [("账号输入框 CSS 选择器", "e_usel"), ("密码输入框 CSS 选择器", "e_psel"), ("登录按钮 CSS 选择器", "e_ssl")]:
            advl.addWidget(QLabel(label)); e = QLineEdit(); e.setPlaceholderText("例如 #username"); setattr(self, attr, e); advl.addWidget(e)
        self.adv.setVisible(False)
        b_adv = QPushButton("高级设置 · 特殊认证页面"); b_adv.setCheckable(True); b_adv.toggled.connect(self.adv.setVisible)
        pfl.addWidget(b_adv); pfl.addWidget(self.adv)
        pc.addWidget(self.portal_fields); wrap.addWidget(self.portal_card)
        self.sw_portal.setChecked(True); self.sw_portal.toggled.connect(self.portal_fields.setVisible)

        save, slv = self._card(); sr = QHBoxLayout()
        b_se = QPushButton("保存并开启自动连接"); b_se.setProperty("class", "primary"); b_se.clicked.connect(lambda: self.save(automatic=True))
        b_s = QPushButton("保存设置"); b_s.clicked.connect(lambda: self.save(automatic=None))
        sr.addWidget(b_se); sr.addWidget(b_s); sr.addStretch(1); sr.addWidget(QLabel("密码加密保存在本机"))
        slv.addLayout(sr); wrap.addWidget(save); wrap.addStretch(1)

        container = QWidget(); container.setLayout(wrap)
        sa = QScrollArea(); sa.setWidgetResizable(True); sa.setWidget(container)
        v.addWidget(sa); return page

    def _page_portal(self):
        page = QWidget(); v = QVBoxLayout(page); v.setContentsMargins(30, 4, 30, 16); v.setSpacing(10)
        row = QHBoxLayout()
        b1 = QPushButton("立即认证"); b1.setProperty("class", "primary"); b1.clicked.connect(lambda: self.open_portal())
        b2 = QPushButton("探测认证地址"); b2.clicked.connect(lambda: self.open_portal(discover=True))
        b3 = QPushButton("检查上网状态"); b3.clicked.connect(lambda: self.check_internet(False))
        b4 = QPushButton("停止"); b4.clicked.connect(self.stop_portal)
        for b in (b1, b2, b3): row.addWidget(b)
        row.addStretch(1); row.addWidget(b4); v.addLayout(row)
        self.portal_status = QLabel(f"连接校园网后，在这里完成上网认证。"); self.portal_status.setObjectName("desc"); self.portal_status.setWordWrap(True)
        v.addWidget(self.portal_status)
        self.addr_row = QWidget(); ar = QHBoxLayout(self.addr_row); ar.setContentsMargins(0, 0, 0, 0)
        self.addr_label = QLabel(); self.addr_label.setObjectName("note")
        b_ad = QPushButton("使用当前页面地址"); b_ad.clicked.connect(self.adopt_address)
        ar.addWidget(self.addr_label, 1); ar.addWidget(b_ad); self.addr_row.setVisible(False); v.addWidget(self.addr_row)
        self.portal.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        v.addWidget(self.portal.view, 1)
        return page

    # ---------------- 导航 ----------------
    def _set_sw(self, switch, value):
        switch.blockSignals(True); switch.setChecked(value); switch.blockSignals(False)

    def navigate(self, key):
        self.stack.setCurrentIndex({"dashboard": 0, "settings": 1, "portal": 2}[key])
        for k, b in self.nav_buttons.items():
            b.setProperty("active", "true" if k == key else "false"); b.style().unpolish(b); b.style().polish(b)
        t = {"dashboard": ("网络概览", f"{DEFAULT_SSID} 校园网，到校自动连。"),
             "settings": ("校园网设置", f"设置 {DEFAULT_SSID} 网络、账号和上网认证方式。"),
             "portal": ("上网认证", "在校园网内打开登录页并填写已保存的凭据。")}[key]
        self.title.setText(t[0]); self.subtitle.setText(t[1])

    # ---------------- 设置交互 ----------------
    def select_connection(self, mode):
        if mode == "wired":
            if self.e_ssid.text().strip(): self._last_wifi_ssid = self.e_ssid.text()
            self.e_ssid.setText("")
        elif not self.e_ssid.text().strip():
            self.e_ssid.setText(self._last_wifi_ssid)
        self._mode_from_ssid()

    def _mode_from_ssid(self):
        w = not self.e_ssid.text().strip()
        self.b_wifi.setChecked(not w); self.b_wired.setChecked(w)
        self.ssid_card.setVisible(not w); self.wifi_mode_card.setVisible(not w); self.wired_card.setVisible(w)
        self._wired_auth_changed()

    def set_wifi_mode(self, mode):
        self.b_open.setChecked(mode == "open"); self.b_saved.setChecked(mode == "saved"); self._wifi_mode = mode

    def _wired_auth_changed(self):
        self._wired_auth = ["web", "pppoe", "dot1x", "client"][self.cb_wired.currentIndex()]
        self.e_eth.setVisible(self._wired_auth != "pppoe")
        self.e_broad.setVisible(self._wired_auth == "pppoe")
        self.e_client.setVisible(self._wired_auth == "client")

    def pick_client(self):
        f, _ = QFileDialog.getOpenFileName(self, "选择学校认证客户端", "", "应用程序 (*.exe)")
        if f: self.e_client.setText(f)

    def draft_profile(self):
        w = not self.e_ssid.text().strip()
        return CampusProfile(
            ssid=self.e_ssid.text().strip(), wired_auth="web" if not w else self._wired_auth,
            ethernet_name=self.e_eth.text().strip(), broadband_name=self.e_broad.text().strip(),
            authentication_client=self.e_client.text(), use_saved_wifi_profile=self._wifi_mode == "saved",
            portal_enabled=self.sw_portal.isChecked(), portal_url=self.e_url.text().strip(),
            username=self.e_user.text().strip(), service_option=self.e_service.text().strip(),
            user_selector=self.e_usel.text().strip(), password_selector=self.e_psel.text().strip(),
            submit_selector=self.e_ssl.text().strip(), auto_submit=self.cb_autosubmit.isChecked(),
            automatic=self.saved.automatic)

    def load_profile_to_ui(self):
        p = self.saved
        self.e_ssid.setText(p.ssid); self._wifi_mode = "saved" if p.use_saved_wifi_profile else "open"
        self.b_open.setChecked(not p.use_saved_wifi_profile); self.b_saved.setChecked(p.use_saved_wifi_profile)
        self.cb_wired.setCurrentIndex(["web", "pppoe", "dot1x", "client"].index(p.wired_auth) if p.wired_auth in ("web", "pppoe", "dot1x", "client") else 0)
        self.e_eth.setText(p.ethernet_name); self.e_broad.setText(p.broadband_name); self.e_client.setText(p.authentication_client)
        self.e_url.setText(p.portal_url); self.e_user.setText(p.username); self.e_service.setText(p.service_option)
        self.e_usel.setText(p.user_selector); self.e_psel.setText(p.password_selector); self.e_ssl.setText(p.submit_selector)
        self.cb_autosubmit.setChecked(p.auto_submit); self._set_sw(self.sw_portal, p.portal_enabled); self.portal_fields.setVisible(p.portal_enabled)
        self._set_sw(self.sw_auto, p.automatic)
        self._mode_from_ssid()

    def save(self, automatic):
        if self.busy:
            self._set_status("正在扫描或连接，请稍候再保存。"); return
        p = self.draft_profile()
        if automatic is not None:
            p = replace(p, automatic=automatic)
        try:
            p.validate()
            if p.automatic and p.uses_web_portal and (not p.username or not self.e_pass.text()):
                raise ValueError("请先填写上网账号和密码，再开启自动连接。")
            self.store.save(p, self.e_pass.text())
        except Exception as e:  # noqa: BLE001
            self._set_status(str(e)); return
        self.saved = p; self.saved_password = self.e_pass.text()
        self.policy.reset(); self.recovery.reset(); self.online = None; self.current_ssid = None
        self.generation += 1; self.portal.stop()
        self._set_status("设置已保存，自动连接已开启。" if p.automatic else "设置已保存。")
        self.refresh(scan=False)

    def set_automatic(self, enabled):
        if not enabled:
            self.pause()
        else:
            self.save(automatic=True)

    def pause(self):
        self.generation += 1; self.recovery.reset(); self.saved = replace(self.saved, automatic=False)
        self.portal.stop()
        try:
            self.store.save(self.saved, self.saved_password); self._set_status("自动连接已暂停。")
        except Exception as e:  # noqa: BLE001
            self._set_status("本次运行已暂停，但保存失败：" + str(e))
        self._set_sw(self.sw_auto, False)

    def set_startup(self, enabled):
        try:
            self.startup.set_enabled(enabled)
            self._set_status("开机自启已开启。" if enabled else "开机自启已关闭。")
        except Exception as e:  # noqa: BLE001
            self._set_status("设置开机自启失败：" + str(e))
        self._push_state()

    def adopt_address(self):
        url = self.portal.address
        if CampusProfile.origin(url) is None:
            self._set_status("当前没有可保存的认证网址。"); return
        self.e_url.setText(url); self.navigate("settings")
        self._set_status("请确认网址属于学校，点击保存后生效。")

    # ---------------- 状态机 ----------------
    def refresh(self, scan=True):
        if self.busy:
            return
        self.busy = True; self._push_state()

        def job():
            bb = [e.name for e in wired.read_broadband_entries()]
            if self.saved.is_wired:
                return ("wired", bb)
            return ("wifi", wifi.current_ssid(), wifi.scan(), bb)
        self.worker.submit(job, lambda k, v: self._after_refresh(k, v, scan))

    def _after_refresh(self, kind, value, scan):
        self.busy = False
        if kind == "err":
            self.permission_needed = ("定位" in str(value)) or ("拒绝" in str(value))
            self._set_status(str(value)); self._push_state(); return
        if value[0] == "wired":
            self.current_ssid = None; self.networks = []; self.last_scan = datetime.now().strftime("%H:%M"); self.permission_needed = False
            self._set_status("有线网络已连接。" if self.saved.is_wired else "")
        else:
            _, current, nets, _bb = value
            self.networks = nets; self.last_scan = datetime.now().strftime("%H:%M"); self.permission_needed = False
            if self.current_ssid != current:
                self.current_ssid = current; self.generation += 1; self.recovery.reset(); self.online = None; self.portal.stop()
                self._set_status("Wi-Fi 连接已断开。" if current is None else "当前连接：" + current)
            if current == self.saved.ssid:
                self._check_internet_async(self.saved.automatic)
            elif self.policy.should_join(self.saved.automatic, self.saved.ssid, current, [n.ssid for n in nets], False, _now()):
                self._connect_async(manual=False)
        self._push_state()

    def manual_connect(self):
        if self.busy:
            self._set_status("正在扫描或连接，请稍候。"); return
        self.busy = True; self._push_state(); self.policy.reset()
        if self.saved.is_wired:
            self._connect_wired_async(manual=True); return
        self.worker.submit(lambda: (wifi.current_ssid(), wifi.scan()), lambda k, v: self._after_manual(k, v))

    def _after_manual(self, kind, value):
        self.busy = False
        if kind == "err":
            self._set_status(str(value)); self._push_state(); return
        self._connect_async(manual=True)

    def _connect_async(self, manual):
        self.joining = True; self.policy.begin(_now()); self._push_state()
        self.worker.submit(lambda: (wifi.connect(self.saved.ssid, self.saved.use_saved_wifi_profile), wifi.wait_connected(self.saved.ssid)),
                           lambda k, v: self._after_connect(k, v, manual))

    def _after_connect(self, kind, value, manual):
        self.joining = False; self.busy = False
        if kind == "err" or not (value and value[1]):
            self._set_status("连接失败，请检查 Wi-Fi 信号和系统中保存的网络配置。"); self._push_state(); return
        self.current_ssid = self.saved.ssid; self.recovery.reset(); self.online = None; self.permission_needed = False
        self._set_status("已连接校园 Wi-Fi，正在检查上网状态…")
        if manual and self.saved.uses_web_portal:
            self.open_portal()
        self._check_internet_async(not manual and self.saved.automatic); self._push_state()

    def _connect_wired_async(self, manual):
        self.worker.submit(lambda: wired.connect(self.saved, self.e_eth.text().strip() or ""),
                           lambda k, v: self._after_wired(k, v, manual))

    def _after_wired(self, kind, value, manual):
        self._set_status(str(value) if kind == "err" else value)
        if manual and self.saved.uses_web_portal:
            self.open_portal()
        self._check_internet_async(not manual and self.saved.automatic)

    def _check_internet_async(self, open_if_offline):
        if self.checking:
            return
        self.checking = True
        def job():
            connected = self.saved.is_wired or (wifi.current_ssid() == self.saved.ssid)
            online = (connectivity.check() == InternetStatus.ONLINE) if connected else False
            return (connected, online)
        self.worker.submit(job, lambda k, v: self._after_check(k, v, open_if_offline))

    def _after_check(self, kind, value, open_if_offline):
        self.checking = False
        if kind == "err":
            self._push_state(); return
        connected, online = value
        if not connected:
            self.online = False; self.recovery.observe(InternetStatus.UNAVAILABLE)
            self._set_status("请先插好网线并启用有线网络。" if self.saved.is_wired else "请先连接校园 Wi-Fi。"); self._push_state(); return
        if open_if_offline and self.online is None and not self.portal.requires_interaction and \
           self.recovery.should_authenticate(self.saved.automatic, self.saved.uses_web_portal, _now()):
            self._set_status("正在立即发起校园网认证…"); self.open_portal(show_page=False)
        self.online = online
        self.recovery.observe(InternetStatus.ONLINE if online else InternetStatus.UNAVAILABLE)
        if online:
            self.portal.confirm_internet(); self.status = ""
        else:
            self.portal.report_unavailable(); self._set_status("探测不通，判定未联网。")
        if self.saved.automatic and self.saved.auto_submit and not self.portal.is_authenticating and \
           self.recovery.should_authenticate(self.saved.automatic, self.saved.uses_web_portal, _now()):
            self._set_status("探测不通，正在重新发起校园网认证…"); self.open_portal(show_page=False)
        self._push_state()

    def open_portal(self, discover=False, show_page=True):
        if self.saved.uses_system_authentication:
            self._set_status("当前使用系统认证，请在连接状态点击立即连接。"); return
        if not self.saved.uses_web_portal and not discover:
            self._set_status("网页认证已关闭，请在设置中开启并保存。"); return
        discover = discover or (not self.saved.portal_url.strip())
        self.recovery.begin(_now())
        if show_page:
            self.navigate("portal")
        self.portal.open(self.saved, self.saved_password, discover); self._push_state()

    def check_internet(self, open_if_offline):
        self._check_internet_async(open_if_offline)

    def stop_portal(self):
        self.portal.stop(); self._set_status("认证已暂停。"); self._push_state()

    # ---------------- 推送 ----------------
    def _set_status(self, message):
        self.status = message; self._push_state()

    def _push_state(self):
        connected = (self.current_ssid == self.saved.ssid) if not self.saved.is_wired else False
        if self.saved.is_wired:
            self.hero_title.setText("有线网络" + ("已连接" if connected else "未连接"))
        elif connected and self.online:
            self.hero_title.setText("校园网已连接 · 可上网")
        elif connected and self.online is False:
            self.hero_title.setText("已连接 · 未联网")
        elif connected:
            self.hero_title.setText("已连接 · 正在确认上网状态")
        else:
            self.hero_title.setText("等待连接校园网")
        self.hero_target.setText(f"目标校园网  {self.saved.ssid if not self.saved.is_wired else '有线网络'}")
        self.auto_desc.setText(f"发现 {self.saved.ssid} 后连接，并使用已保存账号登录。")
        self._set_sw(self.sw_auto, self.saved.automatic)
        self.perm_card.setVisible(self.permission_needed and not self.saved.is_wired)
        online = bool(connected and self.online)
        self.dot.setStyleSheet(f"background:{'#3ba776' if online else '#9aa8b5'}; border-radius:4px;")
        self.status_label.setText(self.status); self.status_label.setVisible(bool(self.status))
        addr = self.portal.address
        self.addr_row.setVisible(bool(addr))
        if addr:
            self.addr_label.setText(addr)
        try:
            self.sw_startup.setEnabled(True); self._set_sw(self.sw_startup, self.startup.is_enabled())
        except Exception:
            self.sw_startup.setEnabled(False)

    # ---------------- 托盘 ----------------
    def _build_tray(self):
        self.tray = QSystemTrayIcon(self)
        try:
            self.tray.setIcon(self.windowIcon())
        except Exception:
            pass
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        menu.addAction("打开主窗口", self._restore)
        menu.addAction("暂停自动连接", self.pause)
        menu.addSeparator(); menu.addAction("退出", self._quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self._restore() if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()

    def _restore(self):
        self.showNormal(); self.show(); self.activateWindow(); self.raise_()

    def _quit(self):
        self._real_quit = True; self.close()

    def closeEvent(self, event):
        if getattr(self, "_real_quit", False) or self.verify_path:
            self.portal.stop(); self.timer.stop(); self.tray.hide(); event.accept()
        else:
            event.ignore(); self.hide()
            self.tray.showMessage(APP_NAME, "程序保留在系统托盘，右键图标可暂停或退出。", QSystemTrayIcon.Information, 2500)

    def _open(self, uri):
        os.startfile(uri)

    def _run_verify(self):
        try:
            snapshot = {
                "pageCount": len(self.nav_buttons),
                "title": self.title.text(),
                "author": AUTHOR,
                "ssid": self.e_ssid.text(),
                "passwordMasked": self.e_pass.echoMode() == QLineEdit.Password,
                "startupToggle": self.sw_startup.isEnabled(),
            }
            with open(self.verify_path, "w", encoding="utf-8") as fh:
                json.dump(snapshot, fh, ensure_ascii=False)
        finally:
            self._quit()


def app_exe() -> str:
    return sys.executable if getattr(sys, "frozen", False) else os.path.abspath(sys.argv[0])
