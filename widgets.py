# 评分星星、封面框、编辑对话框（导图里点作品弹出来的）、鼠标停在作品上时的悬停卡片
import os, math
import numpy as np
from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import (QColor, QPainter, QPainterPath, QPixmap, QImage, QImageReader, QFont, QFontMetricsF, QPolygonF,
                           QPen, QKeySequence, QLinearGradient, QGuiApplication)
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QGridLayout, QApplication, QFileDialog
from qfluentwidgets import (MessageBoxBase, SubtitleLabel, LineEdit, ComboBox, PlainTextEdit, BodyLabel, CaptionLabel,
                            PushButton, TransparentToolButton, ToolTipFilter, ToolTipPosition, MessageBox,
                            FluentIcon as FIF, isDarkTheme, themeColor)
import store

STAR_GOLD = QColor('#e3a21a')
IMAGE_FILTER = '图片 (*.png *.jpg *.jpeg *.webp *.bmp *.gif)'
FONT, DIGITS = 'Microsoft YaHei UI', 'Bahnschrift'      # 数字用 Bahnschrift（Windows 自带的窄体），更有科技感


def font(px, bold=False, family=FONT):
    f = QFont(family); f.setPixelSize(px); f.setBold(bold)
    return f


def text_color(alpha=255):
    return QColor(255, 255, 255, alpha) if isDarkTheme() else QColor(0, 0, 0, alpha)


_pix_cache = {}


def cover_pixmap(path, w, h, dpr):
    """按尺寸裁切缩放好的封面（铺满、居中裁），按文件修改时间缓存，换了图自动失效。"""
    try:
        key = (path, os.path.getmtime(path), w, h, dpr)
    except OSError:
        return None
    pm = _pix_cache.get(key)
    if pm is None:
        img = QImage(path)
        if img.isNull():
            return None
        tw, th = round(w * dpr), round(h * dpr)
        img = img.scaled(tw, th, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        img = img.copy((img.width() - tw) // 2, (img.height() - th) // 2, tw, th)
        pm = QPixmap.fromImage(img); pm.setDevicePixelRatio(dpr)
        _pix_cache[key] = pm
    return pm


def star_path(cx, cy, r):
    pts = []
    for i in range(10):
        a = math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.45
        pts.append(QPointF(cx + rr * math.cos(a), cy - rr * math.sin(a)))
    p = QPainterPath(); p.addPolygon(QPolygonF(pts)); p.closeSubpath()
    return p


def draw_stars(p, x, cy, size, gap, value, empty):
    p.setPen(Qt.NoPen)
    for i in range(store.MAX_RATING):
        p.setBrush(STAR_GOLD if i < value else empty)
        p.drawPath(star_path(x + i * (size + gap) + size / 2, cy, size / 2))


class StarRating(QWidget):
    """10 颗星打分，不要半星。点当前分数再点一次清零。"""
    changed = Signal(int)
    SIZE, GAP = 22, 4

    def __init__(self, value=0, parent=None):
        super().__init__(parent)
        self.value, self.hover = value, 0
        self.setFixedSize(store.MAX_RATING * (self.SIZE + self.GAP), self.SIZE + 4)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

    def _at(self, x):
        return max(0, min(store.MAX_RATING, int(x // (self.SIZE + self.GAP)) + 1))

    def mouseMoveEvent(self, e):
        self.hover = self._at(e.position().x()); self.update()

    def leaveEvent(self, e):
        self.hover = 0; self.update()

    def mouseReleaseEvent(self, e):
        v = self._at(e.position().x())
        self.value = 0 if v == self.value else v
        self.update(); self.changed.emit(self.value)

    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        draw_stars(p, 0, self.height() / 2, self.SIZE, self.GAP, self.hover or self.value, text_color(40))


class CoverBox(QWidget):
    """封面框：点一下选图片，也可以把图片拖进来，或者点一下框再 Ctrl+V 粘贴截图。"""
    W, H = 150, 200

    def __init__(self, work, parent=None):
        super().__init__(parent)
        self.work = work
        self.image = None             # 新选的图（QImage）
        self.removed = False
        self.setFixedSize(self.W, self.H)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip('点击选择图片；也可以把图片拖进来，或者点一下这里再按 Ctrl+V 粘贴截图')
        self.installEventFilter(ToolTipFilter(self, 400, ToolTipPosition.TOP))

    def has_cover(self):
        return self.image is not None or (not self.removed and store.cover_path(self.work) is not None)

    def set_image(self, img):
        if img is not None and not img.isNull():
            self.image, self.removed = img, False
            self.update()

    def remove(self):
        self.image, self.removed = None, True
        self.update()

    def choose(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择封面', '', IMAGE_FILTER)
        if path:
            self.set_image(QImage(path))

    def paste(self):
        self.set_image(image_from_mime(QApplication.clipboard().mimeData()))

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.choose()

    def keyPressEvent(self, e):
        if e.matches(QKeySequence.Paste):
            self.paste()
        else:
            super().keyPressEvent(e)

    def dragEnterEvent(self, e):
        if image_from_mime(e.mimeData()) is not None:
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.set_image(image_from_mime(e.mimeData()))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        rect = QRectF(1, 1, self.W - 2, self.H - 2)
        dpr = self.devicePixelRatioF()
        pm = None
        if self.image is not None:
            img = self.image.scaled(round(self.W * dpr), round(self.H * dpr), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            img = img.copy((img.width() - round(self.W * dpr)) // 2, (img.height() - round(self.H * dpr)) // 2,
                           round(self.W * dpr), round(self.H * dpr))
            pm = QPixmap.fromImage(img); pm.setDevicePixelRatio(dpr)
        elif not self.removed and store.cover_path(self.work):
            pm = cover_pixmap(store.cover_path(self.work), self.W, self.H, dpr)
        if pm:
            clip = QPainterPath(); clip.addRoundedRect(rect, 8, 8)
            p.save(); p.setClipPath(clip); p.drawPixmap(0, 0, pm); p.restore()
        else:
            pen = QPen(themeColor() if self.hasFocus() else text_color(70), 1.2, Qt.DashLine)
            p.setPen(pen); p.setBrush(text_color(8))
            p.drawRoundedRect(rect, 8, 8)
            p.setPen(text_color(130))
            f = QFont(self.font()); f.setPixelSize(12); p.setFont(f)
            p.drawText(rect.adjusted(10, 0, -10, 0), Qt.AlignCenter | Qt.TextWordWrap,
                       '点击选择封面\n\n或把图片拖进来\n或点这里后 Ctrl+V')
        if self.hasFocus() and pm:
            p.setPen(QPen(themeColor(), 2)); p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rect, 8, 8)

    def focusInEvent(self, e):
        self.update(); super().focusInEvent(e)

    def focusOutEvent(self, e):
        self.update(); super().focusOutEvent(e)

    def save(self):
        """确定时把新封面存成 data/封面/<id>.jpg（最长边缩到 800），或者删掉旧封面。"""
        w = self.work
        old = store.cover_path(w)
        if self.image is not None:
            img = self.image
            if max(img.width(), img.height()) > 800:
                img = img.scaled(800, 800, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            if img.hasAlphaChannel():           # jpg 没有透明，垫白底
                bg = QImage(img.size(), QImage.Format_RGB32); bg.fill(Qt.white)
                pt = QPainter(bg); pt.drawImage(0, 0, img); pt.end()
                img = bg
            os.makedirs(store.cover_dir(), exist_ok=True)
            name = f'{w["id"]}.jpg'
            img.save(os.path.join(store.cover_dir(), name), 'JPG', 90)
            w['cover'] = name
        elif self.removed:
            if old:
                try:
                    os.remove(old)
                except OSError:
                    pass
            w['cover'] = ''


def image_from_mime(md):
    if md is None:
        return None
    if md.hasImage():
        img = QImage(md.imageData())
        if not img.isNull():
            return img
    if md.hasUrls():
        for u in md.urls():
            if u.isLocalFile():
                img = QImage(u.toLocalFile())
                if not img.isNull():
                    return img
    return None


class EditDialog(MessageBoxBase):
    """编辑 / 新增作品。确定后 self.work 已改好（封面也已存盘）；点了删除时 self.deleted 为 True。"""

    def __init__(self, parent, work, doc, is_new):
        super().__init__(parent)
        self.work, self.deleted = work, False
        self.viewLayout.addWidget(SubtitleLabel('添加作品' if is_new else '编辑作品'))
        row = QHBoxLayout(); row.setSpacing(18)
        left = QVBoxLayout(); left.setSpacing(6)
        self.cover = CoverBox(work)
        left.addWidget(self.cover)
        btns = QHBoxLayout(); btns.setSpacing(4)
        b_paste = TransparentToolButton(FIF.PASTE); b_paste.setToolTip('粘贴剪贴板里的图片')
        b_paste.clicked.connect(self.cover.paste)
        b_del = TransparentToolButton(FIF.DELETE); b_del.setToolTip('去掉封面')
        b_del.clicked.connect(self.cover.remove)
        for b in (b_paste, b_del):
            b.installEventFilter(ToolTipFilter(b, 300, ToolTipPosition.BOTTOM))
        btns.addStretch(1); btns.addWidget(b_paste); btns.addWidget(b_del); btns.addStretch(1)
        left.addLayout(btns); left.addStretch(1)
        row.addLayout(left)

        form = QGridLayout(); form.setHorizontalSpacing(12); form.setVerticalSpacing(10)
        self.title = LineEdit(); self.title.setText(work['title']); self.title.setPlaceholderText('作品名')
        self.author = LineEdit(); self.author.setText(work['author']); self.author.setPlaceholderText('歌手 / 作者，可以不填')
        self.year = ComboBox()
        years = sorted(set(doc['years']) | {work['year']}, reverse=True)
        for y in years:
            self.year.addItem(str(y), userData=y)
        self.year.setCurrentIndex(years.index(work['year']))
        self.category = ComboBox()
        cats = doc['categories']
        for c in cats:
            self.category.addItem(c)
        self.category.setCurrentIndex(cats.index(work['category']) if work['category'] in cats else 0)
        rate_row = QHBoxLayout(); rate_row.setSpacing(10)
        self.rating = StarRating(work['rating'])
        self.rating_text = CaptionLabel()
        self.rating.changed.connect(self._rating_text)
        rate_row.addWidget(self.rating); rate_row.addWidget(self.rating_text); rate_row.addStretch(1)
        self._rating_text(work['rating'])
        self.comment = PlainTextEdit(); self.comment.setPlainText(work['comment'])
        self.comment.setPlaceholderText('短评 / 备注')
        self.comment.setFixedHeight(96)
        two = QHBoxLayout(); two.setSpacing(10)
        two.addWidget(self.year, 1); two.addWidget(self.category, 1)
        rows = [('名字', self.title), ('作者', self.author), ('年份', two), ('评分', rate_row), ('短评', self.comment)]
        for i, (label, w) in enumerate(rows):
            lb = BodyLabel(label)
            form.addWidget(lb, i, 0, Qt.AlignRight | (Qt.AlignTop if w is self.comment else Qt.AlignVCenter))
            if isinstance(w, QWidget):
                form.addWidget(w, i, 1)
            else:
                form.addLayout(w, i, 1)
        form.setColumnMinimumWidth(1, 300)
        row.addLayout(form, 1)
        self.viewLayout.addLayout(row)

        self.yesButton.setText('保存'); self.cancelButton.setText('取消')
        if not is_new:
            self.delButton = PushButton(FIF.DELETE, '删除')
            self.delButton.clicked.connect(self._delete)
            self.buttonLayout.insertWidget(0, self.delButton, 1)
        self.widget.setMinimumWidth(620)
        self.title.setFocus()

    def _rating_text(self, v):
        self.rating_text.setText(f'{v} / {store.MAX_RATING}' if v else '未评分')

    def validate(self):
        if not self.title.text().strip():
            self.title.setError(True); self.title.setFocus()
            return False
        w = self.work
        w['title'] = self.title.text().strip()
        w['author'] = self.author.text().strip()
        w['year'] = self.year.currentData()
        w['category'] = self.category.currentText()
        w['rating'] = self.rating.value
        w['comment'] = self.comment.toPlainText().strip()
        self.cover.save()
        return True

    def _delete(self):
        box = MessageBox('删除作品', f'确定删除「{self.work["title"]}」吗？删除后不能恢复。', self.window())
        box.yesButton.setText('删除'); box.cancelButton.setText('取消')
        if box.exec():
            self.deleted = True
            self.reject()


# ---------- 悬停卡片（导图是显卡画的，卡片是普通窗口，辉光在 CPU 上算一次缓存） ----------
_glow = {}


def _blur(a, sigma):
    """可分离的高斯模糊（先横后竖）。"""
    r = max(1, int(sigma * 3))
    x = np.arange(-r, r + 1)
    k = np.exp(-x * x / (2 * sigma * sigma)); k /= k.sum()
    a = np.lib.stride_tricks.sliding_window_view(np.pad(a, ((0, 0), (r, r))), 2 * r + 1, axis=1) @ k
    return np.lib.stride_tricks.sliding_window_view(np.pad(a, ((r, r), (0, 0))), 2 * r + 1, axis=0) @ k


def glow_margin(sigma):
    return int(math.ceil(sigma * 3)) + 2


def glow_pixmap(w, h, radius, color, sigma):
    """圆角矩形外的柔光（高斯模糊）。返回 (图, 外边距)。"""
    key = (round(w), round(h), round(radius), color.rgb(), sigma)
    hit = _glow.get(key)
    if hit is None:
        m = glow_margin(sigma)
        W, H = int(w) + 2 * m, int(h) + 2 * m
        mask = QImage(W, H, QImage.Format_Grayscale8); mask.fill(0)
        p = QPainter(mask); p.setRenderHint(QPainter.Antialiasing); p.setPen(Qt.NoPen); p.setBrush(QColor(255, 255, 255))
        p.drawRoundedRect(QRectF(m, m, w, h), radius, radius); p.end()
        a = np.frombuffer(mask.constBits(), np.uint8).reshape(H, mask.bytesPerLine())[:, :W] / 255.0
        alpha = np.clip(_blur(a, sigma * 0.33) * 0.55 + _blur(a, sigma) * 0.62, 0, 1)
        rgb = np.array([color.blue(), color.green(), color.red()], float)
        out = np.empty((H, W, 4), np.uint8)
        out[..., :3] = (rgb * alpha[..., None]).astype(np.uint8)
        out[..., 3] = (alpha * 255).astype(np.uint8)
        hit = (QPixmap.fromImage(QImage(out.tobytes(), W, H, W * 4, QImage.Format_ARGB32_Premultiplied).copy()), m)
        _glow[key] = hit
    return hit


class CoverPopup(QWidget):
    """鼠标停在作品上时弹出的小卡片：封面（没有就画个占位）+ 名字、作者、评分、短评。"""
    W, PAD, SIGMA = 236, 12, 6
    M = glow_margin(SIGMA)

    def __init__(self):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.work, self.color = None, QColor('white')

    def show_for(self, work, color, gpos):
        self.work, self.color = work, QColor(color)
        iw = self.W - 2 * self.PAD
        path = store.cover_path(work)
        self.img_h = 0
        if path:
            sz = QImageReader(path).size()
            if sz.width() > 0:
                self.img_h = min(300, round(iw * sz.height() / sz.width()))
        self.ph = 0 if self.img_h else 96
        self.lines = []
        y = self.PAD + (self.img_h or self.ph) + 10
        for text, f, alpha in ((work['title'], font(14, True), 255), (work['author'], font(12), 170)):
            if text:
                h = QFontMetricsF(f).boundingRect(QRectF(0, 0, iw, 400), Qt.TextWordWrap, text).height()
                self.lines.append((QRectF(self.PAD, y, iw, h), text, f, alpha)); y += h + 2
        self.star_y = None
        if work['rating']:
            self.star_y = y + 9; y += 20
        if work['comment']:
            f = font(12)
            h = min(QFontMetricsF(f).boundingRect(QRectF(0, 0, iw, 400), Qt.TextWordWrap, work['comment']).height(), 72)
            self.lines.append((QRectF(self.PAD, y + 4, iw, h), work['comment'], f, 200)); y += h + 6
        self.ch = y + self.PAD
        self.resize(self.W + 2 * self.M, int(self.ch) + 2 * self.M)
        # 放在鼠标右边，放不下就放左边；上下不出屏幕
        scr = (QGuiApplication.screenAt(gpos) or QGuiApplication.primaryScreen()).availableGeometry()
        x = gpos.x() + 18
        if x + self.width() > scr.right():
            x = gpos.x() - 18 - self.width()
        y = max(scr.top(), min(gpos.y() - 40, scr.bottom() - self.height()))
        self.move(x, y)
        self.show(); self.update()

    def paintEvent(self, e):
        if not self.work:
            return
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        m = self.M
        card = QRectF(m, m, self.W, self.ch)
        p.drawPixmap(QPointF(0, 0), glow_pixmap(card.width(), card.height(), 14, self.color, self.SIGMA)[0])
        p.setPen(QPen(self.color, 1.2)); p.setBrush(QColor(9, 13, 30, 245))
        p.drawRoundedRect(card, 14, 14)
        p.translate(m, m)
        iw = self.W - 2 * self.PAD
        box = QRectF(self.PAD, self.PAD, iw, self.img_h or self.ph)
        clip = QPainterPath(); clip.addRoundedRect(box, 9, 9)
        if self.img_h:
            pm = cover_pixmap(store.cover_path(self.work), round(iw), self.img_h, self.devicePixelRatioF())
            if pm:
                p.save(); p.setClipPath(clip); p.drawPixmap(box.topLeft(), pm); p.restore()
        else:
            g = QLinearGradient(box.topLeft(), box.bottomRight())
            c1, c2 = QColor(self.color), QColor(self.color)
            c1.setAlpha(70); c2.setAlpha(18)
            g.setColorAt(0, c1); g.setColorAt(1, c2)
            p.setPen(Qt.NoPen); p.setBrush(g); p.drawPath(clip)
            p.setPen(QColor(255, 255, 255, 120)); p.setFont(font(12))
            p.drawText(box, Qt.AlignCenter, '还没有封面\n点一下作品可以添加')
        for rect, text, f, alpha in self.lines:
            p.setFont(f); p.setPen(QColor(255, 255, 255, alpha))
            p.drawText(rect, Qt.TextWordWrap, text)
        if self.star_y is not None:
            draw_stars(p, self.PAD, self.star_y, 13, 3.2, self.work['rating'], QColor(255, 255, 255, 40))
