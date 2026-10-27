# 恒星解体成气体被黑洞吸进去。点下去的那一刻，用显卡把所有气体的运动整段模拟出来（transform feedback，一遍算 8 步），
# 路线存成一张显存里的纹理；之后每帧显卡按时间从纹理里取位置来画——收起正着放，展开倒着放（展开 = 收起倒放），
# CPU 不用逐帧算。每颗恒星化成多少团气体、各自的初速度在 CPU 上算一次。
import math
import numpy as np
import moderngl
from shaders import SHARD_SIM_VS, SHARD_VS, SHARD_FS, GAS_K, GRAIN, GRAIN_SPAN, GRAIN_GO

SIM_HZ = 120              # 模拟、记录路线的步长（每秒多少步）
SIM_STEPS = 7 * SIM_HZ    # 最多模拟 7 秒（没掉进去的气体 FADE_AT 秒后淡掉）
FADE_AT = 6.4
PER_PASS = 8              # 显卡每一遍算几步（和 SHARD_SIM_VS 一致）
STRIDE = 10 * 16          # 每团气体每一遍输出的字节数：状态 2 个 vec4 + 8 个位置
TEX_W = 8192              # 路线纹理的宽度（一遍的数据按顺序铺进去，取的时候按编号算位置）
# 引力按真实的平方反比：加速度 = SHARD_G / r²，朝着黑洞（收起时乘一个系数，见 mindmap.C_G）
SHARD_G = 8e7
SHARD_KT = 0.7            # 横向阻力（靠近黑洞时再加大，被盘接住）
SPARK, GAS, CLOUD = 0, 1, 2
PER_STAR = (450, 80, 5)               # 每颗恒星化成多少团气体、亮点，撕开的地方留下几团残留气云（再多就太密太亮）
CLOUD_S = 2.4             # 残留气云持续多久（秒）：它留在原地，不按模拟的路线走
WEIGHT = np.array([0.3, 1.0, 0.0], 'f4')          # 算“吞了多少”、黑洞被照亮多少时，亮点分量轻，气云不算


def life_steps(look, done):
    """每个粒子要画几步：气体、亮点画到掉进视界（没掉进去就到模拟结束），气云按固定时长。"""
    steps = np.where(done >= 0, done, SIM_STEPS - 1)
    return np.where(look[:, 6] == CLOUD, int(CLOUD_S * SIM_HZ), steps)


def _h33(p):
    """和 STAR_FS 里的 h33 一样的散列（float32，结果和显卡上只差最后几位）。"""
    p = np.asarray(p, 'f4')
    p = (p * np.array([0.1031, 0.1030, 0.0973], 'f4')) % 1
    p = p + np.sum(p * (p[:, [1, 0, 2]] + np.float32(33.33)), 1, keepdims=True)
    return ((p[:, [0, 0, 1]] + p[:, [1, 0, 0]]) * p[:, [2, 1, 0]]) % 1


def grain_time(u, seed):
    """u：气体在星体上的位置（以气体分布的半径为 1）。返回它所在的晶胞碎开的时刻（tear 的 0~1），
    和 STAR_FS 里解体的晶胞一一对应：那一粒裂开、缩小的时候，这团气体从那里出发。"""
    g = u.astype('f4') * np.float32(GRAIN) + np.float32(seed * 37.0)
    gi = np.floor(g); gf = g - gi
    best, hc = np.full(len(u), 9.0, 'f4'), np.zeros(len(u), 'f4')
    for x in (-1, 0, 1):
        for y in (-1, 0, 1):
            o = np.array([x, y], 'f4')
            hh = _h33(np.concatenate([gi + o, np.full((len(u), 1), seed * 11.0, 'f4')], 1))
            rr = o + hh[:, :2] * np.float32(0.8) + np.float32(0.1) - gf
            d = np.sum(rr * rr, 1)
            better = d < best
            best[better], hc[better] = d[better], hh[better, 2]
    # 那粒淡掉一些以后才出发（气体叠在完整的星面上会把花纹盖成一片纯色），淡入的 0.1 秒和那粒淡掉的时间叠在一起
    return hc * GRAIN_SPAN + GRAIN_GO * (1 - GRAIN_SPAN)


def debris(rng, color, x0, y0, z0, R, tear_s=0.0, extras=True, burst=None, seed=0.0, spread=None):
    """一颗半径 R 的恒星在世界坐标 (x0, y0, z0) 原地解体时化成的气体。
    tear_s：星体碎完要多久，每团气体等它所在的那粒碎开时才出发（grain_time；seed 是恒星的随机数，和 STAR_FS 一致）。
    extras：要不要残留气云。spread：气体铺在多大的圆里（默认 R；展开那颗恒星画得大，铺开的范围跟着大，每团只稍微大一点，不然叠成一大团过亮的雾）。
    burst：(最小, 最大) 解体时朝各个方向轻轻飘开的速度（收起用）；None 是从静止开始（展开用：倒着放时气体汇到恒星那一刻正好停住）。
    返回 (模拟的初始状态 (N, 8)，画用的参数 (N, 16))；画用参数里的编号、开始时间、步数之后再填。"""
    ng, ns, nc = PER_STAR
    if not extras:
        nc = 0
    N = ng + ns + nc
    kind = np.repeat([GAS, SPARK, CLOUD], [ng, ns, nc])
    rad, th = np.sqrt(rng.random(N)), rng.uniform(0, 6.2832, N)               # 铺满整个恒星
    rad[kind == CLOUD] *= 0.5                                                 # 气云挤在中间
    spread = spread or R
    off = np.stack([rad * np.cos(th), rad * np.sin(th)], 1) * spread
    R = R * (spread / R) ** 0.5
    v = np.zeros((N, 2))
    if burst is not None:
        # 恒星本来是静止的，剥下来的气体也几乎静止，只朝随便哪个方向轻轻飘一点，很快被阻力刹住，
        # 在原地成实心的一团（都往外散会堆成外亮内空的“甜甜圈”）；之后交给引力和漩涡（SHARD_SIM_VS 的 u_orbit / u_swirl）
        a = rng.uniform(0, 6.2832, N)
        sp = rng.uniform(*burst, N)
        v = np.stack([np.cos(a), np.sin(a)], 1) * sp[:, None]
    init = np.zeros((N, 8), 'f4')
    init[:, 0], init[:, 1], init[:, 2] = x0 + off[:, 0], y0 + off[:, 1], z0
    init[:, 3], init[:, 4] = v[:, 0], v[:, 1]
    # 阻力倍数：往外飘的要很快刹住（像胶囊碎掉的晶尘）
    init[:, 6], init[:, 7] = -1, (np.where(kind == GAS, 0.1, 0.2) if burst is None else 0.9)
    c = np.array([color.redF(), color.greenF(), color.blueF()])
    w = rng.uniform(0, 0.25, (N, 1))
    look = np.zeros((N, 16), 'f4')
    look[:, 0:3] = init[:, 0:3]
    look[:, 6] = kind
    look[:, 7] = np.select([kind == GAS, kind == CLOUD], [R * rng.uniform(0.18, 0.38, N), R * rng.uniform(0.6, 0.9, N)],
                           rng.uniform(0.5, 1.3, N))
    look[:, 8:11] = c * (1 - w) + w
    look[:, 11] = rng.random(N)
    # 什么时候从星体上碎下来：它所在的那粒晶胞碎开的时刻（整颗星体各处随机，不分里外）。
    # 在那之前它待在原地不动（模拟的初始已过时间是负的，见 SHARD_SIM_VS）
    look[:, 12] = grain_time(off / spread, seed) * tear_s
    init[:, 5] = -look[:, 12]
    look[kind == CLOUD, 12] = tear_s * 0.3                                    # 气云在撕到一半时冒出来
    look[:, 13], look[:, 15] = 1.0, 3.0                                       # 亮点的亮度、慢慢变暗的快慢
    return init, look


class Burst:
    """一批碎片（一次收起或一次展开）：显存里的路线纹理 + 每片的参数；时间都相对 t0。"""

    def __init__(self, t0, forward, tex, inst, vao, start, steps, kind, streaks):
        self.t0, self.forward, self.streaks = t0, forward, streaks
        self.tex, self.inst, self.vao = tex, inst, vao
        self.n = len(start)
        # 每片碎片消失（掉进视界或淡掉）的时间；倒着放时是它汇到恒星上的时间
        life = np.minimum(steps, FADE_AT * SIM_HZ) if forward else steps
        self.gone = start + life / SIM_HZ
        self.weight = WEIGHT[kind]
        self.end = t0 + float(self.gone.max()) + 0.05

    def release(self):
        for o in (self.tex, self.inst, self.vao):
            o.release()


class SimJob:
    """一次碎片模拟。整段一起算显卡要约 8 毫秒，CPU 等它算完再取结果就会掉几帧，所以分到几帧里提交（pump），
    最后一遍提交后的下一帧再取结果（finish），那时显卡早算完了，不用等。"""
    PASSES_PER_FRAME = 20

    def __init__(self, system, init, g=SHARD_G, orbit=0.0, swirl=0.0, hold=0.0):
        ctx, N = system.ctx, len(init)
        self.system, self.ctx, self.N, self.g, self.orbit, self.swirl, self.hold = system, ctx, N, g, orbit, swirl, hold
        st = np.zeros((N, STRIDE // 4), 'f4'); st[:, :8] = init
        self.bufs = [ctx.buffer(st.tobytes()), ctx.buffer(reserve=N * STRIDE)]
        self.vaos = [ctx.vertex_array(system.sim, [(b, '4f 4f 128x', 'in_a', 'in_b')]) for b in self.bufs]
        self.passes = SIM_STEPS // PER_PASS
        self.rows = math.ceil(self.passes * N * STRIDE / (TEX_W * 16))
        self.rec = ctx.buffer(reserve=self.rows * TEX_W * 16)
        self.p = self.cur = 0

    def submitted(self):
        return self.p >= self.passes

    def pump(self):
        """再提交几遍。"""
        sim, N = self.system.sim, self.N
        for k, v in dict(u_dt=1 / SIM_HZ, u_G=self.g, u_RS=self.system.rs, u_KT=SHARD_KT, u_orbit=self.orbit,
                         u_swirl=self.swirl, u_hold=self.hold).items():
            sim[k].value = v
        for p in range(self.p, min(self.passes, self.p + self.PASSES_PER_FRAME)):
            sim['u_pass'].value = p
            self.vaos[self.cur].transform(self.bufs[1 - self.cur], moderngl.POINTS, vertices=N)
            self.ctx.copy_buffer(self.rec, self.bufs[1 - self.cur], size=N * STRIDE, write_offset=p * N * STRIDE)
            self.cur = 1 - self.cur
            self.p = p + 1

    def finish(self):
        """取结果：(路线纹理, 每片第几步掉进视界（没掉进去是 -1）)。"""
        done = np.frombuffer(self.bufs[self.cur].read(), 'f4').reshape(self.N, STRIDE // 4)[:, 6].astype(int)
        tex = self.ctx.texture((TEX_W, self.rows), 4, dtype='f4')
        tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
        tex.write(self.rec)
        for o in self.vaos + self.bufs + [self.rec]:
            o.release()
        return tex, done


class ShardSystem:
    def __init__(self, ctx, rs, focal):
        self.ctx, self.rs, self.focal = ctx, rs, focal
        self.sim = ctx.program(vertex_shader=SHARD_SIM_VS,
                               varyings=['out_a', 'out_b'] + [f'out_p{i}' for i in range(PER_PASS)])
        self.prog = ctx.program(vertex_shader=SHARD_VS, fragment_shader=SHARD_FS)
        self.quad = ctx.buffer(np.array([-1, -1, 1, -1, -1, 1, 1, 1], 'f4').tobytes())
        self.bursts = []

    def simulate(self, init, g=SHARD_G, orbit=0.0, swirl=0.0, hold=0.0):
        """开始在显卡上把这批碎片往前模拟 SIM_STEPS 步（分几帧提交，见 SimJob）。orbit、swirl、hold：见 SHARD_SIM_VS。"""
        return SimJob(self, init, g, orbit, swirl, hold)

    def add(self, t0, forward, tex, look, start, steps, streaks=True):
        """记下一批要画的碎片。start：每片开始的时间（相对 t0）；steps：路线有几步（正放时到掉进视界为止）；
        streaks：要不要速度拖尾。"""
        look = look.copy()
        look[:, 3] = np.arange(len(look))
        look[:, 4], look[:, 5] = start, steps
        inst = self.ctx.buffer(look.astype('f4').tobytes())
        vao = self.ctx.vertex_array(self.prog, [(self.quad, '2f', 'in_corner'), (inst, '4f 4f 4f 4f/i', 'i_a', 'i_b', 'i_c', 'i_d')])
        b = Burst(t0, forward, tex, inst, vao, start, steps, look[:, 6].astype(int), streaks)
        self.bursts.append(b)
        return b

    def active(self, now, forward=None):
        return any(now < b.end and (forward is None or b.forward == forward) for b in self.bursts)

    def near_hole(self, now):
        """正在掉进黑洞的碎片有多少（按分量算，0~1）：快掉进去（0.15 秒内）的占这批总量的比例，给黑洞亮度用。"""
        g = 0.0
        for b in self.bursts:
            if b.forward and now < b.end:
                dt = b.gone - (now - b.t0)
                g = max(g, float(b.weight[(dt >= 0) & (dt < 0.15)].sum() / (0.15 * b.weight.sum())))
        return min(1.0, g)

    def tidy(self, now):
        for b in [b for b in self.bursts if now > b.end + 0.2]:
            b.release()
            self.bursts.remove(b)

    def draw(self, now, vw, vh, cam_c, cam_s, bh):
        if not self.bursts:
            return
        ctx, prog = self.ctx, self.prog
        ctx.blend_func = moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA       # 大块是实心的（挡住后面），火星透明度 0 = 加色
        for b in self.bursts:
            if now >= b.end:
                continue
            b.tex.use(0)
            for k, v in dict(u_vp=(vw, vh), u_cam=(cam_c.x(), cam_c.y(), cam_s), u_bh=bh, u_t=now - b.t0,
                             u_dir=1.0 if b.forward else -1.0, u_hz=float(SIM_HZ), u_rs=float(self.rs), u_focal=float(self.focal),
                             u_n=b.n, u_w=TEX_W, u_rec=0, u_time=now, u_streak=1.0 if b.streaks else 0.0, u_gas=GAS_K).items():
                m = prog.get(k, None)
                if m is not None:
                    m.value = v
            b.vao.render(moderngl.TRIANGLE_STRIP, instances=b.n)
