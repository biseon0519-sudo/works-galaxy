# 宇宙风放射状导图（显卡渲染）：中心黑洞 → 一圈年份恒星 → 展开的那一年转到右边，伸出分类 → 作品（发光胶囊）。
# 画面全部由显卡着色器画（moderngl，着色器在 shaders.py）：内部按 2 倍分辨率渲染再缩小（超采样，1080p 屏上相当于按 4K 画），
# 文字事先画进图集纹理，也在显卡上画。
# 位置按三维存（x, y, z），用透视投影画到屏幕上：远的小一点、暗一点，拖动时移动得慢一点。鼠标扰动和漂浮只在 x、y 平面上。
import math, random, sys
import numpy as np
import moderngl
from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QTimer, QElapsedTimer
from PySide6.QtGui import QColor, QPainter, QImage, QFontMetricsF, QCursor, QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from qfluentwidgets import RoundMenu, Action, FluentIcon as FIF
from widgets import CoverPopup, font, DIGITS
from shaders import QUAD_VS, SKY_FS, SPRITE_VS, HOLE_FS, STAR_FS, PILL_FS, BEAM_VS, BEAM_FS, DUST_FS, LABEL_FS, DOWN_FS
from shards import ShardSystem, debris, life_steps, SIM_HZ, SHARD_G
from stream import StreamSystem, MAX_STARS

if sys.platform == 'win32':        # Windows 默认定时器精度 15.6 毫秒，掐帧时间要 1 毫秒精度
    import ctypes
    ctypes.windll.winmm.timeBeginPeriod(1)

NEON = {'文学作品': '#ffb86b', '音乐': '#ff5fa2', '小说': '#8c9bff', '电视剧': '#3ee6c4', '电影': '#ff7a59',
        '动漫': '#ffd84d', '综艺': '#b77bff', '鬼畜/梗': '#86ff6b', '游戏': '#4dc3ff'}
EXTRA = ['#ff8ad8', '#6bf0ff', '#ffe08a', '#9dff9d', '#c3a6ff']
STAR_COLORS = ['#ff9a5c', '#ffc46b', '#ffe6a8', '#fff4e0', '#e4ecff', '#b9cfff', '#8fb3ff', '#a99bff', '#d7a0ff']  # 恒星：橙 → 白 → 蓝紫
DISK_COLOR = QColor('#ffb36b')        # 黑洞吸积盘的颜色，中心到年份的光线从这个颜色开始

SS = 2                    # 超采样倍数（内部按几倍分辨率画）
MAX_TEX = 4096            # 内部画布最大边长
RS = 34                   # 全图时黑洞阴影（看到的黑色圆）的半径（世界坐标）
EL_MAP, EL_CINE = 0.22, 0.10          # 黑洞仰角（弧度）：全图稍微斜着看；展开时几乎侧视，像飞船飞到黑洞旁边
# 展开时黑洞很大、偏左上、一部分在画面外，像坐飞船飞到了黑洞边上（用户自己调出来的位置）：
# 中心位置（占宽、高的比例）、阴影半径（占高度的比例）
CINE_X, CINE_Y, CINE_SHADOW = 0.06, 0.34, 0.37
CINE_RIGHT = 0.05         # 展开时胶囊右端离窗口右边的距离（占宽度）
CINE_TOP = 0.34           # 展开时恒星和分支放在这条线（占高度）以下，避开吸积盘
PARALLAX = 0.016          # 展开时黑洞和星空跟着鼠标反方向微微移动（占宽度），看得出黑洞在后、恒星在前
CINE_ROLL = -0.10         # 展开时黑洞稍微歪一点，更有镜头感
CINE_STAR_X = 0.34        # 展开时恒星的位置（占宽度）：在黑洞下面偏左，挡在黑洞前面，右边留给分支
DISK_OUT = 6.2            # 吸积盘外缘（以视界半径为单位，和着色器里的 R_OUT 一致）
ANIM_S, CAM_S = 1.1, 1.1  # 动画时长（秒）：普通移动、镜头（展开时恒星重建的时长按模拟出来的算）
# 收起：恒星不被吸过去、不拉长，原地直接解体（亮一下，整颗化开、变淡，像胶囊碎掉那样），化开的气体先往外迸一下、
# 很快被刹住，再被黑洞吸进去。引力弱一些、绕黑洞走得快一些，所以是绕着黑洞慢慢旋进去（用户要的拉扯感、不用收得太利索）。
# 气体在显卡上整段模拟（见 shards.py）。差不多吞完时黑洞亮一下、荡开一圈涟漪
C_TEAR_S = 0.35           # 原地化开要多久
C_G = SHARD_G * 0.3
C_ORBIT, C_SWIRL = 0.8, 0.8           # 漩涡：被吸进去的路上，绕黑洞的速度慢慢（每秒约 0.8）被带到圆轨道速度的 0.8
C_BURST = (3.0, 15.0)     # 化开时朝各个方向轻轻飘开的速度（气体先在原地成实心的一团，不飞走）
SWALLOW_S = 0.3 + C_TEAR_S + 0.05     # 恒星本体的动画时长（每颗解体的时间错开 0~0.3 秒）
# 撕开时的速度拖尾、残留气云只加在收起上（用户觉得展开现在刚好）；改成 True 展开也加（倒着放）
REBIRTH_FX = False
# 展开 = 一遍“被吞掉”倒着放：先在恒星自己的位置正着模拟一遍（只沿直线掉进黑洞），记下每团气体的路线再倒着播放——
# 气体从黑洞沿直线喷出、越飞越慢，在恒星那里汇成，恒星原地慢慢凝实（DISSOLVE_S），节奏用 BIRTH_TAIL_S 收尾
DISSOLVE_S = 0.4          # 展开时气体汇成星体要多久（太快了恒星像是“弹”出来的）
BIRTH_TAIL_S = 0.55       # 最后一颗恒星成形后，展开动画再留多久（原来的节奏）
ROPE_LAG, ROPE_K, ROPE_D = 0.5, 22.0, 6.0     # 分支光丝的惯性：端点动时控制点只跟上一部分，再靠弹簧追上
# 拖动恒星的手感和鼠标扰动的气泡一样：恒星像在水里，被弹簧带着跟光标走，慢半拍，松手后慢慢停稳
# （阻尼比和扰动的 SPRING / DAMP 差不多，只是硬一些，不然拖起来太飘）
DRAG_K, DRAG_D = 25.0, 9.0
LINK_HIDE, LINK_SHOW = 10.0, 3.5      # 连线藏起来、淡入的速度（每秒）：展开收起时、拖动恒星时先藏起来，停稳后再淡入
STAR_R = 24               # 恒星半径
STAR_ACTIVE = 1.0         # 展开的那颗恒星放大多少（近看能看清表面）
FOCAL = 900.0             # 透视焦距：z 越大越近
LEAF, GROUP_GAP = 36, 18  # 展开的分支里：每个作品占的高度、分类之间多空的距离
BEND = 0.00022            # 分支的弧度：离中线越远越往回收一点，看起来是一段圆弧
# 帧率：有动画、鼠标在动时跟着屏幕刷新（120Hz 屏就是 120 帧）；只是慢慢漂浮时隔一帧画一帧（约 60 帧）。
# Qt 的显卡控件每画一帧都要占满一个核心等屏幕刷新，空闲时减半能省一半 CPU、少发热
MAX_FPS = 120             # 帧率上限：刷新率更高的屏幕（144、240Hz）也不超过 120 帧
FRAME_MARGIN = 0.0006     # 满帧率时提前多少秒开始画下一帧（掐着屏幕刷新的点画，CPU 就不用干等）
IDLE_WAIT_MS = 11         # 空闲时画完一帧后等多久再画下一帧（比一个刷新周期长一点，正好落到下下次刷新）
IDLE_AFTER = 1.2          # 鼠标停下多少秒后算空闲
# 鼠标扰动「来拒去留」：鼠标靠近时把节点顺着鼠标的方向推开，离开时又把节点带着跟过去一点，然后像水里的气泡慢慢漂回原位
SPRING, DAMP, MAX_PUSH = 5.0, 4.2, 14.0
# 节点的“质量”：越重被推开得越少、晃得越慢（阻尼比不变，所以回弹的感觉一样，只是更沉）。黑洞很重，只微微一晃
MASS = {'center': 6.0}
PUSH_R = 90               # 鼠标多近会影响节点（屏幕像素）
PUSH_DRAG, PUSH_AWAY = 1.1, 30.0      # 顺着鼠标走的力度、离得很近时额外被推开的力度
# 自己漂浮：慢、幅度大一点。作品之间挨得近，上下漂得少一点免得叠在一起
AMP = {'center': (4, 4), 'year': (12, 12), 'cat': (7, 4), 'work': (6, 2.5), 'add': (4, 3)}


def neon(cat):
    if cat in NEON:
        return QColor(NEON[cat])
    return QColor(EXTRA[sum(map(ord, cat)) % len(EXTRA)])


def star_color(i, n):
    t = i / max(1, n - 1) * (len(STAR_COLORS) - 1)
    a, b = QColor(STAR_COLORS[int(t)]), QColor(STAR_COLORS[min(len(STAR_COLORS) - 1, int(t) + 1)])
    k = t - int(t)
    return QColor.fromRgbF(a.redF() + (b.redF() - a.redF()) * k, a.greenF() + (b.greenF() - a.greenF()) * k,
                           a.blueF() + (b.blueF() - a.blueF()) * k)


def spiral_points(n, r0=175.0, gap=135.0, grow=46.0):
    """阿基米德螺旋 r = r0 + grow·θ 上按相同弧长 gap 取 n 个点，返回 [(角度, 半径)]。角度往负方向转（和吸积盘转向一致）。"""
    pts, th = [], 0.0
    for _ in range(n):
        r = r0 + grow * th
        pts.append((-th, r))
        th += gap / math.hypot(r, grow)
    return pts


def star_layout(years, seed):
    """恒星的自动位置 {年: (角度, 半径, z)}：沿一条从黑洞旋出去的螺旋按时间排，最早的离黑洞最近，每颗带一点随机偏移和远近。
    seed 决定螺旋的松紧、朝向和偏移，换一个 seed 就是一种新排布；seed 为 None 是最早的固定排布（兼容以前拖过的位置）。"""
    n = max(1, len(years))
    out = {}
    if seed is None:
        pts = spiral_points(n)
        for i, y in enumerate(years):
            r = random.Random(f'year{y}')
            a, rr = pts[i]
            a += r.uniform(-0.1, 0.1); rr *= r.uniform(0.92, 1.08)
            out[y] = (a, rr, r.uniform(-140, 140))
        return out
    r = random.Random(f'layout{seed}')
    pts = spiral_points(n, r0=r.uniform(160, 205), gap=r.uniform(122, 150), grow=r.uniform(32, 62))
    turn = r.uniform(-math.pi, math.pi)
    xy = []
    for i in range(n):
        a, rr = pts[i]
        a += turn + r.uniform(-0.16, 0.16); rr *= r.uniform(0.9, 1.1)
        xy.append([rr * math.cos(a), rr * math.sin(a)])
    # 随机偏移可能让两颗挨得太近（叠在一起）：反复把太近的两颗各推开一半
    MIN = 105
    for _ in range(40):
        moved = False
        for i in range(n):
            for j in range(i + 1, n):
                dx, dy = xy[j][0] - xy[i][0], xy[j][1] - xy[i][1]
                d = math.hypot(dx, dy) or 1e-3
                if d < MIN:
                    k = (MIN - d) / 2 / d
                    xy[i][0] -= dx * k; xy[i][1] -= dy * k; xy[j][0] += dx * k; xy[j][1] += dy * k
                    moved = True
        if not moved:
            break
    for i, y in enumerate(years):
        x, yy = xy[i]
        out[y] = (math.atan2(yy, x), max(150.0, math.hypot(x, yy)), r.uniform(-140, 140))
    return out


def bezier(P, t=None):
    """三次贝塞尔曲线（4 个控制点）在 t 处的点，t 默认是连线的 BEAM_T。"""
    tt = (BEAM_T if t is None else t)[:, None]; mt = 1 - tt
    return mt ** 3 * P[0] + 3 * mt * mt * tt * P[1] + 3 * mt * tt * tt * P[2] + tt ** 3 * P[3]


def fade_link(v, hide, dt):
    """连线的显示程度往 0 走（藏起来，很快）或往 1 走（淡入，慢一点）。"""
    return max(0.0, v - dt * LINK_HIDE) if hide else min(1.0, v + dt * LINK_SHOW)


def lerp(a, b, t):
    return a + (b - a) * t


def ease_spring(t, w=6.5):
    """临界阻尼弹簧的响应曲线：起步柔和、中间走得快、最后很长一段慢慢停稳，不冲过头，比回弹曲线软。"""
    if t >= 1:
        return 1.0
    return (1 - (1 + w * t) * math.exp(-w * t)) / (1 - (1 + w) * math.exp(-w))


class Tween:
    """按真实时间算进度的补间：每帧画之前按当前时间取值，和屏幕刷新同步。
    （QVariantAnimation 按自己的定时器跳，和 120Hz 的画面对不齐，看起来一顿一顿的、发硬）"""

    def __init__(self):
        self.t0, self.dur, self.running = 0.0, 1.0, False

    def start(self, now, dur):
        self.t0, self.dur, self.running = now, dur, True

    def stop(self):
        self.running = False

    def raw(self, now):
        return min(1.0, (now - self.t0) / self.dur) if self.running else 1.0


def smooth(a, b, x):
    t = max(0.0, min(1.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def wrap_angle(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


BEAM_HW = 20.0            # 光线条带的半宽（屏幕像素），要盖住柔光的范围
BEAM_SEG = 40             # 每条线切成几段（段太少，弯的时候能看出折角）
BEAM_T = np.linspace(0, 1, BEAM_SEG + 1)           # 线上每个点的位置（0 = 起点，1 = 终点）


class Node:
    """导图节点。kind：center 黑洞 / year 恒星 / cat 分类 / work 作品 / add 添加按钮。
    圆形节点（center、year、add）的 base 是圆心；胶囊节点（cat、work）的 base 是左端中点，往右伸。"""

    def __init__(self, key, kind):
        self.key, self.kind = key, kind
        self.hover = self.active = self.removing = False
        self.parent_key = None
        self.text = self.sub = ''
        self.color = QColor('white')
        self.data = None
        self.w = self.h = 0
        self.base = QPointF()           # 布局位置（世界坐标 x、y）
        self.z = self.z0 = self.z1 = 0.0   # 远近（世界坐标 z，越大越近）
        self.p0 = self.p1 = QPointF()   # 动画起点、终点；年份按角度转（polar），其他按直线走
        self.polar0 = self.polar1 = None
        self.o0 = self.o1 = self.opacity = 1.0
        r = random.Random(key)
        self.bob = [r.uniform(0.12, 0.22), r.uniform(0.27, 0.4), r.uniform(0.1, 0.2), r.uniform(0.25, 0.38)] + \
                   [r.uniform(0, 6.3) for _ in range(4)]
        self.seed = r.random()
        self.d, self.v = [0.0, 0.0], [0.0, 0.0]      # 鼠标扰动的偏移和速度（只在平面上）
        self.glow = 0.0                 # 悬停亮度 0~1，慢慢过渡
        self.sx = self.sy = 0.0         # 这一帧在屏幕上的位置（像素）
        self.k = 1.0                    # 这一帧的透视缩放（含镜头缩放）
        self.rpx = 0.0                  # 黑洞：这一帧阴影在屏幕上的半径
        self.swallow = None             # 收起时正被黑洞吸过去：(起点, 起点的 z, 碎开前多等的秒数)；胶囊是 None（原地碎成晶尘）
        self.shattered = False          # 已经碎成水晶碎片（星体消失）
        self.dang = 0.0                 # 被拉长的方向（展开时：指向黑洞）
        self.fresh = False              # 刚出现（年份由黑洞里冲出来的碎片凝结出来）
        self.birth_at = 0.0             # 刚出现的恒星在动画开始后第几秒凝结
        self.drift_w = 1.0              # 漂浮的幅度：刚汇成的恒星先不漂（气体汇到的是没漂浮的位置），慢慢恢复，不然一成形就跳一下
        self.form = 1.0                 # 恒星凝结的程度 0~1
        self.flash = 0.0                # 碎开前、凝结时亮一下
        self.tide = 0.0                 # 被潮汐拉长的程度 0~1（展开时刚汇成是拉长的，慢慢恢复成圆的）
        self.tear = 0.0                 # 化开了多少 0~1（收起时原地化开；展开时倒过来，气体汇成星体）

    def round(self):
        return self.kind in ('center', 'year', 'add')

    def grown(self):
        """展开的那颗恒星放大的倍数（其他节点是 1）。"""
        return 1 + STAR_ACTIVE * self.active

    def set_content(self, text, sub, color, data):
        self.text, self.sub, self.color, self.data = text, sub, QColor(color), data
        k = self.kind
        if k == 'center':
            self.w = self.h = RS * 2
        elif k == 'year':
            self.w = self.h = STAR_R * 2
        elif k == 'add':
            self.w = self.h = 26
        elif k == 'cat':
            tw = QFontMetricsF(font(14, True)).horizontalAdvance(text)
            cw = QFontMetricsF(font(13, False, DIGITS)).horizontalAdvance(sub) if sub else 0
            self.w, self.h = tw + (cw + 8 if cw else 0) + 32, 32
        else:
            tw = QFontMetricsF(font(13)).horizontalAdvance(text)
            self.w, self.h = min(tw, 240) + 26, 28

    def drift(self, t):
        """自己漂浮：每个方向两种慢节奏叠在一起，看起来不机械。"""
        ax, ay = AMP[self.kind]
        w1, w2, w3, w4, p1, p2, p3, p4 = self.bob
        return (ax * (0.65 * math.sin(w1 * t + p1) + 0.35 * math.sin(w2 * t + p2)),
                ay * (0.65 * math.sin(w3 * t + p3) + 0.35 * math.sin(w4 * t + p4)))

    def offset(self, t):
        """漂浮再加上鼠标扰动。"""
        x, y = self.drift(t)
        return QPointF(x * self.drift_w + self.d[0], y * self.drift_w + self.d[1])

    def screen_center(self):
        if self.round():
            return QPointF(self.sx, self.sy)
        return QPointF(self.sx + self.w / 2 * self.k, self.sy)

    def hit(self, x, y):
        if self.round():
            r = self.rpx * (0.9 if self.rpx > 80 else 1.25) if self.kind == 'center' else (self.w / 2 * self.grown() + 6) * self.k
            return (x - self.sx) ** 2 + (y - self.sy) ** 2 <= r * r
        return self.sx - 3 <= x <= self.sx + self.w * self.k + 3 and abs(y - self.sy) <= self.h / 2 * self.k + 3

    def edge_point(self, other, out):
        """连线接在哪（屏幕像素）：圆形接在朝向对方的边上；胶囊进线接左端、出线接右端。"""
        if self.round():
            rad = {'center': RS * 1.65, 'year': STAR_R * 1.05 * self.grown(), 'add': 13}[self.kind] * self.k
            dx, dy = other.sx - self.sx, other.sy - self.sy
            n = math.hypot(dx, dy) or 1
            return self.sx + dx / n * rad, self.sy + dy / n * rad
        return (self.sx + self.w * self.k, self.sy) if out else (self.sx, self.sy)


def _rgba(c, a=1.0):
    return (c.redF(), c.greenF(), c.blueF(), a)


class MindMap(QOpenGLWidget):
    editWork = Signal(str)
    deleteWork = Signal(str)
    addWork = Signal(int, str)        # 年份, 分类（空字符串表示不指定）
    addYear = Signal()
    deleteYear = Signal(int)
    layoutChanged = Signal()          # 用户拖动了恒星，要存盘

    def __init__(self, parent=None):
        super().__init__(parent)
        fmt = QSurfaceFormat(); fmt.setVersion(3, 3); fmt.setProfile(QSurfaceFormat.CompatibilityProfile)
        self.setFormat(fmt)
        self.setMouseTracking(True)
        self.setCursor(Qt.OpenHandCursor)
        self.ctx = None
        self.nodes = {}
        self.doc = None
        self.root_open = True           # 中心点一下收起全部，再点展开
        self.expanded = None            # 当前展开的年份（一次只展开一年）
        self.collapsed = set()          # 收起来的分类 (年, 分类)
        self.phi = -math.pi / 2         # 年份圈转到的角度：第一年的位置
        self.r1 = 280
        self.branch_rect = QRectF()
        self.hovered = None
        self.cam_c, self.cam_s = QPointF(0, 0), 1.0       # 镜头：看向的世界坐标、缩放
        self._press = None              # (按下的位置, 是否在拖动, 按下时的镜头中心)
        self._dbl = False
        self._drag_star = None          # 正在拖的恒星
        self._drag = None               # 拖恒星：{恒星, 屏幕位置, 速度, 光标对着的位置, 抓住的偏移, 松手了没}
        self._mouse = None              # 上一次鼠标位置和时间，算划过的速度
        self.cine = 0.0                 # 0 = 全图（黑洞在中间、斜看），1 = 展开（黑洞在左边、侧视放大）
        self.bh = (-9999.0, -9999.0, 1.0, EL_MAP, 0.0)   # 这一帧黑洞在屏幕上的 x、y、阴影半径、仰角、滚转
        self._ropes = {}                # 分支光丝的惯性状态
        self._cine_fit = (1.0, 0.0)     # 展开近景的缩放、恒星在屏幕上的 x（排布时算好，镜头对准时用）
        self._par = QPointF(0, 0)       # 视差：鼠标离画面中心多远（-1~1，平滑过的）
        self._mouse_pos = None
        self._busy = True               # 这一帧有没有东西在动（决定下一帧画不画满帧率）
        self._last_input = 0.0          # 上次鼠标操作的时间
        self.link_fade = 1.0            # 连线整体的显示程度：展开、收起时先隐藏，快停稳时再淡入
        self._anim_moving = False       # 这次动画里有没有东西在飞（只是淡入淡出就不用藏连线）
        # 晶尘粒子，每行：世界 x、y，速度 x、y，剩余寿命，总寿命，大小，颜色 r、g、b，闪烁相位
        self.dust = np.zeros((0, 11), 'f4')
        self._gulp_t = -99.0            # 碎片差不多都被吸进去的时间（黑洞亮一下、荡开涟漪）；收起时是算好的将来某一刻
        self.stream = None              # 物质流的粒子（显卡上模拟，见 stream.py），显卡准备好后才建
        self._stream_dirty = False
        self._stream_grow = False       # 有恒星重新出现：物质流要从恒星长出来
        self._frame_dt = 0.0
        self.parts = None               # 恒星碎片（显卡上模拟，见 shards.py），显卡准备好后才建
        self._pending = []              # 点下去时排好、接下来几帧在显卡上模拟的碎片（收起 / 展开，见 _run_pending）
        self._rope_t = 0.0

        self.anim = Tween()             # 节点移动（展开、收起、飞出、被吞）
        self.cam = Tween()              # 镜头（连同全图 ↔ 展开的黑洞视角一起过渡）
        self._cam0 = self._cam1 = (1.0, QPointF(0, 0), 0.0)
        self.popup = CoverPopup()
        self.pop_timer = QTimer(self, singleShot=True, interval=220)
        self.pop_timer.timeout.connect(self._show_popup)
        self.clock = QElapsedTimer(); self.clock.start()
        self._last_t = 0.0
        # 每画完一帧就请求下一帧，跟着屏幕刷新走（120Hz 屏就是 120 帧）；最小化时停下，看门狗负责重新启动
        self.frameSwapped.connect(self._next_frame)
        self._delay = QTimer(self, singleShot=True, timerType=Qt.PreciseTimer)
        self._delay.timeout.connect(self.update)
        self.watchdog = QTimer(self, interval=250)
        self.watchdog.timeout.connect(self._kick)

    # ---------- 数据和布局 ----------
    def set_doc(self, doc, expand=None, first=False):
        self.doc = doc
        if expand is not None:
            self.expanded = expand if expand in doc['years'] else None
        elif self.expanded not in doc['years']:
            self.expanded = None
        self.relayout(animate=not first)
        if first:
            self.cine = self._cine_target()
            self.fit(animate=False)

    def expand(self, year):
        self.root_open = True
        self.expanded = year
        self.relayout()
        self.fit()

    def collapse(self):
        self.expanded = None
        self.relayout()
        self.fit()

    def toggle_root(self):
        self.root_open = not self.root_open
        if not self.root_open:
            self.expanded = None
        else:
            self._new_layout()          # 每次从黑洞里吐出来，恒星都换一种随机排布
        self.relayout()
        self.fit()

    def _new_layout(self):
        """换一种随机的恒星排布（会清掉手动拖过的位置），存进数据文件。"""
        self.doc['layout_seed'] = random.randrange(1 << 30)
        self.doc.pop('star_pos', None)
        self.layoutChanged.emit()

    def rearrange(self):
        self._new_layout()
        self.relayout()
        self.fit()

    def _cine_target(self):
        return 1.0 if (self.root_open and self.expanded is not None) else 0.0

    def toggle_cat(self, year, cat):
        self.collapsed ^= {(year, cat)}
        self.relayout()
        self.fit()

    def _targets(self):
        """算出每个该显示的节点：key → (kind, 父 key, 文字, 副文字, 颜色, 数据, 位置, 年份的极坐标或 None, z)。"""
        doc = self.doc
        years = sorted(doc['years'])
        n = max(1, len(years))
        # 旋臂：按时间顺序沿一条从黑洞旋出去的螺旋排，最早的离黑洞最近；每颗带一点随机偏移和远近
        lay = star_layout(years, doc.get('layout_seed'))
        custom = doc.get('star_pos', {})        # 用户拖过的恒星：相对自动位置的偏移（没转动前的坐标）
        jit = {}
        for y in years:
            a, rr, z = lay[y]
            x, yy = rr * math.cos(a), rr * math.sin(a)
            if str(y) in custom:
                x += custom[str(y)][0]; yy += custom[str(y)][1]
            jit[y] = (math.atan2(yy, x), math.hypot(x, yy), z)
        self.r1 = max([j[1] for j in jit.values()] + [280]) / 1.24      # 全图的范围
        if self.expanded in years:              # 展开的那一年转到正右边，转最短的方向
            want = -jit[self.expanded][0]
            self.phi += wrap_angle(want - self.phi)
        counts = {}
        for w in doc['works']:
            counts[w['year']] = counts.get(w['year'], 0) + 1
        t = {'c': ('center', None, '年度作品', f'{len(doc["works"])} 个作品', DISK_COLOR, None, QPointF(0, 0), None, 0.0)}
        self.branch_rect = QRectF()
        if not self.root_open:
            return t
        for i, y in enumerate(years):
            a = self.phi + jit[y][0]
            ry = jit[y][1]
            z = 0.0 if y == self.expanded else jit[y][2]       # 展开的那一年移到和分支同一层
            t[f'y{y}'] = ('year', 'c', str(y), str(counts.get(y, '')), star_color(i, n), y,
                          QPointF(ry * math.cos(a), ry * math.sin(a)), (a, ry), z)
        y = self.expanded
        if y in years:
            r1 = jit[y][1]                      # 分支从这一年实际的位置往右长
            ycolor = t[f'y{y}'][4]
            groups = []
            for cat in doc['categories']:
                ws = [w for w in doc['works'] if w['year'] == y and w['category'] == cat]
                if ws:
                    groups.append((cat, ws, (y, cat) in self.collapsed))
            # 竖着排：每个分类一块，块高 = 作品数（收起时算 1 个）
            blocks = [(1 if col else len(ws)) * LEAF for _, ws, col in groups]
            total = sum(blocks) + GROUP_GAP * len(groups) + LEAF
            cur = -total / 2
            cat_w = max([QFontMetricsF(font(14, True)).horizontalAdvance(c) for c, _, _ in groups] + [0]) + 70
            work_w = max([min(QFontMetricsF(font(13)).horizontalAdvance(w['title']), 240) + 26
                          for _, ws, col in groups if not col for w in ws] + [0])
            # 展开的近景：恒星位置固定，胶囊右端贴近窗口右边（随窗口大小变），中间空出来的距离拉长恒星到分类的连线
            gap = self._cine_layout(r1, 240 + cat_w + 60 + work_w, total + 40)
            x2 = r1 + 240 + gap                 # 恒星和分类之间多留点距离
            x3 = x2 + cat_w + 60
            right = x2 + 40
            for (cat, ws, col), h in zip(groups, blocks):
                yc = cur + h / 2
                ck = f'k{y}|{cat}'
                color = neon(cat)
                t[ck] = ('cat', f'y{y}', cat, str(len(ws)) + (' …' if col else ''), color, (y, cat),
                         QPointF(x2 - BEND * yc * yc, yc), None, 0.0)
                if not col:
                    for j, w in enumerate(ws):
                        yy = cur + LEAF * (j + 0.5)
                        t['w' + w['id']] = ('work', ck, w['title'], '', color, w, QPointF(x3 - BEND * yy * yy, yy), None, 0.0)
                        right = max(right, x3 + min(QFontMetricsF(font(13)).horizontalAdvance(w['title']), 240) + 26)
                cur += h + GROUP_GAP
            ya = cur + LEAF / 2
            t[f'a{y}'] = ('add', f'y{y}', '+', '', ycolor, y, QPointF(x2 + 13 - BEND * ya * ya, ya), None, 0.0)
            self.branch_rect = QRectF(QPointF(r1 - 60, -total / 2 - 20), QPointF(right + 30, total / 2 + 20))
        return t

    def _cine_layout(self, r1, width, height):
        """展开的近景里分支的缩放和位置：按高度定缩放（上沿不超过 CINE_TOP，放不下贴住下沿往上长）；
        恒星在 CINE_STAR_X 再往右一个恒星宽；胶囊右端离窗口右边 CINE_RIGHT。返回恒星到分类之间要多拉长的距离（世界坐标）。"""
        vw, vh = max(1, self.width()), max(1, self.height())
        s = max(0.85, min(1.15, (vh * (1 - CINE_TOP) - 16) / height))
        star_sx = vw * CINE_STAR_X + 2 * STAR_R * (1 + STAR_ACTIVE) * s
        room = vw * (1 - CINE_RIGHT) - star_sx          # 恒星中心到胶囊右端能用的屏幕宽度
        gap = 0.0
        if width * s > room:                            # 窗口太窄：缩小一点
            s = max(0.6, room / width)
        else:
            gap = min(500.0, (room - width * s) / s)
        self._cine_fit = (s, star_sx)
        return gap

    def _shatter(self, n):
        """胶囊碎成晶尘：在胶囊范围里撒一把碎屑，往四周慢慢飘散，边闪边消失。"""
        rng = np.random.default_rng()
        cnt = int(max(30, min(150, n.w * n.h / 30)))
        u = rng.random((cnt, 2))
        x = n.base.x() + u[:, 0] * n.w
        y = n.base.y() + (u[:, 1] - 0.5) * n.h
        dx, dy = x - (n.base.x() + n.w / 2), y - n.base.y()
        norm = np.hypot(dx, dy) + 1e-3
        sp = rng.uniform(50, 170, cnt)                   # 一开始猛地炸开，阻力很快让它慢下来，然后慢慢飘
        ang = rng.normal(0, 0.6, cnt)                    # 方向带点随机，不是整齐地往外
        ux, uy = dx / norm, dy / norm
        vx = (ux * np.cos(ang) - uy * np.sin(ang)) * sp + rng.normal(0, 18, cnt)
        vy = (ux * np.sin(ang) + uy * np.cos(ang)) * sp * 0.8 + rng.normal(0, 18, cnt) - 8
        life = rng.uniform(0.8, 1.6, cnt)
        c = np.array([n.color.redF(), n.color.greenF(), n.color.blueF()])
        wmix = rng.uniform(0, 0.6, (cnt, 1))
        col = c * (1 - wmix) + wmix                      # 有的偏白，像水晶反光
        new = np.column_stack([x, y, vx, vy, life, life, rng.uniform(0.5, 1.6, cnt), col, rng.random(cnt)]).astype('f4')
        self.dust = np.concatenate([self.dust, new])

    def _run_pending(self):
        """点下去时排好的碎片：在显卡上模拟（要在画的时候做，这时显卡上下文才是当前的）。
        每帧往前推一点（SimJob.pump），全部提交完的下一帧再取结果，CPU 不用干等显卡。"""
        if self.parts is None:
            self._pending = []
            return
        for job in list(self._pending):
            if 'sim' not in job:
                self._start_sim(job)
            if not job['sim'].submitted():
                job['sim'].pump()
                job['ready'] = False                    # 刚提交的这一帧先不取结果
            elif not job.get('ready'):
                job['ready'] = True
            else:
                self._pending.remove(job)
                self._finish_sim(job)

    def _start_sim(self, job):
        """按每颗恒星碎开的位置算出碎片，交给显卡模拟。"""
        rng = np.random.default_rng()
        init, look, owner, at = [], [], [], []
        for i, n in enumerate(job['nodes']):
            if job['kind'] == 'collapse':
                # 原地解体的位置和时刻（加上那一刻的漂浮），每颗错开的时间见 _step
                start, z0, lag = n.swallow
                ts = lag * self.anim.dur / SWALLOW_S
                dx, dy = n.drift(job['t0'] + ts)
                x0, y0, z = start.x() + dx, start.y() + dy, z0
            else:
                # 展开：在恒星自己的位置正着模拟一遍“被吞掉”，之后倒着放（气体汇过来，恒星原地成形）
                ts = 0.0
                x0, y0, z = n.base.x(), n.base.y(), n.z
            fx = job['kind'] == 'collapse' or REBIRTH_FX
            if job['kind'] == 'collapse':
                a, b = debris(rng, n.color, x0, y0, z, STAR_R * 1.1, 1.0, 1.0, C_TEAR_S, fx, C_G, C_ORBIT, 0.0,
                              carry=0.0, burst=C_BURST)
            else:
                # 展开：气体从黑洞沿直线喷出、先快后慢（用户要的，和以前那版一样），所以正着模拟时只沿直线掉进去
                # 从静止开始掉（不带初速度、不拉开），倒着放时气体正好在汇到恒星的那一刻慢到停住，不会冲过头“跳一下”
                a, b = debris(rng, n.color, x0, y0, z, STAR_R * 1.1, 1.0, 1.0, DISSOLVE_S, fx, tidal_k=0.0,
                              straight=True, carry=0.0)
            init.append(a); look.append(b); owner.append(np.full(len(a), i)); at.append(np.full(len(a), ts))
        job['look'], job['owner'], job['at'] = map(np.concatenate, (look, owner, at))
        job['rng'] = rng
        if job['kind'] == 'collapse':
            job['sim'] = self.parts.simulate(np.concatenate(init), C_G, C_ORBIT, C_SWIRL)
        else:
            # 展开：气体剥下来后先停在原地 DISSOLVE_S 再往里掉，倒着放 = 气体先汇到、停住，恒星再从里面凝出来
            job['sim'] = self.parts.simulate(np.concatenate(init), hold=DISSOLVE_S)

    def _finish_sim(self, job):
        tex, done = job['sim'].finish()
        steps = life_steps(job['look'], done)
        t0, look = job['t0'], job['look']
        if job['kind'] == 'collapse':
            b = self.parts.add(t0, True, tex, look, job['at'], steps, streaks=True)
            # 差不多都吞进去（按分量剩 12%）的那一刻：黑洞亮一下，荡开一圈涟漪
            order = np.argsort(b.gone)
            w = np.cumsum(b.weight[order])
            self._gulp_t = t0 + float(b.gone[order][np.searchsorted(w, 0.88 * w[-1])])
        else:
            steps = np.minimum(steps, 5 * SIM_HZ - 1)       # 展开维持原来的节奏（模拟时长改成 7 秒前是 5 秒）
            # 碎片掉进去得越晚，倒着放时越早出发；同一颗恒星的碎片在同一刻收拢。最慢的碎片也来得及从黑洞飞回来
            nodes = job['nodes']
            lead = (steps.max() + 1) / SIM_HZ
            birth = lead + job['rng'].uniform(0.0, 0.3, len(nodes))
            for n, bt in zip(nodes, birth):
                n.birth_at = bt
            self.parts.add(t0, False, tex, look, birth[job['owner']] - steps / SIM_HZ, steps, streaks=REBIRTH_FX)
            self.anim.dur = lead + 0.3 + BIRTH_TAIL_S + 0.1
            self._gulp_t = t0                           # 黑洞先亮一下、荡开涟漪，碎片接着冲出来

    def relayout(self, animate=True):
        targets = self._targets()
        now = self.now()
        born, broken = [], []
        for key, (kind, parent, text, sub, color, data, pos, polar, z) in targets.items():
            node = self.nodes.get(key)
            if node is None or node.removing:
                node = Node(key, kind)
                par = self.nodes.get(parent)
                start = QPointF(par.base) if par is not None and animate else pos
                node.base = QPointF(start)
                node.z = par.z if par is not None and animate else z
                node.opacity = 0.0 if animate else 1.0
                node.fresh = animate
                self.nodes[key] = node
                if polar is not None:       # 新出来的年份：由黑洞喷出来的碎片在新位置附近凝结，再退回自己的位置
                    node.polar0, node.base, node.z = polar, QPointF(pos), z
                    if animate:
                        node.form, node.drift_w = 0.0, 0.0
                        node.set_content(text, sub, color, data)
                        born.append(node)
            elif polar is not None:
                node.polar0 = (math.atan2(node.base.y(), node.base.x()), math.hypot(node.base.x(), node.base.y()))
            node.parent_key = parent
            node.set_content(text, sub, color, data)
            node.active = (kind == 'year' and data == self.expanded)
            node.p0, node.p1 = QPointF(node.base), pos
            node.z0, node.z1 = node.z, z
            node.o0, node.o1 = node.opacity, 1.0
            node.polar1 = polar
            if polar is not None and node.polar0 is not None and not node.fresh:     # 转最短的方向
                node.polar0 = (polar[0] - wrap_angle(polar[0] - node.polar0[0]), node.polar0[1])
        for key, node in self.nodes.items():
            if key not in targets and not node.removing:
                node.removing = True
                par = targets.get(node.parent_key)
                if node.kind == 'year':
                    # 先被黑洞吸过去一段，再清脆地碎开（见 _step）；每颗碎开的时间错开一点
                    node.base += node.offset(now) - QPointF(*node.d)    # 从现在看到的位置出发
                    node.swallow = (QPointF(node.base), node.z, random.uniform(0.0, 0.3))
                    node.shattered = not animate
                    if animate:
                        broken.append(node)
                else:
                    node.swallow = None             # 胶囊：原地碎成晶尘
                    if animate:
                        self._shatter(node)
                node.z0, node.z1 = node.z, (par[8] if par else 0.0)
                node.o0 = node.opacity
                node.polar1 = None
                node.hover = False
        moving = any(n.fresh or n.removing or (n.p1 - n.p0).manhattanLength() > 3 or
                     (n.polar1 is not None and n.polar0 is not None and abs(n.polar1[0] - n.polar0[0]) > 0.01)
                     for n in self.nodes.values())
        if animate:
            self._anim_moving = moving          # 有东西在飞：连线先隐藏，快停稳时再出现
            years_out = any(n.removing and n.kind == 'year' for n in self.nodes.values())
            # 展开的时长要等碎片模拟完才知道（_run_pending 里改），先放一个够长的
            self.anim.start(now, 9.0 if born else (SWALLOW_S if years_out else ANIM_S))
            if broken:
                self._pending.append(dict(kind='collapse', t0=now, nodes=broken))
            if born:
                self._stream_grow = True
                for n in born:
                    n.birth_at = 99.0                   # 模拟完之前先别出现
                self._pending.append(dict(kind='rebirth', t0=now, nodes=born))
        else:
            self.anim.stop()
            self._step(1.0); self._finish()
        self.update()

    def _step(self, raw):
        """动画进行到 raw（0~1，按时间）时每个节点的位置、远近、透明度。"""
        t = ease_spring(raw)
        for n in self.nodes.values():
            if n.removing and n.swallow is None:      # 碎成晶尘的胶囊：很快淡掉
                n.opacity = n.o0 * (1 - smooth(0.0, 0.18, raw))
                continue
            if n.removing:
                # 先被黑洞吸过去一段、越来越快，被潮汐拉长、越来越亮，然后整颗化成气体被撕开（星体消失，气体接上）
                start, z0, lag = n.swallow
                after = raw * SWALLOW_S - lag                     # 开始解体之后过了多久（秒，之前是负的）
                n.base, n.z = QPointF(start), z0
                n.dang = math.atan2(-start.y(), -start.x())
                n.flash = 0.4 * smooth(-0.06, 0.0, after) * (1 - smooth(0.04, C_TEAR_S, after))    # 解体前亮一下
                n.tide, n.tear = 0.0, min(1.0, max(0.0, after) / C_TEAR_S)
                n.d = [0.0, 0.0]
                if after >= 0.0:
                    n.shattered = True
                n.opacity = n.o0 if after < C_TEAR_S * 1.1 else 0.0
                continue
            k = t
            if n.polar1 is not None and n.polar0 is not None:
                a, r = lerp(n.polar0[0], n.polar1[0], k), lerp(n.polar0[1], n.polar1[1], k)
                n.base = QPointF(r * math.cos(a), r * math.sin(a))
            else:
                n.base = QPointF(lerp(n.p0.x(), n.p1.x(), k), lerp(n.p0.y(), n.p1.y(), k))
            n.z = lerp(n.z0, n.z1, t)
            n.opacity = max(0.0, min(1.0, lerp(n.o0, n.o1, t)))
            if n.fresh and n.kind == 'year' and n.polar1 is not None:
                # 收起倒着放：气体沿直线从黑洞喷过来，在恒星自己的位置汇成，恒星原地慢慢凝实、亮一下
                tau = raw * self.anim.dur - n.birth_at
                a, r = n.polar1
                n.base, n.z = QPointF(r * math.cos(a), r * math.sin(a)), n.z1
                n.drift_w = smooth(0.0, 1.2, tau)
                n.opacity = 1.0 if tau > -DISSOLVE_S * 1.2 else 0.0
                n.form = 1.0
                n.flash = 0.35 * smooth(-0.05, 0.0, tau) * (1 - smooth(0.05, 0.5, tau))
                n.tide, n.tear = 0.0, min(1.0, max(0.0, -tau) / DISSOLVE_S)

    def _finish(self):
        for key in [k for k, n in self.nodes.items() if n.removing]:
            del self.nodes[key]
        for n in self.nodes.values():
            n.polar0 = n.polar1
            n.fresh = False
            n.form, n.flash, n.tide, n.tear, n.drift_w = 1.0, 0.0, 0.0, 0.0, 1.0
            if n.polar1 is not None:
                a, r = n.polar1
                n.base = QPointF(r * math.cos(a), r * math.sin(a))
            else:
                n.base = QPointF(n.p1)
            n.z, n.opacity = n.z1, n.o1
        self.update()

    def now(self):
        """动画用的时间（秒，从控件建好开始算）。"""
        return self.clock.elapsed() / 1000

    def cine_ease(self):
        """全图 → 展开近景的过渡（平滑过的 0~1）：黑洞的位置大小、星空压暗、其他年份退场、文字淡出都按它走。"""
        c = self.cine
        return c * c * (3 - 2 * c)

    # ---------- 投影：世界坐标（x, y, z）→ 屏幕像素 ----------
    def project(self, x, y, z):
        """透视投影：z 越大越近，看起来越大、离画面中心越远；镜头平移时近的动得多、远的动得少。"""
        k = self.cam_s * FOCAL / (FOCAL - z)
        return (x - self.cam_c.x()) * k + self.width() / 2, (y - self.cam_c.y()) * k + self.height() / 2, k

    def unproject(self, sx, sy):
        return QPointF((sx - self.width() / 2) / self.cam_s + self.cam_c.x(), (sy - self.height() / 2) / self.cam_s + self.cam_c.y())

    def _retreat(self, n):
        """展开时其他年份退到画面外：星体很快淡掉（不然会从变大的黑洞前面划过去），只留它们流进黑洞的物质流。"""
        if n.active or self.cine <= 0:
            return 1.0
        return 1 - smooth(0.0, 0.35, self.cine_ease())

    def _layout_screen(self):
        t = self.now()
        for n in self.nodes.values():
            o = n.offset(t)
            n.sx, n.sy, n.k = self.project(n.base.x() + o.x(), n.base.y() + o.y(), n.z)
        c = self.nodes.get('c')
        if c is not None:
            e = self.cine_ease()
            # 展开的近景：黑洞在后面，跟着鼠标反方向微微移动（视差），前面的恒星和分支不动，看得出前后
            c.sx = lerp(c.sx, self.width() * CINE_X - self._par.x() * self.width() * PARALLAX, e)
            c.sy = lerp(c.sy, self.height() * CINE_Y - self._par.y() * self.width() * PARALLAX * 0.7, e)
            c.rpx = lerp(RS * self.cam_s, self.height() * CINE_SHADOW, e)
            self.bh = (c.sx, c.sy, c.rpx, lerp(EL_MAP, EL_CINE, e), CINE_ROLL * e)
            if e > 0:                           # 展开时其他年份退到屏幕左边外面，只留它们流进黑洞的物质流
                for n in self.nodes.values():
                    if n.kind == 'year' and not n.active:
                        n.sx = lerp(n.sx, -90 - 160 * n.bob[0] / 0.22, e)
                        n.sy = lerp(n.sy, self.height() * (0.06 + 0.88 * n.seed), e)

    # ---------- 镜头 ----------
    def fit(self, animate=True):
        """展开时对准那一支，没展开时看整圈，全部收起时看中心。"""
        vw, vh = max(1, self.width()), max(1, self.height())
        if not self.root_open:
            s, center = 1.0, QPointF(0, 0)
        elif self.branch_rect.isValid():
            # 展开时左上留给黑洞；恒星在它下面（挡在黑洞前面），分支往右下展开，上沿不超过 CINE_TOP（避开吸积盘）。
            # 缩放和恒星位置在排布时已经算好（_cine_layout）
            rect = self.branch_rect
            s, star_sx = self._cine_fit
            top, bottom = vh * CINE_TOP, vh - 16
            h = rect.height() * s
            cy = bottom - h / 2 if h > bottom - top else (top + bottom) / 2      # 放不下时贴住下沿、往上长，不再缩小
            center = QPointF(rect.left() + 60 - (star_sx - vw / 2) / s, rect.center().y() - (cy - vh / 2) / s)
        else:
            R = self.r1 * 1.24 + 90
            s = max(0.4, min(1.25, (vw - 80) / (2 * R), (vh - 110) / (2 * R)))
            center = QPointF(0, 0)
        self._cam0 = (self.cam_s, QPointF(self.cam_c), self.cine)
        self._cam1 = (s, center, self._cine_target())
        if animate:
            self.cam.start(self.now(), CAM_S)
        else:
            self.cam.stop()
            self._cam_step(1.0)
        self.update()

    def _cam_step(self, t):
        """镜头过渡：缩放、看向的位置，连同全图 ↔ 展开的黑洞视角一起走，三者同步。"""
        (s0, c0, k0), (s1, c1, k1) = self._cam0, self._cam1
        self.cam_s = s0 * (s1 / s0) ** t
        self.cam_c = QPointF(lerp(c0.x(), c1.x(), t), lerp(c0.y(), c1.y(), t))
        self.cine = lerp(k0, k1, t)

    def fixed_view(self):
        """展开某一年时是固定视角（黑洞在左边、分支在右边），不能拖动缩放；回到全图才可以。"""
        return self._cine_target() > 0.5

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.fixed_view() and self.doc is not None:
            self.relayout(animate=False)        # 分支的拉长距离跟着窗口宽度变
            self.fit(animate=False)

    def wheelEvent(self, e):
        self._last_input = self.now()
        if self.fixed_view():
            return
        self.cam.stop()
        m = e.position()
        before = self.unproject(m.x(), m.y())
        self.cam_s = max(0.25, min(3.0, self.cam_s * 1.0015 ** e.angleDelta().y()))
        self.cam_c += before - self.unproject(m.x(), m.y())     # 以鼠标位置为中心缩放
        self.update()

    # ---------- 渲染 ----------
    def initializeGL(self):
        self.ctx = moderngl.create_context()
        ctx = self.ctx
        quad = ctx.buffer(np.array([-1, -1, 1, -1, -1, 1, 1, 1], 'f4').tobytes())
        self.p_sky = ctx.program(vertex_shader=QUAD_VS, fragment_shader=SKY_FS)
        self.p_sky_low = ctx.program(vertex_shader=QUAD_VS, fragment_shader=SKY_FS.replace('#version 330', '#version 330\n#define LOW', 1))
        self.v_sky_low = ctx.vertex_array(self.p_sky_low, [(quad, '2f', 'in_pos')])
        self.p_down = ctx.program(vertex_shader=QUAD_VS, fragment_shader=DOWN_FS)
        self.v_sky = ctx.vertex_array(self.p_sky, [(quad, '2f', 'in_pos')])
        self.v_down = ctx.vertex_array(self.p_down, [(quad, '2f', 'in_pos')])
        self.sprites = {}
        for name, fs in (('hole', HOLE_FS), ('star', STAR_FS), ('pill', PILL_FS), ('dust', DUST_FS), ('label', LABEL_FS)):
            prog = ctx.program(vertex_shader=SPRITE_VS, fragment_shader=fs)
            inst = ctx.buffer(reserve=16 * 4 * 256, dynamic=True)
            # 着色器里没用到的变量会被编译器去掉，绑定时要跳过（16x = 空出 16 个字节）
            names = [a for a in ('i_rect', 'i_color', 'i_p1', 'i_p2') if a in prog]
            fmt = ' '.join('4f' if a in prog else '16x' for a in ('i_rect', 'i_color', 'i_p1', 'i_p2')) + '/i'
            vao = ctx.vertex_array(prog, [(quad, '2f', 'in_corner'), (inst, fmt, *names)])
            self.sprites[name] = (prog, inst, vao)
        self.p_beam = ctx.program(vertex_shader=BEAM_VS, fragment_shader=BEAM_FS)
        self.beam_buf = ctx.buffer(reserve=4 * 11 * 6 * BEAM_SEG * 64, dynamic=True)
        self.v_beam = ctx.vertex_array(self.p_beam, [(self.beam_buf, '2f 1f 1f 1f 1f 1f 4f', 'in_pos', 'in_x', 'in_w', 'in_along',
                                                      'in_s', 'in_kind', 'in_color')])
        self.off = {}
        self.atlas = None               # (纹理, 画的分辨率, {节点 key: (签名, uv, 左, 上, 宽, 高)})
        self.parts = ShardSystem(ctx, RS, FOCAL)
        self.stream = StreamSystem(ctx)

    def _offscreen(self, name, w, h):
        """离屏画布（按名字各一块，尺寸变了重建）：main 是超采样的整张图，hole 是按屏幕原分辨率单独画的黑洞。"""
        old = self.off.get(name)
        if old is None or old[1] != (w, h):
            if old is not None:
                old[0].release(); old[2].release()
            tex = self.ctx.texture((w, h), 4)
            tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            self.off[name] = (self.ctx.framebuffer(color_attachments=[tex]), (w, h), tex)
        return self.off[name]

    @staticmethod
    def _set(prog, **u):
        for k, v in u.items():
            m = prog.get(k, None)
            if m is not None:           # 着色器里没用到的变量会被编译器优化掉
                m.value = v

    def _rope_path(self, n, a, dt):
        """父节点 a 到 n 的柔软光丝（屏幕像素）：控制点有惯性。端点（世界坐标）动了，控制点只跟上一部分，
        剩下的靠弹簧追上，所以会晃、会拖。"""
        p1, p2 = a.edge_point(n, True), n.edge_point(a, False)
        dx = (p2[0] - p1[0]) * 0.55
        ideal = ((p1[0] + dx, p1[1]), (p2[0] - dx, p2[1]))
        world = [self.unproject(*q) for q in ideal]
        rope = self._ropes.get(n.key)
        if rope is None:
            rope = self._ropes[n.key] = {'last': world, 'o': [0.0] * 4, 'v': [0.0] * 4}
        o, v = rope['o'], rope['v']
        for i in range(2):
            o[2 * i] -= (world[i].x() - rope['last'][i].x()) * ROPE_LAG
            o[2 * i + 1] -= (world[i].y() - rope['last'][i].y()) * ROPE_LAG
        rope['last'] = world
        lim = 0.3 * math.hypot(p2[0] - p1[0], p2[1] - p1[1]) / max(self.cam_s, 1e-3)    # 最多弯到线长的 30%，不会甩出尖角
        for j in range(4):
            v[j] += (-ROPE_K * o[j] - ROPE_D * v[j]) * dt
            o[j] += v[j] * dt
        for j in (0, 2):
            mag = math.hypot(o[j], o[j + 1])
            if mag > lim:
                o[j] *= lim / mag; o[j + 1] *= lim / mag
        k = self.cam_s
        return bezier(np.array([p1, (ideal[0][0] + o[0] * k, ideal[0][1] + o[1] * k),
                                (ideal[1][0] + o[2] * k, ideal[1][1] + o[3] * k), p2]))

    def _beams(self):
        """分支里的柔软光丝拼成三角形条带（有惯性，节点动时会弯、会拖一点）。恒星到黑洞的物质流是真的粒子，见 stream.py。"""
        now = self.now()
        dt = min(0.05, now - self._rope_t); self._rope_t = now
        paths, cols, kinds, alive = [], [], [], set()
        for n in self.nodes.values():
            a = self.nodes.get(n.parent_key)
            if a is None or a.kind == 'center':
                continue
            op = min(a.opacity, n.opacity) * self.link_fade
            alive.add(n.key)
            if op < 0.02:
                continue
            paths.append(self._rope_path(n, a, dt))
            cols.append((_rgba(a.color), _rgba(n.color), op * 0.9)); kinds.append(1.05 + 0.9 * n.seed)
        for key in [key for key in self._ropes if key not in alive]:
            del self._ropes[key]
        if not paths:
            return 0
        E, S = len(paths), BEAM_SEG
        pts = np.array(paths, 'f4')                                             # (E, S+1, 2)
        seglen = np.linalg.norm(np.diff(pts, axis=1), axis=2)
        along = np.concatenate([np.zeros((E, 1), 'f4'), np.cumsum(seglen, axis=1)], axis=1)
        wid = np.ones((E, S + 1), 'f4')
        hw = np.full((E, S + 1), BEAM_HW, 'f4')                                 # 条带半宽，要盖住柔光
        tan = np.gradient(pts, axis=1)
        tan /= np.linalg.norm(tan, axis=2, keepdims=True) + 1e-6
        nor = np.stack([-tan[..., 1], tan[..., 0]], axis=2) * hw[..., None]
        tf = BEAM_T.astype('f4')[None, :, None]
        c0 = np.array([c[0] for c in cols], 'f4'); c1 = np.array([c[1] for c in cols], 'f4')
        col = c0[:, None, :] + (c1 - c0)[:, None, :] * tf                      # (E, S+1, 4)
        col[..., 3] = np.array([c[2] for c in cols], 'f4')[:, None]
        sv = np.broadcast_to(tf, (E, S + 1, 1))
        kv = np.broadcast_to(np.array(kinds, 'f4')[:, None, None], (E, S + 1, 1))
        left, right = pts - nor, pts + nor

        def vert(side, sign, i):
            return np.concatenate([side[:, i], sign * hw[:, i, None], wid[:, i, None], along[:, i, None], sv[:, i], kv[:, i],
                                   col[:, i]], axis=2)
        a, b = slice(0, S), slice(1, S + 1)
        A, B, C, D = vert(left, -1, a), vert(right, 1, a), vert(left, -1, b), vert(right, 1, b)
        data = np.stack([A, B, C, B, D, C], axis=2).astype('f4').tobytes()     # (E, S, 6, 11)
        if len(data) > self.beam_buf.size:
            self.beam_buf.orphan(len(data) * 2)
        self.beam_buf.write(data)
        return E * S * 6

    def paintGL(self):
        if self.ctx is None or self.doc is None:
            return
        ctx = self.ctx
        dpr = self.devicePixelRatioF()
        vw, vh = self.width(), self.height()
        ss = min(SS, MAX_TEX / max(1, vw * dpr), MAX_TEX / max(1, vh * dpr))
        W, H = max(1, int(vw * dpr * ss)), max(1, int(vh * dpr * ss))
        fbo, _, tex = self._offscreen('main', W, H)
        t = self.now()
        if self._pending:
            self._run_pending()
        self._advance(t)
        self._layout_screen()

        fbo.use(); ctx.viewport = (0, 0, W, H)
        ctx.disable(moderngl.BLEND | moderngl.DEPTH_TEST | moderngl.CULL_FACE)
        self._draw_sky(fbo, W, H, dpr, t)
        ctx.enable(moderngl.BLEND)
        holes, stars, pills = self._node_sprites(t)
        # 顺序：黑洞 → 连线（加色，叠在盘上汇进去）→ 恒星 → 胶囊 → 晶尘、碎片 → 文字
        if holes:
            self._draw_hole(holes, fbo, W, H, dpr, t)
        self._draw_stream(vw, vh, t)
        nv = self._beams()
        if nv:
            ctx.blend_func = moderngl.ONE, moderngl.ONE
            self._set(self.p_beam, u_vp=(vw, vh), u_time=t)
            self.v_beam.render(moderngl.TRIANGLES, vertices=nv)
        if stars:
            self._draw('star', np.array(stars, 'f4'), False, vw, vh, t)
        if pills:
            self._draw('pill', np.array(pills, 'f4'), False, vw, vh, t)
        self._draw_particles(vw, vh, t)
        labels = self._label_instances(dpr * ss)
        if len(labels):
            self.atlas[0].use(0)
            self._draw('label', labels, False, vw, vh, t, u_atlas=0)

        # 缩小到屏幕（超采样）
        screen = ctx.detect_framebuffer(self.defaultFramebufferObject())
        screen.use(); ctx.viewport = (0, 0, int(vw * dpr), int(vh * dpr))
        ctx.disable(moderngl.BLEND)
        tex.use(0)
        self._set(self.p_down, u_tex=0, u_keep=0.0)
        self.v_down.render(moderngl.TRIANGLE_STRIP)
        # 把显卡状态复原，免得影响 Qt 自己合成窗口
        f = self.context().extraFunctions()
        f.glBindVertexArray(0); f.glUseProgram(0); f.glBindBuffer(0x8892, 0)
        f.glActiveTexture(0x84C0); f.glBindTexture(0x0DE1, 0)         # GL_TEXTURE0、GL_TEXTURE_2D
        f.glBindSampler(0, 0)
        f.glPixelStorei(0x0CF5, 4); f.glPixelStorei(0x0D05, 4)        # 解包 / 打包对齐恢复默认

    def _draw_sky(self, fbo, W, H, dpr, t):
        """背景分两遍：柔和的银河、星云按屏幕一半的分辨率画，再按超采样分辨率叠上锐利的星星。"""
        ctx = self.ctx
        vw, vh = self.width(), self.height()
        e = self.cine_ease()
        gt = t - self._gulp_t
        sky = dict(u_vp=(vw, vh), u_time=t, u_bh=self.bh[:3], u_cine=e, u_ripple=(gt, 1.0 if 0 <= gt < 1.8 else 0.0),
                   u_pan=(self.cam_c.x() * self.cam_s - self._par.x() * vw * 0.4 * e,
                          self.cam_c.y() * self.cam_s - self._par.y() * vh * 0.4 * e))
        lw, lh = max(1, int(vw * dpr / 2)), max(1, int(vh * dpr / 2))
        lfbo, _, ltex = self._offscreen('sky', lw, lh)
        lfbo.use(); ctx.viewport = (0, 0, lw, lh)
        self._set(self.p_sky_low, **sky)
        self.v_sky_low.render(moderngl.TRIANGLE_STRIP)
        fbo.use(); ctx.viewport = (0, 0, W, H)
        ltex.use(0)
        self._set(self.p_sky, u_low=0, **sky)
        self.v_sky.render(moderngl.TRIANGLE_STRIP)

    def _node_sprites(self, t):
        """这一帧要画的黑洞、恒星、胶囊（每个一行实例参数，格式见各自的着色器）。"""
        holes, stars, pills = [], [], []
        for n in self.nodes.values():
            if n.opacity < 0.01:
                continue
            gl = max(n.glow, 1.0 if n.active else 0.0)
            if n.kind == 'center':
                if self.parts is not None:              # 碎片正往里掉得越多越亮
                    gl = max(gl, self.parts.near_hole(t))
                ft = t - self._gulp_t                   # 吞完后慢慢暗回去
                if ft >= 0:
                    gl = max(gl, 1 - smooth(0.0, 1.2, ft))
                rs_px = n.rpx / 2.6                     # 看到的阴影比视界大 2.6 倍（光线被弯过来）
                half = rs_px * 11
                holes.append((n.sx, n.sy, half, half) + _rgba(n.color) + (rs_px, gl, n.opacity, half,
                                                                         self.bh[3], self.bh[4], self.cine_ease(), 0))
            elif n.kind == 'year':
                R = STAR_R * n.k * (1 + 0.12 * n.glow + STAR_ACTIVE * n.active) * (0.2 + 0.8 * n.form)
                R *= (1 + 0.15 * n.flash) * (1 + 0.15 * n.tide)     # 被拉长时精灵要放大一点，不然拉长的那头会被方框切掉
                bright = 0.75 + 0.25 * max(-1, min(1, n.z / 140))
                # 朝向：平时指向黑洞（潮汐拉出的那一侧），被吞时是运动方向
                ang = n.dang if n.removing else math.atan2(self.bh[1] - n.sy, self.bh[0] - n.sx)
                stars.append((n.sx, n.sy, R * 5, R * 5) + _rgba(n.color, n.tide) + (R, n.glow + 3 * n.flash, n.opacity * self._retreat(n), 1.0 if n.active else 0.0,
                                                                                 n.seed, bright, n.tear, ang))
            else:
                k = n.k * (1 + 0.06 * n.glow)
                hw, hh = n.w / 2 * k, n.h / 2 * k
                cx, cy = n.screen_center().x(), n.sy
                par = self.nodes.get(n.parent_key)
                lx, ly = ((par.sx - cx), (par.sy - cy)) if par else (-1, 0)
                ln = math.hypot(lx, ly) or 1
                pills.append((cx, cy, hw + 30, hh + 30) + _rgba(n.color) + (hw, hh, gl, n.opacity,
                                                                         lx / ln, ly / ln, n.seed, 2.0 if n.kind == 'add' else 0.0))
        return holes, stars, pills

    def _draw_stream(self, vw, vh, t):
        """物质流：把每颗恒星的位置换算成以黑洞为中心、视界半径为单位的坐标交给显卡，粒子在那边模拟、画出来。"""
        if self.stream is None:
            return
        bx, by, shadow, el, roll = self.bh
        rs_px = max(shadow / 2.6, 1e-3)                 # 看到的阴影是视界的 2.6 倍
        cr, sr = math.cos(roll), math.sin(roll)
        stars = self.stream.stars
        stars[:, 3] = 0.0                               # 不在了的恒星：不再往外喷，已经在路上的粒子照样流进去
        colors = np.zeros((MAX_STARS, 4), 'f4'); colors[:, 3] = 1.0
        slot = {y: i for i, y in enumerate(sorted(self.doc['years'])[:MAX_STARS])}
        for n in self.nodes.values():
            i = slot.get(n.data) if n.kind == 'year' else None
            if i is None:
                continue
            dx, dy = (n.sx - bx) / rs_px, (n.sy - by) / rs_px
            stars[i, 0], stars[i, 1] = cr * dx - sr * dy, -(sr * dx + cr * dy)     # 去掉滚转，y 朝上
            stars[i, 2] = STAR_R * n.k * n.grown() / rs_px
            stars[i, 3] = 1.0 if (not n.shattered and n.form > 0.9 and n.opacity > 0.5) else 0.0
            colors[i] = _rgba(n.color, 1.0 if (n.active or n.glow > 0.3) else 0.62)
        self.stream.update(self._frame_dt, stars, self.cine_ease(), el, rs_px)
        self.stream.draw(vw, vh, (bx, by), rs_px, roll, colors, self.link_fade, _rgba(DISK_COLOR)[:3], t)

    def _draw_hole(self, holes, fbo, W, H, dpr, t):
        """黑洞逐像素追光线很费显卡，而且画面本身很柔和：按屏幕原分辨率单独画（像素少 4 倍），再放大叠进超采样画布。"""
        ctx = self.ctx
        vw, vh = self.width(), self.height()
        hw_, hh_ = max(1, int(vw * dpr)), max(1, int(vh * dpr))
        hfbo, _, htex = self._offscreen('hole', hw_, hh_)
        hfbo.use(); ctx.viewport = (0, 0, hw_, hh_); hfbo.clear(0.0, 0.0, 0.0, 0.0)
        self._draw('hole', np.array(holes, 'f4'), False, vw, vh, t)
        fbo.use(); ctx.viewport = (0, 0, W, H)
        htex.use(0)
        ctx.blend_func = moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA
        self._set(self.p_down, u_tex=0, u_keep=1.0)
        self.v_down.render(moderngl.TRIANGLE_STRIP)

    def _draw_particles(self, vw, vh, t):
        """胶囊碎成的晶尘（CPU 上算，很少），恒星的碎片（显卡上按记下的路线画，收起正着放、展开倒着放）。"""
        if len(self.dust):
            d = self.dust
            sx = (d[:, 0] - self.cam_c.x()) * self.cam_s + vw / 2
            sy = (d[:, 1] - self.cam_c.y()) * self.cam_s + vh / 2
            size = np.maximum(0.6, d[:, 6] * min(1.6, self.cam_s))
            z = np.zeros_like(sx)
            self._draw('dust', np.column_stack([sx, sy, size * 5, size * 5, d[:, 7:10], z + 1, size, (d[:, 4] / d[:, 5]) ** 0.7,
                                                d[:, 10], z, z, z, z, z]), True, vw, vh, t)
        if self.parts is not None:
            self.parts.draw(t, vw, vh, self.cam_c, self.cam_s, self.bh[:3])

    def _draw(self, name, inst, additive, vw, vh, t, **uniforms):
        """一次画一批同种精灵（每行一个实例的参数）。additive：加色混合（发光的粒子），否则按预乘透明度叠上去。"""
        prog, buf, vao = self.sprites[name]
        data = inst.astype('f4').tobytes()
        if len(data) > buf.size:
            buf.orphan(len(data) * 2)
        buf.write(data)
        self.ctx.blend_func = (moderngl.ONE, moderngl.ONE) if additive else (moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA)
        self._set(prog, u_vp=(vw, vh), u_time=t, **uniforms)
        vao.render(moderngl.TRIANGLE_STRIP, instances=len(inst))

    # ---------- 文字 ----------
    def _label_ops(self, n):
        """节点上要写的字：[(框, 对齐, 文字, 字体, 颜色)]，坐标相对锚点、缩放前。随悬停、展开变的亮度不画进来，画的时候再乘。"""
        k = n.kind
        if k == 'center':
            return [(QRectF(-100, 0, 200, 24), Qt.AlignCenter, n.text, font(17, True), QColor(255, 236, 210)),
                    (QRectF(-100, 24, 200, 18), Qt.AlignCenter, n.sub, font(12), QColor(255, 210, 170, 170))]
        if k == 'year':
            f = font(17, True, DIGITS)
            tw = QFontMetricsF(f).horizontalAdvance(n.text)
            sub = n.sub if n.active else ''             # 作品数量只在展开那一年显示
            sw = QFontMetricsF(font(12, False, DIGITS)).horizontalAdvance(sub) + 6 if sub else 0
            x0 = -(tw + sw) / 2
            ops = [(QRectF(x0, 0, tw + 2, 22), Qt.AlignLeft | Qt.AlignVCenter, n.text, f, QColor(255, 255, 255))]
            if sub:
                c = QColor(n.color); c.setAlpha(230)
                ops.append((QRectF(x0 + tw + 6, 2, sw, 22), Qt.AlignLeft | Qt.AlignVCenter, sub, font(12, False, DIGITS), c))
            return ops
        r = QRectF(-n.w / 2, -n.h / 2, n.w, n.h)
        if k == 'add':
            c = QColor(n.color); c.setAlpha(230)
            return [(r.adjusted(0, -2, 0, -2), Qt.AlignCenter, '+', font(18), c)]
        if k == 'cat':
            tr = r.adjusted(16, 0, -16, 0)
            ops = [(tr, Qt.AlignLeft | Qt.AlignVCenter, n.text, font(14, True), QColor(255, 255, 255))]
            if n.sub:
                ops.append((tr, Qt.AlignRight | Qt.AlignVCenter, n.sub, font(13, False, DIGITS), n.color.lighter(115)))
            return ops
        tr = r.adjusted(13, 0, -13, 0)
        text = QFontMetricsF(font(13)).elidedText(n.text, Qt.ElideRight, tr.width() + 1)
        return [(tr, Qt.AlignLeft | Qt.AlignVCenter, text, font(13), QColor(255, 255, 255))]

    def _build_atlas(self, res, sigs):
        """把所有标签按分辨率 res 画进一张图集，一行行排开，四周留空免得多级纹理互相渗色。"""
        PAD, W = 6, 2048
        boxes, ops_all, x, y, row = {}, {}, PAD, PAD, 0
        for key in sigs:
            ops = ops_all[key] = self._label_ops(self.nodes[key])
            box = ops[0][0]
            for o in ops[1:]:
                box = box.united(o[0])
            box = box.adjusted(-2, -2, 2, 2)
            pw, ph = math.ceil(box.width() * res), math.ceil(box.height() * res)
            if x + pw + PAD > W:
                x, y, row = PAD, y + row + PAD, 0
            boxes[key] = (box, x, y, pw, ph)
            x += pw + PAD; row = max(row, ph)
        H = y + row + PAD
        img = QImage(W, H, QImage.Format_RGBA8888_Premultiplied); img.fill(0)
        p = QPainter(img)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        uvs = {}
        for key, (box, x, y, pw, ph) in boxes.items():
            p.save()
            p.translate(x, y); p.scale(res, res); p.translate(-box.left(), -box.top())
            for rect, align, text, f, color in ops_all[key]:
                p.setFont(f); p.setPen(color)
                p.drawText(rect, align, text)
            p.restore()
            # 在图集里的位置（0~1），以及按整像素取过整的逻辑尺寸，保证画出来和图集 1:1
            uvs[key] = (sigs[key], (x / W, y / H, (x + pw) / W, (y + ph) / H), box.left(), box.top(), pw / res, ph / res)
        p.end()
        if self.atlas is not None:
            self.atlas[0].release()
        tex = self.ctx.texture((W, H), 4, bytes(img.constBits()))
        tex.build_mipmaps()
        tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
        self.atlas = (tex, res, uvs)

    def _label_instances(self, res):
        """这一帧所有文字的实例参数；标签内容变了（换年份、改名字、展开）才重画图集。"""
        items = []
        e = self.cine_ease()
        for n in self.nodes.values():
            if n.opacity < 0.05:
                continue
            if n.kind == 'center':
                if e > 0.95:
                    continue
                alpha = n.opacity * (1 - e)                     # 展开时黑洞变成背景，名字淡掉
                below = max(n.rpx * 1.5, n.rpx / 2.6 * DISK_OUT * math.sin(self.bh[3]) + 8)    # 放在吸积盘下面
                ax, ay, k = n.sx, n.sy + below, n.k
            elif n.kind == 'year':
                alpha = n.opacity * self._retreat(n) * (200 + 35 * max(float(n.active), n.glow)) / 255
                alpha *= 1 - smooth(0.0, 0.4, n.tear)       # 星体化开时年份跟着淡掉，别比星体留得久（残影）
                ax, ay, k = n.sx, n.sy + STAR_R * 1.3 * n.k * n.grown(), n.k
            else:
                k = n.k * (1 + 0.06 * n.glow)
                if k < 0.05:
                    continue
                alpha = n.opacity * ((228 + 27 * n.glow) / 255 if n.kind == 'work' else 1.0)
                ax, ay = n.screen_center().x(), n.sy
            items.append((n, alpha, ax, ay, k))
        sigs = {n.key: (n.kind, n.text, n.sub, n.active, n.color.rgb(), n.w) for n, *_ in items}
        at = self.atlas
        if at is None or at[1] != res or any(key not in at[2] or at[2][key][0] != sig for key, sig in sigs.items()):
            self._build_atlas(res, sigs)
        uvs = self.atlas[2]
        out = np.empty((len(items), 16), 'f4')
        for i, (n, alpha, ax, ay, k) in enumerate(items):
            _, uv, ox, oy, lw, lh = uvs[n.key]
            hw, hh = lw / 2 * k, lh / 2 * k
            out[i] = (ax + (ox + lw / 2) * k, ay + (oy + lh / 2) * k, hw, hh) + uv + (alpha, hw, hh, 0, 0, 0, 0, 0)
        return out

    # ---------- 每一帧 ----------
    def _advance(self, now):
        """每帧画之前推进所有会动的东西（按真实时间，和屏幕刷新同步）。"""
        raw_dt = min(0.25, max(0.0, now - self._last_t))
        self._frame_dt = raw_dt
        dt = min(0.05, raw_dt); self._last_t = now
        if self.anim.running:
            raw = self.anim.raw(now)
            self._step(raw)
            if raw >= 1.0:
                self.anim.stop()
                self._finish()
        if self.cam.running:
            raw = self.cam.raw(now)
            self._cam_step(ease_spring(raw))
            if raw >= 1.0:
                self.cam.stop()
        else:                                   # 镜头动画被拖动、缩放打断时，视角自己慢慢过渡完
            want = self._cine_target()
            if self.cine != want:
                self.cine += (want - self.cine) * min(1.0, dt * 4.0)
                if abs(self.cine - want) < 0.002:
                    self.cine = want
        # 视差：鼠标位置平滑跟随（移出窗口时回到中间）
        want = QPointF(0, 0)
        if self._mouse_pos is not None:
            want = QPointF(max(-1.0, min(1.0, self._mouse_pos.x() / max(1, self.width()) * 2 - 1)),
                           max(-1.0, min(1.0, self._mouse_pos.y() / max(1, self.height()) * 2 - 1)))
        self._par += (want - self._par) * min(1.0, dt * 2.5)
        # 连线：东西在飞、镜头在转时先藏起来（快速），快停稳时就淡入
        hide = ((self.anim.running and self._anim_moving and self.anim.raw(now) < 0.7) or
                (self.cam.running and self.cam.raw(now) < 0.7) or
                (not self.cam.running and abs(self.cine - self._cine_target()) > 0.05) or
                any(n.fresh and n.kind == 'year' for n in self.nodes.values()))    # 新恒星还没凝结好：物质流等它成形再出现
        self.link_fade = fade_link(self.link_fade, hide, dt)
        dg = self._drag
        if dg is not None and dt > 0 and 'target' in dg:
            # 拖着的恒星：弹簧带着它跟光标走（像扰动的气泡一样慢半拍），松手后停稳了再存位置
            d = dg['target'] - dg['pos']
            dg['vel'] += (d * DRAG_K - dg['vel'] * DRAG_D) * dt
            step = dg['vel'] * dt
            dg['pos'] += step
            n = dg['n']
            n.base += QPointF(step.x() / n.k, step.y() / n.k)
            n.polar1 = n.polar0 = (math.atan2(n.base.y(), n.base.x()), math.hypot(n.base.x(), n.base.y()))
            if dg['released'] and abs(d.x()) + abs(d.y()) < 0.5 and abs(dg['vel'].x()) + abs(dg['vel'].y()) < 3:
                self._drag = None
                self._save_star(n)
        if hide:
            self._stream_dirty = True           # 换了视角：物质流等连线重新出现时从头来（快进一段）
        elif self._stream_dirty and self.stream is not None:
            self._stream_dirty = False
            # 展开（进近景、恒星重新放出来）时物质流从恒星往黑洞长过去；回到全图时一出现就是完整的
            self.stream.reset(grow=self._stream_grow or self.expanded is not None)
            self._stream_grow = False
        for n in self.nodes.values():
            # 鼠标扰动：弹簧把节点拉回原位，阻尼接近临界，像在水里一样慢慢漂回去
            m = MASS.get(n.kind, 1.0)
            for i in (0, 1):
                if n.d[i] or n.v[i]:
                    n.v[i] += (-SPRING * n.d[i] - DAMP * math.sqrt(m) * n.v[i]) / m * dt
                    n.d[i] = max(-MAX_PUSH, min(MAX_PUSH, n.d[i] + n.v[i] * dt))
                    if abs(n.d[i]) < 0.03 and abs(n.v[i]) < 0.03:
                        n.d[i] = n.v[i] = 0.0
            # 悬停亮度慢慢过渡
            want = 1.0 if n.hover else 0.0
            if n.glow != want:
                n.glow += (want - n.glow) * min(1.0, dt * 9)
                if abs(n.glow - want) <= 0.005:
                    n.glow = want
        self._busy = (self.anim.running or self.cam.running or 0.0 < self.link_fade < 1.0 or now - self._last_input < IDLE_AFTER
                      or self.cine != self._cine_target() or self._drag is not None or len(self.dust) > 0 or now - self._gulp_t < 1.8
                      or (self.parts is not None and self.parts.active(now))
                      or any(n.v[0] or n.v[1] or n.glow != (1.0 if n.hover else 0.0)
                             for n in self.nodes.values()))
        self._advance_particles(now, raw_dt)

    def _advance_particles(self, now, raw_dt):
        """胶囊的晶尘按真实经过的时间往前走；恒星碎片的路线早就算好了，这里只清掉放完的。"""
        if self.parts is not None:
            self.parts.tidy(now)
        if len(self.dust):                      # 晶尘：慢慢飘散、减速，寿命到了就去掉（按真实经过的时间）
            d = self.dust
            d[:, 0:2] += d[:, 2:4] * raw_dt
            d[:, 2:4] *= math.exp(-2.6 * raw_dt)
            d[:, 4] -= raw_dt
            self.dust = d[d[:, 4] > 0]

    def _next_frame(self):
        if self.isVisible() and not self.window().isMinimized():
            if not self._busy:
                self._delay.start(IDLE_WAIT_MS)
                return
            # Qt 的显卡控件画完一帧后会让 CPU 空转等屏幕刷新（和画面大小无关，空白控件也占满一个核心）。
            # 所以掐着时间：上一帧开始后差不多一个刷新周期再开始画，几乎不用等，CPU 从约 100% 降到约 30%
            wait = 1 / MAX_FPS - FRAME_MARGIN - (self.now() - self._last_t)
            if wait > 0:
                self._delay.start(max(1, round(wait * 1000)))
            else:
                self.update()

    def _kick(self):
        """看门狗：窗口从最小化恢复等情况下帧循环断了，重新启动。"""
        if self.now() - self._last_t > 0.2:
            self._next_frame()

    def showEvent(self, e):
        super().showEvent(e)
        self.watchdog.start()
        self.update()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.watchdog.stop()

    def push(self, x, y):
        """鼠标划过（屏幕像素）：附近的节点被顺着鼠标的方向带一下——靠近时被推开，离开时被拉着跟过去一点（来拒去留）。"""
        now = self.now()
        mvx = mvy = dt = 0.0
        if self._mouse is not None:
            dt = min(0.05, max(0.004, now - self._mouse[2]))
            mvx, mvy = (x - self._mouse[0]) / dt, (y - self._mouse[1]) / dt
            sp = math.hypot(mvx, mvy)
            if sp > 1400:
                mvx, mvy = mvx * 1400 / sp, mvy * 1400 / sp
        self._mouse = (x, y, now)
        if not dt:
            return
        speed = min(1.0, math.hypot(mvx, mvy) / 300)
        for n in self.nodes.values():
            if n.removing or n.opacity < 0.3:
                continue
            c = n.screen_center()
            dx, dy = c.x() - x, c.y() - y
            half_w = 0 if n.round() else (n.w - n.h) / 2 * n.k
            ex = max(0.0, abs(dx) - half_w)                    # 胶囊按离边的距离算
            dist = max(0.0, math.hypot(ex, dy) - n.h / 2 * n.k)
            if dist >= PUSH_R:
                continue
            f = (1 - dist / PUSH_R) ** 2 * dt / max(0.3, n.k) / MASS.get(n.kind, 1.0)  # 屏幕上的力换算成世界坐标
            norm = math.hypot(dx, dy) or 1
            n.v[0] += (mvx * PUSH_DRAG + dx / norm * PUSH_AWAY * speed) * f
            n.v[1] += (mvy * PUSH_DRAG + dy / norm * PUSH_AWAY * speed) * f

    # ---------- 鼠标 ----------
    def node_at(self, pos):
        best = None
        for n in self.nodes.values():
            if not n.removing and n.opacity > 0.3 and n.hit(pos.x(), pos.y()):
                if best is None or n.kind in ('work', 'cat', 'add') or (n.kind == 'year' and best.kind == 'center'):
                    best = n                    # 胶囊在最上层，恒星在黑洞前面
        return best

    def _set_hover(self, n):
        if n is self.hovered:
            return
        if self.hovered is not None:
            self.hovered.hover = False
        self.hovered = n
        self.popup.hide(); self.pop_timer.stop()
        if n is not None:
            n.hover = True
            if n.kind == 'work':
                self.pop_timer.start()
        self.setCursor(Qt.PointingHandCursor if n is not None else Qt.OpenHandCursor)

    def _show_popup(self):
        n = self.hovered
        if n is not None and n.kind == 'work' and not (self._press and self._press[1]):
            self.popup.show_for(n.data, n.color, QCursor.pos())

    def mousePressEvent(self, e):
        self._last_input = self.now()
        self.cam.stop()
        self.popup.hide(); self.pop_timer.stop()
        if e.button() == Qt.LeftButton:
            self._press = (e.position(), False, QPointF(self.cam_c))
            n = self.node_at(e.position())
            # 全图里按住恒星：拖的是这颗恒星，不是整个画面
            self._drag_star = n if (n is not None and n.kind == 'year' and not self.fixed_view()) else None

    def mouseMoveEvent(self, e):
        self._last_input = self.now()
        pos = e.position()
        self._mouse_pos = QPointF(pos)
        if self._press:
            d = pos - self._press[0]
            if not self._press[1] and abs(d.x()) + abs(d.y()) > 5 and not self.fixed_view():
                self._press = (self._press[0], True, self._press[2])     # 在拖动画布
                self.setCursor(Qt.ClosedHandCursor)
                self._set_hover(None)
            if self._press[1] and self._drag_star is not None:
                n = self._drag_star
                dg = self._drag
                if dg is None or dg['n'] is not n or dg['released']:     # 刚开始拖：记下恒星和光标的相对位置
                    if dg is not None and dg['n'] is not n:
                        self._save_star(dg['n'])                        # 上一颗还没停稳就去拖别的：先存好
                    p0 = QPointF(n.sx, n.sy)
                    vel = dg['vel'] if dg is not None and dg['n'] is n else QPointF()
                    dg = self._drag = dict(n=n, pos=p0, vel=vel, grab=self._press[0] - p0, released=False)
                dg['target'] = pos - dg['grab']
                self._mouse = None
                self.update()
                return
            if self._press[1]:
                self.cam_c = self._press[2] - d / self.cam_s
                self._mouse = None
                self.update()
                return
        self._set_hover(self.node_at(pos))
        self.push(pos.x(), pos.y())

    def mouseReleaseEvent(self, e):
        press, self._press = self._press, None
        star, self._drag_star = self._drag_star, None
        if star is not None and press and press[1]:
            if self._drag is not None:
                self._drag['released'] = True           # 等它停稳了再存（见 _advance）
            else:
                self._save_star(star)
            self._set_hover(self.node_at(e.position()))
            return
        if self._dbl:
            self._dbl = False
            return
        if e.button() == Qt.LeftButton and press and not press[1]:
            self.click(self.node_at(e.position()))
        self._set_hover(self.node_at(e.position()))

    def mouseDoubleClickEvent(self, e):
        self._dbl = True
        if e.button() == Qt.LeftButton and self.node_at(e.position()) is None:
            self.fit()

    def leaveEvent(self, e):
        self._mouse_pos = None
        self._set_hover(None)
        self._mouse = None
        super().leaveEvent(e)

    def _save_star(self, n):
        """把拖过的恒星位置存成相对自动位置的偏移（换算到没转动前的坐标，展开时整体转动也不会乱）。"""
        a, rr, _ = star_layout(sorted(self.doc['years']), self.doc.get('layout_seed'))[n.data]
        c, s_ = math.cos(-self.phi), math.sin(-self.phi)
        bx, by = n.base.x() * c - n.base.y() * s_, n.base.x() * s_ + n.base.y() * c
        self.doc.setdefault('star_pos', {})[str(n.data)] = [round(bx - rr * math.cos(a), 1), round(by - rr * math.sin(a), 1)]
        self.layoutChanged.emit()

    def reset_star(self, year):
        self.doc.get('star_pos', {}).pop(str(year), None)
        self.layoutChanged.emit()
        self.relayout()

    def busy_animating(self):
        """收起、展开的动画还没结束（包括碎片还在往黑洞里落）：这时点年份、分类、黑洞都不理，免得收放叠在一起。"""
        return self.anim.running or (self.parts is not None and self.parts.active(self.now(), forward=True)) or \
            self.now() < self._gulp_t + 0.3 or \
            any(n.fresh for n in self.nodes.values())

    def click(self, n):
        if n is None:
            return
        k = n.kind
        if k in ('center', 'year', 'cat') and self.busy_animating():
            return
        if k == 'center':
            self.toggle_root()
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
        n = self.node_at(QPointF(e.pos()))
        self._set_hover(None)
        menu = RoundMenu(parent=self)

        def add(icon, text, fn):
            a = Action(icon, text, self); a.triggered.connect(fn); menu.addAction(a)
        if n is None or n.kind == 'center':
            add(FIF.UP if self.root_open else FIF.DOWN, '收起全部' if self.root_open else '展开全部', self.toggle_root)
            add(FIF.ADD, '添加年份', self.addYear.emit)
            if self.root_open:
                add(FIF.SYNC, '重新排布恒星', self.rearrange)
            add(FIF.FULL_SCREEN, '回到全图', self.collapse)
        elif n.kind == 'year':
            add(FIF.ADD, f'在 {n.data} 年添加作品', lambda: self.addWork.emit(n.data, ''))
            if str(n.data) in self.doc.get('star_pos', {}):
                add(FIF.HISTORY, '恢复自动位置', lambda: self.reset_star(n.data))
            add(FIF.SYNC, '重新排布恒星', self.rearrange)
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
