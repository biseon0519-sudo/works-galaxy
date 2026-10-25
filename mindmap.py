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
RS = 34                   # 全图时黑洞阴影（看到的黑色圆）的半径（世界坐标）
EL_MAP, EL_CINE = 0.22, 0.10          # 黑洞仰角（弧度）：全图稍微斜着看；展开时几乎侧视，像飞船飞到黑洞旁边
CINE_X, CINE_SHADOW = 0.15, 0.10      # 展开时黑洞在画面左边的位置（占宽度的比例）、阴影半径（占高度的比例）
CINE_ROLL = -0.10         # 展开时黑洞稍微歪一点，更有镜头感
DISK_OUT = 6.2            # 吸积盘外缘（以视界半径为单位，和着色器里的 R_OUT 一致）
SWALLOW_MS, BIRTH_MS = 1300, 1000     # 收起时被黑洞吞掉、展开时从黑洞里螺旋飞出的动画时长
# 收起时恒星化成星尘被吸进去（艺术化的“越过洛希极限解体”，和胶囊碎成晶尘同一个路子）：
# 恒星飞向黑洞、轻微拉长，到洛希极限时化成一小团闪烁的星尘，先轻轻飘开，再被越来越强的吸力带着旋转落进吸积盘
ROCHE = RS * 4.0          # 洛希极限（世界坐标，离黑洞中心）
TDE_AT = 0.42             # 动画进行到多少时化成星尘
TDE_N = 100               # 每颗恒星化成多少颗星尘
PULL0, PULL1 = 60.0, 1400.0           # 吸力：一开始很弱，随时间（秒）平方增强
SWIRL = 0.45              # 吸进去时带一点旋转（切向力占径向力的比例）
ROPE_LAG, ROPE_K, ROPE_D = 0.5, 22.0, 6.0     # 分支光丝的惯性：端点动时控制点只跟上一部分，再靠弹簧追上
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


def spiral_points(n, r0=175.0, gap=135.0, grow=46.0):
    """阿基米德螺旋 r = r0 + grow·θ 上按相同弧长 gap 取 n 个点，返回 [(角度, 半径)]。角度往负方向转（和吸积盘转向一致）。"""
    pts, th = [], 0.0
    for _ in range(n):
        r = r0 + grow * th
        pts.append((-th, r))
        th += gap / math.hypot(r, grow)
    return pts


def lerp(a, b, t):
    return a + (b - a) * t


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
    // 星星：满天都有，银河里密得多；最细的两层是满天的微光，远的一层动得最少
    float dens = band * (1.0 - lanes * 0.7);
    col += stars(sp + u_pan * 0.01, 3.2, 0.06 + 0.5 * dens, 0.32) * (0.5 + 0.8 * dens);
    col += stars(sp + u_pan * 0.015, 5.5, 0.05 + 0.3 * dens, 0.42) * 0.9;
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

# 黑洞：逐像素追踪光线被黑洞弯曲的路径（光线步进），光线穿过吸积盘就把盘的光加上，掉进视界就是黑的。
# 光子环、盘的远侧被弯到上下方、多普勒一侧更亮、引力红移，都是算出来的，不是画上去的。
HOLE_FS = '''
#version 330
uniform float u_time;
in vec2 v_local; flat in vec4 v_color; flat in vec4 v_p1; flat in vec4 v_p2;
out vec4 f;
''' + NOISE + '''
const float R_IN = 2.3, R_OUT = 6.2;
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
    float n = mix(fbm(pp1 * 0.9 + vec2(rr * 0.6, 0.0)), fbm(pp2 * 0.9 + vec2(rr * 0.6, 0.0)), mixw);
    n = clamp((n - 0.5) * 1.5 + 0.5, 0.0, 1.0);             // 两层混合会把明暗抵消掉一些，补回对比度
    float streak = mix(fbm(pp1 * 0.35 + vec2(rr * 1.5, 3.0)), fbm(pp2 * 0.35 + vec2(rr * 1.5, 3.0)), mixw);    // 大尺度的明暗起伏
    float x = (rr - R_IN) / (R_OUT - R_IN);
    float T = pow(R_IN / rr, 0.9);                          // 越靠里越热
    vec3 base = mix(vec3(0.95, 0.28, 0.06), vec3(1.0, 0.78, 0.45), T);
    base = mix(base, vec3(1.0, 0.97, 0.9), T * T * 0.7);
    vec3 vel = normalize(vec3(-hit.z, 0.0, hit.x));         // 盘的转动方向
    float beta = sqrt(0.5 / rr);
    float dop = sqrt(1.0 - beta * beta) / (1.0 - beta * dot(vel, -v));     // 朝我们转来的一侧更亮
    float g = sqrt(max(0.0, 1.0 - 1.0 / rr));               // 引力红移
    float I = (pow(dop * g, 2.5) + 0.15) * pow(R_IN / rr, 1.2) * 1.6;
    float edge = smoothstep(0.0, 0.06, x) * (1.0 - smoothstep(0.35, 1.0, x));
    float dens = edge * (0.45 + 0.75 * n) * (0.92 + 0.16 * streak);     // 平滑的气体湍流（加细环会显得一条条的）
    return vec4(base * I * 3.0, clamp(dens * min(I * 1.5, 1.0), 0.0, 0.95));
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
    vec3 col = vec3(0.0); float alpha = 0.0;
    float b = dot(p, v), disc = b * b - (dot(p, p) - 24.0 * 24.0);
    if (disc > 0.0){                                        // 光线会经过黑洞附近：先直线走过去，再一步步算弯曲
        p += v * (-b - sqrt(disc));
        vec3 hc = cross(p, v); float h2 = dot(hc, hc);
        bool captured = false;
        for (int i = 0; i < 360; i++){
            float r = length(p);
            float dt = clamp(0.045 * r, 0.012, 0.45);
            v += -1.5 * h2 * p / pow(r, 5.0) * dt;
            vec3 pn = p + v * dt;
            if (p.y * pn.y < 0.0){
                vec3 hit = mix(p, pn, p.y / (p.y - pn.y));
                float rr = length(hit.xz);
                if (rr > R_IN && rr < R_OUT){
                    vec4 e = disk(hit, rr, normalize(v));
                    if (v.y > 0.0) e *= vec4(0.3, 0.3, 0.3, 0.45);     // 光线从下面穿上来 = 看到的是盘的底面（黑洞下方那道弧），压暗压细
                    col += (1.0 - alpha) * e.rgb * e.a;
                    alpha += (1.0 - alpha) * e.a;
                }
            }
            p = pn;
            if (dot(p, p) < 1.0){ captured = true; break; }
            if (r > 25.0 && dot(p, v) > 0.0) break;
            if (alpha > 0.98) break;
        }
        if (captured) alpha = 1.0;
    }
    float rq = length(q);
    col += vec3(1.0, 0.55, 0.25) * exp(-max(rq - 2.6, 0.0) * 0.4) * 0.09 * (1.0 + hv) * (1.0 - alpha);
    col = 1.0 - exp(-col * 1.25);                           // 色调映射，亮处不发白爆掉
    float win = 1.0 - smoothstep(0.8, 1.0, max(abs(v_local.x), abs(v_local.y)) / half_);
    f = vec4(col * op * win, alpha * op * win);
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
    vec2 q = v_local / R, q0 = q;
    vec3 c = v_color.rgb;
    float doom = v_p2.z, dang = v_p2.w;
    if (doom > 0.0){                                        // 被黑洞吞掉：顺着运动方向拉长、变红
        vec2 dd = vec2(cos(dang), sin(dang));
        float al = dot(q, dd);
        q += dd * (al / (1.0 + 1.5 * doom) - al);
        c = mix(c, vec3(1.0, 0.25, 0.08), doom * 0.8);
    }
    float r = length(q);
    float body = 1.0 - smoothstep(0.96, 1.04, r);
    float mu = sqrt(max(0.0, 1.0 - r * r));
    float limb = 0.35 + 0.65 * pow(mu, 0.55);
    float gran = fbm(q * 3.2 / (0.6 + mu) + vec2(u_time * 0.04, seed * 13.0));
    vec3 surf = mix(c, vec3(1.0), 0.3 * mu) * (0.55 + 0.75 * limb) * (0.85 + 0.35 * gran) * 1.9;
    float lift = (0.8 + 0.45 * hv + 0.35 * act) * bright * (0.92 + 0.08 * sin(u_time * 1.6 + seed * 20.0));
    lift *= 1.0 + 1.5 * smoothstep(0.3, 0.5, doom);          // 化成星尘前亮一下
    float corona = exp(-max(r - 1.0, 0.0) * 1.7) * 1.1 + exp(-max(r - 1.0, 0.0) * 0.6) * 0.18;
    vec3 em = c * corona * lift * (1.0 - smoothstep(3.2, 4.9, max(abs(q0.x), abs(q0.y))));   // 画到方块边缘前淡掉
    vec3 col = surf * body * (0.8 + 0.3 * lift) + em * (1.0 - body * 0.6);
    col = 1.0 - exp(-col * 1.3);
    f = vec4(col * op, body * op);
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
in vec2 in_pos; in float in_x; in float in_along; in float in_s; in float in_kind; in vec4 in_color;
out float v_x; out float v_along; out float v_s; flat out float v_kind; out vec4 v_color;
void main(){
    v_x = in_x; v_along = in_along; v_s = in_s; v_kind = in_kind; v_color = in_color;
    gl_Position = vec4(in_pos.x / u_vp.x * 2.0 - 1.0, 1.0 - in_pos.y / u_vp.y * 2.0, 0, 1);
}
'''
BEAM_FS = '''
#version 330
uniform float u_time;
in float v_x; in float v_along; in float v_s; flat in float v_kind; in vec4 v_color;
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
        // 物质流：一层断断续续的薄雾 + 往黑洞里流的粒子，越靠近黑洞流得越快
        float flow = v_along * (1.0 - 0.35 * v_s);    // 越靠近黑洞空间越“短”，同样速度看起来流得越快；对 along 的导数约 1 - 0.7s，始终为正，方向不会反
        float mist = fbm(vec2(flow * 0.018 - u_time * 0.5 + seed * 37.0, x * 0.15 + seed * 11.0));
        float haze = exp(-x * x / (2.0 * 3.2 * 3.2)) * (0.07 + 0.17 * smoothstep(0.38, 0.8, mist));   // 留一层最低亮度
        float pt = particles(flow + seed * 500.0, x, 30.0, 11.0, 1.0 + seed * 13.0, 3.5)
                 + particles(flow + seed * 300.0, x, 21.0, 17.0, 7.0 + seed * 13.0, 6.0) * 0.7;
        float fade = smoothstep(0.0, 0.12, v_s) * (1.0 - smoothstep(0.75, 1.0, v_s));
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

# 晶尘：胶囊碎掉时迸出的菱形小碎屑，会闪，带一点十字闪光；加色混合
DUST_FS = '''
#version 330
uniform float u_time;
in vec2 v_local; flat in vec4 v_color; flat in vec4 v_p1; flat in vec4 v_p2;
out vec4 f;
void main(){
    float s = v_p1.x, a = v_p1.y, ph = v_p1.z;
    vec2 q = v_local / s;
    if (v_p1.w > 0.5){                                       // 恒星碎屑：顺着运动方向拉长的柔和气团（短流线）
        vec2 dir = v_p2.xy;
        q = vec2(dot(q, dir) / max(v_p2.z, 1.0), dot(q, vec2(-dir.y, dir.x)));
        float r = length(q);
        float core = exp(-r * r * 0.9), halo = exp(-r * 0.9) * 0.25;
        float win2 = 1.0 - smoothstep(3.5, 5.0, max(abs(v_local.x), abs(v_local.y)) / (s * max(v_p2.z, 1.0)));
        f = vec4((v_color.rgb * (core * 1.3 + halo) + vec3(core * 0.3)) * a * win2, 0.0);
        return;
    }
    float dia = abs(q.x) + abs(q.y);
    float core = exp(-dia * dia * 1.2);
    float tw = 0.55 + 0.45 * sin(u_time * 9.0 + ph * 40.0);
    float spark = (exp(-abs(q.x) * 6.0) * exp(-abs(q.y) * 1.2) + exp(-abs(q.y) * 6.0) * exp(-abs(q.x) * 1.2)) * 0.35 * tw;
    vec3 col = v_color.rgb * (core * 1.4 + spark) + vec3(core * 0.5 * tw);
    float win = 1.0 - smoothstep(3.5, 5.0, max(abs(q.x), abs(q.y)));
    f = vec4(col * a * win, 0.0);
}
'''

DOWN_FS = '''
#version 330
uniform sampler2D u_tex;
in vec2 v_uv; out vec4 f;
void main(){ f = vec4(texture(u_tex, v_uv).rgb, 1.0); }
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
        self.swallow = None             # 正在被吞：(吞它的点, 起始半径, 起始角度, 一共转多少)
        self.doom = self.dang = 0.0     # 被吞的进度、运动方向（给恒星拉长用）
        self.fresh = False              # 刚出现（年份要从黑洞里螺旋飞出）

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
            r = self.rpx * 1.25 if self.kind == 'center' else (self.w / 2 + 6) * self.k
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
        self.link_fade = 1.0            # 连线整体的显示程度：展开、收起时先隐藏，稳定后再淡入
        self._link_hold = 0.0           # 到这个时间之前连线保持隐藏
        # 晶尘粒子，每行：世界 x、y，速度 x、y，剩余寿命，总寿命，大小，颜色 r、g、b，闪烁相位
        self.dust = np.zeros((0, 11), 'f4')
        # 恒星被撕碎后的碎屑，格式同上，坐标是以黑洞为原点、没压扁的盘面坐标
        self.debris = np.zeros((0, 11), 'f4')
        self._rope_t = 0.0

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
        # 旋臂：按时间顺序沿一条从黑洞旋出去的螺旋排，最早的离黑洞最近；每颗带一点固定的随机偏移和远近
        spiral = spiral_points(n)
        custom = doc.get('star_pos', {})        # 用户拖过的恒星：相对自动位置的偏移（没转动前的坐标）
        jit = {}
        for i, y in enumerate(years):
            r = random.Random(f'year{y}')
            a, rr = spiral[i]
            a += r.uniform(-0.1, 0.1); rr *= r.uniform(0.92, 1.08)
            x, yy = rr * math.cos(a), rr * math.sin(a)
            if str(y) in custom:
                x += custom[str(y)][0]; yy += custom[str(y)][1]
            jit[y] = (math.atan2(yy, x), math.hypot(x, yy), r.uniform(-140, 140))
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
            x2 = r1 + 240                       # 恒星和分类之间多留点距离
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

    def _disrupt(self, n, r, th):
        """恒星化成一小团星尘：在恒星的位置撒一把，先轻轻往四周飘开，之后由 _tick 里的吸力带进黑洞。"""
        rng = np.random.default_rng()
        c0 = np.array([r * math.cos(th), r * math.sin(th)])
        pos = c0 + rng.normal(0, STAR_R * 0.45, (TDE_N, 2))
        ang = rng.uniform(0, 2 * math.pi, TDE_N)
        sp = rng.uniform(15, 60, TDE_N)
        vel = np.stack([np.cos(ang) * sp, np.sin(ang) * sp], 1) + np.array([math.sin(th), -math.cos(th)]) * 35   # 顺着盘的转向带一点
        life = rng.uniform(2.4, 3.2, TDE_N)
        c = np.array([n.color.redF(), n.color.greenF(), n.color.blueF()])
        wmix = rng.uniform(0, 0.5, (TDE_N, 1))
        new = np.column_stack([pos, vel, life, life, rng.uniform(0.6, 1.4, TDE_N), c * (1 - wmix) + wmix,
                               rng.random(TDE_N)]).astype('f4')
        self.debris = np.concatenate([self.debris, new])

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
                if polar is not None:       # 新出来的年份从黑洞里螺旋着飞出去
                    node.polar0 = (polar[0] + 1.7 * math.pi, 0.0) if animate else polar
                node.fresh = animate
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
            if polar is not None and node.polar0 is not None and not node.fresh:     # 转最短的方向
                node.polar0 = (polar[0] - wrap_angle(polar[0] - node.polar0[0]), node.polar0[1])
        for key, node in self.nodes.items():
            if key not in targets and not node.removing:
                # 要消失的节点：绕着吞它的点（父节点；父节点也没了就是黑洞）螺旋着越转越快地掉进去
                node.removing = True
                par = targets.get(node.parent_key)
                P = par[6] if par else QPointF(0, 0)
                d = node.base - P
                r0, th0 = math.hypot(d.x(), d.y()), math.atan2(d.y(), d.x())
                if node.kind == 'year':
                    # 掉向黑洞：顺着盘的转向绕小半圈飞到洛希极限，在那里被撕碎（见 _disrupt）
                    node.swallow = (P, r0, th0, -0.8 * math.pi, ROCHE * (0.95 + 0.1 * node.seed), True)
                    node.disrupted = False
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
        if animate and moving:
            self._link_hold = float('inf')      # 有东西在飞：连线先隐藏，动画结束、稳定一会儿再出现
        if animate:
            years_out = any(n.removing and n.kind == 'year' for n in self.nodes.values())
            years_in = any(n.fresh and n.kind == 'year' for n in self.nodes.values())
            self.anim.stop()
            self.anim.setDuration(SWALLOW_MS if years_out else BIRTH_MS if years_in else ANIM_MS)
            self.anim.start()
        else:
            self._step(1.0); self._finish()

    def _step(self, t):
        t = float(t)
        tc = min(1.0, t)                        # 回弹曲线会超过 1：位置可以冲过头，透明度和远近不行
        raw = self.anim.currentTime() / max(1, self.anim.duration()) if self.anim.state() == QVariantAnimation.Running else 1.0
        for n in self.nodes.values():
            if n.removing and n.swallow is None:      # 碎成晶尘的胶囊：很快淡掉
                n.opacity = n.o0 * (1 - smooth(0.0, 0.18, raw))
                continue
            if n.removing:
                P, r0, th0, sw, r_end, into_hole = n.swallow
                if into_hole:
                    k = min(1.0, raw / TDE_AT)          # 0 → 1：飞到洛希极限
                    pr = k * k * (3 - 2 * k)
                    th = th0 + sw * k ** 1.3
                    r = lerp(r0, r_end, pr)
                    sq = lerp(1.0, 0.7, pr)             # 越靠近越接近盘面
                    n.base = QPointF(P.x() + r * math.cos(th), P.y() + r * math.sin(th) * sq)
                    n.doom = 0.5 * smooth(0.5, 1.0, k)   # 轻微拉长、变暖
                    n.dang = math.atan2(math.sin(th) * sq, math.cos(th))   # 沿指向黑洞的方向拉长
                    n.z = lerp(n.z0, 0.0, pr)
                    if raw >= TDE_AT and not n.disrupted:
                        n.disrupted = True
                        self._disrupt(n, r, th)
                    n.opacity = n.o0 * (1 - smooth(TDE_AT - 0.02, TDE_AT + 0.1, raw))   # 解体后星体很快消失，只剩碎屑
                    continue
                pr = raw * raw * (3 - 2 * raw)          # 半径：先慢、中间快、最后轻轻落进去
                th = th0 + sw * raw ** 1.5              # 角度：越转越快
                r = lerp(r0, r_end, pr)
                sq = lerp(1.0, math.sin(EL_MAP), pr ** 1.5) if into_hole else 1.0    # 越靠近越被压到盘面上
                n.base = QPointF(P.x() + r * math.cos(th), P.y() + r * math.sin(th) * sq)
                n.doom, n.dang = raw, th - math.pi / 2
                n.z = lerp(n.z0, n.z1, pr)
                n.opacity = n.o0 * (1 - smooth(0.55, 1.0, raw))      # 后面一段慢慢淡出
                if into_hole and math.sin(th) < 0:                    # 转到黑洞后面、在视界范围里：被挡住
                    n.opacity *= smooth(RS * 0.75, RS * 1.1, math.hypot(r * math.cos(th), r * math.sin(th) * sq))
                continue
            k = t
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
        if self._link_hold == float('inf'):
            self._link_hold = self.clock.elapsed() / 1000 + 0.3
        for n in self.nodes.values():
            n.polar0 = n.polar1
            n.fresh = False
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
        c = self.nodes.get('c')
        if c is not None:
            e = self.cine * self.cine * (3 - 2 * self.cine)
            c.sx = lerp(c.sx, self.width() * CINE_X, e)
            c.sy = lerp(c.sy, self.height() * 0.5, e)
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
        center = rect.center() + QPointF(0, -14 / s)    # 稍微往上一点，给底下的提示文字留位置
        if self.root_open and self.branch_rect.isValid():
            left = vw * 0.34                    # 展开时左边留给黑洞，恒星和分支放在右边
            aw = vw - left - 30
            s = max(0.6, min(1.15, aw / rect.width(), (vh - 110) / rect.height()))
            center = QPointF(rect.center().x() - (left + aw / 2 - vw / 2) / s, rect.center().y() - 14 / s)
        self._cam0 = (self.cam_s, QPointF(self.cam_c))
        self._cam1 = (s, center)
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

    def fixed_view(self):
        """展开某一年时是固定视角（黑洞在左边、分支在右边），不能拖动缩放；回到全图才可以。"""
        return self._cine_target() > 0.5

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.fixed_view() and self.doc is not None:
            self.fit(animate=False)

    def wheelEvent(self, e):
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
        self.p_down = ctx.program(vertex_shader=QUAD_VS, fragment_shader=DOWN_FS)
        self.v_sky = ctx.vertex_array(self.p_sky, [(quad, '2f', 'in_pos')])
        self.v_down = ctx.vertex_array(self.p_down, [(quad, '2f', 'in_pos')])
        self.sprites = {}
        for name, fs in (('hole', HOLE_FS), ('star', STAR_FS), ('pill', PILL_FS), ('dust', DUST_FS)):
            prog = ctx.program(vertex_shader=SPRITE_VS, fragment_shader=fs)
            inst = ctx.buffer(reserve=16 * 4 * 256, dynamic=True)
            # 着色器里没用到的变量会被编译器去掉，绑定时要跳过（16x = 空出 16 个字节）
            names = [a for a in ('i_rect', 'i_color', 'i_p1', 'i_p2') if a in prog]
            fmt = ' '.join('4f' if a in prog else '16x' for a in ('i_rect', 'i_color', 'i_p1', 'i_p2')) + '/i'
            vao = ctx.vertex_array(prog, [(quad, '2f', 'in_corner'), (inst, fmt, *names)])
            self.sprites[name] = (prog, inst, vao)
        self.p_beam = ctx.program(vertex_shader=BEAM_VS, fragment_shader=BEAM_FS)
        self.beam_buf = ctx.buffer(reserve=4 * 10 * 6 * BEAM_SEG * 64, dynamic=True)
        self.v_beam = ctx.vertex_array(self.p_beam, [(self.beam_buf, '2f 1f 1f 1f 1f 4f', 'in_pos', 'in_x', 'in_along',
                                                      'in_s', 'in_kind', 'in_color')])
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
        """连线拼成三角形条带：恒星到黑洞是流进吸积盘的物质流；分支里是柔软的光丝。两种都有惯性，节点动时会弯、会拖一点。"""
        bx, by, shadow, el, roll = self.bh
        rd = DISK_OUT * shadow / 2.6 * 0.92             # 吸积盘外缘（屏幕像素）
        flat = max(0.05, math.sin(el))                  # 斜着看时盘被压扁的比例
        cr, sr = math.cos(roll), math.sin(roll)
        t = np.linspace(0, 1, BEAM_SEG + 1)
        now = self.clock.elapsed() / 1000
        dt = min(0.05, now - self._rope_t); self._rope_t = now
        paths, cols, kinds, alive = [], [], [], set()
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
        for key in [key for key in self._ropes if key not in alive]:
            del self._ropes[key]
        for key in [key for key in self._trails if key not in alive]:
            del self._trails[key]
        if not paths:
            return 0
        E, S = len(paths), BEAM_SEG
        pts = np.array(paths, 'f4')                                             # (E, S+1, 2)
        tan = np.gradient(pts, axis=1)
        tan /= np.linalg.norm(tan, axis=2, keepdims=True) + 1e-6
        nor = np.stack([-tan[..., 1], tan[..., 0]], axis=2) * BEAM_HW
        seglen = np.linalg.norm(np.diff(pts, axis=1), axis=2)
        along = np.concatenate([np.zeros((E, 1), 'f4'), np.cumsum(seglen, axis=1)], axis=1)
        tf = t.astype('f4')[None, :, None]
        c0 = np.array([c[0] for c in cols], 'f4'); c1 = np.array([c[1] for c in cols], 'f4')
        col = c0[:, None, :] + (c1 - c0)[:, None, :] * tf                      # (E, S+1, 4)
        col[..., 3] = np.array([c[2] for c in cols], 'f4')[:, None]
        sv = np.broadcast_to(tf, (E, S + 1, 1))
        kv = np.broadcast_to(np.array(kinds, 'f4')[:, None, None], (E, S + 1, 1))
        left, right = pts - nor, pts + nor

        def vert(side, x, i):
            return np.concatenate([side[:, i], np.full((E, S, 1), x, 'f4'), along[:, i, None], sv[:, i], kv[:, i], col[:, i]], axis=2)
        a, b = slice(0, S), slice(1, S + 1)
        A, B, C, D = vert(left, -BEAM_HW, a), vert(right, BEAM_HW, a), vert(left, -BEAM_HW, b), vert(right, BEAM_HW, b)
        data = np.stack([A, B, C, B, D, C], axis=2).astype('f4').tobytes()     # (E, S, 6, 10)
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
        fbo, _, tex = self._offscreen(W, H)
        self._layout_screen()
        t = self.clock.elapsed() / 1000
        bh = self.bh[:3]

        fbo.use(); ctx.viewport = (0, 0, W, H)
        ctx.disable(moderngl.BLEND | moderngl.DEPTH_TEST | moderngl.CULL_FACE)
        self._set(self.p_sky, u_vp=(vw, vh), u_pan=(self.cam_c.x() * self.cam_s, self.cam_c.y() * self.cam_s), u_time=t, u_bh=bh)
        self.v_sky.render(moderngl.TRIANGLE_STRIP)
        ctx.enable(moderngl.BLEND)
        holes, stars, pills = [], [], []
        for n in self.nodes.values():
            if n.opacity < 0.01:
                continue
            gl = max(n.glow, 1.0 if n.active else 0.0)
            if n.kind == 'center':
                feed = 0.0
                if len(self.debris):                    # 碎屑落到黑洞附近越多，光晕越亮
                    near = np.hypot(self.debris[:, 0], self.debris[:, 1]) < RS * 2.5
                    feed = min(1.0, float(near.sum()) / 150.0)
                gl = max(gl, feed)
                rs_px = n.rpx / 2.6                     # 看到的阴影比视界大 2.6 倍（光线被弯过来）
                half = rs_px * 11
                holes.append((n.sx, n.sy, half, half) + _rgba(n.color) + (rs_px, gl, n.opacity, half,
                                                                         self.bh[3], self.bh[4], 0, 0))
            elif n.kind == 'year':
                R = STAR_R * n.k * (1 + 0.12 * n.glow + 0.15 * n.active) * (1 - 0.9 * n.doom)
                bright = 0.75 + 0.25 * max(-1, min(1, n.z / 140))
                stars.append((n.sx, n.sy, R * 5, R * 5) + _rgba(n.color) + (R, n.glow, n.opacity, 1.0 if n.active else 0.0,
                                                                               n.seed, bright, n.doom, n.dang))
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
        for name, items in (('hole', holes), ('beam', None), ('star', stars), ('pill', pills)):
            if name == 'beam':
                ctx.blend_func = moderngl.ONE, moderngl.ONE
                nv = self._beams()
                if nv:
                    self._set(self.p_beam, u_vp=(vw, vh), u_time=t)
                    self.v_beam.render(moderngl.TRIANGLES, vertices=nv)
                continue
            ctx.blend_func = moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA      # 预乘透明度
            if not items:
                continue
            prog, inst, vao = self.sprites[name]
            data = np.array(items, 'f4').tobytes()
            if len(data) > inst.size:
                inst.orphan(len(data) * 2)
            inst.write(data)
            self._set(prog, u_vp=(vw, vh), u_time=t)
            vao.render(moderngl.TRIANGLE_STRIP, instances=len(items))

        if len(self.debris):
            d = self.debris
            bx, by, shadow, el, roll = self.bh
            sc = shadow / RS                                    # 黑洞附近：屏幕像素 / 世界单位
            rr = np.hypot(d[:, 0], d[:, 1])
            close = np.clip((ROCHE - rr) / (ROCHE - RS * 2.2), 0, 1)
            close = close * close * (3 - 2 * close)
            sq = 0.7 + (max(0.05, math.sin(el)) - 0.7) * close
            X, Y = d[:, 0] * sc, d[:, 1] * sq * sc
            cr, sr = math.cos(roll), math.sin(roll)
            sx, sy = bx + X * cr - Y * sr, by + X * sr + Y * cr
            disk = np.array([DISK_COLOR.redF(), DISK_COLOR.greenF(), DISK_COLOR.blueF()])
            col = d[:, 7:10] * (1 - close[:, None]) + (disk * 0.8 + 0.2) * close[:, None]
            size = np.maximum(0.6, d[:, 6] * max(0.8, sc))
            a = np.minimum(1.0, (d[:, 4] / d[:, 5]) ** 0.5 * 1.2)
            # 转到黑洞后面（盘的远侧、在屏幕上偏上）又落在视界里的：被挡住
            behind = (Y * cr + X * sr) < 0
            a = a * np.where(behind, np.clip((np.hypot(X, Y) - shadow * 0.85) / (shadow * 0.25), 0, 1), 1.0)
            z = np.zeros_like(sx)
            inst = np.column_stack([sx, sy, size * 5, size * 5, col, z + 1, size, a, d[:, 10], z, z, z, z, z])   # 和晶尘一样的菱形闪光
            prog, buf, vao = self.sprites['dust']
            data = inst.astype('f4').tobytes()
            if len(data) > buf.size:
                buf.orphan(len(data) * 2)
            buf.write(data)
            ctx.blend_func = moderngl.ONE, moderngl.ONE
            self._set(prog, u_vp=(vw, vh), u_time=t)
            vao.render(moderngl.TRIANGLE_STRIP, instances=len(inst))
        if len(self.dust):
            d = self.dust
            sx = (d[:, 0] - self.cam_c.x()) * self.cam_s + vw / 2
            sy = (d[:, 1] - self.cam_c.y()) * self.cam_s + vh / 2
            size = np.maximum(0.6, d[:, 6] * min(1.6, self.cam_s))
            a = (d[:, 4] / d[:, 5]) ** 0.7
            z = np.zeros_like(sx)
            inst = np.column_stack([sx, sy, size * 5, size * 5, d[:, 7], d[:, 8], d[:, 9], z + 1, size, a, d[:, 10], z, z, z, z, z])
            prog, buf, vao = self.sprites['dust']
            data = inst.astype('f4').tobytes()
            if len(data) > buf.size:
                buf.orphan(len(data) * 2)
            buf.write(data)
            ctx.blend_func = moderngl.ONE, moderngl.ONE
            self._set(prog, u_vp=(vw, vh), u_time=t)
            vao.render(moderngl.TRIANGLE_STRIP, instances=len(inst))

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
                e = self.cine * self.cine * (3 - 2 * self.cine)
                if e > 0.95:
                    p.restore()
                    continue
                p.setOpacity(n.opacity * (1 - e))               # 展开时黑洞变成背景，名字淡掉
                below = max(n.rpx * 1.5, n.rpx / 2.6 * DISK_OUT * math.sin(self.bh[3]) + 8)    # 放在吸积盘下面
                p.translate(n.sx, n.sy + below); p.scale(n.k, n.k)
                p.setPen(QColor(255, 236, 210)); p.setFont(font(17, True))
                p.drawText(QRectF(-100, 0, 200, 24), Qt.AlignCenter, n.text)
                p.setPen(QColor(255, 210, 170, 170)); p.setFont(font(12))
                p.drawText(QRectF(-100, 24, 200, 18), Qt.AlignCenter, n.sub)
            elif n.kind == 'year':
                p.setOpacity(n.opacity * (1 - smooth(0.15, 0.45, n.doom)))      # 被吞时文字先淡掉
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
                k = n.k * (1 + 0.06 * n.glow) * (1 - 0.8 * n.doom)
                if k < 0.05:
                    p.restore()
                    continue
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
        hide = now < self._link_hold or self.cam.state() == QVariantAnimation.Running or self.cine != self._cine_target()
        lw = 0.0 if hide else 1.0
        if self.link_fade != lw:                # 隐藏得快、出现得慢
            self.link_fade = max(lw, self.link_fade - dt * 10) if hide else min(1.0, self.link_fade + dt * 2.2)
            busy = True
        want = self._cine_target()
        if self.cine != want:
            self.cine += (want - self.cine) * min(1.0, dt * 3.2)
            if abs(self.cine - want) < 0.002:
                self.cine = want
            busy = True
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
        if len(self.debris):
            d = self.debris
            age = d[:, 5] - d[:, 4]
            r = np.hypot(d[:, 0], d[:, 1]) + 1e-3
            ux, uy = d[:, 0] / r, d[:, 1] / r
            pull = (PULL0 + PULL1 * age * age) * dt          # 吸力越来越强
            d[:, 2] += (-ux + SWIRL * uy) * pull             # 往里吸，顺着盘的转向带点旋转
            d[:, 3] += (-uy - SWIRL * ux) * pull
            d[:, 2:4] *= math.exp(-1.2 * dt)
            d[:, 0:2] += d[:, 2:4] * dt
            d[:, 4] -= dt
            inner = np.hypot(d[:, 0], d[:, 1]) < RS * 0.95
            d[inner, 4] = np.minimum(d[inner, 4], 0.2)          # 落进盘内圈：很快消失
            self.debris = d[d[:, 4] > 0]
            busy = True
        if len(self.dust):                      # 晶尘：慢慢飘散、减速，寿命到了就去掉
            d = self.dust
            d[:, 0:2] += d[:, 2:4] * dt
            d[:, 2:4] *= math.exp(-2.6 * dt)
            d[:, 4] -= dt
            self.dust = d[d[:, 4] > 0]
            busy = True
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
            n = self.node_at(e.position())
            # 全图里按住恒星：拖的是这颗恒星，不是整个画面
            self._drag_star = n if (n is not None and n.kind == 'year' and not self.fixed_view()) else None

    def mouseMoveEvent(self, e):
        pos = e.position()
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
        self._set_hover(None)
        self._mouse = None
        super().leaveEvent(e)

    def _save_star(self, n):
        """把拖过的恒星位置存成相对自动位置的偏移（换算到没转动前的坐标，展开时整体转动也不会乱）。"""
        years = sorted(self.doc['years'])
        i = years.index(n.data)
        r = random.Random(f'year{n.data}')
        a, rr = spiral_points(len(years))[i]
        a += r.uniform(-0.1, 0.1); rr *= r.uniform(0.92, 1.08)
        c, s_ = math.cos(-self.phi), math.sin(-self.phi)
        bx, by = n.base.x() * c - n.base.y() * s_, n.base.x() * s_ + n.base.y() * c
        self.doc.setdefault('star_pos', {})[str(n.data)] = [round(bx - rr * math.cos(a), 1), round(by - rr * math.sin(a), 1)]
        self.layoutChanged.emit()

    def reset_star(self, year):
        self.doc.get('star_pos', {}).pop(str(year), None)
        self.layoutChanged.emit()
        self.relayout()

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
            if str(n.data) in self.doc.get('star_pos', {}):
                add(FIF.SYNC, '恢复自动位置', lambda: self.reset_star(n.data))
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
