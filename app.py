# 年度作品：按年份记录每年喜欢的作品（音乐、小说、综艺……），可以从 MarginNote 导出的导图导入
import os, sys, threading, datetime, traceback
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QFontDatabase
from PySide6.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout, QWidget, QFileDialog, QListWidgetItem
if __name__ == '__main__' and QApplication.instance() is None:
    # 启动提速（同抽卡统计）：先建好 QApplication，让后台线程去扫系统字体，和下面导入界面库同时进行
    _app = QApplication(sys.argv)
    threading.Thread(target=QFontDatabase.families, daemon=True).start()
from qfluentwidgets import (CaptionLabel, StrongBodyLabel, TitleLabel, PushButton, PrimaryPushButton, SmoothScrollArea,
                            ListWidget, InfoBar, InfoBarPosition, MessageBoxBase, SubtitleLabel, SpinBox, MessageBox,
                            TransparentToolButton, RoundMenu, Action, FlowLayout, ToolTipFilter, ToolTipPosition,
                            FluentIcon as FIF, qconfig)
import store, marginnote
from widgets import WorkCard, EditDialog
from fluent_ui import make_app, Window, show_window, single_instance

VERSION = '2026.10.24'                    # 日历版本号：发布当天的日期，同一天再发就加 .1、.2


def caption(text=''):
    lb = CaptionLabel(text)
    lb.setTextColor(QColor(0, 0, 0, 150), QColor(255, 255, 255, 160))
    return lb


def scroll_of(widget):
    s = SmoothScrollArea(); s.setWidgetResizable(True); s.setWidget(widget)
    s.setStyleSheet('QScrollArea{background:transparent;border:none}')
    # 只透明这一层：不带选择器的 background:transparent 会传给里面的提示框，提示框就变成一个黑框
    widget.setObjectName('scrollBody')
    widget.setStyleSheet('#scrollBody{background:transparent}')
    return s


class YearPage(QWidget):
    """右边：一年的作品，按分类分组。每个分类一行标题（名字 · 个数 · ＋），下面是作品卡片。"""

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(4, 0, 12, 16); self.v.setSpacing(6)

    def clear(self):
        while self.v.count():
            it = self.v.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
            elif it.layout():
                self._drop_layout(it.layout())

    def _drop_layout(self, lay):
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
            elif it.layout():
                self._drop_layout(it.layout())
        lay.deleteLater()

    def show_year(self, doc, year):
        self.clear()
        works = [w for w in doc['works'] if w['year'] == year]
        head = QHBoxLayout(); head.setSpacing(12)
        head.addWidget(TitleLabel(f'{year} 年度作品'))
        head.addWidget(caption(f'{len(works)} 个' if works else '还没有作品'), 0, Qt.AlignBottom)
        head.addStretch(1)
        self.v.addLayout(head)
        self.v.addSpacing(6)
        for cat in doc['categories']:
            items = [w for w in works if w['category'] == cat]
            row = QHBoxLayout(); row.setSpacing(8)
            row.addWidget(StrongBodyLabel(cat))
            row.addWidget(caption(str(len(items)) if items else ''))
            add = TransparentToolButton(FIF.ADD); add.setFixedSize(28, 28)
            add.setToolTip(f'添加{cat}'); add.installEventFilter(ToolTipFilter(add, 300, ToolTipPosition.TOP))
            add.clicked.connect(lambda *_, c=cat: self.app.add_work(year, c))
            row.addWidget(add); row.addStretch(1)
            self.v.addLayout(row)
            if items:
                box = QWidget()
                flow = FlowLayout(box, needAni=False)
                flow.setContentsMargins(0, 0, 0, 0); flow.setHorizontalSpacing(14); flow.setVerticalSpacing(14)
                for w in items:
                    card = WorkCard(w)
                    card.clicked.connect(self.app.edit_work)
                    card.menuRequested.connect(self.app.work_menu)
                    flow.addWidget(card)
                self.v.addWidget(box)
                self.v.addSpacing(10)
        self.v.addStretch(1)


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
        self.resize(*self.settings.get('size', (1180, 800)))
        self.setMinimumSize(860, 600)
        self.doc = store.load()
        if not self.doc['years']:
            self.doc['years'] = [datetime.date.today().year]

        top = QHBoxLayout(); top.setSpacing(8)
        self.status = caption()
        btn_import = PushButton(FIF.DOWNLOAD, '从 MarginNote 导入')
        btn_import.setToolTip('在 MarginNote 里用「导出到 OmniOutliner」导出，选那个 xml 文件')
        btn_import.installEventFilter(ToolTipFilter(btn_import, 300, ToolTipPosition.BOTTOM))
        btn_import.clicked.connect(self.import_marginnote)
        btn_year = PrimaryPushButton(FIF.ADD, '添加年份')
        btn_year.clicked.connect(self.add_year)
        top.addWidget(self.status, 1); top.addWidget(btn_import); top.addWidget(btn_year)
        self.body.addLayout(top)

        main = QHBoxLayout(); main.setSpacing(12)
        self.years = ListWidget()
        self.years.setFixedWidth(150)
        self.years.currentItemChanged.connect(lambda *_: self.show_current())
        self.years.setContextMenuPolicy(Qt.CustomContextMenu)
        self.years.customContextMenuRequested.connect(self.year_menu)
        main.addWidget(self.years)
        self.page = YearPage(self)
        main.addWidget(scroll_of(self.page), 1)
        self.body.addLayout(main, 1)

        qconfig.themeChanged.connect(lambda *_: self.page.update())
        self.fill_years(self.settings.get('year'))

    # ---------- 显示 ----------
    def fill_years(self, select=None):
        cur = select if select is not None else self.current_year()
        self.years.blockSignals(True)
        self.years.clear()
        counts = {}
        for w in self.doc['works']:
            counts[w['year']] = counts.get(w['year'], 0) + 1
        row = 0
        for i, y in enumerate(self.doc['years']):
            it = QListWidgetItem(f'{y}' + (f'　·　{counts[y]}' if y in counts else ''))
            it.setData(Qt.UserRole, y)
            self.years.addItem(it)
            if y == cur:
                row = i
        self.years.blockSignals(False)
        if self.years.count():
            self.years.setCurrentRow(row)
        self.show_current()
        self.status.setText(f'共 {len(self.doc["works"])} 个作品，{len(self.doc["years"])} 年')

    def current_year(self):
        it = self.years.currentItem()
        return it.data(Qt.UserRole) if it else None

    def show_current(self):
        y = self.current_year()
        if y is not None:
            self.page.show_year(self.doc, y)

    def save(self, select=None):
        store.save(self.doc)
        self.fill_years(select)

    # ---------- 作品 ----------
    def find(self, wid):
        return next((w for w in self.doc['works'] if w['id'] == wid), None)

    def add_work(self, year, category):
        w = store.new_work(year, category)
        d = EditDialog(self, w, self.doc, True)
        if d.exec():
            self.doc['works'].append(w)
            self.save(w['year'])

    def edit_work(self, wid):
        w = self.find(wid)
        if w is None:
            return
        backup = dict(w)
        d = EditDialog(self, w, self.doc, False)
        if d.exec():
            self.save(w['year'] if w['year'] != backup['year'] else None)
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

    def move_work(self, wid, step):
        """在同一年同一分类里往前 / 往后挪一格。"""
        w = self.find(wid)
        works = self.doc['works']
        same = [i for i, x in enumerate(works) if x['year'] == w['year'] and x['category'] == w['category']]
        k = same.index(works.index(w)) + step
        if 0 <= k < len(same):
            i, j = works.index(w), same[k]
            works[i], works[j] = works[j], works[i]
            self.save()

    def work_menu(self, wid, pos):
        menu = RoundMenu(parent=self)
        for icon, text, fn in ((FIF.EDIT, '编辑', lambda: self.edit_work(wid)),
                               (FIF.LEFT_ARROW, '往前挪', lambda: self.move_work(wid, -1)),
                               (FIF.RIGHT_ARROW, '往后挪', lambda: self.move_work(wid, 1)),
                               (FIF.DELETE, '删除', lambda: self.delete_work(wid))):
            a = Action(icon, text, self)
            a.triggered.connect(fn)
            menu.addAction(a)
        menu.exec(pos)

    # ---------- 年份 ----------
    def add_year(self):
        d = YearDialog(self, max(self.doc['years'], default=datetime.date.today().year - 1) + 1)
        if d.exec():
            y = d.spin.value()
            if y not in self.doc['years']:
                self.doc['years'].append(y)
            self.save(y)

    def year_menu(self, pos):
        it = self.years.itemAt(pos)
        if it is None:
            return
        y = it.data(Qt.UserRole)
        menu = RoundMenu(parent=self)
        a = Action(FIF.DELETE, f'删除 {y} 年', self)
        a.triggered.connect(lambda: self.delete_year(y))
        menu.addAction(a)
        menu.exec(self.years.viewport().mapToGlobal(pos))

    def delete_year(self, y):
        if any(w['year'] == y for w in self.doc['works']):
            InfoBar.warning('删不了', f'{y} 年里还有作品，先把作品删掉或改到别的年份',
                            duration=4000, position=InfoBarPosition.TOP, parent=self)
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
        self.settings.update(year=self.current_year(), size=[self.width(), self.height()])
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
    win = None
    if not single_instance('yearly-works', lambda: win):
        return
    win = App()
    show_window(win)
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
