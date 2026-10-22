"""在真实桌面会话中渲染主窗口三页并截图到 doc/（不用 offscreen，保证中文字体正常）。"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("QT_QPA_PLATFORM", None)
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--no-sandbox --disable-gpu"
os.environ["XIAOFEI_DATA_DIR"] = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "work", "shot-data")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from xiaofei import theme
from xiaofei.ui import MainWindow

QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
app = QApplication(sys.argv[:1])
app.setStyleSheet(theme.qss())
w = MainWindow()
w.resize(1180, 780)
w.show()

def pump(ms):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents(); time.sleep(0.02)

out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "doc")
os.makedirs(out, exist_ok=True)
pump(1500)
for key in ["dashboard", "settings", "portal"]:
    w.navigate(key); pump(600)
    w.raise_(); app.processEvents()
    pix = w.grab()
    pix.save(os.path.join(out, f"{key}.png"))
    print("saved", key, pix.width(), pix.height())
print("DONE")
