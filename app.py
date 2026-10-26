# 年度作品：按年份记录每年喜欢的作品（音乐、小说、综艺……），放射状思维导图显示；可以从 MarginNote 导出的导图导入
import os, sys, gc, threading, datetime, traceback
from PySide6.QtGui import QIcon, QFontDatabase, QGuiApplication, QCursor
from PySide6.QtWidgets import QApplication, QHBoxLayout, QWidget, QFileDialog
if __name__ == '__main__' and QApplication.instance() is None:
    # 启动提速（同抽卡统计）：先建好 QApplication，让后台线程去扫系统字体，和下面导入界面库同时进行
    _app = QApplication(sys.argv)
    threading.Thread(target=QFontDatabase.families, daemon=True).start()
from qfluentwidgets import (PushButton, InfoBar, InfoBarPosition, MessageBoxBase, SubtitleLabel, SpinBox,
                            MessageBox, ToolTipFilter, ToolTipPosition, FluentIcon as FIF, setTheme, setThemeColor, Theme)
import store, marginnote
from widgets import EditDialog
from mindmap import MindMap
from fluent_ui import make_app, Window, show_window, single_instance

VERSION = '2026.10.25'                    # 日历版本号：发布当天的日期，同一天再发就加 .1、.2
ACCENT = '#29c4f6'                        # 导图是深色霓虹风，界面固定用深色 + 青色主题色


class YearDialog(MessageBoxBase):
    def __init__(self, parent, year):
        super().__init__(parent)
        self.viewLayout.addWidget(SubtitleLabel('添加年份'))
        self.spin = SpinBox(); self.spin.setRange(1900, 2100); self.spin.setValue(year)
        self.viewLayout.addWidget(self.spin)
        self.yesButton.setText('添加'); self.cancelButton.setText('取消')
        self.widget.setMinimumWidth(320)


class App(Window):
    def __init__(self):
        super().__init__(f'年度作品  {VERSION}')
        self.setWindowIcon(QIcon(os.path.join(store.RES, 'icon.ico')))
        self.settings = store.load_settings()
        self.setMinimumSize(860, 600)
        # 打开时居中：放在鼠标所在的屏幕正中间；上次的尺寸比屏幕还大时（换了小屏幕）先缩到放得下
        scr = (QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()).availableGeometry()
        w, h = self.settings.get('size', (1180, 800))
        self.resize(min(w, scr.width()), min(h, scr.height()))
        self.move(scr.center() - self.rect().center())
        self.doc = store.load()
        if not self.doc['years']:
            self.doc['years'] = [datetime.date.today().year]

        self.body.setContentsMargins(0, 0, 0, 0)       # 导图铺满整个窗口（标题栏底下也是星空）
        self.map = MindMap(self)
        self.body.addWidget(self.map)
        self.map.editWork.connect(self.edit_work)
        self.map.deleteWork.connect(self.delete_work)
        self.map.addWork.connect(self.add_work)
        self.map.addYear.connect(self.add_year)
        self.map.deleteYear.connect(self.delete_year)
        self.map.layoutChanged.connect(lambda: store.save(self.doc))     # 拖过恒星：位置存进 data/作品.json

        # 浮在导图上的按钮
        self.tools = QWidget(self)
        h = QHBoxLayout(self.tools); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(8)
        btn_import = PushButton(FIF.DOWNLOAD, '从 MarginNote 导入')
        btn_import.setToolTip('在 MarginNote 里用「导出到 OmniOutliner」导出，选那个 xml 文件')
        btn_import.installEventFilter(ToolTipFilter(btn_import, 300, ToolTipPosition.BOTTOM))
        btn_import.clicked.connect(self.import_marginnote)
        btn_year = PushButton(FIF.ADD, '添加年份')
        btn_year.clicked.connect(self.add_year)
        h.addWidget(btn_import); h.addWidget(btn_year)
        self.tools.adjustSize()
        self.titleBar.raise_()

        self.map.set_doc(self.doc, expand=self.settings.get('year'), first=True)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not hasattr(self, 'tools'):       # 父类初始化时就会触发 resize，那时还没建好
            return
        self.tools.move(self.width() - self.tools.width() - 16, self.titleBar.height() + 8)

    def showEvent(self, e):
        super().showEvent(e)
        if not getattr(self, '_centered', False):   # 第一次显示：按窗口实际大小再对一次中（无边框窗口显示后尺寸会略变）
            self._centered = True
            scr = (self.screen() or QGuiApplication.primaryScreen()).availableGeometry()
            self.move(self.pos() + scr.center() - self.frameGeometry().center())
        self.map.fit(animate=False)          # 窗口真正显示出来、尺寸定了再对准一次

    def save(self, expand=None):
        store.save(self.doc)
        self.map.set_doc(self.doc)
        if expand is not None and expand != self.map.expanded:
            self.map.expand(expand)
        else:
            self.map.fit()

    # ---------- 作品 ----------
    def find(self, wid):
        return next((w for w in self.doc['works'] if w['id'] == wid), None)

    def add_work(self, year, category):
        w = store.new_work(year, category or self.doc['categories'][0])
        d = EditDialog(self, w, self.doc, True)
        if d.exec():
            self.doc['works'].append(w)
            self.map.collapsed.discard((w['year'], w['category']))
            self.save(w['year'])

    def edit_work(self, wid):
        w = self.find(wid)
        if w is None:
            return
        backup = dict(w)
        d = EditDialog(self, w, self.doc, False)
        if d.exec():
            self.save(w['year'])
        elif d.deleted:
            self.delete_work(wid, ask=False)
        else:
            w.clear(); w.update(backup)

    def delete_work(self, wid, ask=True):
        w = self.find(wid)
        if w is None:
            return
        if ask:
            box = MessageBox('删除作品', f'确定删除「{w["title"]}」吗？删除后不能恢复。', self)
            box.yesButton.setText('删除'); box.cancelButton.setText('取消')
            if not box.exec():
                return
        path = store.cover_path(w)
        if path:
            try:
                os.remove(path)
            except OSError:
                pass
        self.doc['works'].remove(w)
        self.save()

    # ---------- 年份 ----------
    def add_year(self):
        d = YearDialog(self, max(self.doc['years'], default=datetime.date.today().year - 1) + 1)
        if d.exec():
            y = d.spin.value()
            if y not in self.doc['years']:
                self.doc['years'].append(y)
            self.save(y)

    def delete_year(self, y):
        if any(w['year'] == y for w in self.doc['works']):
            InfoBar.warning('删不了', f'{y} 年里还有作品，先把作品删掉或改到别的年份',
                            duration=4000, position=InfoBarPosition.TOP, parent=self)
            return
        if len(self.doc['years']) == 1:
            InfoBar.warning('删不了', '至少要留一个年份', duration=3000, position=InfoBarPosition.TOP, parent=self)
            return
        self.doc['years'].remove(y)
        self.save()

    # ---------- 导入 ----------
    def import_marginnote(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择 MarginNote 导出的文件', '',
                                              'MarginNote 导出 (*.xml *.opml);;所有文件 (*)')
        if not path:
            return
        try:
            years, works = marginnote.parse(path)
        except marginnote.ImportError_ as e:
            InfoBar.error('导入失败', str(e), duration=-1, position=InfoBarPosition.TOP, parent=self)
            return
        except Exception as e:
            traceback.print_exc()
            InfoBar.error('导入失败', f'读文件时出错：{e}', duration=-1, position=InfoBarPosition.TOP, parent=self)
            return
        added, skipped = marginnote.merge(self.doc, years, works, store.new_work)
        self.save()
        InfoBar.success('导入完成', f'新增 {added} 个作品' + (f'，跳过 {skipped} 个已有的' if skipped else ''),
                        duration=5000, position=InfoBarPosition.TOP, parent=self)

    def closeEvent(self, e):
        self.map.popup.hide()
        self.settings.update(year=self.map.expanded, size=[self.width(), self.height()])
        store.save_settings(self.settings)
        super().closeEvent(e)


class ErrorLog:
    """exe 没有控制台：报错写到旁边的 log.txt。真有内容要写时才建文件，正常运行不留空的 log.txt"""
    file = None

    def write(self, s):
        if self.file is None:
            self.file = open(os.path.join(store.HERE, 'log.txt'), 'w', encoding='utf-8', buffering=1)
        return self.file.write(s)

    def flush(self):
        if self.file:
            self.file.flush()

    def isatty(self):
        return False


def main():
    if getattr(sys, 'frozen', False) and sys.stderr is None:
        sys.stdout = sys.stderr = ErrorLog()
    app = make_app()
    setTheme(Theme.DARK)
    setThemeColor(ACCENT)
    win = None
    if not single_instance('yearly-works', lambda: win):
        return
    win = App()
    show_window(win)
    # 启动时建的对象（界面库、字体、着色器……）不会变成垃圾：冻结起来，之后垃圾回收不再反复扫它们，动画中不会突然卡几毫秒
    gc.collect(); gc.freeze()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
