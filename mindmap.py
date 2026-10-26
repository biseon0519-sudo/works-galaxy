# 宇宙风放射状导图（显卡渲染）：中心黑洞 → 一圈年份恒星 → 展开的那一年转到右边，伸出分类 → 作品（发光胶囊）。
# 画面全部由显卡着色器画（moderngl）：内部按 2 倍分辨率渲染再缩小（超采样，1080p 屏上相当于按 4K 画），文字最后用 QPainter 叠上去保持清晰。
# 位置按三维存（x, y, z），用透视投影画到屏幕上：远的小一点、暗一点，拖动时移动得慢一点。鼠标扰动和漂浮只在 x、y 平面上。
import math, random, sys
import numpy as np
import moderngl
from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QTimer, QElapsedTimer
from PySide6.QtGui import (QColor, QPainter, QPainterPath, QPixmap, QImage, QImageReader, QFont, QFontMetricsF, QPen,
                           QLinearGradient, QCursor, QGuiApplication, QSurfaceFormat)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QWidget
from qfluentwidgets import RoundMenu, Action, FluentIcon as FIF
import store
from widgets import cover_pixmap, draw_stars

if sys.platform == 'win32':        # Windows 默认定时器精度 15.6 毫秒，掐帧时间要 1 毫秒精度
    import ctypes
    ctypes.windll.winmm.timeBeginPeriod(1)

FONT, DIGITS = 'Microsoft YaHei UI', 'Bahnschrift'      # 数字用 Bahnschrift（Windows 自带的窄体），更有科技感
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
ANIM_S, BIRTH_S, CAM_S = 1.1, 1.5, 1.1     # 动画时长（秒）：普通移动、展开时恒星重建、镜头
# 收起（艺术化处理）：恒星先被黑洞吸过去一段、越来越快，然后像水晶胶囊一样清脆地碎开（亮一下、迸开一点点就停住），
# 碎片再一边往里落一边顺着盘转一点被吸进去，快慢各不相同；最后一批进去时黑洞亮一下、荡开一圈涟漪
ATTRACT_S = 0.55          # 被吸过去的时长（之后碎开）
ATTRACT_D = 0.35          # 碎开前已经被吸过去的距离比例
SWALLOW_S = ATTRACT_S + 0.35          # 恒星本体的动画时长（每颗恒星碎开的时间错开一点）
SHARD_N = 70              # 每颗恒星碎成多少片
GULP_S = 1.25             # 碎开后多久碎片基本都进去了（黑洞亮一下、荡开涟漪）
# 展开：水晶碎片从黑洞里旋出来，飞到各自恒星的位置汇合，恒星亮一下、清脆地凝结出来
BIRTH_N = 70
FORM_AT = 0.72            # 展开动画进行到多少时恒星凝结（碎片大多到了）
ROPE_LAG, ROPE_K, ROPE_D = 0.5, 22.0, 6.0     # 分支光丝的惯性：端点动时控制点只跟上一部分，再靠弹簧追上
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


def font(px, bold=False, family=FONT):
    f = QFont(family); f.setPixelSize(px); f.setBold(bold)
    return f


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


# ---------- 悬停卡片的辉光（CPU 上算一次缓存） ----------
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


# ---------- 着色器 ----------
NOISE = '''
float hash(vec2 p){ p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
float noise(vec2 p){ vec2 i = floor(p), f = fract(p); vec2 u = f * f * (3. - 2. * f);
    return mix(mix(hash(i), hash(i + vec2(1, 0)), u.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), u.x), u.y); }
float fbm(vec2 p){ float v = 0., a = .5; for (int i = 0; i < 5; i++){ v += a * noise(p); p = p * 2.03 + vec2(1.7, 9.2); a *= .5; } return v; }
'''

QUAD_VS = '''
#version 330
in vec2 in_pos; out vec2 v_uv;
void main(){ v_uv = in_pos * 0.5 + 0.5; gl_Position = vec4(in_pos, 0, 1); }
'''

# 背景：深蓝渐变 + 银河 + 缓慢流动的星云 + 几层视差星星（会闪），黑洞周围的星空被引力弯成光环。
# 分两遍画：柔和的部分（渐变、银河、星云，噪声很多、最费显卡）定义 LOW，按屏幕一半的分辨率画进一张图，
# 银河里星星的疏密放在透明度通道里；第二遍按超采样分辨率读这张图，只画锐利的星星
SKY_FS = '''
#version 330
uniform vec2 u_vp;        // 逻辑视口尺寸（像素）
uniform sampler2D u_low;  // 第一遍画好的柔和部分
uniform vec2 u_ripple;    // 黑洞吞完后荡开的一圈涟漪：已过的时间（秒）、强度
uniform float u_cine;     // 0 = 全图，1 = 展开的近景
uniform vec2 u_pan;       // 镜头平移（屏幕像素），给星空做视差
uniform float u_time;
uniform vec3 u_bh;        // 黑洞在屏幕上的位置和视界半径（像素）
in vec2 v_uv; out vec4 f;
''' + NOISE + '''
vec3 stars(vec2 p, float cell, float density, float size){
    vec2 g = floor(p / cell), q = p / cell - g;
    float h = hash(g);
    if (h > density) return vec3(0);
    vec2 c = vec2(0.2) + 0.6 * vec2(hash(g + 3.1), hash(g + 7.7));
    float d = length((q - c) * cell);
    float tw = 0.6 + 0.4 * sin(u_time * (0.5 + 2.0 * hash(g + 1.3)) + 6.28 * hash(g + 5.0));
    float b = exp(-d * d / (size * size)) * tw * (0.35 + 0.65 * hash(g + 9.0));
    return mix(vec3(0.72, 0.82, 1.0), vec3(1.0, 0.88, 0.78), hash(g + 2.2)) * b;
}
void main(){
    vec2 px = vec2(v_uv.x, 1.0 - v_uv.y) * u_vp;
    if (u_ripple.y > 0.0){    // 涟漪：一圈往外扩的空间扭曲，扩散中慢慢消失
        vec2 rd = px - u_bh.xy; float r0 = max(length(rd), 1.0);
        float R = u_bh.z * 1.3 + u_ripple.x * 520.0;
        px -= rd / r0 * 14.0 * u_ripple.y * exp(-pow((r0 - R) / 38.0, 2.0)) * (1.0 - smoothstep(0.5, 1.6, u_ripple.x));
    }
    vec2 c = u_vp * 0.5;
    float dmax = max(u_vp.x, u_vp.y);
    vec3 col = mix(vec3(0.055, 0.086, 0.22), vec3(0.008, 0.012, 0.035), smoothstep(0.0, 0.8 * dmax, length(px - c)));
    // 引力透镜：看到的位置 px 对应的星空其实来自更靠近黑洞的地方，靠近视界的一圈会出现被放大的光环
    vec2 d = px - u_bh.xy; float r = max(length(d), 0.001);
    float E = u_bh.z * mix(2.3, 1.2, smoothstep(40.0, 160.0, u_bh.z));    // 黑洞很大时透镜减弱，不然满屏星星被拉成一道道“雨丝”
    vec2 src = px - d / r * (E * E / max(r, u_bh.z * 0.6));
    float lens = smoothstep(u_bh.z * 0.95, u_bh.z * 1.2, r);
    vec2 sp = mix(px, src, lens);
#ifdef LOW
    // 银河：从左上斜贯到右下的一条光带。视差很小，像在很远的地方
    vec2 gp = sp + u_pan * 0.03;
    vec2 dir = normalize(u_vp), nrm = vec2(-dir.y, dir.x);
    vec2 rel = gp - c;
    float along = dot(rel, dir), across = dot(rel, nrm);
    float wob = (fbm(vec2(along / 600.0, 3.0)) - 0.5) * dmax * 0.12;       // 光带边缘不是直的
    float band = exp(-pow((across + wob) / (dmax * 0.16), 2.0));
    float bulge = exp(-pow((along + dmax * 0.12) / (dmax * 0.35), 2.0));      // 偏左上一团更亮的核心
    float clouds = fbm(gp / 140.0) * 0.6 + fbm(gp / 45.0 + 7.0) * 0.4;        // 星云团
    float lanes = smoothstep(0.48, 0.72, fbm(vec2(along / 260.0, (across + wob) / 70.0) + 11.0));   // 顺着光带拉长的暗色尘埃带
    float lane2 = smoothstep(0.55, 0.8, fbm(gp / 60.0 + 23.0));
    vec3 mw = mix(vec3(0.62, 0.72, 1.0), vec3(1.0, 0.82, 0.62), bulge * 0.8 + clouds * 0.2);
    float glow = band * (0.10 + 0.22 * bulge) * (0.45 + 0.9 * clouds);
    glow *= 1.0 - (lanes * 0.8 + lane2 * 0.35) * band;
    col += mw * glow;
    col += vec3(0.95, 0.32, 0.45) * smoothstep(0.68, 0.85, fbm(gp / 80.0 + 41.0)) * band * 0.12;   // 零星的粉红色发射星云
    // 淡淡的蓝紫色星云（弱一点，别抢银河）
    vec2 np = (sp + u_pan * 0.05) / 520.0;
    float n = fbm(np + vec2(u_time * 0.006, -u_time * 0.004));
    float m = fbm(np * 1.7 + vec2(4.0, 1.0) - u_time * 0.003);
    vec3 neb = mix(vec3(0.42, 0.20, 0.85), vec3(0.0, 0.55, 0.85), smoothstep(0.3, 0.7, m));
    col += neb * smoothstep(0.42, 0.9, n) * 0.16;
    // 黑洞周围一圈被引力聚起来的暖光
    col += vec3(1.0, 0.6, 0.3) * exp(-max(r - u_bh.z, 0.0) / (u_bh.z * 2.5)) * 0.10 * lens;
    f = vec4(col, band * (1.0 - lanes * 0.7));
#else
    vec4 low = texture(u_low, v_uv);
    col = low.rgb;
    // 星星：满天都有，银河里密得多；最细的两层是满天的微光，远的一层动得最少
    float dens = low.a;
    col += stars(sp + u_pan * 0.01, 3.2, 0.06 + 0.5 * dens, 0.32) * (0.5 + 0.8 * dens);
    col += stars(sp + u_pan * 0.015, 5.5, 0.05 + 0.3 * dens, 0.42) * 0.9;
    col += stars(sp + u_pan * 0.02, 9.0, 0.10, 0.55);
    col += stars(sp + u_pan * 0.05, 23.0, 0.16, 0.8) * 1.2;
    col += stars(sp + u_pan * 0.10, 61.0, 0.22, 1.15) * 1.5;
    // 展开的近景：黑洞周围的星空被压暗，画面边缘也暗一圈，黑洞显得更沉、更有压迫感
    float dark = exp(-max(r - u_bh.z, 0.0) / (u_bh.z * 1.4)) * 0.6
               + smoothstep(0.45, 1.0, length((v_uv - 0.5) * vec2(1.25, 1.0)) * 1.35) * 0.4;
    col *= 1.0 - u_cine * dark;
    f = vec4(col, 1.0);
#endif
}
'''

SPRITE_VS = '''
#version 330
uniform vec2 u_vp;
in vec2 in_corner;            // -1..1
in vec4 i_rect;               // 中心 x、y（屏幕像素），半宽、半高
in vec4 i_color;
in vec4 i_p1;
in vec4 i_p2;
out vec2 v_local;
flat out vec4 v_color; flat out vec4 v_p1; flat out vec4 v_p2;
void main(){
    vec2 px = i_rect.xy + in_corner * i_rect.zw;
    v_local = in_corner * i_rect.zw;
    v_color = i_color; v_p1 = i_p1; v_p2 = i_p2;
    gl_Position = vec4(px.x / u_vp.x * 2.0 - 1.0, 1.0 - px.y / u_vp.y * 2.0, 0, 1);
}
'''

# 黑洞：逐像素追踪光线被黑洞弯曲的路径（光线步进），光线穿过吸积盘就把盘的光加上，掉进视界就是黑的。
# 光子环、盘的远侧被弯到上下方、多普勒一侧更亮、引力红移，都是算出来的，不是画上去的。
HOLE_FS = '''
#version 330
uniform float u_time;
in vec2 v_local; flat in vec4 v_color; flat in vec4 v_p1; flat in vec4 v_p2;
out vec4 f;
''' + NOISE + '''
const float R_IN = 2.3, R_OUT = 6.2;
// 盘有厚度（不是一张纸）：半厚度内薄外厚，外缘微微鼓起
float halfH(float rr){ return 0.04 + 0.045 * (clamp(rr, R_IN, R_OUT) - R_IN); }
// 盘里一点的发光颜色（rgb）和密度（a）
vec4 disk(vec3 hit, float rr, vec3 v){
    float phi = atan(hit.z, hit.x);
    // 内圈转得快、外圈转得慢。不能直接用 时间 × 转速：时间一长内外圈转过的角度差越来越大，纹理被拧成一圈圈细线。
    // 改用两层纹理交替（流动贴图）：每层只转 T 秒就重置，两层错开半个周期，重置时那层刚好完全淡出，看不出跳变
    const float PERIOD = 6.0;
    float w = 1.6 * pow(rr, -1.5);
    float ph1 = fract(u_time / PERIOD), ph2 = fract(u_time / PERIOD + 0.5);
    float a1 = phi - w * ph1 * PERIOD, a2 = phi - w * ph2 * PERIOD;
    vec2 pp1 = vec2(cos(a1), sin(a1)) * rr + 7.3 * floor(u_time / PERIOD);           // 每次重置换一块纹理，不重复
    vec2 pp2 = vec2(cos(a2), sin(a2)) * rr + 7.3 * floor(u_time / PERIOD + 0.5) + 3.7;
    float mixw = abs(1.0 - 2.0 * ph1);                     // 第一层重置时（ph1 = 0）只看第二层
    float yv = hit.y * 0.7;                                 // 不同高度的气体略有不同，看起来才有体积，不是一张纸压出来的
    float n = mix(fbm(pp1 * 0.9 + vec2(rr * 0.6, yv)), fbm(pp2 * 0.9 + vec2(rr * 0.6, yv)), mixw);
    n = clamp((n - 0.5) * 1.9 + 0.5, 0.0, 1.0);             // 两层混合会把明暗抵消掉一些，补回对比度
    float x = (rr - R_IN) / (R_OUT - R_IN);
    float T = pow(R_IN / rr, 0.9);                          // 越靠里越热
    vec3 base = mix(vec3(0.95, 0.28, 0.06), vec3(1.0, 0.78, 0.45), T);
    base = mix(base, vec3(1.0, 0.97, 0.9), T * T * 0.7);
    vec3 vel = normalize(vec3(-hit.z, 0.0, hit.x));         // 盘的转动方向
    float beta = sqrt(0.5 / rr);
    float dop = sqrt(1.0 - beta * beta) / (1.0 - beta * dot(vel, -v));     // 朝我们转来的一侧更亮
    float g = sqrt(max(0.0, 1.0 - 1.0 / rr));               // 引力红移
    // 真实的多普勒增亮两边能差十几倍（一边几乎看不见）；这里压到三倍左右，保留一点真实感，另一边也看得到盘
    float I = (pow(dop, 1.3) * g * g + 0.22) * pow(R_IN / rr, 1.2) * 1.45;
    float edge = smoothstep(0.0, 0.06, x) * (1.0 - smoothstep(0.35, 1.0, x));
    float h = halfH(rr) * (0.7 + 0.6 * n);                  // 上下表面跟着湍流起伏，边缘是一缕缕的
    float prof = exp(-pow(hit.y / h, 2.0));
    float dens = edge * prof * (0.45 + 0.75 * n);
    return vec4(base * I * 3.0, dens * min(I * 1.5, 1.0));
}
void main(){
    float rsPx = v_p1.x, hv = v_p1.y, op = v_p1.z, half_ = v_p1.w;
    float el = v_p2.x, roll = v_p2.y;
    vec2 q = mat2(cos(roll), sin(roll), -sin(roll), cos(roll)) * (v_local / rsPx);
    q.y = -q.y;
    const float D = 40.0;
    vec3 cam = D * vec3(0.0, sin(el), -cos(el));
    vec3 fw = normalize(-cam);
    vec3 rt = normalize(cross(vec3(0.0, 1.0, 0.0), fw));
    vec3 up = cross(fw, rt);
    vec3 v = normalize(fw + (q.x * rt + q.y * up) / D);
    vec3 p = cam;
    vec3 col = vec3(0.0); float trans = 1.0;
    const float RB = 16.0;                                  // 这个范围外光线几乎不弯，也碰不到盘
    float b = dot(p, v), disc = b * b - (dot(p, p) - RB * RB);
    if (disc > 0.0){                                        // 光线会经过黑洞附近：先直线走过去，再一步步算弯曲
        p += v * (-b - sqrt(disc));
        vec3 hc = cross(p, v); float h2 = dot(hc, hc);
        bool captured = false;
        float rmin = 99.0;
        float jit = hash(gl_FragCoord.xy);                  // 每个像素的采样点错开一点，避免出现一层层的条纹
        for (int i = 0; i < 700; i++){
            float r = length(p);
            float dt = clamp(0.045 * r, 0.012, 0.45);
            float rr = length(p.xz);
            float hh = halfH(rr);
            bool inR = rr > R_IN * 0.8 && rr < R_OUT * 1.08;
            // 盘是一层有厚度的气体：快到盘时步子放小，穿过盘时一小步一小步地累加发光和遮挡（体积渲染）
            if (inR){
                float gap = max(abs(p.y) - hh * 2.4, 0.0);
                dt = min(dt, (gap + hh * 0.5) / max(abs(v.y), 1e-3));
                if (gap == 0.0) dt = min(dt, 0.14);
                dt = max(dt, 0.008);
            }
            v += -1.5 * h2 * p / pow(r, 5.0) * dt;
            vec3 pn = p + v * dt;
            rmin = min(rmin, r);
            if (inR && abs(p.y) < hh * 2.6){
                vec3 s = mix(p, pn, jit);
                float sr = length(s.xz);
                if (sr > R_IN && sr < R_OUT){
                    vec4 e = disk(s, sr, normalize(v));
                    // 光线往上走 = 看到的是盘的底面（黑洞下方那道弧），压暗压细，不然像“眼袋”
                    float under = smoothstep(-0.03, 0.03, v.y);
                    e.rgb *= 1.0 - 0.7 * under;
                    float dA = 1.0 - exp(-e.a * dt * mix(9.0, 2.5, under));       // 吸收强一点：看到的是盘最外面一层，湍流细节不会被平均掉
                    col += trans * e.rgb * dA;
                    trans *= 1.0 - dA;
                }
            }
            p = pn;
            if (dot(p, p) < 1.0){ captured = true; break; }
            if (r > RB + 1.0 && dot(p, v) > 0.0) break;
            if (trans < 0.02) break;
        }
        if (captured) trans = 0.0;
        else {                // 光子环：贴着光子球（1.5 倍视界）绕过的光，阴影边上一圈锐利的细亮线
            float ring = exp(-pow((rmin - 1.56) / 0.06, 2.0));
            col += vec3(1.0, 0.86, 0.7) * ring * 0.9 * trans;
            trans *= 1.0 - ring * 0.6;
        }
    }
    float alpha = 1.0 - trans;
    float rq = length(q);
    col += vec3(1.0, 0.55, 0.25) * exp(-max(rq - 2.6, 0.0) * 0.4) * 0.09 * (1.0 + hv) * (1.0 - alpha);
    col = 1.0 - exp(-col * mix(1.25, 0.95, v_p2.z));        // 色调映射，亮处不发白爆掉；近景收一点曝光，盘不糊成一片
    float win = 1.0 - smoothstep(0.8, 1.0, max(abs(v_local.x), abs(v_local.y)) / half_);
    f = vec4(col * op * win, alpha * op * win);
}
'''

# 恒星：照着太阳实拍的样子——会自转的球面上有米粒状的对流元胞、明暗斑、几个黑子（本影 + 半影），边缘变暗偏红，
# 边上一圈色球层和一缕缕往外喷的日珥，外面是带放射状亮纹的日冕。朝黑洞那一侧被潮汐轻轻拉出一点，物质从那里被吸走
STAR_FS = '''
#version 330
uniform float u_time;
in vec2 v_local; flat in vec4 v_color; flat in vec4 v_p1; flat in vec4 v_p2;
out vec4 f;
''' + NOISE + '''
float h31(vec3 p){ p = fract(p * vec3(0.1031, 0.1030, 0.0973)); p += dot(p, p.yxz + 33.33); return fract((p.x + p.y) * p.z); }
vec3 h33(vec3 p){ p = fract(p * vec3(0.1031, 0.1030, 0.0973)); p += dot(p, p.yxz + 33.33); return fract((p.xxy + p.yxx) * p.zyx); }
float n3(vec3 x){
    vec3 i = floor(x), u = fract(x); u = u * u * (3. - 2. * u);
    return mix(mix(mix(h31(i), h31(i + vec3(1, 0, 0)), u.x), mix(h31(i + vec3(0, 1, 0)), h31(i + vec3(1, 1, 0)), u.x), u.y),
               mix(mix(h31(i + vec3(0, 0, 1)), h31(i + vec3(1, 0, 1)), u.x), mix(h31(i + vec3(0, 1, 1)), h31(i + vec3(1, 1, 1)), u.x), u.y), u.z);
}
float fbm3(vec3 p){ float v = 0., a = .5; for (int i = 0; i < 4; i++){ v += a * n3(p); p = p * 2.07 + 3.1; a *= .5; } return v; }
// 米粒组织：三维细胞噪声。元胞中间是鼓上来的亮气泡，往边上慢慢变暗，元胞之间是柔和的暗缝（不是细线网格）
float granules(vec3 p){
    vec3 i = floor(p), fr = fract(p); float d1 = 9., d2 = 9.;
    for (int x = -1; x <= 1; x++) for (int y = -1; y <= 1; y++) for (int z = -1; z <= 1; z++){
        vec3 o = vec3(x, y, z); vec3 r = o + h33(i + o) - fr; float d = dot(r, r);
        if (d < d1){ d2 = d1; d1 = d; } else if (d < d2) d2 = d;
    }
    return 1.0 - smoothstep(0.0, 0.9, sqrt(d1));
}
void main(){
    float R = v_p1.x, hv = v_p1.y, op = v_p1.z, act = v_p1.w, seed = v_p2.x, bright = v_p2.y;
    float doom = v_p2.z, dang = v_p2.w;
    float t = u_time;
    vec2 q = v_local / R, q0 = q;
    vec3 c = v_color.rgb;
    vec2 dd = vec2(cos(dang), sin(dang));                   // 指向黑洞（被吞时是运动方向）
    float al = dot(q, dd);
    q -= dd * max(al, 0.0) * 0.08 / 1.08;                   // 潮汐：朝黑洞那半边轻轻鼓出来一点
    if (doom > 0.0){                                        // 被黑洞吞掉：顺着运动方向拉长、变红
        al = dot(q, dd);
        q += dd * (al / (1.0 + 1.5 * doom) - al);
        c = mix(c, vec3(1.0, 0.25, 0.08), doom * 0.8);
    }
    float r = length(q);
    float body = 1.0 - smoothstep(0.97, 1.02, r);
    vec3 surf = vec3(0.0);
    if (r < 1.03){
        float mu = sqrt(max(0.0, 1.0 - r * r));
        vec3 nrm = vec3(q.x, -q.y, mu);
        // 自转：绕稍微歪一点的轴慢慢转，黑子会从一边转到另一边
        float tilt = 0.35 * (seed - 0.5), spin = t * 0.05 + seed * 6.283;
        nrm = vec3(nrm.x, nrm.y * cos(tilt) - nrm.z * sin(tilt), nrm.y * sin(tilt) + nrm.z * cos(tilt));
        vec3 s = vec3(nrm.x * cos(spin) + nrm.z * sin(spin), nrm.y, -nrm.x * sin(spin) + nrm.z * cos(spin));
        // 等离子：扭曲过的噪声，亮的细丝 + 暗一点的团块，慢慢流动；底下再叠一层很细的米粒
        vec3 wp = vec3(fbm3(s * 2.0 + vec3(seed * 5.0, t * 0.03, 0.0)), fbm3(s * 2.0 + vec3(1.7, 9.2 - t * 0.03, seed * 3.0)), 0.0);
        float plasma = fbm3(s * 3.2 + wp * 1.8 + vec3(0.0, 0.0, t * 0.05));
        float fil = 1.0 - abs(plasma * 2.0 - 1.0); fil *= fil * fil;
        float gran = granules(s * 13.0 + vec3(seed * 31.0, 0.0, t * 0.12));    // 元胞在噪声里慢慢穿行 = 对流翻涌
        float sp = fbm3(s * 1.6 + vec3(seed * 13.0, 5.0, 0.0));
        float band = 1.0 - smoothstep(0.3, 0.62, abs(s.y));                   // 黑子只在低纬度出现
        float pen = smoothstep(0.66, 0.70, sp) * band, umb = smoothstep(0.72, 0.745, sp) * band;
        float limb = 1.0 - 0.55 * (1.0 - mu) - 0.25 * (1.0 - mu) * (1.0 - mu); // 边缘变暗（太阳的实测系数）
        float I = (0.42 + 0.7 * plasma + 0.45 * fil) * (0.88 + 0.24 * gran) * limb;
        I *= (1.0 - 0.45 * pen) * (1.0 - 0.55 * umb);
        I += smoothstep(0.6, 0.75, plasma) * pow(1.0 - mu, 1.5) * 0.4;      // 光斑：靠近边缘的亮网
        // 颜色按亮度从恒星本色里取：暗处是更浓的本色，中间是本色，最亮处偏白（像过曝的太阳照片）。
        // 白色、淡蓝的恒星本色太淡，先把饱和度提上去，不然表面是灰的，像月亮
        vec3 cs = clamp(mix(vec3(dot(c, vec3(0.3, 0.59, 0.11))), c, 2.6), 0.0, 1.0);
        vec3 deep = pow(cs, vec3(2.0)) * 0.9, hot = mix(cs, vec3(1.0, 0.98, 0.94), 0.5);
        vec3 sc = I < 0.6 ? mix(deep, cs, I / 0.6) : mix(cs, hot, min(1.0, (I - 0.6) / 0.6));
        surf = sc * (0.9 + 1.7 * I);
    }
    float o = max(r - 1.0, 0.0);
    vec2 dir = q / max(r, 1e-4);
    float lift = (0.85 + 0.4 * hv + 0.3 * act) * bright * (0.94 + 0.06 * sin(t * 1.6 + seed * 20.0));
    lift *= 1.0 + 1.5 * smoothstep(0.3, 0.5, doom);          // 化成星尘前亮一下
    // 色球层：贴着边缘的一圈细亮边；日珥：边上一缕缕往外喷的火焰；日冕：柔光 + 放射状亮纹
    float chrom = exp(-o * 28.0) * smoothstep(0.9, 1.0, r);
    float flame = fbm3(vec3(dir * 3.2 + seed * 17.0, o * 7.0 - t * 0.3));
    float prom = smoothstep(0.55, 0.8, flame) * exp(-o * 6.5) * smoothstep(0.98, 1.02, r);
    float streak = 0.5 + 0.9 * fbm3(vec3(dir * 2.2 + seed * 9.0, t * 0.03));
    float corona = exp(-o * 4.5) * 0.7 + exp(-o * 1.4) * 0.2 * streak;
    vec3 em = (c * corona + mix(c, vec3(1.0, 0.42, 0.22), 0.55) * (prom * 1.4 + chrom * 0.8)) * lift;
    em *= 1.0 - smoothstep(3.2, 4.9, max(abs(q0.x), abs(q0.y)));      // 画到方块边缘前淡掉
    vec3 col = surf * body * (0.85 + 0.25 * lift) + em * (1.0 - body);
    col = 1.0 - exp(-col * 1.25);
    float shade = act * 0.45 * exp(-o * 1.3) * (1.0 - smoothstep(2.6, 4.6, max(abs(q0.x), abs(q0.y))));
    f = vec4(col * op, (body + (1.0 - body) * shade) * op);
}
'''

# 胶囊（分类、作品、添加按钮）：半透明的黑水晶——深色晶体能隐约透出后面的星空，几个切面明暗不同、切面之间有细亮的棱，
# 边缘内侧一圈折射般的亮边，顶上一道锐利的高光，偶尔有一道反光扫过；朝向父节点那侧的描边被照亮
PILL_FS = '''
#version 330
uniform float u_time;
in vec2 v_local; flat in vec4 v_color; flat in vec4 v_p1; flat in vec4 v_p2;
out vec4 f;
''' + NOISE + '''
float sd(vec2 p, vec2 b){ float r = b.y; vec2 q = abs(p) - b + r; return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r; }
void main(){
    vec2 b = v_p1.xy; float hv = v_p1.z, op = v_p1.w;
    vec2 L = v_p2.xy; float seed = v_p2.z, kind = v_p2.w;
    vec3 c = v_color.rgb;
    vec2 p = v_local;
    float d = sd(p, b);
    vec2 n = normalize(vec2(sd(p + vec2(0.5, 0), b) - sd(p - vec2(0.5, 0), b), sd(p + vec2(0, 0.5), b) - sd(p - vec2(0, 0.5), b)) + 1e-5);
    float inside = 1.0 - smoothstep(-0.6, 0.6, d);
    vec2 fp = p / b.y;                                      // 以半高为单位
    // 切面：两组斜线把晶体切成几块，每块明暗不同（角度按 seed 变化，每个胶囊不一样）
    float k1 = 0.45 + 0.3 * seed, k2 = 0.9 - 0.3 * seed;
    float u1 = fp.x * 0.18 + fp.y * k1 + seed * 3.0, u2 = fp.x * 0.14 - fp.y * k2 + seed * 7.0;
    float facet = hash(vec2(floor(u1), floor(u2)) + seed * 17.0);
    float g1 = fract(u1), g2 = fract(u2);
    float ridge = (1.0 - smoothstep(0.0, fwidth(u1) * 1.3, min(g1, 1.0 - g1)))
                + (1.0 - smoothstep(0.0, fwidth(u2) * 1.3, min(g2, 1.0 - g2)));
    float yN = clamp(p.y / b.y, -1.0, 1.0);
    vec3 tint = mix(vec3(0.03, 0.04, 0.10), c * 0.30, 0.22 + 0.10 * hv);
    vec3 body = tint * (0.7 + 0.5 * facet) * (1.15 - 0.35 * (yN * 0.5 + 0.5));
    float bodyA = (kind > 1.5) ? 0.35 : 0.58;              // 半透明
    // 发光的部分（加在上面，不挡后面的东西）
    float rim = exp(min(d, 0.0) / 2.6) * inside;           // 边缘内侧折射般的亮边
    float spec = exp(-pow((yN + 0.62) / 0.13, 2.0)) * (1.0 - smoothstep(0.55, 1.0, abs(p.x) / b.x)) * inside;   // 顶上的高光
    float sweepX = (fract(u_time * 0.07 + seed) * 3.0 - 1.0) * b.x * 1.4;
    float glint = exp(-pow((p.x - sweepX + p.y * 0.8) / 5.0, 2.0)) * inside;      // 偶尔扫过的一道反光
    vec3 emit = c * (rim * 0.55 + ridge * 0.12 * inside) + vec3(rim * 0.12 + spec * 0.32 + glint * 0.16 + ridge * 0.04 * inside);
    // 描边和外面的柔光
    float facing = max(0.0, dot(n, L));
    float border = exp(-pow(d / 0.9, 2.0));
    if (kind > 1.5) border *= step(0.45, fract(atan(p.y, p.x) * 10.0 / 6.2832 + 0.25));    // 添加按钮：虚线圈
    vec3 bcol = c * (0.5 + 1.0 * facing + 0.7 * hv);
    float out_ = max(d, 0.0);
    float glow = (exp(-out_ / (4.0 + 3.0 * hv)) * (0.14 + 0.30 * hv) + exp(-out_ / 14.0) * 0.05) * (1.0 - inside)
               * (1.0 - smoothstep(18.0, 29.0, out_));
    vec3 col = body * inside * bodyA + emit * (1.0 + 0.6 * hv) + bcol * border + c * glow;
    float alpha = clamp(inside * bodyA + border * 0.35, 0.0, 1.0);
    f = vec4(col * op, alpha * op);
}
'''

# 连线（加色混合）：kind 0 = 恒星被黑洞抽出的物质流，越靠近黑洞越宽越亮，一缕缕气体和光点往里流；
# kind 1 = 分支里柔软的光丝，细亮线 + 柔光，光点沿着往外流
BEAM_VS = '''
#version 330
uniform vec2 u_vp;
in vec2 in_pos; in float in_x; in float in_w; in float in_along; in float in_s; in float in_kind; in vec4 in_color;
out float v_x; out float v_w; out float v_along; out float v_s; flat out float v_kind; out vec4 v_color;
void main(){
    v_x = in_x; v_w = in_w; v_along = in_along; v_s = in_s; v_kind = in_kind; v_color = in_color;
    gl_Position = vec4(in_pos.x / u_vp.x * 2.0 - 1.0, 1.0 - in_pos.y / u_vp.y * 2.0, 0, 1);
}
'''
BEAM_FS = '''
#version 330
uniform float u_time;
in float v_x; in float v_w; in float v_along; in float v_s; flat in float v_kind; in vec4 v_color;
out vec4 f;
''' + NOISE + '''
// 沿着线一格一格放粒子：每格最多一个，位置、大小、亮度、左右偏移都随机，有的格子是空的，所以看起来断断续续
float particles(float along, float x, float speed, float spacing, float seed, float spread){
    float u = along - u_time * speed;               // speed 必须是常数，粒子才会一直朝同一个方向流
    float cell = floor(u / spacing);
    float fu = u - cell * spacing;
    float h = hash(vec2(cell, seed));
    if (h < 0.38) return 0.0;
    float pos = spacing * (0.2 + 0.6 * hash(vec2(cell, seed + 1.7)));
    float off = (hash(vec2(cell, seed + 3.3)) - 0.5) * spread;
    float size = 0.45 + 0.75 * hash(vec2(cell, seed + 5.1));
    vec2 d = vec2(fu - pos, x - off);
    float tw = 0.6 + 0.4 * sin(u_time * (1.5 + 3.0 * h) + h * 40.0);
    return exp(-dot(d, d) / (size * size)) * (0.35 + 0.65 * h) * tw;
}
void main(){
    float x = v_x;
    vec3 col;
    float kindId = floor(v_kind), seed = fract(v_kind);    // 整数部分是种类，小数部分是这条线自己的随机种子
    // 每条线按自己的种子错开雾和粒子的图案；不然几条线会同时变淡、同时变亮，像一起呼吸
    if (kindId < 0.5){
        // 物质流：像漏斗——在恒星那头张得很宽（把恒星的一侧整个罩住），往黑洞去很快收成一股细流。
        // 一层顺着流向拉长的薄雾 + 往黑洞里流的粒子；粒子的横向位置按漏斗宽度缩放，所以边流边往中间汇拢
        float w = v_w, xn = x / w;
        float flow = v_along * (1.0 - 0.35 * v_s);    // 越靠近黑洞空间越“短”，同样速度看起来流得越快；对 along 的导数约 1 - 0.7s，始终为正，方向不会反
        float mist = fbm(vec2(flow * 0.018 - u_time * 0.5 + seed * 37.0, xn * 1.3 + seed * 11.0));
        float wide = clamp((w - 3.2) / 18.0, 0.0, 1.0);             // 漏斗口那一段
        float core = exp(-xn * xn * 1.4);
        float shell = exp(-pow(abs(xn) - 0.75, 2.0) * 9.0) * wide;   // 漏斗口两侧亮一点，看得出是个张开的锥面
        float haze = (core * (0.07 + 0.17 * smoothstep(0.38, 0.8, mist)) + shell * 0.10 * (0.5 + mist))
                   * (1.0 + 0.8 * wide);                             // 刚从恒星上被扯下来的那段更浓
        float pt = particles(flow + seed * 500.0, x, 30.0, 11.0, 1.0 + seed * 13.0, w * 1.1)
                 + particles(flow + seed * 300.0, x, 21.0, 17.0, 7.0 + seed * 13.0, w * 1.7) * 0.7;
        float fade = smoothstep(0.0, 0.04, v_s) * (1.0 - smoothstep(0.75, 1.0, v_s));
        col = (v_color.rgb * (haze + pt * 1.5) + vec3(pt * 0.45)) * fade;
    } else {
        // 分支光丝：更细更稀疏，一丝很淡的线 + 稀疏的光点往外流
        float mist = fbm(vec2(v_along * 0.025 - u_time * 0.4 + seed * 37.0, seed * 11.0));
        float haze = exp(-x * x / (2.0 * 1.6 * 1.6)) * (0.10 + 0.16 * smoothstep(0.3, 0.75, mist));
        float pt = particles(v_along + seed * 500.0, x, 26.0, 14.0, 3.0 + seed * 13.0, 2.0)
                 + particles(v_along + seed * 300.0, x, 17.0, 23.0, 9.0 + seed * 13.0, 3.0) * 0.6;
        col = v_color.rgb * (haze + pt * 1.3) + vec3(pt * 0.35);
    }
    f = vec4(col * v_color.a, 0.0);
}
'''

# 晶尘：胶囊、恒星碎掉时迸出的菱形小碎屑，会闪，带一点十字闪光；加色混合
DUST_FS = '''
#version 330
uniform float u_time;
in vec2 v_local; flat in vec4 v_color; flat in vec4 v_p1; flat in vec4 v_p2;
out vec4 f;
void main(){
    float s = v_p1.x, a = v_p1.y, ph = v_p1.z;
    vec2 q = v_local / s;
    float dia = abs(q.x) + abs(q.y);
    float core = exp(-dia * dia * 1.2);
    float tw = 0.55 + 0.45 * sin(u_time * 9.0 + ph * 40.0);
    float spark = (exp(-abs(q.x) * 6.0) * exp(-abs(q.y) * 1.2) + exp(-abs(q.y) * 6.0) * exp(-abs(q.x) * 1.2)) * 0.35 * tw;
    vec3 col = v_color.rgb * (core * 1.4 + spark) + vec3(core * 0.5 * tw);
    float win = 1.0 - smoothstep(3.5, 5.0, max(abs(q.x), abs(q.y)));
    f = vec4(col * a * win, 0.0);
}
'''

# 文字：所有标签事先画进一张图集（超采样分辨率 + 多级纹理），每帧按位置、缩放、透明度一次画完
LABEL_FS = '''
#version 330
uniform sampler2D u_atlas;
in vec2 v_local; flat in vec4 v_color; flat in vec4 v_p1; flat in vec4 v_p2;
out vec4 f;
void main(){
    vec2 uv = mix(v_color.xy, v_color.zw, v_local / v_p1.yz * 0.5 + 0.5);    // v_color 借来放图集里的位置
    f = texture(u_atlas, uv) * v_p1.x;
}
'''

# 星尘粒子：CPU 只在产生时上传一次起点、终点和时间，之后每帧的位置都由显卡按时间算（CPU、GPU 各干各的）。
# mode 2 = 收起：恒星的水晶碎片迸开一点后被吸进黑洞；mode 3 = 展开：碎片从黑洞里旋出来、飞到恒星的位置汇合。
# 都画成菱形闪光（像水晶胶囊的晶尘），片元用 DUST_FS
PARTICLE_VS = '''
#version 330
uniform vec2 u_vp;
uniform vec3 u_cam;       // 镜头看向的世界坐标 x、y，缩放
uniform vec3 u_bh;        // 黑洞在屏幕上的位置、阴影半径（像素）
uniform float u_time;
in vec2 in_corner;
in vec4 a_from; in vec4 a_to; in vec4 a_time; in vec4 a_look; in vec4 a_misc;
out vec2 v_local; flat out vec4 v_color; flat out vec4 v_p1; flat out vec4 v_p2;
const float FOCAL = ''' + str(FOCAL) + ''';
vec2 proj(vec3 p){ float k = u_cam.z * FOCAL / (FOCAL - p.z); return (p.xy - u_cam.xy) * k + u_vp * 0.5; }
vec2 at(float t){
    if (a_time.z < 2.5){
        // 碎片：先清脆地迸开一小下（很快停住），等一会儿再一边往里落一边顺着盘转一点，越靠里越贴近盘面
        float tau = max(t - a_time.x, 0.0);
        vec2 S = a_from.xy + a_to.xy * (1.0 - exp(-tau * 9.0));
        float e = pow(clamp((tau - a_time.w) / a_time.y, 0.0, 1.0), 1.8);
        float r = length(S) * (1.0 - e), th = atan(S.y, S.x) - a_to.z * pow(e, 1.3);
        return proj(vec3(r * cos(th), r * sin(th) * mix(1.0, 0.4, e), a_from.z * (1.0 - e)));
    }
    // 展开：从黑洞边上反着旋出来（先快后慢），越往外越离开盘面，最后落到恒星圆面上的一点
    float e = 1.0 - pow(1.0 - clamp((t - a_time.x) / a_time.y, 0.0, 1.0), 2.4);
    vec2 T = a_to.xy;
    float r = mix(a_from.x, length(T), e), th = atan(T.y, T.x) + a_to.z * pow(1.0 - e, 1.3);
    return proj(vec3(r * cos(th), r * sin(th) * mix(0.4, 1.0, e), a_to.w * e));
}
void main(){
    float t = u_time, inward = step(1.5, a_time.z) * step(a_time.z, 2.5);
    float u = (t - a_time.x - inward * a_time.w) / a_time.y;
    vec2 s = at(t);
    float alpha = smoothstep(u_bh.z * 0.85, u_bh.z * 1.35, length(s - u_bh.xy));     // 在黑洞阴影里看不见
    if (inward > 0.5){        // 收起：碎开那一刻就出现，进了视界消失
        if (t < a_time.x || u >= 1.0) alpha = 0.0;
    } else {                  // 展开：到了恒星那里一下子收拢消失，交给凝结出来的恒星
        alpha *= 1.0 - smoothstep(0.88, 1.0, u);
        if (u < 0.0 || u >= 1.0) alpha = 0.0;
    }
    float size = a_look.w * max(0.8, u_cam.z);
    float ext = alpha > 0.0 ? size * 5.0 : 0.0;      // 看不见的退化成一个点，不画
    v_local = in_corner * ext;
    v_color = vec4(a_look.rgb, 1.0);
    v_p1 = vec4(size, alpha, a_misc.z, 0.0);
    v_p2 = vec4(0.0);
    vec2 px = s + in_corner * ext;
    gl_Position = vec4(px.x / u_vp.x * 2.0 - 1.0, 1.0 - px.y / u_vp.y * 2.0, 0, 1);
}
'''

DOWN_FS = '''
#version 330
uniform sampler2D u_tex;
uniform float u_keep;     // 1 = 保留透明度（把单独画的黑洞叠上去），0 = 不透明（缩小到屏幕）
in vec2 v_uv; out vec4 f;
void main(){ vec4 c = texture(u_tex, v_uv); f = vec4(c.rgb, mix(1.0, c.a, u_keep)); }
'''

BEAM_HW = 20.0            # 光线条带的半宽（屏幕像素），要盖住柔光的范围
BEAM_SEG = 40             # 每条线切成几段（段太少，弯的时候能看出折角）
# 物质流像烟、像彗尾：线上离恒星 s 处的气体，是恒星大约 TRAIL_T·s 秒前放出来的，所以那一段沿着恒星刚走过的路线；
# 越往黑洞那头越淡化回平稳的形状。来回甩会自然扭出 S 形、波浪形。只看恒星在空间里的真实移动，镜头切换不算
TRAIL_T = 0.7
TRAIL_W = (1 - np.linspace(0, 1, BEAM_SEG + 1)) ** 1.5
TRAIL_MAX = 0.6                   # 尾迹偏离最多是线长的多少


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
        self.swallow = None             # 正在坠入黑洞：(起点, 起点的 z)
        self.doom = self.dang = 0.0     # 被吞的进度、运动方向（给恒星拉长用）
        self.fresh = False              # 刚出现（年份由黑洞喷出的星尘凝聚出来）
        self.form = 1.0                 # 恒星凝聚的程度 0~1
        self.flash = 0.0                # 碎开前亮一下
        self.shattered = False

    def round(self):
        return self.kind in ('center', 'year', 'add')

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

    def offset(self, t):
        """自己漂浮：每个方向两种慢节奏叠在一起，看起来不机械；再加上鼠标扰动。"""
        ax, ay = AMP[self.kind]
        w1, w2, w3, w4, p1, p2, p3, p4 = self.bob
        return QPointF(ax * (0.65 * math.sin(w1 * t + p1) + 0.35 * math.sin(w2 * t + p2)) + self.d[0],
                       ay * (0.65 * math.sin(w3 * t + p3) + 0.35 * math.sin(w4 * t + p4)) + self.d[1])

    def screen_center(self):
        if self.round():
            return QPointF(self.sx, self.sy)
        return QPointF(self.sx + self.w / 2 * self.k, self.sy)

    def hit(self, x, y):
        if self.round():
            r = self.rpx * (0.9 if self.rpx > 80 else 1.25) if self.kind == 'center' else (self.w / 2 * (1 + STAR_ACTIVE * self.active) + 6) * self.k
            return (x - self.sx) ** 2 + (y - self.sy) ** 2 <= r * r
        return self.sx - 3 <= x <= self.sx + self.w * self.k + 3 and abs(y - self.sy) <= self.h / 2 * self.k + 3

    def edge_point(self, other, out):
        """连线接在哪（屏幕像素）：圆形接在朝向对方的边上；胶囊进线接左端、出线接右端。"""
        if self.round():
            rad = {'center': RS * 1.65, 'year': STAR_R * 1.05 * (1 + STAR_ACTIVE * self.active), 'add': 13}[self.kind] * self.k
            dx, dy = other.sx - self.sx, other.sy - self.sy
            n = math.hypot(dx, dy) or 1
            return self.sx + dx / n * rad, self.sy + dy / n * rad
        return (self.sx + self.w * self.k, self.sy) if out else (self.sx, self.sy)


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
        self._mouse = None              # 上一次鼠标位置和时间，算划过的速度
        self.cine = 0.0                 # 0 = 全图（黑洞在中间、斜看），1 = 展开（黑洞在左边、侧视放大）
        self.bh = (-9999.0, -9999.0, 1.0, EL_MAP, 0.0)   # 这一帧黑洞在屏幕上的 x、y、阴影半径、仰角、滚转
        self._ropes = {}                # 分支光丝的惯性状态
        self._trails = {}               # 物质流的尾迹：每颗恒星最近的位置记录
        self._cine_fit = (1.0, 0.0)     # 展开近景的缩放、恒星在屏幕上的 x（排布时算好，镜头对准时用）
        self._par = QPointF(0, 0)       # 视差：鼠标离画面中心多远（-1~1，平滑过的）
        self._mouse_pos = None
        self._busy = True               # 这一帧有没有东西在动（决定下一帧画不画满帧率）
        self._last_input = 0.0          # 上次鼠标操作的时间
        self.link_fade = 1.0            # 连线整体的显示程度：展开、收起时先隐藏，快停稳时再淡入
        self._anim_moving = False       # 这次动画里有没有东西在飞（只是淡入淡出就不用藏连线）
        # 晶尘粒子，每行：世界 x、y，速度 x、y，剩余寿命，总寿命，大小，颜色 r、g、b，闪烁相位
        self.dust = np.zeros((0, 11), 'f4')
        # 坠入、喷出的星尘（位置由显卡按时间算），每行 20 个数：起点 x、y、z、空，终点 x、y、z、空，
        # 开始时间、时长、模式（0 坠入 / 1 喷出）、亮起时间，颜色 r、g、b、大小，随机数、偏移、闪烁相位、空
        self.parts = np.zeros((0, 20), 'f4')
        self._gulp_t = -99.0            # 碎片差不多都被吸进去的时间（黑洞亮一下、荡开涟漪）
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

    def _emit(self, rows):
        self.parts = np.concatenate([self.parts, rows.astype('f4')])
        self._parts_dirty = True

    def _emit_shards(self, n, now):
        """恒星碎开：撒一把水晶碎片，迸开一小下就停住，等一会儿再各自被吸进黑洞（位置由显卡按时间算）。"""
        rng = np.random.default_rng()
        N = SHARD_N
        off = rng.normal(0, 0.4, (N, 2)) * STAR_R
        burst = rng.normal(0, 3.5, (N, 2)) + off * 0.12        # 只迸开一点点，方向乱一点（不要整齐地往外炸成一圈）
        c = np.array([n.color.redF(), n.color.greenF(), n.color.blueF()])
        col = c * (1 - (w := rng.uniform(0, 0.3, (N, 1)))) + w
        z = np.zeros(N)
        self._emit(np.column_stack([n.base.x() + off[:, 0], n.base.y() + off[:, 1], z + n.z, z,
                                    burst, rng.uniform(0.3, 1.3, N), z,
                                    z + now, rng.uniform(0.6, 1.1, N), z + 2, rng.uniform(0.08, 0.35, N),
                                    col, rng.uniform(0.9, 2.0, N), rng.random(N), z, rng.random(N), z]))
        self._gulp_t = max(self._gulp_t, now + GULP_S)

    def _emit_birth(self, n, pos, z_to, now):
        """恒星重建：水晶碎片从黑洞边上旋出来，飞到恒星圆面上（位置由显卡按时间算）。"""
        rng = np.random.default_rng()
        N = BIRTH_N
        off = rng.normal(0, 0.35, (N, 2)) * STAR_R
        c = np.array([n.color.redF(), n.color.greenF(), n.color.blueF()])
        col = c * (1 - (w := rng.uniform(0, 0.3, (N, 1)))) + w
        z = np.zeros(N)
        T0 = BIRTH_S * FORM_AT                          # 碎片在恒星凝结前后陆续到达
        dur = rng.uniform(0.55, 0.85, N)
        self._emit(np.column_stack([rng.uniform(RS * 0.8, RS * 1.2, N), z, z, z,
                                    pos.x() + off[:, 0], pos.y() + off[:, 1], rng.uniform(0.4, 1.4, N), z + z_to,
                                    now + T0 - dur * rng.uniform(0.85, 1.1, N), dur, z + 3, z,
                                    col, rng.uniform(0.9, 2.0, N), rng.random(N), z, rng.random(N), z]))

    def relayout(self, animate=True):
        targets = self._targets()
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
                if polar is not None:       # 新出来的年份不飞：就在自己的位置上，由黑洞喷出来的星尘凝聚出来
                    node.polar0, node.base, node.z = polar, QPointF(pos), z
                    if animate:
                        node.form = 0.0
                        node.set_content(text, sub, color, data)
                        self._emit_birth(node, pos, z, self.clock.elapsed() / 1000)
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
                    node.base += node.offset(self.clock.elapsed() / 1000) - QPointF(*node.d)    # 从现在看到的位置出发
                    node.swallow = (QPointF(node.base), node.z, random.uniform(0.0, 0.3))
                    node.shattered = not animate
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
            years_in = any(n.fresh and n.kind == 'year' for n in self.nodes.values())
            self.anim.start(self.clock.elapsed() / 1000, SWALLOW_S if years_out else BIRTH_S if years_in else ANIM_S)
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
                # 先被黑洞吸过去一段、越来越快，碎开前亮一下，然后一下子碎成水晶碎片（星体立刻消失）
                start, z0, lag = n.swallow
                u = max(0.0, raw * SWALLOW_S - lag) / ATTRACT_S
                pr = ATTRACT_D * min(1.0, u) ** 2
                n.base = start * (1 - pr)
                n.z = z0 * (1 - pr)
                n.doom = 0.05 * min(1.0, u)
                n.dang = math.atan2(-start.y(), -start.x())
                n.flash = smooth(0.6, 1.0, u)
                n.d = [0.0, 0.0]
                if u >= 1.0 and not n.shattered:
                    n.shattered = True
                    self._emit_shards(n, self._last_t)        # 用这一帧的时间，碎片在同一帧出现
                n.opacity = 0.0 if n.shattered else n.o0
                continue
            k = t
            if n.polar1 is not None and n.polar0 is not None:
                a, r = lerp(n.polar0[0], n.polar1[0], k), lerp(n.polar0[1], n.polar1[1], k)
                n.base = QPointF(r * math.cos(a), r * math.sin(a))
            else:
                n.base = QPointF(lerp(n.p0.x(), n.p1.x(), k), lerp(n.p0.y(), n.p1.y(), k))
            n.z = lerp(n.z0, n.z1, t)
            n.opacity = max(0.0, min(1.0, lerp(n.o0, n.o1, t)))
            if n.fresh and n.kind == 'year':        # 碎片到齐时恒星一下子凝结出来，亮一下
                n.opacity = smooth(FORM_AT - 0.05, FORM_AT + 0.03, raw)
                n.form = smooth(FORM_AT - 0.05, FORM_AT + 0.08, raw)
                n.flash = smooth(FORM_AT - 0.05, FORM_AT, raw) * (1 - smooth(FORM_AT + 0.02, 1.0, raw))

    def _finish(self):
        for key in [k for k, n in self.nodes.items() if n.removing]:
            del self.nodes[key]
        for n in self.nodes.values():
            n.polar0 = n.polar1
            n.fresh = False
            n.form, n.flash = 1.0, 0.0
            if n.polar1 is not None:
                a, r = n.polar1
                n.base = QPointF(r * math.cos(a), r * math.sin(a))
            else:
                n.base = QPointF(n.p1)
            n.z, n.opacity = n.z1, n.o1
        self.update()

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
        return 1 - smooth(0.0, 0.35, self.cine * self.cine * (3 - 2 * self.cine))

    def _layout_screen(self):
        t = self.clock.elapsed() / 1000
        for n in self.nodes.values():
            o = n.offset(t)
            n.sx, n.sy, n.k = self.project(n.base.x() + o.x(), n.base.y() + o.y(), n.z)
        c = self.nodes.get('c')
        if c is not None:
            e = self.cine * self.cine * (3 - 2 * self.cine)
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
            rect, s = QRectF(-220, -220, 440, 440), 1.0
        elif self.branch_rect.isValid():
            rect = self.branch_rect
            s = max(0.7, min(1.15, (vw - 80) / rect.width(), (vh - 110) / rect.height()))
        else:
            R = self.r1 * 1.24 + 90
            rect = QRectF(-R, -R, 2 * R, 2 * R)
            s = max(0.4, min(1.25, (vw - 80) / rect.width(), (vh - 110) / rect.height()))
        center = rect.center()
        if self.root_open and self.branch_rect.isValid():
            # 展开时左上留给黑洞；恒星在它下面（挡在黑洞前面），分支往右下展开，上沿不超过 CINE_TOP（避开吸积盘）。
            # 缩放和恒星位置在排布时已经算好（_cine_layout）
            s, star_sx = self._cine_fit
            top, bottom = vh * CINE_TOP, vh - 16
            h = rect.height() * s
            cy = bottom - h / 2 if h > bottom - top else (top + bottom) / 2      # 放不下时贴住下沿、往上长，不再缩小
            center = QPointF(rect.left() + 60 - (star_sx - vw / 2) / s, rect.center().y() - (cy - vh / 2) / s)
        self._cam0 = (self.cam_s, QPointF(self.cam_c), self.cine)
        self._cam1 = (s, center, self._cine_target())
        if animate:
            self.cam.start(self.clock.elapsed() / 1000, CAM_S)
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
        self._last_input = self.clock.elapsed() / 1000
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
        self.p_parts = ctx.program(vertex_shader=PARTICLE_VS, fragment_shader=DUST_FS)
        self.parts_buf = ctx.buffer(reserve=20 * 4 * 2048, dynamic=True)
        self.v_parts = ctx.vertex_array(self.p_parts, [(quad, '2f', 'in_corner'),
                                                       (self.parts_buf, '4f 4f 4f 4f 4f/i', 'a_from', 'a_to', 'a_time', 'a_look', 'a_misc')])
        self._parts_dirty = True
        self.p_beam = ctx.program(vertex_shader=BEAM_VS, fragment_shader=BEAM_FS)
        self.beam_buf = ctx.buffer(reserve=4 * 11 * 6 * BEAM_SEG * 64, dynamic=True)
        self.v_beam = ctx.vertex_array(self.p_beam, [(self.beam_buf, '2f 1f 1f 1f 1f 1f 4f', 'in_pos', 'in_x', 'in_w', 'in_along',
                                                      'in_s', 'in_kind', 'in_color')])
        self.off = {}
        self.atlas = None               # (纹理, 画的分辨率, {节点 key: (签名, uv, 左, 上, 宽, 高)})

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

    def _beams(self):
        """连线拼成三角形条带：恒星到黑洞是流进吸积盘的物质流；分支里是柔软的光丝。两种都有惯性，节点动时会弯、会拖一点。"""
        bx, by, shadow, el, roll = self.bh
        rd = DISK_OUT * shadow / 2.6 * 0.92             # 吸积盘外缘（屏幕像素）
        flat = max(0.05, math.sin(el))                  # 斜着看时盘被压扁的比例
        cr, sr = math.cos(roll), math.sin(roll)
        t = np.linspace(0, 1, BEAM_SEG + 1)
        now = self.clock.elapsed() / 1000
        dt = min(0.05, now - self._rope_t); self._rope_t = now
        paths, cols, kinds, mouths, alive = [], [], [], [], set()
        for n in self.nodes.values():
            a = self.nodes.get(n.parent_key)
            if a is None:
                continue
            op = min(a.opacity, n.opacity) * self.link_fade
            alive.add(n.key)
            if op < 0.02:
                continue
            if a.kind == 'center':
                # 物质流：一条平滑的三次曲线，从恒星出发，顺滑地汇进吸积盘边缘（落点在恒星方向和盘的椭圆交点，最后顺一点盘的转向）
                dx, dy = n.sx - bx, n.sy - by
                ux, uy = dx * cr + dy * sr, -dx * sr + dy * cr          # 转到盘的坐标（去掉滚转）
                r0 = math.hypot(ux, uy) or 1.0
                cx_, cy_ = ux / r0, uy / r0
                te = min(1 / math.sqrt(cx_ * cx_ / (rd * rd) + cy_ * cy_ / (rd * rd * flat * flat)), r0 * 0.6)
                ex, ey = cx_ * te, cy_ * te
                phi = math.atan2(ey / flat, ex)                         # 落点在椭圆上的参数角
                tx, ty = math.sin(phi) * rd, -math.cos(phi) * rd * flat  # 盘转的方向
                tl = math.hypot(tx, ty) or 1.0
                L = math.hypot(ux - ex, uy - ey) or 1.0
                ix, iy = (ex - ux) / L * 0.8 + tx / tl * 0.2, (ey - uy) / L * 0.8 + ty / tl * 0.2
                P = np.array([(ux, uy), (ux + (ex - ux) * 0.33, uy + (ey - uy) * 0.33),
                              (ex - ix * L * 0.3, ey - iy * L * 0.3), (ex, ey)])
                tt = t[:, None]; mt = 1 - tt
                q = mt ** 3 * P[0] + 3 * mt * mt * tt * P[1] + 3 * mt * tt * tt * P[2] + tt ** 3 * P[3]
                ideal = np.stack([bx + q[:, 0] * cr - q[:, 1] * sr, by + q[:, 0] * sr + q[:, 1] * cr], 1)
                # 尾迹：记下恒星最近的位置（世界坐标），按时间插值出每一段该在的地方
                wpos = n.base + n.offset(now)
                hist = self._trails.setdefault(n.key, [])
                hist.append((now, wpos.x(), wpos.y()))
                while len(hist) > 2 and hist[1][0] < now - TRAIL_T - 0.1:
                    hist.pop(0)
                ht = np.array(hist)
                ts = now - TRAIL_T * t
                off = np.stack([np.interp(ts, ht[:, 0], ht[:, 1]) - wpos.x(),
                                np.interp(ts, ht[:, 0], ht[:, 2]) - wpos.y()], 1) * TRAIL_W[:, None] * self.cam_s
                mag = np.hypot(off[:, 0], off[:, 1])
                lim = TRAIL_MAX * L
                off *= np.minimum(1.0, lim / np.maximum(mag, 1e-6))[:, None]
                paths.append(ideal + off)
                strength = 1.0 if (n.active or n.glow > 0.3) else 0.62
                cols.append((_rgba(n.color), _rgba(DISK_COLOR), op * strength)); kinds.append(0.05 + 0.9 * n.seed)
                mouths.append(STAR_R * n.k * (1 + STAR_ACTIVE * n.active))     # 漏斗口和恒星一样大
                continue
            # 柔软光丝：控制点有惯性。端点（世界坐标）动了，控制点只跟上一部分，剩下的靠弹簧追上，所以会晃、会拖
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
            P = np.array([p1, (ideal[0][0] + o[0] * k, ideal[0][1] + o[1] * k),
                          (ideal[1][0] + o[2] * k, ideal[1][1] + o[3] * k), p2])
            tt = t[:, None]; mt = 1 - tt
            paths.append(mt ** 3 * P[0] + 3 * mt * mt * tt * P[1] + 3 * mt * tt * tt * P[2] + tt ** 3 * P[3])
            cols.append((_rgba(a.color), _rgba(n.color), op * 0.9)); kinds.append(1.05 + 0.9 * n.seed)
            mouths.append(0.0)
        for key in [key for key in self._ropes if key not in alive]:
            del self._ropes[key]
        for key in [key for key in self._trails if key not in alive]:
            del self._trails[key]
        if not paths:
            return 0
        E, S = len(paths), BEAM_SEG
        pts = np.array(paths, 'f4')                                             # (E, S+1, 2)
        seglen = np.linalg.norm(np.diff(pts, axis=1), axis=2)
        along = np.concatenate([np.zeros((E, 1), 'f4'), np.cumsum(seglen, axis=1)], axis=1)
        # 物质流的宽度：在恒星那头和恒星差不多宽，离开两三个恒星半径就收成细流（漏斗）；分支光丝不用
        R = np.array(mouths, 'f4')[:, None]
        mouth = R > 0
        wid = np.where(mouth, 3.2 + R * 1.1 * np.exp(-(along / np.maximum(R * 2.8, 1e-3)) ** 1.3), 1.0).astype('f4')
        hw = np.where(mouth, np.maximum(BEAM_HW, wid * 2.4), BEAM_HW).astype('f4')        # 条带半宽，要盖住柔光
        tan = np.gradient(pts, axis=1)
        tan /= np.linalg.norm(tan, axis=2, keepdims=True) + 1e-6
        nor = np.stack([-tan[..., 1], tan[..., 0]], axis=2) * hw[..., None]
        tf = t.astype('f4')[None, :, None]
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
        t = self.clock.elapsed() / 1000
        self._advance(t)
        self._layout_screen()
        bh = self.bh[:3]

        fbo.use(); ctx.viewport = (0, 0, W, H)
        ctx.disable(moderngl.BLEND | moderngl.DEPTH_TEST | moderngl.CULL_FACE)
        e = self.cine * self.cine * (3 - 2 * self.cine)
        gt = t - self._gulp_t
        sky = dict(u_vp=(vw, vh), u_time=t, u_bh=bh, u_cine=e, u_ripple=(gt, 1.0 if 0 <= gt < 1.8 else 0.0),
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
        ctx.enable(moderngl.BLEND)
        holes, stars, pills = [], [], []
        for n in self.nodes.values():
            if n.opacity < 0.01:
                continue
            gl = max(n.glow, 1.0 if n.active else 0.0)
            if n.kind == 'center':
                ft = self.clock.elapsed() / 1000 - self._gulp_t      # 碎片被吸进去时黑洞亮一下
                gl = max(gl, smooth(-0.6, 0.0, ft) * (1 - smooth(0.3, 1.4, ft)))
                rs_px = n.rpx / 2.6                     # 看到的阴影比视界大 2.6 倍（光线被弯过来）
                half = rs_px * 11
                e = self.cine * self.cine * (3 - 2 * self.cine)
                holes.append((n.sx, n.sy, half, half) + _rgba(n.color) + (rs_px, gl, n.opacity, half,
                                                                         self.bh[3], self.bh[4], e, 0))
            elif n.kind == 'year':
                R = STAR_R * n.k * (1 + 0.12 * n.glow + STAR_ACTIVE * n.active) * (1 - 0.9 * n.doom) * (0.2 + 0.8 * n.form)
                R *= 1 + 0.15 * n.flash
                bright = 0.75 + 0.25 * max(-1, min(1, n.z / 140))
                # 朝向：平时指向黑洞（潮汐拉出的那一侧），被吞时是运动方向
                ang = n.dang if n.removing else math.atan2(self.bh[1] - n.sy, self.bh[0] - n.sx)
                stars.append((n.sx, n.sy, R * 5, R * 5) + _rgba(n.color) + (R, n.glow + 3 * n.flash, n.opacity * self._retreat(n), 1.0 if n.active else 0.0,
                                                                               n.seed, bright, n.doom, ang))
            else:
                k = n.k * (1 + 0.06 * n.glow) * (1 - 0.8 * n.doom)
                hw, hh = n.w / 2 * k, n.h / 2 * k
                cx, cy = n.screen_center().x(), n.sy
                par = self.nodes.get(n.parent_key)
                lx, ly = ((par.sx - cx), (par.sy - cy)) if par else (-1, 0)
                ln = math.hypot(lx, ly) or 1
                pills.append((cx, cy, hw + 30, hh + 30) + _rgba(n.color) + (hw, hh, gl, n.opacity,
                                                                         lx / ln, ly / ln, n.seed, 2.0 if n.kind == 'add' else 0.0))
        # 顺序：黑洞 → 连线（加色，叠在盘上汇进去）→ 恒星 → 胶囊
        if holes:
            # 黑洞逐像素追光线很费显卡，而且画面本身很柔和：按屏幕原分辨率单独画（像素少 4 倍），再放大叠进超采样画布
            hw_, hh_ = max(1, int(vw * dpr)), max(1, int(vh * dpr))
            hfbo, _, htex = self._offscreen('hole', hw_, hh_)
            hfbo.use(); ctx.viewport = (0, 0, hw_, hh_); hfbo.clear(0.0, 0.0, 0.0, 0.0)
            self._draw('hole', np.array(holes, 'f4'), False, vw, vh, t)
            fbo.use(); ctx.viewport = (0, 0, W, H)
            htex.use(0)
            ctx.blend_func = moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA
            self._set(self.p_down, u_tex=0, u_keep=1.0)
            self.v_down.render(moderngl.TRIANGLE_STRIP)
        for name, items in (('beam', None), ('star', stars), ('pill', pills)):
            if name == 'beam':
                ctx.blend_func = moderngl.ONE, moderngl.ONE
                nv = self._beams()
                if nv:
                    self._set(self.p_beam, u_vp=(vw, vh), u_time=t)
                    self.v_beam.render(moderngl.TRIANGLES, vertices=nv)
                continue
            if items:
                self._draw(name, np.array(items, 'f4'), False, vw, vh, t)

        if len(self.parts):
            if self._parts_dirty:
                data = self.parts.tobytes()
                if len(data) > self.parts_buf.size:
                    self.parts_buf.orphan(len(data) * 2)
                self.parts_buf.write(data)
                self._parts_dirty = False
            ctx.blend_func = moderngl.ONE, moderngl.ONE
            self._set(self.p_parts, u_vp=(vw, vh), u_cam=(self.cam_c.x(), self.cam_c.y(), self.cam_s), u_bh=bh, u_time=t)
            self.v_parts.render(moderngl.TRIANGLE_STRIP, instances=len(self.parts))
        if len(self.dust):
            d = self.dust
            sx = (d[:, 0] - self.cam_c.x()) * self.cam_s + vw / 2
            sy = (d[:, 1] - self.cam_c.y()) * self.cam_s + vh / 2
            size = np.maximum(0.6, d[:, 6] * min(1.6, self.cam_s))
            a = (d[:, 4] / d[:, 5]) ** 0.7
            z = np.zeros_like(sx)
            self._draw('dust', np.column_stack([sx, sy, size * 5, size * 5, d[:, 7], d[:, 8], d[:, 9], z + 1, size, a, d[:, 10],
                                                z, z, z, z, z]), True, vw, vh, t)
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
        e = self.cine * self.cine * (3 - 2 * self.cine)
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
                alpha = n.opacity * self._retreat(n) * (1 - smooth(0.15, 0.45, n.doom)) * (200 + 35 * max(float(n.active), n.glow)) / 255
                ax, ay, k = n.sx, n.sy + STAR_R * 1.3 * n.k * (1 + STAR_ACTIVE * n.active), n.k
            else:
                k = n.k * (1 + 0.06 * n.glow) * (1 - 0.8 * n.doom)
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
        dt = min(0.05, max(0.0, now - self._last_t)); self._last_t = now
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
                (not self.cam.running and abs(self.cine - self._cine_target()) > 0.05))
        if hide:
            self.link_fade = max(0.0, self.link_fade - dt * 10)
        else:
            self.link_fade = min(1.0, self.link_fade + dt * 3.5)
        for n in self.nodes.values():
            # 鼠标扰动：弹簧把节点拉回原位，阻尼接近临界，像在水里一样慢慢漂回去
            for i in (0, 1):
                if n.d[i] or n.v[i]:
                    n.v[i] += (-SPRING * n.d[i] - DAMP * n.v[i]) * dt
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
                      or self.cine != self._cine_target() or len(self.parts) > 0 or len(self.dust) > 0
                      or now - self._gulp_t < 1.8
                      or any(n.v[0] or n.v[1] or n.glow != (1.0 if n.hover else 0.0) for n in self.nodes.values()))
        if len(self.parts):                     # 星尘的位置由显卡算，这里只去掉已经结束的（碎片还要加上等待的时间）
            alive = self.parts[:, 8] + self.parts[:, 9] + np.where(self.parts[:, 10] == 2, self.parts[:, 11], 0) > now - 0.05
            if not alive.all():
                self.parts = self.parts[alive]
                self._parts_dirty = True
        if len(self.dust):                      # 晶尘：慢慢飘散、减速，寿命到了就去掉
            d = self.dust
            d[:, 0:2] += d[:, 2:4] * dt
            d[:, 2:4] *= math.exp(-2.6 * dt)
            d[:, 4] -= dt
            self.dust = d[d[:, 4] > 0]

    def _next_frame(self):
        if self.isVisible() and not self.window().isMinimized():
            if not self._busy:
                self._delay.start(IDLE_WAIT_MS)
                return
            # Qt 的显卡控件画完一帧后会让 CPU 空转等屏幕刷新（和画面大小无关，空白控件也占满一个核心）。
            # 所以掐着时间：上一帧开始后差不多一个刷新周期再开始画，几乎不用等，CPU 从约 100% 降到约 30%
            wait = 1 / MAX_FPS - FRAME_MARGIN - (self.clock.elapsed() / 1000 - self._last_t)
            if wait > 0:
                self._delay.start(max(1, round(wait * 1000)))
            else:
                self.update()

    def _kick(self):
        """看门狗：窗口从最小化恢复等情况下帧循环断了，重新启动。"""
        if self.clock.elapsed() / 1000 - self._last_t > 0.2:
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
        now = self.clock.elapsed() / 1000
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
            f = (1 - dist / PUSH_R) ** 2 * dt / max(0.3, n.k)  # 屏幕上的力换算成世界坐标
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
        self._last_input = self.clock.elapsed() / 1000
        self.cam.stop()
        self.popup.hide(); self.pop_timer.stop()
        if e.button() == Qt.LeftButton:
            self._press = (e.position(), False, QPointF(self.cam_c))
            n = self.node_at(e.position())
            # 全图里按住恒星：拖的是这颗恒星，不是整个画面
            self._drag_star = n if (n is not None and n.kind == 'year' and not self.fixed_view()) else None

    def mouseMoveEvent(self, e):
        self._last_input = self.clock.elapsed() / 1000
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
                w = self.unproject(pos.x(), pos.y())
                o = n.offset(self.clock.elapsed() / 1000)
                n.base = QPointF(w.x() - o.x(), w.y() - o.y())   # 跟着鼠标走（扣掉漂浮）
                n.polar1 = n.polar0 = (math.atan2(n.base.y(), n.base.x()), math.hypot(n.base.x(), n.base.y()))
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
        return self.anim.running or self.clock.elapsed() / 1000 < self._gulp_t + 0.3 or \
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
