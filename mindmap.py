# 宇宙风放射状导图（显卡渲染）：中心黑洞 → 一圈年份恒星 → 展开的那一年转到右边，伸出分类 → 作品（发光胶囊）。
# 画面全部由显卡着色器画（moderngl）：内部按 2 倍分辨率渲染再缩小（超采样，1080p 屏上相当于按 4K 画），文字最后用 QPainter 叠上去保持清晰。
# 位置按三维存（x, y, z），用透视投影画到屏幕上：远的小一点、暗一点，拖动时移动得慢一点。鼠标扰动和漂浮只在 x、y 平面上。
import math, random
import numpy as np
import moderngl
from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QVariantAnimation, QEasingCurve, QTimer, QElapsedTimer
from PySide6.QtGui import (QColor, QPainter, QPainterPath, QPixmap, QImage, QImageReader, QFont, QFontMetricsF, QPen,
                           QLinearGradient, QCursor, QGuiApplication, QSurfaceFormat)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QWidget
from qfluentwidgets import RoundMenu, Action, FluentIcon as FIF
import store
from widgets import cover_pixmap, draw_stars

FONT, DIGITS = 'Microsoft YaHei UI', 'Bahnschrift'      # 数字用 Bahnschrift（Windows 自带的窄体），更有科技感
NEON = {'文学作品': '#ffb86b', '音乐': '#ff5fa2', '小说': '#8c9bff', '电视剧': '#3ee6c4', '电影': '#ff7a59',
        '动漫': '#ffd84d', '综艺': '#b77bff', '鬼畜/梗': '#86ff6b', '游戏': '#4dc3ff'}
EXTRA = ['#ff8ad8', '#6bf0ff', '#ffe08a', '#9dff9d', '#c3a6ff']
STAR_COLORS = ['#ff9a5c', '#ffc46b', '#ffe6a8', '#fff4e0', '#e4ecff', '#b9cfff', '#8fb3ff', '#a99bff', '#d7a0ff']  # 恒星：橙 → 白 → 蓝紫
DISK_COLOR = QColor('#ffb36b')        # 黑洞吸积盘的颜色，中心到年份的光线从这个颜色开始

SS = 2                    # 超采样倍数（内部按几倍分辨率画）
MAX_TEX = 4096            # 内部画布最大边长
RS = 38                   # 黑洞事件视界半径（世界坐标）
STAR_R = 21               # 恒星半径
FOCAL = 900.0             # 透视焦距：z 越大越近
LEAF, GROUP_GAP = 36, 18  # 展开的分支里：每个作品占的高度、分类之间多空的距离
BEND = 0.00022            # 分支的弧度：离中线越远越往回收一点，看起来是一段圆弧
ANIM_MS = 700
FPS_BUSY, FPS_CALM = 60, 30           # 有动画/鼠标扰动时 60 帧；只是慢慢漂浮时 30 帧就够了，省 CPU
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


def lerp(a, b, t):
    return a + (b - a) * t


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

# 背景：深蓝渐变 + 缓慢流动的星云 + 三层视差星星（会闪），黑洞周围的星空被引力弯成光环
SKY_FS = '''
#version 330
uniform vec2 u_vp;        // 逻辑视口尺寸（像素）
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
    vec2 c = u_vp * 0.5;
    float dmax = max(u_vp.x, u_vp.y);
    vec3 col = mix(vec3(0.055, 0.086, 0.22), vec3(0.008, 0.012, 0.035), smoothstep(0.0, 0.8 * dmax, length(px - c)));
    // 引力透镜：看到的位置 px 对应的星空其实来自更靠近黑洞的地方，靠近视界的一圈会出现被放大的光环
    vec2 d = px - u_bh.xy; float r = max(length(d), 0.001);
    float E = u_bh.z * 2.3;
    vec2 src = px - d / r * (E * E / max(r, u_bh.z * 0.6));
    float lens = smoothstep(u_bh.z * 0.95, u_bh.z * 1.2, r);
    vec2 sp = mix(px, src, lens);
    // 星云
    vec2 np = (sp + u_pan * 0.05) / 520.0;
    float n = fbm(np + vec2(u_time * 0.006, -u_time * 0.004));
    float m = fbm(np * 1.7 + vec2(4.0, 1.0) - u_time * 0.003);
    vec3 neb = mix(vec3(0.42, 0.20, 0.85), vec3(0.0, 0.55, 0.85), smoothstep(0.3, 0.7, m));
    col += neb * smoothstep(0.38, 0.9, n) * 0.42;
    // 星星：远的一层动得最少
    col += stars(sp + u_pan * 0.02, 9.0, 0.10, 0.55);
    col += stars(sp + u_pan * 0.05, 23.0, 0.16, 0.8) * 1.2;
    col += stars(sp + u_pan * 0.10, 61.0, 0.22, 1.15) * 1.5;
    // 黑洞周围一圈被引力聚起来的暖光
    col += vec3(1.0, 0.6, 0.3) * exp(-max(r - u_bh.z, 0.0) / (u_bh.z * 2.5)) * 0.10 * lens;
    f = vec4(col, 1.0);
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

# 黑洞：纯黑的视界 + 光子环 + 斜看的吸积盘（内圈转得快、朝我们转来的一侧更亮），盘的远侧被引力弯到黑洞上方
HOLE_FS = '''
#version 330
uniform float u_time;
in vec2 v_local; flat in vec4 v_color; flat in vec4 v_p1; flat in vec4 v_p2;
out vec4 f;
''' + NOISE + '''
void main(){
    float rs = v_p1.x, hv = v_p1.y, op = v_p1.z;
    vec2 q = v_local / rs;
    float r = length(q);
    const float tilt = 0.26;
    vec2 e = vec2(q.x, q.y / tilt);
    float rho = length(e);
    float spin = u_time * 0.9 / pow(max(rho, 1.2), 1.5);
    float a = atan(e.y, e.x) + spin;
    float turb = fbm(vec2(cos(a), sin(a)) * rho * 1.6 + vec2(rho * 1.3, 0.0));
    float band = smoothstep(1.45, 1.9, rho) * (1.0 - smoothstep(3.0, 4.6, rho));
    float heat = clamp(1.0 - (rho - 1.6) / 2.6, 0.0, 1.0);
    vec3 hot = mix(vec3(1.0, 0.38, 0.10), vec3(1.0, 0.93, 0.78), heat * heat);
    float doppler = 1.0 - 0.6 * e.x / max(rho, 0.001);
    float disk = band * (0.35 + 1.1 * turb) * doppler * (0.55 + 0.8 * heat);
    float shadow = 1.0 - smoothstep(0.97, 1.03, r);
    float photon = exp(-pow((r - 1.06) / 0.035, 2.0)) * 1.1;
    float ang = atan(q.y, q.x);
    float lensed = exp(-pow((r - 1.38) / 0.17, 2.0)) * (0.25 + 0.75 * abs(q.y) / max(r, 0.001))
                 * (0.5 + 0.9 * fbm(vec2(ang * 2.5 + u_time * 0.25, r * 3.0)));
    float halo = exp(-max(r - 1.0, 0.0) * 0.9) * 0.18 * (1.0 + 0.5 * hv);
    vec3 front = (q.y > 0.0) ? hot * disk : vec3(0);
    vec3 back = hot * ((q.y <= 0.0) ? disk : 0.0) + hot * lensed * 0.9 + vec3(1.0, 0.86, 0.62) * photon + hot * halo;
    vec3 col = (back * (1.0 - shadow) + front) * (1.0 - smoothstep(3.6, 4.9, max(abs(q.x), abs(q.y))));
    col = 1.0 - exp(-col * 1.4);                    // 色调映射，亮处不发白爆掉
    f = vec4(col * op, shadow * op);
}
'''

# 恒星：边缘变暗的星体 + 缓慢翻涌的表面 + 日冕 + 四道星芒，会轻轻闪
STAR_FS = '''
#version 330
uniform float u_time;
in vec2 v_local; flat in vec4 v_color; flat in vec4 v_p1; flat in vec4 v_p2;
out vec4 f;
''' + NOISE + '''
void main(){
    float R = v_p1.x, hv = v_p1.y, op = v_p1.z, act = v_p1.w, seed = v_p2.x, bright = v_p2.y;
    vec2 q = v_local / R;
    float r = length(q);
    vec3 c = v_color.rgb;
    float body = 1.0 - smoothstep(0.96, 1.04, r);
    float mu = sqrt(max(0.0, 1.0 - r * r));
    float limb = 0.35 + 0.65 * pow(mu, 0.55);
    float gran = fbm(q * 3.2 / (0.6 + mu) + vec2(u_time * 0.04, seed * 13.0));
    vec3 surf = mix(c, vec3(1.0), 0.3 * mu) * (0.55 + 0.75 * limb) * (0.85 + 0.35 * gran) * 1.9;
    float lift = (0.8 + 0.45 * hv + 0.35 * act) * bright * (0.92 + 0.08 * sin(u_time * 1.6 + seed * 20.0));
    float corona = exp(-max(r - 1.0, 0.0) * 1.7) * 1.1 + exp(-max(r - 1.0, 0.0) * 0.6) * 0.18;
    float a = seed * 3.1;
    vec2 k = mat2(cos(a), -sin(a), sin(a), cos(a)) * q;
    float spikes = (exp(-abs(k.x) * 14.0) * exp(-abs(k.y) * 0.55) + exp(-abs(k.y) * 14.0) * exp(-abs(k.x) * 0.55)) * 0.9;
    vec3 em = c * (corona + spikes) * lift * (1.0 - smoothstep(3.2, 4.9, max(abs(q.x), abs(q.y))));   // 画到方块边缘前淡掉
    vec3 col = surf * body * (0.8 + 0.3 * lift) + em * (1.0 - body * 0.6);
    col = 1.0 - exp(-col * 1.3);
    f = vec4(col * op, body * op);
}
'''

# 胶囊（分类、作品、添加按钮）：深色玻璃身体 + 顶上一道高光 + 彩色描边，朝向光源的一侧描边更亮，外面一圈柔光
PILL_FS = '''
#version 330
in vec2 v_local; flat in vec4 v_color; flat in vec4 v_p1; flat in vec4 v_p2;
out vec4 f;
float sd(vec2 p, vec2 b){ float r = b.y; vec2 q = abs(p) - b + r; return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r; }
void main(){
    vec2 b = v_p1.xy; float hv = v_p1.z, op = v_p1.w;
    vec2 L = v_p2.xy; float kind = v_p2.w;
    vec3 c = v_color.rgb;
    vec2 p = v_local;
    float d = sd(p, b);
    vec2 n = normalize(vec2(sd(p + vec2(0.5, 0), b) - sd(p - vec2(0.5, 0), b), sd(p + vec2(0, 0.5), b) - sd(p - vec2(0, 0.5), b)) + 1e-5);
    float inside = 1.0 - smoothstep(-0.6, 0.6, d);
    float yN = clamp(p.y / b.y, -1.0, 1.0);
    vec3 body = mix(vec3(0.075, 0.095, 0.21), vec3(0.025, 0.035, 0.10), yN * 0.5 + 0.5) + c * (0.07 + 0.08 * hv);
    float spec = exp(-pow((d + 3.0) / 1.6, 2.0)) * smoothstep(0.1, -0.7, yN) * 0.28;
    float facing = max(0.0, dot(n, L));
    float border = exp(-pow(d / 0.9, 2.0));
    if (kind > 1.5) border *= step(0.45, fract(atan(p.y, p.x) * 10.0 / 6.2832 + 0.25));    // 添加按钮：虚线圈
    vec3 bcol = c * (0.55 + 1.0 * facing + 0.7 * hv);
    float out_ = max(d, 0.0);
    float glow = (exp(-out_ / (4.0 + 3.0 * hv)) * (0.16 + 0.30 * hv) + exp(-out_ / 14.0) * 0.06) * (1.0 - inside)
               * (1.0 - smoothstep(18.0, 29.0, out_));
    float bodyA = (kind > 1.5) ? 0.75 : 0.9;
    vec3 col = (body + vec3(spec)) * inside * bodyA + bcol * border + c * glow;
    float alpha = clamp(inside * bodyA + border * 0.4, 0.0, 1.0);
    f = vec4(col * op, alpha * op);
}
'''

# 光线：中间一条细亮线 + 一层宽的柔光，加色混合；有光脉冲沿着线往外流
BEAM_VS = '''
#version 330
uniform vec2 u_vp;
in vec2 in_pos; in float in_x; in float in_along; in vec4 in_color;
out float v_x; out float v_along; out vec4 v_color;
void main(){
    v_x = in_x; v_along = in_along; v_color = in_color;
    gl_Position = vec4(in_pos.x / u_vp.x * 2.0 - 1.0, 1.0 - in_pos.y / u_vp.y * 2.0, 0, 1);
}
'''
BEAM_FS = '''
#version 330
uniform float u_time;
in float v_x; in float v_along; in vec4 v_color;
out vec4 f;
void main(){
    float x = v_x;
    float core = exp(-x * x / (2.0 * 0.6 * 0.6));
    float halo = exp(-x * x / (2.0 * 3.0 * 3.0)) * 0.32;
    float far = exp(-abs(x) / 8.0) * 0.08;
    float pulse = 1.0 + 0.7 * pow(0.5 + 0.5 * sin(v_along * 0.022 - u_time * 2.0), 10.0);
    vec3 col = v_color.rgb * (core * 0.85 + halo + far) * pulse + vec3(core * 0.22);
    f = vec4(col * v_color.a, 0.0);
}
'''

DOWN_FS = '''
#version 330
uniform sampler2D u_tex;
in vec2 v_uv; out vec4 f;
void main(){ f = vec4(texture(u_tex, v_uv).rgb, 1.0); }
'''

BEAM_HW = 20.0            # 光线条带的半宽（屏幕像素），要盖住柔光的范围
BEAM_SEG = 18             # 每条线切成几段


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
            r = (RS * 1.6 if self.kind == 'center' else self.w / 2 + 6) * self.k
            return (x - self.sx) ** 2 + (y - self.sy) ** 2 <= r * r
        return self.sx - 3 <= x <= self.sx + self.w * self.k + 3 and abs(y - self.sy) <= self.h / 2 * self.k + 3

    def edge_point(self, other, out):
        """连线接在哪（屏幕像素）：圆形接在朝向对方的边上；胶囊进线接左端、出线接右端。"""
        if self.round():
            rad = {'center': RS * 1.65, 'year': STAR_R * 1.05, 'add': 13}[self.kind] * self.k
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
        self._mouse = None              # 上一次鼠标位置和时间，算划过的速度

        ease = QEasingCurve(QEasingCurve.OutBack); ease.setOvershoot(1.3)      # 展开时稍微冲过头再弹回来
        self.anim = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=ANIM_MS)
        self.anim.setEasingCurve(ease)
        self.anim.valueChanged.connect(self._step)
        self.anim.finished.connect(self._finish)
        self.cam = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=ANIM_MS)
        self.cam.setEasingCurve(QEasingCurve.OutCubic)
        self.cam.valueChanged.connect(self._cam_step)
        self.popup = CoverPopup()
        self.pop_timer = QTimer(self, singleShot=True, interval=220)
        self.pop_timer.timeout.connect(self._show_popup)
        self.clock = QElapsedTimer(); self.clock.start()
        self._last_t = 0.0
        self.ticker = QTimer(self, timerType=Qt.PreciseTimer, interval=1000 // FPS_CALM)
        self.ticker.timeout.connect(self._tick)

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
        self.relayout()
        self.fit()

    def toggle_cat(self, year, cat):
        self.collapsed ^= {(year, cat)}
        self.relayout()
        self.fit()

    def _targets(self):
        """算出每个该显示的节点：key → (kind, 父 key, 文字, 副文字, 颜色, 数据, 位置, 年份的极坐标或 None, z)。"""
        doc = self.doc
        years = sorted(doc['years'])
        n = max(1, len(years))
        step = 2 * math.pi / n
        self.r1 = r1 = max(280, n * 100 / (2 * math.pi))
        # 每年离中心的远近、角度、前后都带一点固定的随机偏移，看起来是自然散开的
        jit = {}
        for i, y in enumerate(years):
            r = random.Random(f'year{y}')
            jit[y] = (r.uniform(-0.22, 0.22) * step, r1 * r.uniform(0.8, 1.24), r.uniform(-140, 140))
        if self.expanded in years:              # 展开的那一年转到正右边，转最短的方向
            want = -(years.index(self.expanded) * step + jit[self.expanded][0])
            self.phi += wrap_angle(want - self.phi)
        counts = {}
        for w in doc['works']:
            counts[w['year']] = counts.get(w['year'], 0) + 1
        t = {'c': ('center', None, '年度作品', f'{len(doc["works"])} 个作品', DISK_COLOR, None, QPointF(0, 0), None, 0.0)}
        self.branch_rect = QRectF()
        if not self.root_open:
            return t
        for i, y in enumerate(years):
            a = self.phi + i * step + jit[y][0]
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
            x2 = r1 + 140
            cat_w = max([QFontMetricsF(font(14, True)).horizontalAdvance(c) for c, _, _ in groups] + [0]) + 70
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
                if polar is not None:
                    node.polar0 = (polar[0], 0.0) if animate else polar       # 新出来的年份从中心飞出去
                self.nodes[key] = node
            elif polar is not None:
                node.polar0 = (math.atan2(node.base.y(), node.base.x()), math.hypot(node.base.x(), node.base.y()))
            node.parent_key = parent
            node.set_content(text, sub, color, data)
            node.active = (kind == 'year' and data == self.expanded)
            node.p0, node.p1 = QPointF(node.base), pos
            node.z0, node.z1 = node.z, z
            node.o0, node.o1 = node.opacity, 1.0
            node.polar1 = polar
            if polar is not None and node.polar0 is not None:     # 转最短的方向
                node.polar0 = (polar[0] - wrap_angle(polar[0] - node.polar0[0]), node.polar0[1])
        for key, node in self.nodes.items():
            if key not in targets and not node.removing:
                node.removing = True
                par = targets.get(node.parent_key)
                node.p0, node.p1 = QPointF(node.base), (par[6] if par else QPointF(0, 0))
                node.z0, node.z1 = node.z, (par[8] if par else 0.0)
                node.o0, node.o1 = node.opacity, 0.0
                node.polar1 = None
                node.hover = False
        if animate:
            self.anim.stop(); self.anim.start()
        else:
            self._step(1.0); self._finish()

    def _step(self, t):
        t = float(t)
        tc = min(1.0, t)                        # 回弹曲线会超过 1：位置可以冲过头，透明度和远近不行
        for n in self.nodes.values():
            k = tc if n.removing else t
            if n.polar1 is not None and n.polar0 is not None:
                a, r = lerp(n.polar0[0], n.polar1[0], k), lerp(n.polar0[1], n.polar1[1], k)
                n.base = QPointF(r * math.cos(a), r * math.sin(a))
            else:
                n.base = QPointF(lerp(n.p0.x(), n.p1.x(), k), lerp(n.p0.y(), n.p1.y(), k))
            n.z = lerp(n.z0, n.z1, tc)
            n.opacity = max(0.0, min(1.0, lerp(n.o0, n.o1, tc)))
        self.update()

    def _finish(self):
        for key in [k for k, n in self.nodes.items() if n.removing]:
            del self.nodes[key]
        for n in self.nodes.values():
            n.polar0 = n.polar1
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

    def _layout_screen(self):
        t = self.clock.elapsed() / 1000
        for n in self.nodes.values():
            o = n.offset(t)
            n.sx, n.sy, n.k = self.project(n.base.x() + o.x(), n.base.y() + o.y(), n.z)

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
        self._cam0 = (self.cam_s, QPointF(self.cam_c))
        self._cam1 = (s, rect.center() + QPointF(0, -14 / s))    # 稍微往上一点，给底下的提示文字留位置
        self.cam.stop()
        if animate:
            self.cam.start()
        else:
            self._cam_step(1.0)

    def _cam_step(self, t):
        t = float(t)
        (s0, c0), (s1, c1) = self._cam0, self._cam1
        self.cam_s = s0 * (s1 / s0) ** t
        self.cam_c = QPointF(lerp(c0.x(), c1.x(), t), lerp(c0.y(), c1.y(), t))
        self.update()

    def wheelEvent(self, e):
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
        self.p_down = ctx.program(vertex_shader=QUAD_VS, fragment_shader=DOWN_FS)
        self.v_sky = ctx.vertex_array(self.p_sky, [(quad, '2f', 'in_pos')])
        self.v_down = ctx.vertex_array(self.p_down, [(quad, '2f', 'in_pos')])
        self.sprites = {}
        for name, fs in (('hole', HOLE_FS), ('star', STAR_FS), ('pill', PILL_FS)):
            prog = ctx.program(vertex_shader=SPRITE_VS, fragment_shader=fs)
            inst = ctx.buffer(reserve=16 * 4 * 256, dynamic=True)
            # 着色器里没用到的变量会被编译器去掉，绑定时要跳过（16x = 空出 16 个字节）
            names = [a for a in ('i_rect', 'i_color', 'i_p1', 'i_p2') if a in prog]
            fmt = ' '.join('4f' if a in prog else '16x' for a in ('i_rect', 'i_color', 'i_p1', 'i_p2')) + '/i'
            vao = ctx.vertex_array(prog, [(quad, '2f', 'in_corner'), (inst, fmt, *names)])
            self.sprites[name] = (prog, inst, vao)
        self.p_beam = ctx.program(vertex_shader=BEAM_VS, fragment_shader=BEAM_FS)
        self.beam_buf = ctx.buffer(reserve=4 * 8 * 6 * BEAM_SEG * 64, dynamic=True)
        self.v_beam = ctx.vertex_array(self.p_beam, [(self.beam_buf, '2f 1f 1f 4f', 'in_pos', 'in_x', 'in_along', 'in_color')])
        self.off = None

    def _offscreen(self, w, h):
        if self.off is None or self.off[1] != (w, h):
            if self.off is not None:
                self.off[0].release(); self.off[2].release()
            tex = self.ctx.texture((w, h), 4)
            tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            self.off = (self.ctx.framebuffer(color_attachments=[tex]), (w, h), tex)
        return self.off

    @staticmethod
    def _set(prog, **u):
        for k, v in u.items():
            m = prog.get(k, None)
            if m is not None:           # 着色器里没用到的变量会被编译器优化掉
                m.value = v

    def _beams(self):
        """所有连线拼成三角形条带：中心到年份是直线，分支里是平滑曲线；颜色从父节点渐变到子节点。"""
        segs = []
        for n in self.nodes.values():
            a = self.nodes.get(n.parent_key)
            if a is None:
                continue
            op = min(a.opacity, n.opacity)
            if op < 0.02:
                continue
            p1, p2 = a.edge_point(n, True), n.edge_point(a, False)
            if a.kind == 'center':
                c1 = (lerp(p1[0], p2[0], 1 / 3), lerp(p1[1], p2[1], 1 / 3))
                c2 = (lerp(p1[0], p2[0], 2 / 3), lerp(p1[1], p2[1], 2 / 3))
                strength = 1.0 if (n.active or n.glow > 0.3) else 0.5
            else:
                dx = (p2[0] - p1[0]) * 0.55
                c1, c2 = (p1[0] + dx, p1[1]), (p2[0] - dx, p2[1])
                strength = 0.9
            segs.append((p1, c1, c2, p2, _rgba(a.color), _rgba(n.color), op * strength))
        if not segs:
            return 0
        E = len(segs)
        P = np.array([[s[0], s[1], s[2], s[3]] for s in segs], 'f4')          # (E, 4, 2)
        t = np.linspace(0, 1, BEAM_SEG + 1, dtype='f4')[None, :, None]
        mt = 1 - t
        pts = mt ** 3 * P[:, None, 0] + 3 * mt * mt * t * P[:, None, 1] + 3 * mt * t * t * P[:, None, 2] + t ** 3 * P[:, None, 3]
        tan = np.gradient(pts, axis=1)
        tan /= np.linalg.norm(tan, axis=2, keepdims=True) + 1e-6
        nor = np.stack([-tan[..., 1], tan[..., 0]], axis=2) * BEAM_HW
        seglen = np.linalg.norm(np.diff(pts, axis=1), axis=2)
        along = np.concatenate([np.zeros((E, 1), 'f4'), np.cumsum(seglen, axis=1)], axis=1)
        c0 = np.array([s[4] for s in segs], 'f4'); c1 = np.array([s[5] for s in segs], 'f4')
        col = c0[:, None, :] + (c1 - c0)[:, None, :] * t                       # (E, S+1, 4)
        col[..., 3] = np.array([s[6] for s in segs], 'f4')[:, None]
        left, right = pts - nor, pts + nor

        def vert(side, x, i):
            return np.concatenate([side[:, i], np.full((E, BEAM_SEG, 1), x, 'f4'), along[:, i, None], col[:, i]], axis=2)
        a, b = slice(0, BEAM_SEG), slice(1, BEAM_SEG + 1)
        A, B, C, D = vert(left, -BEAM_HW, a), vert(right, BEAM_HW, a), vert(left, -BEAM_HW, b), vert(right, BEAM_HW, b)
        data = np.stack([A, B, C, B, D, C], axis=2).astype('f4').tobytes()     # (E, S, 6, 8)
        if len(data) > self.beam_buf.size:
            self.beam_buf.orphan(len(data) * 2)
        self.beam_buf.write(data)
        return E * BEAM_SEG * 6

    def paintGL(self):
        if self.ctx is None or self.doc is None:
            return
        ctx = self.ctx
        dpr = self.devicePixelRatioF()
        vw, vh = self.width(), self.height()
        ss = min(SS, MAX_TEX / max(1, vw * dpr), MAX_TEX / max(1, vh * dpr))
        W, H = max(1, int(vw * dpr * ss)), max(1, int(vh * dpr * ss))
        fbo, _, tex = self._offscreen(W, H)
        self._layout_screen()
        t = self.clock.elapsed() / 1000
        c = self.nodes.get('c')
        bh = (c.sx, c.sy, RS * c.k) if c else (-9999.0, -9999.0, 1.0)

        fbo.use(); ctx.viewport = (0, 0, W, H)
        ctx.disable(moderngl.BLEND | moderngl.DEPTH_TEST | moderngl.CULL_FACE)
        self._set(self.p_sky, u_vp=(vw, vh), u_pan=(self.cam_c.x() * self.cam_s, self.cam_c.y() * self.cam_s), u_time=t, u_bh=bh)
        self.v_sky.render(moderngl.TRIANGLE_STRIP)
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.ONE, moderngl.ONE              # 光线：加色
        nv = self._beams()
        if nv:
            self._set(self.p_beam, u_vp=(vw, vh), u_time=t)
            self.v_beam.render(moderngl.TRIANGLES, vertices=nv)
        ctx.blend_func = moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA      # 其余：预乘透明度
        holes, stars, pills = [], [], []
        for n in self.nodes.values():
            if n.opacity < 0.01:
                continue
            gl = max(n.glow, 1.0 if n.active else 0.0)
            if n.kind == 'center':
                holes.append((n.sx, n.sy, RS * n.k * 5, RS * n.k * 5) + _rgba(n.color) + (RS * n.k, gl, n.opacity, 0, 0, 0, 0, 0))
            elif n.kind == 'year':
                R = STAR_R * n.k * (1 + 0.12 * n.glow + 0.15 * n.active)
                bright = 0.75 + 0.25 * max(-1, min(1, n.z / 140))
                stars.append((n.sx, n.sy, R * 5, R * 5) + _rgba(n.color) + (R, n.glow, n.opacity, 1.0 if n.active else 0.0,
                                                                               n.seed, bright, 0, 0))
            else:
                k = n.k * (1 + 0.06 * n.glow)
                hw, hh = n.w / 2 * k, n.h / 2 * k
                cx, cy = n.screen_center().x(), n.sy
                par = self.nodes.get(n.parent_key)
                lx, ly = ((par.sx - cx), (par.sy - cy)) if par else (-1, 0)
                ln = math.hypot(lx, ly) or 1
                pills.append((cx, cy, hw + 30, hh + 30) + _rgba(n.color) + (hw, hh, gl, n.opacity,
                                                                         lx / ln, ly / ln, 0, 2.0 if n.kind == 'add' else 0.0))
        for name, items in (('hole', holes), ('star', stars), ('pill', pills)):
            if not items:
                continue
            prog, inst, vao = self.sprites[name]
            data = np.array(items, 'f4').tobytes()
            if len(data) > inst.size:
                inst.orphan(len(data) * 2)
            inst.write(data)
            self._set(prog, u_vp=(vw, vh), u_time=t)
            vao.render(moderngl.TRIANGLE_STRIP, instances=len(items))

        # 缩小到屏幕（超采样）
        screen = ctx.detect_framebuffer(self.defaultFramebufferObject())
        screen.use(); ctx.viewport = (0, 0, int(vw * dpr), int(vh * dpr))
        ctx.disable(moderngl.BLEND)
        tex.use(0)
        self._set(self.p_down, u_tex=0)
        self.v_down.render(moderngl.TRIANGLE_STRIP)
        # 交还给 QPainter 写字前，把显卡状态复原，免得互相干扰
        f = self.context().extraFunctions()
        f.glBindVertexArray(0); f.glUseProgram(0); f.glBindBuffer(0x8892, 0)
        f.glActiveTexture(0x84C0); f.glBindTexture(0x0DE1, 0)         # GL_TEXTURE0、GL_TEXTURE_2D
        f.glBindSampler(0, 0)
        f.glPixelStorei(0x0CF5, 4); f.glPixelStorei(0x0D05, 4)        # 解包 / 打包对齐恢复默认
        self._labels()

    def _labels(self):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        for n in self.nodes.values():
            if n.opacity < 0.05:
                continue
            p.setOpacity(n.opacity)
            p.save()
            if n.kind == 'center':
                p.translate(n.sx, n.sy + RS * 2.15 * n.k); p.scale(n.k, n.k)
                p.setPen(QColor(255, 236, 210)); p.setFont(font(17, True))
                p.drawText(QRectF(-100, 0, 200, 24), Qt.AlignCenter, n.text)
                p.setPen(QColor(255, 210, 170, 170)); p.setFont(font(12))
                p.drawText(QRectF(-100, 24, 200, 18), Qt.AlignCenter, n.sub)
            elif n.kind == 'year':
                p.translate(n.sx, n.sy + STAR_R * 1.35 * n.k * (1 + 0.15 * n.active)); p.scale(n.k, n.k)
                p.setFont(font(17, True, DIGITS))
                tw = p.fontMetrics().horizontalAdvance(n.text)
                sw = QFontMetricsF(font(12, False, DIGITS)).horizontalAdvance(n.sub) + 6 if n.sub else 0
                x0 = -(tw + sw) / 2
                p.setPen(QColor(255, 255, 255, 235 if (n.active or n.glow > 0.5) else 200))
                p.drawText(QRectF(x0, 0, tw + 2, 22), Qt.AlignLeft | Qt.AlignVCenter, n.text)
                if n.sub:
                    c = QColor(n.color); c.setAlpha(220)
                    p.setPen(c); p.setFont(font(12, False, DIGITS))
                    p.drawText(QRectF(x0 + tw + 6, 2, sw, 22), Qt.AlignLeft | Qt.AlignVCenter, n.sub)
            else:
                k = n.k * (1 + 0.06 * n.glow)
                p.translate(n.screen_center().x(), n.sy); p.scale(k, k)
                r = QRectF(-n.w / 2, -n.h / 2, n.w, n.h)
                if n.kind == 'add':
                    c = QColor(n.color); c.setAlpha(230)
                    p.setPen(c); p.setFont(font(18))
                    p.drawText(r.adjusted(0, -2, 0, -2), Qt.AlignCenter, '+')
                elif n.kind == 'cat':
                    tr = r.adjusted(16, 0, -16, 0)
                    p.setPen(QColor(255, 255, 255)); p.setFont(font(14, True))
                    p.drawText(tr, Qt.AlignLeft | Qt.AlignVCenter, n.text)
                    if n.sub:
                        p.setFont(font(13, False, DIGITS)); p.setPen(n.color.lighter(115))
                        p.drawText(tr, Qt.AlignRight | Qt.AlignVCenter, n.sub)
                else:
                    tr = r.adjusted(13, 0, -13, 0)
                    p.setFont(font(13)); p.setPen(QColor(255, 255, 255, 255 if n.glow > 0.5 else 228))
                    p.drawText(tr, Qt.AlignLeft | Qt.AlignVCenter,
                               p.fontMetrics().elidedText(n.text, Qt.ElideRight, int(tr.width()) + 1))
            p.restore()
        p.end()

    # ---------- 每一帧 ----------
    def _tick(self):
        if self.window().isMinimized():
            return
        now = self.clock.elapsed() / 1000
        dt = min(0.05, now - self._last_t); self._last_t = now
        busy = self.anim.state() == QVariantAnimation.Running or self.cam.state() == QVariantAnimation.Running
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
            if abs(n.glow - want) > 0.005:
                n.glow += (want - n.glow) * min(1.0, dt * 9)
                if abs(n.glow - want) <= 0.005:
                    n.glow = want
            busy = busy or bool(n.v[0] or n.v[1]) or n.glow != want
        self.ticker.setInterval(1000 // (FPS_BUSY if busy else FPS_CALM))
        self.update()

    def showEvent(self, e):
        super().showEvent(e)
        self.ticker.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.ticker.stop()

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
                if best is None or n.kind in ('work', 'cat', 'add'):    # 胶囊在上层，优先
                    best = n
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
        self.cam.stop()
        self.popup.hide(); self.pop_timer.stop()
        if e.button() == Qt.LeftButton:
            self._press = (e.position(), False, QPointF(self.cam_c))

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._press:
            d = pos - self._press[0]
            if not self._press[1] and abs(d.x()) + abs(d.y()) > 5:
                self._press = (self._press[0], True, self._press[2])     # 在拖动画布
                self.setCursor(Qt.ClosedHandCursor)
                self._set_hover(None)
            if self._press[1]:
                self.cam_c = self._press[2] - d / self.cam_s
                self._mouse = None
                self.update()
                return
        self._set_hover(self.node_at(pos))
        self.push(pos.x(), pos.y())

    def mouseReleaseEvent(self, e):
        press, self._press = self._press, None
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
        self._set_hover(None)
        self._mouse = None
        super().leaveEvent(e)

    def click(self, n):
        if n is None:
            return
        k = n.kind
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
