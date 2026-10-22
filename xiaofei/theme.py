"""主题与资源：颜色、QSS（Qt 样式表，写在 Python 里以保持仓库为纯 Python）、资源路径。"""
from __future__ import annotations

import os
import sys

ACCENT = "#2f6ea8"
ACCENT_2 = "#3f86c6"
TEXT = "#1f2d3a"
MUTED = "#7b8b99"
LINE = "rgba(31,61,90,.10)"
BG = "#f6f9fc"


def resource_path(name: str) -> str:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "xiaofei", "resources", name)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", name)


def qss() -> str:
    wall = resource_path("wallpaper.jpg").replace("\\", "/")
    avatar = resource_path("avatar.jpg").replace("\\", "/")
    return f"""
QWidget {{ font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif; color: {TEXT}; }}
#root {{ background: transparent; }}
#backdrop {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 rgba(246,249,252,.42), stop:1 rgba(246,249,252,.82)); }}
#sidebar {{ background: rgba(255,255,255,.80); border-right: 1px solid {LINE}; }}
#brandAvatar {{ border-radius: 22px; border: 3px solid #fff; image: url("{avatar}"); }}
#brandName {{ font-size: 15px; font-weight: 800; }}
#brandCaption {{ font-size: 8px; font-weight: 600; letter-spacing: 2px; color: {MUTED}; }}
#edition {{ font-size: 9px; color: {ACCENT}; background: rgba(47,110,168,.10); border: 1px solid rgba(47,110,168,.12); border-radius: 10px; padding: 2px 8px; }}
QPushButton.nav {{ background: transparent; border: none; border-radius: 9px; padding: 10px 14px; text-align: left; font-size: 13px; color: #5f7186; }}
QPushButton.nav:hover {{ background: rgba(31,61,90,.05); }}
QPushButton.nav[active="true"] {{ background: rgba(47,110,168,.10); color: {ACCENT}; font-weight: 700; }}
#pageTitle {{ font-size: 24px; font-weight: 800; }}
#pageSub {{ font-size: 12px; color: {MUTED}; }}
#headTag {{ font-size: 10.5px; color: {MUTED}; }}
.card {{ background: #fff; border: 1px solid rgba(31,61,90,.08); border-radius: 14px; }}
#heroTitle {{ font-size: 20px; font-weight: 700; }}
#heroTarget {{ font-size: 11.5px; color: {MUTED}; }}
#bearLine {{ font-size: 11px; color: {MUTED}; }}
#fieldLabel {{ font-size: 11.5px; font-weight: 500; color: #46596a; }}
#desc {{ font-size: 11px; color: {MUTED}; }}
#note {{ font-size: 10.5px; color: {MUTED}; }}
QLineEdit, QComboBox {{ background: #fff; border: 1px solid #dfe7ef; border-radius: 7px; padding: 7px 10px; font-size: 12.5px; }}
QLineEdit:focus, QComboBox:focus {{ border: 1px solid {ACCENT}; }}
QPushButton {{ background: #fff; border: 1px solid #dbe5ee; border-radius: 8px; padding: 6px 12px; font-size: 12.5px; color: {TEXT}; }}
QPushButton:hover {{ background: #fbfdff; border-color: #b9cfe3; }}
QPushButton:disabled {{ color: #b3bec8; background: #f2f5f8; }}
QPushButton.primary {{ background: {ACCENT}; border: 1px solid {ACCENT}; color: #fff; }}
QPushButton.primary:hover {{ background: #2a6397; }}
QPushButton.quick {{ background: rgba(255,255,255,.72); border: 1px solid rgba(31,61,90,.08); border-radius: 14px; text-align: left; padding: 14px 16px; }}
QPushButton.quick:hover {{ background: #fff; border-color: rgba(47,110,168,.3); }}
#footer {{ background: rgba(255,255,255,.76); border-top: 1px solid {LINE}; }}
#statusText {{ font-size: 11px; color: {MUTED}; }}
#version {{ font-size: 10px; color: #a2aeba; }}
#author {{ font-size: 11px; color: {MUTED}; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ width: 10px; background: transparent; }}
QScrollBar::handle:vertical {{ background: rgba(31,61,90,.18); border-radius: 5px; min-height: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""
