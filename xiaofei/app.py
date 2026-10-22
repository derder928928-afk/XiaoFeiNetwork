"""程序入口：单实例互斥、参数解析、启动 Qt 应用。"""
from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import Qt, QCoreApplication
from PySide6.QtWidgets import QApplication, QMessageBox

from . import APP_NAME
from .ui import MainWindow


def _acquire_mutex():
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, "Local\\XiaoFeiNetwork.Windows")
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        return None
    return handle


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    start_tray = any(a.lower() == "--startup" for a in argv)
    verify_path = None
    if "--verify-ui" in argv:
        i = argv.index("--verify-ui")
        if i + 1 < len(argv):
            verify_path = argv[i + 1]

    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
    mutex = _acquire_mutex()
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    from . import theme
    app.setStyleSheet(theme.qss())
    if mutex is None:
        if not start_tray:
            QMessageBox.information(None, APP_NAME, "小飞网络助手已在运行，请从系统托盘打开。")
        return 0

    win = MainWindow(start_in_tray=start_tray, verify_path=verify_path)
    if not start_tray:
        win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
