# 恒星碎裂的碎片。点下去的那一刻，用显卡把所有碎片的运动整段模拟出来（transform feedback，一遍算 8 步），
# 路线存成一张显存里的纹理；之后每帧显卡按时间从纹理里取位置来画——收起正着放，展开倒着放（展开 = 收起倒放），
# CPU 不用逐帧算碎片。每颗恒星怎么碎（几块、多大、往哪迸）在 CPU 上算一次。
import math
import numpy as np
import moderngl
from shaders import SHARD_SIM_VS, SHARD_VS, SHARD_FS

SIM_HZ = 120              # 模拟、记录路线的步长（每秒多少步）
SIM_STEPS = 5 * SIM_HZ    # 最多模拟 5 秒（没掉进去的碎片 4.4 秒后淡掉）
PER_PASS = 8              # 显卡每一遍算几步（和 SHARD_SIM_VS 一致）
STRIDE = 10 * 16          # 每片碎片每一遍输出的字节数：状态 2 个 vec4 + 8 个位置
TEX_W = 8192              # 路线纹理的宽度（一遍的数据按顺序铺进去，取的时候按编号算位置）
# 碎片的引力按真实的平方反比：加速度 = SHARD_G / r²，朝着黑洞（离得近的很快掉进去，远的晚一些，越靠近越快）
SHARD_G = 8e7
SHARD_KT, SHARD_KR = 0.7, 0.0         # 引力接管后横向、径向的阻力
SHARD_CARRY = 120.0       # 恒星碎开时本身正被吸过去的速度，碎片继承一部分
TIDAL = 80.0              # 离黑洞近时，潮汐把碎片顺着指向黑洞的方向拉开（近的一侧往里、远的一侧往外）
# 三种碎片：火星（很多、很小、迸得快停得快）、碎片、大块（少、慢、阻力小，看起来沉）
SPARK, SHARD, CHUNK = 0, 1, 2
WEIGHT = np.array([0.3, 2.0, 8.0], 'f4')      # 算“吞了多少”、黑洞被照亮多少时，大块分量重


def tidal(r):
    """离黑洞多近（世界坐标的距离）→ 潮汐强度 0~1：150 以内最强，450 以外最弱。"""
    t = min(1.0, max(0.0, (450.0 - r) / 300.0))
    return t * t * (3 - 2 * t)


def fragments(rng, color, x0, y0, z0, R):
    """一颗半径 R 的恒星在世界坐标 (x0, y0, z0) 碎开时的碎片。离黑洞越近崩得越猛、碎得越细，顺着指向黑洞的方向被拉开。
    返回 (模拟的初始状态 (N, 8)，画用的参数 (N, 16))；画用参数里的编号、开始时间、步数之后再填。"""
    r0 = math.hypot(x0, y0) or 1.0
    ur = np.array([x0 / r0, y0 / r0])           # 从黑洞指向恒星
    td = tidal(r0)
    kc, km, ks = round(5 + 4 * td), round(18 + 16 * td), round(130 + 130 * td)
    # 大块：在恒星圆面上均匀铺开（向日葵排布 + 抖动），合起来盖住大半个圆面，碎开那一刻看起来就是恒星裂成了几块
    i = np.arange(kc) + 0.5
    rad, th = np.sqrt(i / kc) * 0.62 * R, i * 2.39996 + rng.uniform(0, 6.28)
    off_c = np.stack([rad * np.cos(th), rad * np.sin(th)], 1) + rng.normal(0, 0.06 * R, (kc, 2))
    size_c = R * math.sqrt(0.55 / kc) * rng.uniform(0.8, 1.15, kc)
    rad, th = np.sqrt(rng.random(km)) * 0.95 * R, rng.uniform(0, 6.28, km)
    off_m = np.stack([rad * np.cos(th), rad * np.sin(th)], 1)
    size_m = R * rng.uniform(0.07, 0.14, km)
    off_s = rng.normal(0, 0.4 * R, (ks, 2))
    size_s = rng.uniform(0.5, 1.5, ks)
    off = np.concatenate([off_c, off_m, off_s])
    size = np.concatenate([size_c, size_m, size_s])
    kind = np.repeat([CHUNK, SHARD, SPARK], [kc, km, ks])
    N = len(off)
    # 往外迸：大块慢、火星快；离黑洞越近越猛。方向带点随机，不是整齐地往外
    lo = np.array([70, 40, 18])[kind] * 1.0; hi = np.array([190, 100, 45])[kind] * 1.0
    sp = rng.uniform(lo, hi) * np.where(kind == SPARK, 0.7 + 0.8 * td, 0.6 + 0.9 * td)
    norm = np.hypot(off[:, 0], off[:, 1]) + 1e-3
    a = rng.normal(0, 0.5, N)
    ux, uy = off[:, 0] / norm, off[:, 1] / norm
    vx = (ux * np.cos(a) - uy * np.sin(a)) * sp
    vy = (ux * np.sin(a) + uy * np.cos(a)) * sp
    carry = SHARD_CARRY * rng.uniform(0.7, 1.3, N)
    stretch = (off @ ur) / R * TIDAL * td                      # 潮汐：靠黑洞的一侧被往里拉、外侧落在后面
    vx += ur[0] * (stretch - carry) + rng.normal(0, 10, N)
    vy += ur[1] * (stretch - carry) + rng.normal(0, 10, N)
    drag = np.array([1.4, 0.8, 0.35])[kind]
    init = np.zeros((N, 8), 'f4')
    init[:, 0], init[:, 1], init[:, 2], init[:, 3] = x0 + off[:, 0], y0 + off[:, 1], z0, vx
    init[:, 4], init[:, 6], init[:, 7] = vy, -1, drag
    c = np.array([color.redF(), color.greenF(), color.blueF()])
    w = rng.uniform(0, 0.3, (N, 1))
    look = np.zeros((N, 16), 'f4')
    look[:, 0:3] = init[:, 0:3]
    look[:, 6], look[:, 7] = kind, size
    look[:, 8:11] = c * (1 - w) + w
    look[:, 11] = rng.random(N)
    look[:, 12] = np.where(kind == CHUNK, rng.uniform(-1.5, 1.5, N), rng.uniform(-5, 5, N))
    look[:, 13] = np.where(kind == CHUNK, rng.uniform(0.95, 1.1, N), rng.uniform(0.85, 1.08, N)) * (0.9 + 0.1 * td)
    look[:, 14] = rng.uniform(0, 6.28, N)
    look[:, 15] = rng.uniform(*np.array([[0.35, 0.6], [0.5, 0.8], [1.0, 1.4]])[kind].T)      # 大块冷却得慢
    return init, look


class Burst:
    """一批碎片（一次收起或一次展开）：显存里的路线纹理 + 每片的参数；时间都相对 t0。"""

    def __init__(self, t0, forward, tex, inst, vao, start, steps, kind):
        self.t0, self.forward = t0, forward
        self.tex, self.inst, self.vao = tex, inst, vao
        self.n = len(start)
        # 每片碎片消失（掉进视界或淡掉）的时间；倒着放时是它汇到恒星上的时间
        life = np.minimum(steps, 4.4 * SIM_HZ) if forward else steps
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

    def __init__(self, system, init):
        ctx, N = system.ctx, len(init)
        self.system, self.ctx, self.N = system, ctx, N
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
        for k, v in dict(u_dt=1 / SIM_HZ, u_G=SHARD_G, u_RS=self.system.rs, u_KT=SHARD_KT, u_KR=SHARD_KR).items():
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

    def simulate(self, init):
        """开始在显卡上把这批碎片往前模拟 SIM_STEPS 步（分几帧提交，见 SimJob）。"""
        return SimJob(self, init)

    def add(self, t0, forward, tex, look, start, steps):
        """记下一批要画的碎片。start：每片开始的时间（相对 t0）；steps：路线有几步（正放时到掉进视界为止）。"""
        look = look.copy()
        look[:, 3] = np.arange(len(look))
        look[:, 4], look[:, 5] = start, steps
        inst = self.ctx.buffer(look.astype('f4').tobytes())
        vao = self.ctx.vertex_array(self.prog, [(self.quad, '2f', 'in_corner'), (inst, '4f 4f 4f 4f/i', 'i_a', 'i_b', 'i_c', 'i_d')])
        b = Burst(t0, forward, tex, inst, vao, start, steps, look[:, 6].astype(int))
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
                             u_n=b.n, u_w=TEX_W, u_rec=0, u_time=now).items():
                m = prog.get(k, None)
                if m is not None:
                    m.value = v
            b.vao.render(moderngl.TRIANGLE_STRIP, instances=b.n)
