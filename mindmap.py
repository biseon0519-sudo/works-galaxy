# 放射状思维导图：中心「年度作品」→ 一圈年份 → 点开的那一年转到右边，伸出分类 → 作品。
# 深色星空背景 + 霓虹辉光。辉光按尺寸和颜色预先画好缓存，不用 QGraphicsDropShadowEffect（节点多了会卡）。
import math, random
from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QVariantAnimation, QEasingCurve, QTimer, QSize
from PySide6.QtGui import (QColor, QPainter, QPainterPath, QPixmap, QImage, QImageReader, QFont, QFontMetricsF, QPen,
                           QLinearGradient, QRadialGradient, QTransform, QCursor, QGuiApplication)
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsItem, QWidget
from qfluentwidgets import RoundMenu, Action, FluentIcon as FIF
import store
from widgets import cover_pixmap, draw_stars

FONT, DIGITS = 'Microsoft YaHei UI', 'Bahnschrift'      # 数字用 Bahnschrift（Windows 自带的窄体），更有科技感
NEON = {'文学作品': '#ffb86b', '音乐': '#ff5fa2', '小说': '#8c9bff', '电视剧': '#3ee6c4', '电影': '#ff7a59',
        '动漫': '#ffd84d', '综艺': '#b77bff', '鬼畜/梗': '#86ff6b', '游戏': '#4dc3ff'}
EXTRA = ['#ff8ad8', '#6bf0ff', '#ffe08a', '#9dff9d', '#c3a6ff']
CENTER_COLOR = QColor('#5ee7ff')

LEAF, GROUP_GAP = 34, 18          # 展开的分支里：每个作品占的高度、分类之间多空的距离
BEND = 0.00022                    # 分支的弧度：离中线越远越往回收一点，看起来是一段圆弧
ANIM_MS = 650


def neon(cat):
    if cat in NEON:
        return QColor(NEON[cat])
    return QColor(EXTRA[sum(map(ord, cat)) % len(EXTRA)])


def year_color(i, n):
    """年份一圈从青色渐变到紫、粉。"""
    h = 190 + 140 * (i / max(1, n - 1))
    return QColor.fromHsv(int(h) % 360, 165, 255)


def font(px, bold=False, family=FONT):
    f = QFont(family); f.setPixelSize(px); f.setBold(bold)
    return f


_glow = {}


def glow_pixmap(w, h, radius, color, spread):
    """节点外的一圈辉光：一层层放大的圆角矩形叠起来，越靠近节点越亮。"""
    key = (round(w), round(h), round(radius), color.rgb(), spread)
    pm = _glow.get(key)
    if pm is None:
        img = QImage(int(w + 2 * spread + 2), int(h + 2 * spread + 2), QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img); p.setRenderHint(QPainter.Antialiasing); p.setPen(Qt.NoPen)
        c = QColor(color)
        for i in range(spread, 0, -1):
            t = 1 - i / spread
            c.setAlphaF(0.012 + 0.085 * t * t)
            p.setBrush(c)
            p.drawRoundedRect(QRectF(spread - i + 1, spread - i + 1, w + 2 * i, h + 2 * i), radius + i, radius + i)
        p.end()
        pm = QPixmap.fromImage(img)
        _glow[key] = pm
    return pm


def lerp(a, b, t):
    return a + (b - a) * t


def wrap_angle(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


class Node(QGraphicsItem):
    """导图节点。kind：center 中心 / year 年份 / cat 分类 / work 作品 / add 添加按钮。
    圆形节点（center、year、add）的 pos 是圆心；胶囊节点（cat、work）的 pos 是左端中点，往右伸。"""
    SPREAD = {'center': 40, 'year': 24, 'cat': 18, 'work': 13, 'add': 12}

    def __init__(self, key, kind):
        super().__init__()
        self.key, self.kind = key, kind
        self.hover = self.active = self.removing = False
        self.parent_key = None
        self.text = self.sub = ''
        self.color = QColor('white')
        self.data = None
        self.w = self.h = 0
        self.setZValue(2)
        # 动画用：起点、终点；年份按角度转，其他按直线走
        self.p0 = self.p1 = QPointF()
        self.polar0 = self.polar1 = None
        self.o0 = self.o1 = 1.0

    def round(self):
        return self.kind in ('center', 'year', 'add')

    def set_content(self, text, sub, color, data):
        if (text, sub) != (self.text, self.sub) or not self.w:
            self.prepareGeometryChange()
            self.text, self.sub = text, sub
            self._measure()
        self.color, self.data = QColor(color), data
        self.update()

    def _measure(self):
        k = self.kind
        if k == 'center':
            self.w = self.h = 120
        elif k == 'year':
            self.w = self.h = 72
        elif k == 'add':
            self.w = self.h = 30
        elif k == 'cat':
            tw = QFontMetricsF(font(14, True)).horizontalAdvance(self.text)
            cw = QFontMetricsF(font(13, False, DIGITS)).horizontalAdvance(self.sub) if self.sub else 0
            self.w, self.h = tw + (cw + 8 if cw else 0) + 32, 32
        else:
            tw = QFontMetricsF(font(13)).horizontalAdvance(self.text)
            self.w, self.h = min(tw, 240) + 26, 28

    def body(self):
        if self.round():
            return QRectF(-self.w / 2, -self.h / 2, self.w, self.h)
        return QRectF(0, -self.h / 2, self.w, self.h)

    def boundingRect(self):
        s = self.SPREAD[self.kind] + 2
        return self.body().adjusted(-s, -s, s, s)

    def edge_point(self, toward, out):
        """连线接在哪：圆形节点接在朝向对方的圆周上；胶囊节点进线接左端、出线接右端。"""
        p = self.pos()
        if self.round():
            d = toward - p
            n = math.hypot(d.x(), d.y()) or 1
            return p + d * (self.w / 2 / n)
        return p + QPointF(self.w, 0) if out else p

    def paint(self, p, option, widget=None):
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        r = self.body()
        rad = r.height() / 2
        lit = self.hover or self.active
        s = self.SPREAD[self.kind]
        glow = glow_pixmap(r.width(), r.height(), rad, self.color, s)
        p.setOpacity(p.opacity() * (1.0 if lit else 0.62))
        p.drawPixmap(QPointF(r.x() - s - 1, r.y() - s - 1), glow)
        if self.hover:
            p.drawPixmap(QPointF(r.x() - s - 1, r.y() - s - 1), glow)
        p.setOpacity(self.effectiveOpacity())
        getattr(self, '_paint_' + self.kind)(p, r, rad, lit)

    def _paint_center(self, p, r, rad, lit):
        g = QRadialGradient(r.center(), rad)
        g.setColorAt(0, QColor(220, 250, 255)); g.setColorAt(0.35, QColor('#5ee7ff'))
        g.setColorAt(0.75, QColor('#5a4bff')); g.setColorAt(1, QColor(30, 20, 90))
        p.setPen(QPen(QColor(200, 245, 255, 200), 1.5)); p.setBrush(g)
        p.drawEllipse(r)
        p.setPen(QColor(10, 14, 40))
        p.setFont(font(18, True))
        p.drawText(r.adjusted(0, -14, 0, -14), Qt.AlignCenter, self.text)
        p.setFont(font(12))
        p.setPen(QColor(10, 14, 40, 200))
        p.drawText(r.adjusted(0, 22, 0, 22), Qt.AlignCenter, self.sub)

    def _paint_year(self, p, r, rad, lit):
        g = QRadialGradient(r.center(), rad)
        c = QColor(self.color)
        g.setColorAt(0, QColor(8, 12, 30, 235)); g.setColorAt(0.72, QColor(10, 14, 34, 235))
        c.setAlpha(120 if lit else 70); g.setColorAt(1, c)
        p.setPen(QPen(self.color, 2.2 if lit else 1.6)); p.setBrush(g)
        p.drawEllipse(r.adjusted(1, 1, -1, -1))
        p.setPen(QColor(255, 255, 255))
        p.setFont(font(19, True, DIGITS))
        dy = -7 if self.sub else 0
        p.drawText(r.adjusted(0, dy, 0, dy), Qt.AlignCenter, self.text)
        if self.sub:
            p.setFont(font(12, False, DIGITS))
            c = QColor(self.color); c.setAlpha(230)
            p.setPen(c)
            p.drawText(r.adjusted(0, 32, 0, 0), Qt.AlignCenter, self.sub)     # 数字下面一行：这一年几个作品

    def _paint_cat(self, p, r, rad, lit):
        c = QColor(self.color); c.setAlpha(60 if lit else 42)
        p.setPen(Qt.NoPen); p.setBrush(QColor(8, 12, 30, 230)); p.drawRoundedRect(r, rad, rad)
        p.setBrush(c); p.setPen(QPen(self.color, 1.6 if lit else 1.2))
        p.drawRoundedRect(r.adjusted(0.6, 0.6, -0.6, -0.6), rad, rad)
        p.setPen(QColor(255, 255, 255)); p.setFont(font(14, True))
        tr = r.adjusted(16, 0, -16, 0)
        p.drawText(tr, Qt.AlignLeft | Qt.AlignVCenter, self.text)
        if self.sub:
            p.setFont(font(13, False, DIGITS)); p.setPen(self.color.lighter(115))
            p.drawText(tr, Qt.AlignRight | Qt.AlignVCenter, self.sub)

    def _paint_work(self, p, r, rad, lit):
        p.setPen(Qt.NoPen); p.setBrush(QColor(8, 12, 30, 225)); p.drawRoundedRect(r, rad, rad)
        c = QColor(self.color); c.setAlpha(255 if lit else 170)
        fill = QColor(self.color); fill.setAlpha(40 if lit else 16)
        p.setBrush(fill); p.setPen(QPen(c, 1.5 if lit else 1.1))
        p.drawRoundedRect(r.adjusted(0.6, 0.6, -0.6, -0.6), rad, rad)
        p.setFont(font(13)); p.setPen(QColor(255, 255, 255, 255 if lit else 225))
        tr = r.adjusted(13, 0, -13, 0)
        p.drawText(tr, Qt.AlignLeft | Qt.AlignVCenter, p.fontMetrics().elidedText(self.text, Qt.ElideRight, int(tr.width()) + 1))

    def _paint_add(self, p, r, rad, lit):
        c = QColor(self.color); c.setAlpha(255 if lit else 150)
        p.setPen(QPen(c, 1.4, Qt.DashLine)); p.setBrush(QColor(8, 12, 30, 200))
        p.drawEllipse(r.adjusted(1, 1, -1, -1))
        p.setPen(QPen(c, 2)); m = 9
        p.drawLine(QPointF(r.center().x() - rad + m, r.center().y()), QPointF(r.center().x() + rad - m, r.center().y()))
        p.drawLine(QPointF(r.center().x(), r.center().y() - rad + m), QPointF(r.center().x(), r.center().y() + rad - m))


class Edges(QGraphicsItem):
    """所有连线画在一个图层里：中心到年份是直线光束，分支里是平滑曲线；颜色从父节点渐变到子节点。"""

    def __init__(self):
        super().__init__()
        self.links = []
        self.setZValue(1)

    def boundingRect(self):
        return QRectF(-8000, -8000, 16000, 16000)

    def paint(self, p, option, widget=None):
        p.setRenderHint(QPainter.Antialiasing)
        for a, b in self.links:
            op = min(a.opacity(), b.opacity())
            if op < 0.02:
                continue
            p1, p2 = a.edge_point(b.pos(), True), b.edge_point(a.pos(), False)
            path = QPainterPath(p1)
            if a.kind == 'center':
                path.lineTo(p2)
            else:
                dx = (p2.x() - p1.x()) * 0.55
                path.cubicTo(p1 + QPointF(dx, 0), p2 - QPointF(dx, 0), p2)
            lit = b.active or b.hover or (a.kind != 'center')
            g = QLinearGradient(p1, p2)
            for w, alpha in ((7, 0.10), (3, 0.22), (1.3, 0.9)):
                ca, cb = QColor(a.color), QColor(b.color)
                k = alpha * op * (1 if lit else 0.45)
                ca.setAlphaF(min(1, k)); cb.setAlphaF(min(1, k))
                g.setColorAt(0, ca); g.setColorAt(1, cb)
                p.setPen(QPen(g, w, Qt.SolidLine, Qt.RoundCap)); p.setBrush(Qt.NoBrush)
                p.drawPath(path)


class CoverPopup(QWidget):
    """鼠标停在作品上时弹出的小卡片：封面（没有就画个占位）+ 名字、作者、评分、短评。"""
    W, PAD, M = 236, 12, 14           # 卡片宽、内边距、外面留给辉光的边

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
        p.drawPixmap(QPointF(m - m - 1, m - m - 1), glow_pixmap(card.width(), card.height(), 14, self.color, m))
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


class MindMap(QGraphicsView):
    editWork = Signal(str)
    deleteWork = Signal(str)
    addWork = Signal(int, str)        # 年份, 分类（空字符串表示不指定）
    addYear = Signal()
    deleteYear = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(-8000, -8000, 16000, 16000, self))
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)    # 星空背景跟着视口画，不能只重画局部
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setMouseTracking(True)
        self.setStyleSheet('QGraphicsView{background:#050816;border:none}')

        self.edges = Edges()
        self.scene().addItem(self.edges)
        self.nodes = {}
        self.doc = None
        self.expanded = None            # 当前展开的年份（一次只展开一年）
        self.collapsed = set()          # 收起来的分类 (年, 分类)
        self.phi = -math.pi / 2         # 年份圈转到的角度：第一年的位置
        self.r1 = 250
        self.branch_rect = QRectF()
        self.hovered = None
        self._press = None
        self._dbl = False
        self._stars = None

        self.anim = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=ANIM_MS)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.valueChanged.connect(self._step)
        self.anim.finished.connect(self._finish)
        self.cam = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=ANIM_MS)
        self.cam.setEasingCurve(QEasingCurve.OutCubic)
        self.cam.valueChanged.connect(self._cam_step)
        self.popup = CoverPopup()
        self.pop_timer = QTimer(self, singleShot=True, interval=220)
        self.pop_timer.timeout.connect(self._show_popup)

    # ---------- 数据和布局 ----------
    def set_doc(self, doc, expand=None, first=False):
        self.doc = doc
        if expand is not None:
            self.expanded = expand if expand in doc['years'] else None
        elif self.expanded not in doc['years']:
            self.expanded = None
        self.relayout(animate=not first)
        if first:
            self.fit(animate=False)

    def expand(self, year):
        self.expanded = year
        self.relayout()
        self.fit()

    def collapse(self):
        self.expanded = None
        self.relayout()
        self.fit()

    def toggle_cat(self, year, cat):
        self.collapsed ^= {(year, cat)}
        self.relayout()
        self.fit()

    def _targets(self):
        """算出每个该显示的节点：key → (kind, 父 key, 文字, 副文字, 颜色, 数据, 位置, 年份的极坐标或 None)。"""
        doc = self.doc
        years = sorted(doc['years'])
        n = max(1, len(years))
        step = 2 * math.pi / n
        self.r1 = r1 = max(250, n * 92 / (2 * math.pi))
        if self.expanded in years:              # 展开的那一年转到正右边，转最短的方向
            want = -years.index(self.expanded) * step
            self.phi += wrap_angle(want - self.phi)
        counts = {}
        for w in doc['works']:
            counts[w['year']] = counts.get(w['year'], 0) + 1
        t = {'c': ('center', None, '年度作品', f'{len(doc["works"])} 个作品', CENTER_COLOR, None, QPointF(0, 0), None)}
        for i, y in enumerate(years):
            a = self.phi + i * step
            t[f'y{y}'] = ('year', 'c', str(y), str(counts.get(y, '')), year_color(i, n), y,
                          QPointF(r1 * math.cos(a), r1 * math.sin(a)), (a, r1))
        self.branch_rect = QRectF()
        y = self.expanded
        if y in years:
            ycolor = t[f'y{y}'][4]
            groups = []
            for cat in doc['categories']:
                ws = [w for w in doc['works'] if w['year'] == y and w['category'] == cat]
                if ws:
                    groups.append((cat, ws, (y, cat) in self.collapsed))
            # 竖着排：每个分类一块，块高 = 作品数（收起时算 1 个）
            blocks = [max(1, 1 if col else len(ws)) * LEAF for _, ws, col in groups]
            total = sum(blocks) + GROUP_GAP * len(groups) + LEAF
            cur = -total / 2
            x2 = r1 + 150
            cat_w = max([QFontMetricsF(font(14, True)).horizontalAdvance(c) for c, _, _ in groups] + [0]) + 70
            x3 = x2 + cat_w + 60
            right = x2 + 40
            for (cat, ws, col), h in zip(groups, blocks):
                yc = cur + h / 2
                ck = f'k{y}|{cat}'
                color = neon(cat)
                t[ck] = ('cat', f'y{y}', cat, str(len(ws)) + (' …' if col else ''), color, (y, cat),
                         QPointF(x2 - BEND * yc * yc, yc), None)
                if not col:
                    for j, w in enumerate(ws):
                        yy = cur + LEAF * (j + 0.5)
                        t['w' + w['id']] = ('work', ck, w['title'], '', color, w, QPointF(x3 - BEND * yy * yy, yy), None)
                        right = max(right, x3 + min(QFontMetricsF(font(13)).horizontalAdvance(w['title']), 240) + 26)
                cur += h + GROUP_GAP
            ya = cur + LEAF / 2
            t[f'a{y}'] = ('add', f'y{y}', '', '', ycolor, y, QPointF(x2 + 15 - BEND * ya * ya, ya), None)
            self.branch_rect = QRectF(QPointF(r1 - 60, -total / 2 - 20), QPointF(right + 30, total / 2 + 20))
        return t

    def relayout(self, animate=True):
        targets = self._targets()
        sc = self.scene()
        for key, (kind, parent, text, sub, color, data, pos, polar) in targets.items():
            node = self.nodes.get(key)
            if node is None or node.removing:
                if node is not None:
                    sc.removeItem(node)
                node = Node(key, kind)
                par = self.nodes.get(parent)
                start = par.pos() if par is not None and animate else pos
                node.setPos(start)
                node.setOpacity(0 if animate else 1)
                if polar is not None:
                    node.polar0 = (polar[0], polar[1]) if not animate else (polar[0], 0)
                sc.addItem(node)
                self.nodes[key] = node
            elif polar is not None:
                node.polar0 = (math.atan2(node.y(), node.x()), math.hypot(node.x(), node.y()))
            node.parent_key = parent
            node.set_content(text, sub, color, data)
            node.active = (kind == 'year' and data == self.expanded)
            node.p0, node.p1 = node.pos(), pos
            node.o0, node.o1 = node.opacity(), 1.0
            node.polar1 = polar
            if polar is not None and node.polar0 is not None:     # 转最短的方向
                node.polar0 = (polar[0] - wrap_angle(polar[0] - node.polar0[0]), node.polar0[1])
        for key, node in self.nodes.items():
            if key not in targets and not node.removing:
                node.removing = True
                par = targets.get(node.parent_key)
                node.p0, node.p1 = node.pos(), (par[6] if par else node.pos())
                node.o0, node.o1 = node.opacity(), 0.0
                node.polar1 = None
                node.hover = False
        self._links()
        if animate:
            self.anim.stop(); self.anim.start()
        else:
            self._step(1.0); self._finish()

    def _links(self):
        self.edges.links = [(self.nodes[n.parent_key], n) for n in self.nodes.values()
                            if n.parent_key in self.nodes]
        self.edges.update()

    def _step(self, t):
        t = float(t)
        for n in self.nodes.values():
            if n.polar1 is not None and n.polar0 is not None:
                a, r = lerp(n.polar0[0], n.polar1[0], t), lerp(n.polar0[1], n.polar1[1], t)
                n.setPos(r * math.cos(a), r * math.sin(a))
            else:
                n.setPos(lerp(n.p0.x(), n.p1.x(), t), lerp(n.p0.y(), n.p1.y(), t))
            n.setOpacity(lerp(n.o0, n.o1, t))
        self.edges.update()

    def _finish(self):
        for key in [k for k, n in self.nodes.items() if n.removing]:
            self.scene().removeItem(self.nodes.pop(key))
        for n in self.nodes.values():
            n.polar0 = n.polar1
        self._links()

    # ---------- 镜头 ----------
    def fit(self, animate=True):
        """展开时对准那一支，没展开时看整圈。"""
        vw, vh = self.viewport().width(), self.viewport().height()
        if self.branch_rect.isValid():
            rect = self.branch_rect
            s = max(0.7, min(1.15, (vw - 80) / rect.width(), (vh - 110) / rect.height()))
        else:
            R = self.r1 + 90
            rect = QRectF(-R, -R, 2 * R, 2 * R)
            s = max(0.4, min(1.25, (vw - 80) / rect.width(), (vh - 110) / rect.height()))
        self._cam0 = (self.transform().m11(), self.mapToScene(self.viewport().rect().center()))
        self._cam1 = (s, rect.center() + QPointF(0, -14 / s))    # 稍微往上一点，给底下的提示文字留位置
        self.cam.stop()
        if animate:
            self.cam.start()
        else:
            self._cam_step(1.0)

    def _cam_step(self, t):
        t = float(t)
        (s0, c0), (s1, c1) = self._cam0, self._cam1
        s = s0 * (s1 / s0) ** t
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setTransform(QTransform.fromScale(s, s))
        self.centerOn(QPointF(lerp(c0.x(), c1.x(), t), lerp(c0.y(), c1.y(), t)))
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)

    def wheelEvent(self, e):
        self.cam.stop()
        f = 1.0015 ** e.angleDelta().y()
        s = self.transform().m11()
        f = max(0.25 / s, min(3.0 / s, f))
        self.scale(f, f)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._stars = None

    # ---------- 背景 ----------
    def _star_pixmap(self):
        size = self.viewport().size()
        if self._stars is None or self._stars.size() != size:
            pm = QPixmap(size); pm.fill(Qt.transparent)
            p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing); p.setPen(Qt.NoPen)
            rnd = random.Random(7)
            for _ in range(size.width() * size.height() // 2600):
                x, y = rnd.uniform(0, size.width()), rnd.uniform(0, size.height())
                r = rnd.choice((0.5, 0.6, 0.7, 0.8, 1.0, 1.3))
                c = rnd.choice((QColor(255, 255, 255), QColor(170, 210, 255), QColor(210, 180, 255)))
                c.setAlpha(rnd.randint(40, 200 if r < 1 else 255))
                p.setBrush(c); p.drawEllipse(QPointF(x, y), r, r)
            p.end()
            self._stars = pm
        return self._stars

    def drawBackground(self, p, rect):
        vp = self.viewport().rect()
        p.save(); p.resetTransform()
        c = QPointF(vp.center())
        g = QRadialGradient(c, max(vp.width(), vp.height()) * 0.75)
        g.setColorAt(0, QColor('#0e1638')); g.setColorAt(0.55, QColor('#070b1f')); g.setColorAt(1, QColor('#020309'))
        p.fillRect(vp, g)
        for (fx, fy), col, rr in (((0.18, 0.2), QColor(120, 60, 255, 38), 0.45), ((0.85, 0.85), QColor(0, 200, 255, 30), 0.5)):
            ng = QRadialGradient(QPointF(vp.width() * fx, vp.height() * fy), max(vp.width(), vp.height()) * rr)
            ng.setColorAt(0, col); ng.setColorAt(1, QColor(0, 0, 0, 0))
            p.fillRect(vp, ng)
        # 星星跟着画布慢慢挪一点（视差），有纵深感
        stars = self._star_pixmap()
        off = self.mapToScene(vp.center()) * 0.04
        ox, oy = -off.x() % vp.width(), -off.y() % vp.height()
        for dx in (ox - vp.width(), ox):
            for dy in (oy - vp.height(), oy):
                p.drawPixmap(QPointF(dx, dy), stars)
        p.restore()
        # 年份那一圈轨道和里外两圈细线
        for r, alpha, dash in ((self.r1, 55, True), (self.r1 * 0.62, 30, False), (self.r1 + 64, 22, False)):
            pen = QPen(QColor(120, 190, 255, alpha), 1, Qt.DashLine if dash else Qt.SolidLine)
            pen.setCosmetic(True)
            p.setPen(pen); p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(0, 0), r, r)

    # ---------- 鼠标 ----------
    def node_at(self, pos):
        for it in self.items(pos):
            if isinstance(it, Node) and not it.removing and it.opacity() > 0.3:
                return it
        return None

    def _set_hover(self, n):
        if n is self.hovered:
            return
        if self.hovered is not None:
            self.hovered.hover = False; self.hovered.update()
        self.hovered = n
        self.popup.hide(); self.pop_timer.stop()
        if n is not None:
            n.hover = True; n.update()
            if n.kind == 'work':
                self.pop_timer.start()
        self.viewport().setCursor(Qt.PointingHandCursor if n is not None else Qt.OpenHandCursor)
        self.edges.update()

    def _show_popup(self):
        n = self.hovered
        if n is not None and n.kind == 'work' and not (self._press and self._press[1]):
            self.popup.show_for(n.data, n.color, QCursor.pos())

    def mousePressEvent(self, e):
        self.cam.stop()
        self.popup.hide(); self.pop_timer.stop()
        self._press = (e.position().toPoint(), False)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        super().mouseMoveEvent(e)
        if self._press and (e.position().toPoint() - self._press[0]).manhattanLength() > 5:
            self._press = (self._press[0], True)          # 在拖动画布
        if not (self._press and self._press[1]):
            self._set_hover(self.node_at(e.position().toPoint()))

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        press, self._press = self._press, None
        if self._dbl:
            self._dbl = False
            return
        if e.button() == Qt.LeftButton and press and not press[1]:
            self.click(self.node_at(e.position().toPoint()))
        self._set_hover(self.node_at(e.position().toPoint()))

    def mouseDoubleClickEvent(self, e):
        self._dbl = True
        if e.button() == Qt.LeftButton and self.node_at(e.position().toPoint()) is None:
            self.fit()

    def leaveEvent(self, e):
        self._set_hover(None)
        super().leaveEvent(e)

    def click(self, n):
        if n is None:
            return
        k = n.kind
        if k == 'center':
            self.collapse()
        elif k == 'year':
            self.collapse() if n.data == self.expanded else self.expand(n.data)
        elif k == 'cat':
            self.toggle_cat(*n.data)
        elif k == 'work':
            self._set_hover(None)
            self.editWork.emit(n.data['id'])
        elif k == 'add':
            self.addWork.emit(n.data, '')

    def contextMenuEvent(self, e):
        n = self.node_at(e.pos())
        self._set_hover(None)
        menu = RoundMenu(parent=self)

        def add(icon, text, fn):
            a = Action(icon, text, self); a.triggered.connect(fn); menu.addAction(a)
        if n is None or n.kind == 'center':
            add(FIF.ADD, '添加年份', self.addYear.emit)
            add(FIF.FULL_SCREEN, '回到全图', self.collapse)
        elif n.kind == 'year':
            add(FIF.ADD, f'在 {n.data} 年添加作品', lambda: self.addWork.emit(n.data, ''))
            add(FIF.DELETE, f'删除 {n.data} 年', lambda: self.deleteYear.emit(n.data))
        elif n.kind == 'cat':
            y, cat = n.data
            add(FIF.ADD, f'添加{cat}', lambda: self.addWork.emit(y, cat))
            add(FIF.UP if (y, cat) not in self.collapsed else FIF.DOWN,
                '收起' if (y, cat) not in self.collapsed else '展开', lambda: self.toggle_cat(y, cat))
        elif n.kind == 'work':
            wid = n.data['id']
            add(FIF.EDIT, '编辑', lambda: self.editWork.emit(wid))
            add(FIF.DELETE, '删除', lambda: self.deleteWork.emit(wid))
        elif n.kind == 'add':
            add(FIF.ADD, '添加作品', lambda: self.addWork.emit(n.data, ''))
        menu.exec(e.globalPos())
