# Win11 风格（从 C:\CosyVoiceLocal\fluent_ui.py 复制，和打字代说保持一致）：Mica 磨砂背景、跟随系统深浅色、用系统主题色
import os, sys, winreg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QApplication, QVBoxLayout
from qfluentwidgets import FluentWidget, setTheme, setThemeColor, Theme, isDarkTheme

FONT = 'Microsoft YaHei UI'


def system_accent(dark):
    """读 Windows 的强调色调色板。浅色模式用基准色，深色模式用浅 2（和 Win11 自带应用的取法一致）。"""
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Explorer\Accent')
        p = winreg.QueryValueEx(k, 'AccentPalette')[0]
        i = 1 if dark else 3
        return QColor(p[i * 4], p[i * 4 + 1], p[i * 4 + 2])
    except Exception:
        return QColor('#0078d4')


def make_app():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setFont(QFont(FONT, 10))
    setTheme(Theme.AUTO)
    setThemeColor(system_accent(isDarkTheme()))
    return app


def show_window(w):
    """显示并调到最前。启动脚本用"隐藏"方式运行 python（免得弹黑框），Windows 会把这个隐藏套到进程第一次显示的窗口上，
    所以 Qt 的 show() 之后再用系统接口强制显示一次。"""
    import ctypes
    w.show()
    hwnd = int(w.winId())
    ctypes.windll.user32.ShowWindow(hwnd, 5)          # SW_SHOW
    ctypes.windll.user32.SetForegroundWindow(hwnd)
    w.raise_(); w.activateWindow()


def single_instance(key, get_window):
    """同一个程序只开一个：已经开着时，通知旧窗口跳到最前，返回 False（新进程应退出）。"""
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    s = QLocalSocket(); s.connectToServer(key)
    if s.waitForConnected(300):
        s.write(b'show'); s.flush(); s.waitForBytesWritten(300); s.disconnectFromServer()
        return False
    QLocalServer.removeServer(key)
    server = QLocalServer(QApplication.instance()); server.listen(key)
    def on_conn():
        c = server.nextPendingConnection()
        w = get_window()
        if w is not None:
            if w.isMinimized(): w.showNormal()
            show_window(w)
        c.disconnectFromServer()
    server.newConnection.connect(on_conn)
    QApplication.instance()._single_server = server
    return True


class Window(FluentWidget):
    """带 Mica 磨砂背景的无边框窗口；内容放在 self.body（一个竖向布局）里。"""
    def __init__(self, title, topmost=False):
        super().__init__()
        self.setWindowTitle(title)
        self.titleBar.raise_()
        if topmost: self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(16, self.titleBar.height() + 4, 16, 14)
        self.body.setSpacing(10)
