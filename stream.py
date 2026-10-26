# 物质流：每颗恒星被黑洞扯下来的物质，几万颗粒子各自在显卡上模拟（transform feedback，每帧一遍）。
# 坐标以黑洞为中心、视界半径为单位（见 shaders.py 的 STREAM_*），所以全图、展开近景、镜头平移缩放都通用；
# CPU 每帧只上传恒星的位置、速度、颜色。粒子掉进去就回到自己的恒星重新出发，物质流一直连续；
# 恒星动了，已经飞出去的粒子还沿着自己的轨道走，自然拖出弯曲的尾迹。
import math
import numpy as np
import moderngl
from shaders import STREAM_SIM_VS, STREAM_VS, STREAM_FS, GAS_K

MAX_STARS = 32            # 和着色器里的 MAXS 一致
PER_STAR = 800            # 每颗恒星的粒子数（稀一点，像原来那样薄薄的一股）
SPARK_SHARE = 0.4         # 其中亮点的比例（其余是薄薄的发光气体）
LIFE = 40.0               # 一颗粒子最多飞多久（秒），到了就回去重新出发
SIM_HZ = 120              # 每秒最多算几步
V_FLOW = 28.0             # 流速（像素/秒）：慢悠悠的，靠近黑洞稍微快一点
V_DISK = 60.0             # 在吸积盘外缘绕的速度（像素/秒），越往里越快
CAP_MAP, CAP_CINE = 9.0, 4.0          # 从离黑洞多远（视界半径）开始被盘接住：近景里恒星本来就离黑洞只有五个视界半径，要近一些才接
PREWARM_S = 24.0          # 重新开始时先快进多少秒，物质流一出现就是完整的（流得慢，要快进得久一点）
PREWARM_DT = 1 / 30       # 快进的步长
PREWARM_PASSES = 12       # 每帧快进几遍（一遍 8 步），分到几帧里做，不卡


class StreamSystem:
    def __init__(self, ctx):
        self.ctx = ctx
        self.sim = ctx.program(vertex_shader=STREAM_SIM_VS, varyings=['out_a', 'out_b'])
        self.prog = ctx.program(vertex_shader=STREAM_VS, fragment_shader=STREAM_FS)
        N = self.n = MAX_STARS * PER_STAR
        rng = np.random.default_rng(7)
        state = np.zeros((N, 8), 'f4')
        state[:, 3] = -rng.random(N) * LIFE * 0.6          # 一开始错开出发
        state[:, 7] = rng.random(N) * 1000
        static = np.zeros((N, 4), 'f4')
        static[:, 0] = np.repeat(np.arange(MAX_STARS), PER_STAR)
        static[:, 1] = rng.random(N) * 100
        static[:, 2] = (rng.random(N) < SPARK_SHARE).astype('f4')
        static[:, 3] = np.where(static[:, 2] > 0.5, rng.uniform(0.6, 1.4, N), rng.uniform(0.12, 0.42, N))
        self.static = ctx.buffer(static.tobytes())
        self.bufs = [ctx.buffer(state.tobytes()), ctx.buffer(reserve=N * 32)]
        self.sim_vaos = [ctx.vertex_array(self.sim, [(b, '4f 4f', 'in_a', 'in_b'), (self.static, '4f', 'in_c')]) for b in self.bufs]
        quad = ctx.buffer(np.array([-1, -1, 1, -1, -1, 1, 1, 1], 'f4').tobytes())
        self.draw_vaos = [ctx.vertex_array(self.prog, [(quad, '2f', 'in_corner'), (b, '4f 16x/i', 'i_a'),
                                                       (self.static, '4f/i', 'i_c')]) for b in self.bufs]
        self.cur = 0
        self.stars = np.zeros((MAX_STARS, 4), 'f4')
        self.prev = None
        self.need_reset = True
        self.grow = False
        self.warm_left = 0        # 还要快进几遍；快进完之前不画

    def reset(self, grow=False):
        """镜头视角换了（全图 ↔ 近景）或恒星重新出现：所有粒子重新从恒星出发。
        grow：物质流从恒星那头慢慢往黑洞长过去（展开时）；否则先快进一段，一出现就是完整的（回到全图时）。"""
        self.need_reset = True
        self.grow = grow

    def ready(self):
        return self.warm_left == 0 and not self.need_reset

    def _pass(self, dt, steps, reset=False):
        for k, v in dict(u_dt=dt, u_steps=steps, u_reset=1.0 if reset else 0.0).items():
            self.sim[k].value = v
        self.sim_vaos[self.cur].transform(self.bufs[1 - self.cur], moderngl.POINTS, vertices=self.n)
        self.cur = 1 - self.cur

    def update(self, dt, stars, cine, el, rs_px):
        """stars：MAX_STARS 行（x、y、半径、还喷不喷），单位是视界半径。cine：0 全图 ~ 1 近景；el：吸积盘的仰角；
        rs_px：一个视界半径多少像素。"""
        stars = np.asarray(stars, 'f4')
        reset = self.need_reset
        vel = np.zeros((MAX_STARS, 2), 'f4')
        if self.prev is not None and dt > 0 and not reset:
            vel = (stars[:, :2] - self.prev[:, :2]) / dt
            lim = 4 * V_FLOW / rs_px                                    # 换视角、跳位置时别把粒子甩飞
            sp = np.hypot(vel[:, 0], vel[:, 1])[:, None]
            vel *= np.minimum(1.0, lim / np.maximum(sp, 1e-6))
        self.prev = stars.copy()
        sim = self.sim
        sim['u_star'].write(stars.tobytes())
        sim['u_svel'].write(vel.tobytes())
        for k, v in dict(u_life=LIFE, u_n=(0.0, math.cos(el), -math.sin(el)), u_rspx=rs_px, u_vflow=V_FLOW,
                         u_vdisk=V_DISK, u_cap=CAP_MAP + (CAP_CINE - CAP_MAP) * cine).items():
            sim[k].value = v
        if reset:
            self.need_reset = False
            self._pass(0.0, 1, reset=True)
            self.warm_left = 0 if self.grow else int(PREWARM_S / PREWARM_DT) // 8
        if self.warm_left:
            for _ in range(min(PREWARM_PASSES, self.warm_left)):
                self._pass(PREWARM_DT, 8)
            self.warm_left -= min(PREWARM_PASSES, self.warm_left)
        elif dt > 0:
            steps = max(1, min(8, math.ceil(dt * SIM_HZ)))
            self._pass(dt / steps, steps)

    def draw(self, vw, vh, bh, rs_px, roll, colors, alpha, disk, t):
        """bh：黑洞在屏幕上的位置；rs_px：一个视界半径多少像素；colors：MAX_STARS 行（r、g、b、这条流的透明度）。"""
        if not self.ready():
            return
        prog = self.prog
        prog['u_star'].write(self.stars_for_draw.tobytes())
        prog['u_scol'].write(np.asarray(colors, 'f4').tobytes())
        for k, v in dict(u_vp=(vw, vh), u_bh=(bh[0], bh[1], rs_px), u_roll=roll, u_alpha=alpha, u_disk=disk, u_time=t, u_gas=GAS_K).items():
            m = prog.get(k, None)
            if m is not None:
                m.value = v
        self.ctx.blend_func = moderngl.ONE, moderngl.ONE
        self.draw_vaos[self.cur].render(moderngl.TRIANGLE_STRIP, instances=self.n)

    @property
    def stars_for_draw(self):
        return self.prev if self.prev is not None else self.stars
