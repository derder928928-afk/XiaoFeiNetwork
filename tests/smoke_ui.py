"""离屏渲染冒烟测试：构建主窗口、切换三页、截图。"""
import os, sys, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\Users\der\Desktop\自嘲熊\XiaoFeiNetwork-py")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from xiaofei import theme
from xiaofei.ui import MainWindow

QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
app = QApplication(sys.argv[:1])
app.setStyleSheet(theme.qss())
w = MainWindow()
w.resize(1200, 800)
w.show()

def pump(ms):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents(); time.sleep(0.01)

pump(1200)
out = r"C:\Users\der\Desktop\自嘲熊\work\shots"
os.makedirs(out, exist_ok=True)
for key in ["dashboard", "settings", "portal"]:
    w.navigate(key); pump(500)
    pix = w.grab(); pix.save(os.path.join(out, f"{key}.png"))
    print("saved", key, pix.width(), "x", pix.height())
print("OK")
