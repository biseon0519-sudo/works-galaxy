# 恒星被黑洞撕碎（潮汐瓦解）。点下去的那一刻，用显卡把所有气体的运动整段模拟出来（transform feedback，一遍算 8 步），
# 路线存成一张显存里的纹理；之后每帧显卡按时间从纹理里取位置来画——收起正着放，展开倒着放（展开 = 收起倒放），
# CPU 不用逐帧算。每颗恒星化成多少团气体、各自的初速度在 CPU 上算一次。
import math
import numpy as np
import moderngl
from shaders import SHARD_SIM_VS, SHARD_VS, SHARD_FS

SIM_HZ = 120              # 模拟、记录路线的步长（每秒多少步）
SIM_STEPS = 5 * SIM_HZ    # 最多模拟 5 秒（没掉进去的气体 4.4 秒后淡掉）
PER_PASS = 8              # 显卡每一遍算几步（和 SHARD_SIM_VS 一致）
STRIDE = 10 * 16          # 每团气体每一遍输出的字节数：状态 2 个 vec4 + 8 个位置
TEX_W = 8192              # 路线纹理的宽度（一遍的数据按顺序铺进去，取的时候按编号算位置）
# 引力按真实的平方反比：加速度 = SHARD_G / r²，朝着黑洞。恒星大小范围内近的一侧比远的一侧受的引力大，
# 自己就会被拉成一长条（“意大利面化”）；再加上恒星本来绕着黑洞走的速度，这一长条会绕着黑洞旋进去
SHARD_G = 8e7
SHARD_KT, SHARD_KR = 0.7, 0.0         # 横向、径向的阻力（靠近黑洞时横向阻力再加大，被盘接住）
SHARD_CARRY = 120.0       # 恒星被撕开时本身正被吸过去的速度
ORBIT = 0.55              # 恒星绕黑洞走的速度（圆轨道速度的几成），顺着吸积盘转的方向
TIDAL = 90.0              # 潮汐：撕开那一刻，近的一侧已经比远的一侧走得快（拉长）、两侧往中间挤
GAS, SPARK = 1, 0
PER_STAR = (700, 120)     # 每颗恒星化成多少团气体、多少个亮点
WEIGHT = np.array([0.3, 1.0], 'f4')           # 算“吞了多少”、黑洞被照亮多少时，亮点分量轻


def tidal(r):
    """离黑洞多近（世界坐标的距离）→ 潮汐强度 0~1：150 以内最强，450 以外最弱。"""
    t = min(1.0, max(0.0, (450.0 - r) / 300.0))
    return t * t * (3 - 2 * t)


def debris(rng, color, x0, y0, z0, R, long_=1.0, thin=1.0, tear_s=0.0):
    """一颗半径 R 的恒星在世界坐标 (x0, y0, z0) 被撕开时化成的气体。离黑洞越近，拉得越长。
    long_、thin：撕开那一刻星体已经顺着黑洞方向被拉长、两侧被挤扁的比例，气体就铺在同样的椭圆里，接得上。
    tear_s：星体从朝黑洞的一侧到背面被撕完要多久，每团气体等撕到它那里才出现。
    返回 (模拟的初始状态 (N, 8)，画用的参数 (N, 16))；画用参数里的编号、开始时间、步数之后再填。"""
    r0 = math.hypot(x0, y0) or 1.0
    ur = np.array([x0 / r0, y0 / r0])           # 从黑洞指向恒星
    ut = np.array([y0 / r0, -x0 / r0])          # 绕黑洞走的方向（和吸积盘在屏幕上的转向一致）
    td = tidal(r0)
    ng, ns = PER_STAR
    N = ng + ns
    kind = np.repeat([GAS, SPARK], [ng, ns])
    rad, th = np.sqrt(rng.random(N)), rng.uniform(0, 6.2832, N)               # 铺满整个（被拉长的）恒星
    along, side = rad * np.cos(th), rad * np.sin(th)                          # 沿着 / 垂直于“黑洞—恒星”方向的位置（-1~1）
    off = (along * R * long_)[:, None] * ur + (side * R * thin)[:, None] * ut
    vc = math.sqrt(SHARD_G / r0)
    # 整颗恒星一起：被吸过去 + 绕着黑洞走；各部分之间：近的一侧往里冲、远的一侧落在后面（拉长），
    # 近的一侧绕得也快一点（剪切，拉出来的一条是弯的），两侧往中间挤
    v_r = -SHARD_CARRY * rng.uniform(0.9, 1.1) + along * TIDAL * (0.5 + td)
    v_t = vc * ORBIT * (1 - 0.3 * along) - side * 30.0
    v = v_r[:, None] * ur + v_t[:, None] * ut + rng.normal(0, 6, (N, 2))
    init = np.zeros((N, 8), 'f4')
    init[:, 0], init[:, 1], init[:, 2] = x0 + off[:, 0], y0 + off[:, 1], z0
    init[:, 3], init[:, 4] = v[:, 0], v[:, 1]
    init[:, 6], init[:, 7] = -1, np.where(kind == GAS, 0.1, 0.2)                # 气体没有“迸开”的那一下，阻力很小
    c = np.array([color.redF(), color.greenF(), color.blueF()])
    w = rng.uniform(0, 0.25, (N, 1))
    look = np.zeros((N, 16), 'f4')
    look[:, 0:3] = init[:, 0:3]
    look[:, 6] = kind
    look[:, 7] = np.where(kind == GAS, R * rng.uniform(0.18, 0.38, N), rng.uniform(0.5, 1.3, N))
    look[:, 8:11] = c * (1 - w) + w
    look[:, 11] = rng.random(N)
    look[:, 12] = (along + 1) / 2 * tear_s                                    # 什么时候被撕到（朝黑洞的一侧先）
    look[:, 13], look[:, 15] = 1.0, 3.0                                       # 亮点的亮度、慢慢变暗的快慢
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
