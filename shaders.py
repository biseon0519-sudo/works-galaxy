# 导图的着色器（GLSL 3.3）：背景星空、黑洞光追、恒星、水晶胶囊、连线、晶尘、文字、缩小到屏幕
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
float fbm4(vec2 p){ float v = 0., a = .5; for (int i = 0; i < 4; i++){ v += a * noise(p); p = p * 2.03 + vec2(1.7, 9.2); a *= .5; } return v + 0.03; }
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
    float n = mix(fbm4(pp1 * 0.9 + vec2(rr * 0.6, yv)), fbm4(pp2 * 0.9 + vec2(rr * 0.6, yv)), mixw);
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
            float dt = clamp(0.05 * r, 0.012, 0.6);
            float rr = length(p.xz);
            float hh = halfH(rr);
            bool inR = rr > R_IN * 0.8 && rr < R_OUT * 1.08;
            // 盘是一层有厚度的气体：快到盘时步子放小，穿过盘时一小步一小步地累加发光和遮挡（体积渲染）
            if (inR){
                float gap = max(abs(p.y) - hh * 2.4, 0.0);
                dt = min(dt, (gap + hh * 0.5) / max(abs(v.y), 1e-3));
                if (gap == 0.0) dt = min(dt, 0.2);         // 在盘里每步 0.2（再小看不出区别，只是更费显卡）
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
            if (trans < 0.03) break;
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
    float tear = v_p2.z, dang = v_p2.w;
    float tide = v_color.a;                                 // 被潮汐拉长的程度：0 = 圆的（展开时刚汇成是拉长的，慢慢恢复）
    float t = u_time;
    vec2 q = v_local / R, q0 = q;
    vec3 c = v_color.rgb;
    vec2 dd = vec2(cos(dang), sin(dang));                   // 指向黑洞
    float al = dot(q, dd);
    q -= dd * max(al, 0.0) * 0.08 / 1.08;                   // 潮汐：朝黑洞那半边轻轻鼓出来一点
    if (tide > 0.0){                                        // 潮汐：顺着指向黑洞的方向被拉长，两侧被挤扁
        float al2 = dot(q, dd);
        q = dd * al2 / (1.0 + 0.45 * tide) + (q - dd * al2) * (1.0 + 0.18 * tide);
    }
    float r = length(q);
    float body = 1.0 - smoothstep(0.97, 1.02, r);
    float keep = 1.0, rim = 0.0, body0 = body;              // body0：化开之前的星体范围（外圈柔光只画在它外面）
    if (tear > 0.0){
        // 原地解体：从外圈往里一层层蒸发，边缘不规则、发亮；剥下来的那一层就地变成粒子（shards.debris 按同样的顺序出发），
        // 所以粒子是从星体上出来的，不是星体消失后凭空出现（展开时倒过来：粒子汇过来，星体从中心长出来）。
        // 以前试过一道撕口扫过去（像月食，有残影）、到处冒洞（像奶牛斑、裂成好几片）、整颗一起变淡（和粒子接不上），都不好
        float n = fbm(q * 3.0 + seed * 7.0);
        // 还剩下的半径：刚开始蒸发时边缘很不规则（粒子出发也是半随机的），快没了时收成中间的一小团（展开时从中心长出来，不是从边上冒出来）
        float edge = 1.02 - tear * 1.15 + (n - 0.5) * 0.4 * (1.0 - tear);
        keep = 1.0 - smoothstep(edge - 0.05, edge + 0.01, r);
        float de = (r - edge) / 0.05;
        rim = exp(-de * de) * body * (1.0 - smoothstep(0.75, 1.0, tear));
        body *= keep;
    }
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
        surf *= 1.0 + 0.2 * tide;                           // 被撕开前越来越亮（被挤压、加热）
    }
    float o = max(r - 1.0, 0.0);
    vec2 dir = q / max(r, 1e-4);
    float lift = (0.85 + 0.4 * hv + 0.3 * act) * bright * (0.94 + 0.06 * sin(t * 1.6 + seed * 20.0)) * (1.0 + 0.2 * tide);
    // 色球层：贴着边缘的一圈细亮边；日珥：边上一缕缕往外喷的火焰；日冕：柔光 + 放射状亮纹
    float chrom = exp(-o * 28.0) * smoothstep(0.9, 1.0, r);
    float flame = fbm3(vec3(dir * 3.2 + seed * 17.0, o * 7.0 - t * 0.3));
    float prom = smoothstep(0.55, 0.8, flame) * exp(-o * 6.5) * smoothstep(0.98, 1.02, r);
    float streak = 0.5 + 0.9 * fbm3(vec3(dir * 2.2 + seed * 9.0, t * 0.03));
    float corona = exp(-o * 4.5) * 0.7 + exp(-o * 1.4) * 0.2 * streak;
    vec3 em = (c * corona + mix(c, vec3(1.0, 0.42, 0.22), 0.55) * (prom * 1.4 + chrom * 0.8)) * lift;
    em *= 1.0 - smoothstep(3.2, 4.9, max(abs(q0.x), abs(q0.y)));      // 画到方块边缘前淡掉
    // 一开始撕，外面的柔光就很快没了：柔光照亮了周围的星空，撕掉的那块没有柔光，对比起来像个跟着星体走的暗洞（残影）
    em *= exp(-tear * 12.0);
    vec3 col = surf * body * (0.85 + 0.25 * lift) + em * (1.0 - body0) + mix(c, vec3(1.0, 0.95, 0.85), 0.5) * rim * 1.6;
    col = 1.0 - exp(-col * 1.25);
    float shade = act * 0.45 * exp(-o * 1.3) * (1.0 - smoothstep(2.6, 4.6, max(abs(q0.x), abs(q0.y))));
    // 散到一半的地方主要是发光、不怎么挡后面（不然半透明的残块会显成暗灰的斑）
    f = vec4(col * op, (body * keep + (1.0 - body) * shade) * op);
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

# ---------- 物质流（stream.py）----------
# 坐标：以黑洞为中心、视界半径为单位，x 向右、y 向上（屏幕平面里，去掉了滚转），z 朝画面里面（和黑洞光追的相机一致）。
# 吸积盘所在的平面法线是 u_n（随仰角变）。每颗粒子单独模拟：从恒星朝黑洞那半边被扯下来，平方反比引力，
# 靠近黑洞时被盘“接住”——往盘面压、顺着盘的转向绕、慢慢往里旋；掉进去（或太久）就回到自己的恒星重新出发
STREAM_COMMON = '''
#define MAXS 32
uniform vec4 u_star[MAXS];    // 恒星：x、y、半径，还在不在往外喷（1 / 0）
float hsh(float x){ return fract(sin(x * 12.9898 + 78.233) * 43758.5453); }
'''

STREAM_SIM_VS = '''
#version 330
''' + STREAM_COMMON + '''
uniform vec2 u_svel[MAXS];    // 恒星的速度
uniform float u_dt, u_life, u_reset;
uniform float u_rspx;         // 一个视界半径是多少像素（流速按屏幕像素定，全图、近景看起来一样慢悠悠）
uniform float u_vflow, u_vdisk;               // 流速、在盘里绕的速度（像素/秒）
uniform float u_cap;          // 从多远开始被吸积盘接住（视界半径）
uniform int u_steps;
uniform vec3 u_n;
in vec4 in_a;                 // 位置 xyz，出发后过了多久（< 0 = 还在等着出发）
in vec4 in_b;                 // 速度 xyz，第几次出发（给随机数用）
in vec4 in_c;                 // 属于哪颗恒星，随机数，种类，大小
out vec4 out_a; out vec4 out_b;
void spawn(inout vec3 p, inout vec3 v, float seed, float gen, vec4 st, vec2 sv){
    float h1 = hsh(seed * 3.1 + gen * 1.7), h2 = hsh(seed * 5.3 + gen * 2.9);
    float h3 = hsh(seed * 7.7 + gen * 0.37), h4 = hsh(seed * 1.3 + gen * 4.1);
    vec2 S = st.xy; float rs = max(length(S), 1e-3);
    vec2 d = -S / rs, tc = vec2(-S.y, S.x) / rs;              // 指向黑洞；逆时针（和盘在屏幕上的转向一致）
    float a = (h1 - 0.5) * 2.6;                                // 从恒星朝黑洞的那半边出发，口子张得和恒星一样大
    vec2 dir = d * cos(a) + tc * sin(a);
    p = vec3(S + dir * st.z * 0.95, (h3 - 0.5) * st.z * 0.8);
    // 朝着黑洞慢慢出发。基本直着流向黑洞（没有固定的侧弯），弯曲只来自恒星移动时的惯性（sv），快到盘边时被盘接住、顺一点盘的转向
    vec2 aim = -p.xy / max(length(p.xy), 1e-3);
    v = vec3(sv + aim * u_vflow / u_rspx * (0.4 + 0.4 * h2), -p.z * 0.2);
}
void main(){
    vec3 p = in_a.xyz, v = in_b.xyz;
    float age = in_a.w, gen = in_b.w, seed = in_c.y;
    int o = int(in_c.x);
    vec4 st = u_star[o];
    if (u_reset > 0.5){                                       // 重新开始：出发时间在“流过去要多久”里错开，快进完就是匀匀的一股
        float trip = length(st.xy) * u_rspx / u_vflow;
        age = -hsh(seed * 9.7 + gen) * min(trip, u_life); gen += 1.0; v = vec3(0.0);
    }
    for (int s = 0; s < u_steps; s++){
        if (age < 0.0){                                       // 还没出发
            age += u_dt;
            if (age >= 0.0){
                if (st.w > 0.5){ spawn(p, v, seed, gen, st, u_svel[o]); age = 0.0; }
                else age = -0.2 - hsh(seed + gen) * clamp(length(st.xy) * u_rspx / u_vflow, 1.0, u_life);   // 恒星不在：等它出现，出发时间错开
            }
            continue;
        }
        float r = max(length(p), 1e-3);
        float rs0 = max(length(st.xy), 1e-3);
        // 慢悠悠地流过去：速度慢慢贴近“朝着黑洞、每秒 u_vflow 像素”，越靠近黑洞稍微快一点；
        // 贴近得不快（约 0.7 秒），所以恒星挪动时，已经在路上的粒子按惯性拖出弯
        float cap = smoothstep(u_cap, u_cap * 0.6, r);        // 吸积盘的范围：被盘接住
        vec3 want = -p / r * u_vflow / u_rspx * (1.0 + 0.6 * (1.0 - clamp(r / rs0, 0.0, 1.0)));
        float hgt = dot(p, u_n);
        vec3 pin = p - u_n * hgt;
        float rin = max(length(pin), 1e-3);
        vec3 tdir = cross(-u_n, pin) / rin;
        float vk = u_vdisk / u_rspx * sqrt(6.2 / max(rin, 2.0));
        vec3 vtar = tdir * vk - pin / rin * vk * 0.25;        // 在盘里顺着盘转，同时慢慢往里旋
        vec3 acc = (mix(want, vtar, cap) - v) * (1.5 + cap);
        float vt = dot(v, tdir);
        acc -= pin / rin * (vt * vt / rin) * cap;             // 绕圈要的向心力单独给，上面那项才能真的把它往里带
        acc -= u_n * (hgt * 4.0 + dot(v, u_n) * 2.0) * cap;   // 压到盘面上
        // 漏斗：刚出发的粒子被往“恒星—黑洞”这条线上收拢（临界阻尼），两三个恒星半径内收成细流；
        // 出发 2.5 秒后就不管了，恒星动的时候已经在路上的粒子照样按惯性拖出弯
        vec2 ax = -st.xy / rs0;
        vec2 lat = p.xy - ax * dot(p.xy, ax), vlat = v.xy - ax * dot(v.xy, ax);
        acc.xy -= (lat * 2.0 + vlat * 2.8) * (1.0 - smoothstep(1.5, 2.5, age)) * step(0.5, st.w);
        v += acc * u_dt;
        p += v * u_dt;
        age += u_dt;
        if (length(p) < 2.0 || age > u_life){                 // 掉进去了（或太久）：回到恒星重新出发
            gen += 1.0;
            if (st.w > 0.5){ spawn(p, v, seed, gen, st, u_svel[o]); age = 0.0; }
            else age = -0.2 - hsh(seed + gen) * clamp(length(st.xy) * u_rspx / u_vflow, 1.0, u_life);   // 恒星不在：等它出现，出发时间错开
        }
    }
    out_a = vec4(p, age); out_b = vec4(v, gen);
}
'''

STREAM_VS = '''
#version 330
''' + STREAM_COMMON + '''
uniform vec4 u_scol[MAXS];    // 恒星的颜色、这条流的透明度
uniform vec2 u_vp;
uniform vec3 u_bh;            // 黑洞在屏幕上的位置、一个视界半径是多少像素
uniform float u_roll, u_alpha;
uniform vec3 u_disk;          // 吸积盘的颜色
in vec2 in_corner;
in vec4 i_a;                  // 位置 xyz，出发后过了多久
in vec4 i_c;                  // 属于哪颗恒星，随机数，种类，大小
out vec2 v_local;
flat out vec4 v_col;
flat out vec2 v_kind;         // 种类、随机数
void main(){
    float age = i_a.w;
    if (age < 0.0){ gl_Position = vec4(-9.0, -9.0, 0.0, 1.0); v_col = vec4(0.0); v_local = vec2(0.0); v_kind = vec2(0.0); return; }
    vec3 p = i_a.xyz;
    float f = 40.0 / max(40.0 + p.z, 8.0);                    // 和黑洞光追一样的透视（相机在 40 个视界半径外）
    vec2 q = p.xy * f;
    vec2 local = mat2(cos(u_roll), -sin(u_roll), sin(u_roll), cos(u_roll)) * vec2(q.x, -q.y) * u_bh.z;
    int o = int(i_c.x);
    float kind = i_c.z, sz = i_c.w, r = length(p);
    float near = smoothstep(14.0, 3.0, r);                    // 越靠近黑洞越热、越细
    float Rpx = u_star[o].z * u_bh.z;                         // 恒星在屏幕上的半径
    float size = kind < 0.5 ? clamp(Rpx * sz * mix(1.0, 0.4, near), 1.5, 36.0) : max(0.7, Rpx * 0.035 * sz);
    float ext = size * 2.0;
    v_local = in_corner * 2.0;
    vec2 px = u_bh.xy + local + in_corner * ext;
    gl_Position = vec4(px.x / u_vp.x * 2.0 - 1.0, 1.0 - px.y / u_vp.y * 2.0, 0.0, 1.0);
    float a = smoothstep(0.0, 0.3, age) * smoothstep(2.0, 2.9, r);
    if (p.z > 0.0) a *= smoothstep(2.45, 2.8, length(q));     // 绕到黑洞后面：被挡住
    a *= 1.0 - 0.55 * smoothstep(6.5, 3.0, r);                // 汇进盘里，和盘的光融在一起
    vec3 col = mix(u_scol[o].rgb, u_disk, smoothstep(0.0, 1.0, near));
    col = mix(col, vec3(1.0, 0.95, 0.88), near * near * 0.5);
    v_col = vec4(col * (1.0 + 1.2 * near), a * u_scol[o].a * u_alpha);
    v_kind = vec2(kind, i_c.y);
}
'''

STREAM_FS = '''
#version 330
uniform float u_time;
in vec2 v_local; flat in vec4 v_col; flat in vec2 v_kind;
out vec4 f;
void main(){
    if (v_col.a <= 0.0) discard;
    vec2 q = v_local;
    float d2 = dot(q, q);
    float win = 1.0 - smoothstep(1.6, 2.0, max(abs(q.x), abs(q.y)));
    float I;
    if (v_kind.x < 0.5) I = exp(-d2 * 1.6) * 0.04;           // 一团薄薄的发光气体，叠在一起才是浓的
    else {                                                    // 亮点，会闪
        float tw = 0.6 + 0.4 * sin(u_time * (3.0 + 4.0 * v_kind.y) + v_kind.y * 40.0);
        I = exp(-d2 * 3.0) * 0.9 * tw;
    }
    f = vec4(v_col.rgb * I * v_col.a * win, 0.0);
}
'''

# ---------- 恒星被黑洞撕碎（shards.py）----------
# 模拟：transform feedback，每个顶点是一片碎片，一遍往前算 8 步（1/120 秒一步），把 8 个位置都输出来记下路线。
# 引力按平方反比朝着黑洞；刚迸开时阻力大（清脆地停住，小碎片阻力更大、大块更“沉”），之后只有横向一点阻力，
# 靠近黑洞时横向阻力加大（被盘里的气体拖住，不会擦过黑洞又被甩出去）
SHARD_SIM_VS = '''
#version 330
uniform float u_dt;
uniform int u_pass;
uniform float u_G, u_RS, u_KT, u_KR;
uniform float u_orbit;    // 漩涡：绕黑洞走的速度慢慢被带到圆轨道速度的这几成（0 = 没有漩涡）
uniform float u_swirl;    // 漩涡带起来的快慢（每秒）：粒子从星体上离开时几乎静止，被吸进去的路上越转越快
uniform float u_hold;     // 刚剥下来的这么多秒里先不受引力（展开倒放时 = 气体先汇到、停在原地，恒星再从里面凝出来）
in vec4 in_a;             // x, y, z, 速度 x
in vec4 in_b;             // 速度 y, 已过时间, 第几步掉进视界（-1 = 还没有）, 阻力倍数
out vec4 out_a; out vec4 out_b;
out vec4 out_p0; out vec4 out_p1; out vec4 out_p2; out vec4 out_p3;
out vec4 out_p4; out vec4 out_p5; out vec4 out_p6; out vec4 out_p7;
void main(){
    vec3 p = in_a.xyz; vec2 v = vec2(in_a.w, in_b.x);
    float age = in_b.y, done = in_b.z, drag = in_b.w;
    vec4 rec[8];
    for (int s = 0; s < 8; s++){
        float r = length(p.xy) + 1e-3;
        vec2 u = -p.xy / r;
        float m = max(r, u_RS * 1.2);
        float pull = smoothstep(u_hold, u_hold + 0.25, age);
        v += u * (u_G / (m * m)) * pull * u_dt;
        float early = 2.8 * drag * exp(-age * 2.5);
        v *= exp(-early * u_dt);
        vec2 tdir = vec2(-u.y, u.x);
        v += tdir * (u_orbit * sqrt(u_G / m) - dot(v, tdir)) * (1.0 - exp(-u_swirl * pull * u_dt));
        float vr = dot(v, u); vec2 vt = v - vr * u;
        vr *= exp(-u_KR * u_dt);
        float disk = 5.0 * clamp((u_RS * 4.0 - r) / (u_RS * 3.0), 0.0, 1.0);
        vt *= exp(-(u_KT + disk) * u_dt);
        v = vr * u + vt;
        p.xy += v * u_dt;
        p.z *= exp(-2.0 * u_dt);              // 慢慢落到黑洞所在的那一层
        age += u_dt;
        if (done < 0.0 && length(p.xy) < u_RS * 0.85) done = float(u_pass * 8 + s + 1);
        rec[s] = vec4(p, 0.0);
    }
    out_a = vec4(p, v.x); out_b = vec4(v.y, age, done, drag);
    out_p0 = rec[0]; out_p1 = rec[1]; out_p2 = rec[2]; out_p3 = rec[3];
    out_p4 = rec[4]; out_p5 = rec[5]; out_p6 = rec[6]; out_p7 = rec[7];
}
'''

# 画撕开的气体：按时间从记下的路线里取位置（收起正着放，展开倒着放），投影到屏幕；越靠近黑洞越贴近盘面，进视界消失
SHARD_VS = '''
#version 330
uniform vec2 u_vp;
uniform vec3 u_cam;       // 镜头看向的世界坐标 x、y，缩放
uniform vec3 u_bh;        // 黑洞在屏幕上的位置和阴影半径
uniform float u_t;        // 这批开始后过了多久（秒）
uniform float u_dir;      // 1 = 正着放（收起），-1 = 倒着放（展开）
uniform float u_hz, u_rs, u_focal;
uniform int u_n, u_w;     // 粒子数，路线纹理的宽度
uniform sampler2D u_rec;
uniform float u_streak;   // 1 = 速度拖尾
in vec2 in_corner;
in vec4 i_a;              // 起点 x、y、z，编号
in vec4 i_b;              // 开始时间，路线有几步，种类（0 亮点 / 1 气体 / 2 残留气云），大小
in vec4 i_c;              // 颜色 r、g、b，随机数
in vec4 i_d;              // 被撕到的时刻（秒），亮点的亮度，（没用），亮点变暗的快慢（秒）
out vec2 v_local;
flat out vec4 v_col;      // 颜色、透明度
flat out vec4 v_par;      // 亮点的亮度 / 离黑洞多近，随机数，被撕下来多久（秒），种类
vec3 at(int k){
    if (k <= 0) return i_a.xyz;
    int j = k - 1, pass = j / 8;
    int L = pass * u_n * 10 + int(i_a.w) * 10 + 2 + (j - pass * 8);
    return texelFetch(u_rec, ivec2(L % u_w, L / u_w), 0).xyz;
}
vec2 screen(vec3 p, out float kk){
    float close = clamp((u_rs * 4.0 - length(p.xy)) / (u_rs * 2.5), 0.0, 1.0);    // 越靠近黑洞越贴近盘面
    kk = u_cam.z * u_focal / (u_focal - p.z);
    return (vec2(p.x, p.y * (1.0 - 0.45 * close * close)) - u_cam.xy) * kk + u_vp * 0.5;
}
void main(){
    float n = i_b.y;
    float k = u_dir > 0.0 ? (u_t - i_b.x) * u_hz : n - 1.0 - (u_t - i_b.x) * u_hz;
    if (k < 0.0 || k > n - 1.0){
        gl_Position = vec4(-9.0, -9.0, 0.0, 1.0); v_col = vec4(0.0); v_par = vec4(0.0); v_local = vec2(0.0); return;
    }
    float kind = i_b.z, age = k / u_hz, born = age - i_d.x;
    int k0 = int(floor(k));
    vec3 p = kind < 1.5 ? mix(at(k0), at(k0 + 1), k - float(k0))
                        : i_a.xyz + vec3(normalize(i_a.xy) * 10.0 * age, 0.0);     // 残留气云留在撕开的地方，慢慢往外飘
    float kk;
    vec2 s = screen(p, kk);
    float a = clamp((length(s - u_bh.xy) - u_bh.z * 0.85) / (u_bh.z * 0.5), 0.0, 1.0);
    if (u_dir > 0.0 && kind < 1.5) a *= clamp((6.4 - age) / 0.6, 0.0, 1.0);      // 没掉进去的慢慢淡掉（和 shards.FADE_AT 一致）
    a *= smoothstep(0.0, 0.1, born);          // 星体散到它时才出现（各处随机）；展开时倒过来
    vec2 ax = vec2(1.0, 0.0), ay = vec2(0.0, 1.0);
    float ext, stretch = 1.0;
    if (kind < 1.5){
        // 速度拖尾：顺着屏幕上的运动方向拉长，越快越长；光摊开了就暗一点
        float k2;
        vec2 vs = (screen(at(k0 + 1), k2) - screen(at(k0), k2)) * u_hz;
        float sp = length(vs);
        if (sp > 1.0){ ax = vs / sp; ay = vec2(-ax.y, ax.x); }
        stretch = 1.0 + min(sp * 0.012, 3.0) * u_streak;
        a /= pow(stretch, 0.8);               // 光摊开在更长的一条上，总亮度不变多少
        if (kind < 0.5){                      // 亮点：和晶尘一样的菱形光点
            ext = max(0.6, i_b.w * min(1.6, kk)) * 5.0;
            v_local = in_corner * 5.0;
        } else {                              // 气体：按世界大小的一团柔光；刚从星体上剥下来时小一点，0.4 秒内胀成一团
            ext = max(1.5, i_b.w * kk * mix(0.75, 1.0, smoothstep(0.0, 0.4, born))) * 2.0;
            v_local = in_corner * 2.0;
        }
    } else {                                  // 残留气云：撕开的地方一大团淡淡的光，慢慢胀大、淡掉
        ext = i_b.w * kk * (1.0 + 0.3 * age) * 2.0;
        v_local = in_corner * 2.0;
        a *= smoothstep(0.0, 0.3, born) * (1.0 - smoothstep(0.6, 2.4, age));
    }
    vec2 px = s + (ax * in_corner.x * stretch + ay * in_corner.y) * ext;
    gl_Position = vec4(px.x / u_vp.x * 2.0 - 1.0, 1.0 - px.y / u_vp.y * 2.0, 0.0, 1.0);
    float near = smoothstep(u_rs * 7.0, u_rs * 1.5, length(p.xy));    // 越靠近黑洞越热、越亮
    v_col = vec4(i_c.rgb, a);
    v_par = vec4(kind < 0.5 ? i_d.y * exp(-age / i_d.w) : near, i_c.w, born, kind);
}
'''

SHARD_FS = '''
#version 330
uniform float u_time;
in vec2 v_local; flat in vec4 v_col; flat in vec4 v_par;
out vec4 f;
''' + NOISE + '''
void main(){
    float heat = v_par.x, seed = v_par.y, born = v_par.z, kind = v_par.w;
    float op = v_col.a;
    if (op <= 0.0) discard;
    // 带上恒星本来的颜色（淡色恒星先提饱和度，不然白的、淡蓝的恒星化开是一团白）
    vec3 cs = clamp(mix(vec3(dot(v_col.rgb, vec3(0.3, 0.59, 0.11))), v_col.rgb, 2.2), 0.0, 1.0);
    vec2 q = v_local;
    float edge = kind < 0.5 ? 5.0 : 2.0;
    float win = 1.0 - smoothstep(0.8, 1.0, max(abs(q.x), abs(q.y)) / edge);
    vec3 col;
    if (kind < 0.5){
        // 亮点：菱形光点 + 十字闪光，会闪，慢慢变暗；加色（透明度 0）
        float dia = abs(q.x) + abs(q.y);
        float core = exp(-dia * dia * 1.2);
        float tw = 0.55 + 0.45 * sin(u_time * 9.0 + seed * 40.0);
        float spark = (exp(-abs(q.x) * 6.0) * exp(-abs(q.y) * 1.2) + exp(-abs(q.y) * 6.0) * exp(-abs(q.x) * 1.2)) * 0.35 * tw;
        col = (mix(vec3(1.0), cs * 1.3, 0.5) * (core * 1.1 + spark) + vec3(core * 0.2 * tw)) * heat;
    } else if (kind < 1.5){
        // 气体：一团薄薄的发光等离子体（和物质流同一种画法），叠在一起就是恒星化开的那一大片；
        // 颜色从恒星本色慢慢变成吸积盘的暖色，越靠近黑洞越亮
        col = mix(cs * 1.2, vec3(1.0, 0.72, 0.42), heat) * (1.0 + 1.2 * heat) * exp(-dot(q, q) * 1.6) * 0.017;
        col *= 1.0 + 0.8 * (1.0 - smoothstep(0.0, 0.6, born));   // 刚从星体上散出来时亮一些，0.6 秒内暗下来
    } else {
        // 残留气云：边缘不规则的一团淡光，恒星本色偏暖
        float cloud = 0.55 + 0.9 * fbm(q * 1.3 + seed * 17.0 + u_time * 0.05);
        col = mix(cs, vec3(1.0, 0.6, 0.35), 0.35) * exp(-dot(q, q) * 1.4) * cloud * 0.04;
    }
    f = vec4(col * op * win, 0.0);
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

DOWN_FS = '''
#version 330
uniform sampler2D u_tex;
uniform float u_keep;     // 1 = 保留透明度（把单独画的黑洞叠上去），0 = 不透明（缩小到屏幕）
in vec2 v_uv; out vec4 f;
void main(){ vec4 c = texture(u_tex, v_uv); f = vec4(c.rgb, mix(1.0, c.a, u_keep)); }
'''
