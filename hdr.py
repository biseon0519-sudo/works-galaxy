# 真 HDR 输出：OpenGL 画的图通过 WGL_NV_DX_interop 写进 D3D11 纹理，再拷到 DXGI 交换链上 Present。
# 交换链挂在一个盖住整个窗口的子窗口上（命中测试返回 HTTRANSPARENT，鼠标照常落到底下的 Qt 窗口）。
# 屏幕开着 HDR：16 位浮点 scRGB（线性，1.0 = 80 尼特）；SDR 屏：8 位，像素和以前 QOpenGLWidget 输出的一样。
import ctypes as C
from ctypes import wintypes as W
import uuid

u32, dxgi, d3d11, gl32 = C.windll.user32, C.windll.dxgi, C.windll.d3d11, C.windll.opengl32


class GUID(C.Structure):
    _fields_ = [('b', C.c_ubyte * 16)]


def _iid(s):
    g = GUID(); C.memmove(C.byref(g), uuid.UUID(s).bytes_le, 16); return g


IID_FACTORY2 = _iid('50c83a1c-e072-4c48-87b0-3630fa36a6d0')
IID_OUTPUT6 = _iid('068346e8-aaec-4b84-add7-137f513f77a1')
IID_SWAP3 = _iid('94d99bdb-f1f8-4ab0-b236-7da0170edab1')
IID_TEX2D = _iid('6f15aaf2-d208-4e89-9ab4-489535d34f9c')

FMT_F16, FMT_RGBA8 = 10, 28
CS_SRGB, CS_SCRGB, CS_HDR10 = 0, 1, 12


def call(obj, i, *args, res=C.c_long, types=None):
    """调 COM 方法：第 i 个虚函数。"""
    fn = C.cast(obj, C.POINTER(C.POINTER(C.c_void_p)))[0][i]
    if types is None:
        types = [type(a) if not isinstance(a, int) else C.c_uint for a in args]
    return C.WINFUNCTYPE(res, C.c_void_p, *types)(fn)(obj, *args)


def check(hr, what):
    if hr < 0:
        raise OSError(f'{what} 失败 0x{hr & 0xffffffff:08x}')


def release(obj):
    if obj:
        call(obj, 2, res=C.c_ulong, types=[])


class SAMPLE(C.Structure):
    _fields_ = [('Count', C.c_uint), ('Quality', C.c_uint)]


class SWAP_DESC1(C.Structure):
    _fields_ = [('Width', C.c_uint), ('Height', C.c_uint), ('Format', C.c_int), ('Stereo', W.BOOL),
                ('Sample', SAMPLE), ('Usage', C.c_uint), ('BufferCount', C.c_uint), ('Scaling', C.c_int),
                ('SwapEffect', C.c_int), ('AlphaMode', C.c_int), ('Flags', C.c_uint)]


class TEX_DESC(C.Structure):
    _fields_ = [('Width', C.c_uint), ('Height', C.c_uint), ('MipLevels', C.c_uint), ('ArraySize', C.c_uint),
                ('Format', C.c_int), ('Sample', SAMPLE), ('Usage', C.c_int), ('BindFlags', C.c_uint),
                ('CPUAccessFlags', C.c_uint), ('MiscFlags', C.c_uint)]


class ADAPTER_DESC1(C.Structure):
    _fields_ = [('Description', C.c_wchar * 128), ('VendorId', C.c_uint), ('DeviceId', C.c_uint),
                ('SubSysId', C.c_uint), ('Revision', C.c_uint), ('DVM', C.c_size_t), ('DSM', C.c_size_t),
                ('SSM', C.c_size_t), ('Luid', C.c_int64), ('Flags', C.c_uint)]


class OUTPUT_DESC1(C.Structure):
    _fields_ = [('DeviceName', C.c_wchar * 32), ('rc', W.RECT), ('Attached', W.BOOL), ('Rot', C.c_int),
                ('Mon', W.HMONITOR), ('Bits', C.c_uint), ('ColorSpace', C.c_int),
                ('prim', C.c_float * 8), ('MinLum', C.c_float), ('MaxLum', C.c_float), ('MaxFull', C.c_float)]


# ---------- 显示器信息：HDR 开没开、峰值亮度、Windows 设置里的 SDR 内容亮度 ----------
class _LUID(C.Structure):
    _fields_ = [('lo', C.c_uint32), ('hi', C.c_int32)]


class _HDR(C.Structure):
    _fields_ = [('type', C.c_int), ('size', C.c_uint32), ('adapter', _LUID), ('id', C.c_uint32)]


class _SOURCE_NAME(C.Structure):
    _fields_ = [('h', _HDR), ('gdi', C.c_wchar * 32)]


class _WHITE(C.Structure):
    _fields_ = [('h', _HDR), ('level', C.c_ulong)]


class _PATH(C.Structure):     # DISPLAYCONFIG_PATH_INFO：只用到 source 的适配器/编号和 target 的适配器/编号
    _fields_ = [('src_adapter', _LUID), ('src_id', C.c_uint32), ('src_mode', C.c_uint32), ('src_flags', C.c_uint32),
                ('tgt_adapter', _LUID), ('tgt_id', C.c_uint32), ('tgt_mode', C.c_uint32), ('tech', C.c_int),
                ('rot', C.c_int), ('scale', C.c_int), ('refresh', C.c_uint32 * 2), ('scan', C.c_int),
                ('avail', W.BOOL), ('tgt_flags', C.c_uint32), ('flags', C.c_uint32)]


def sdr_white(gdi_name):
    """Windows「SDR 内容亮度」滑块对应的尼特数（HDR 打开时 SDR 白色有多亮），查不到返回 None。"""
    try:
        n_path, n_mode = C.c_uint32(), C.c_uint32()
        if u32.GetDisplayConfigBufferSizes(2, C.byref(n_path), C.byref(n_mode)):     # QDC_ONLY_ACTIVE_PATHS
            return None
        paths = (_PATH * n_path.value)()
        modes = (C.c_byte * (64 * max(1, n_mode.value)))()
        if u32.QueryDisplayConfig(2, C.byref(n_path), paths, C.byref(n_mode), modes, None):
            return None
        for p in paths[:n_path.value]:
            src = _SOURCE_NAME(); src.h = _HDR(1, C.sizeof(_SOURCE_NAME), p.src_adapter, p.src_id)
            if u32.DisplayConfigGetDeviceInfo(C.byref(src)) or src.gdi != gdi_name:
                continue
            wl = _WHITE(); wl.h = _HDR(11, C.sizeof(_WHITE), p.tgt_adapter, p.tgt_id)
            if u32.DisplayConfigGetDeviceInfo(C.byref(wl)) == 0:
                return wl.level / 1000 * 80
    except Exception:
        pass
    return None


# ---------- 子窗口：交换链挂在它上面，鼠标穿透 ----------
WNDPROC = C.WINFUNCTYPE(C.c_ssize_t, W.HWND, C.c_uint, W.WPARAM, W.LPARAM)
u32.DefWindowProcW.argtypes = [W.HWND, C.c_uint, W.WPARAM, W.LPARAM]
u32.DefWindowProcW.restype = C.c_ssize_t
u32.CreateWindowExW.restype = W.HWND
u32.CreateWindowExW.argtypes = [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, C.c_int, C.c_int, C.c_int, C.c_int,
                                W.HWND, W.HMENU, W.HINSTANCE, W.LPVOID]
u32.SetWindowPos.argtypes = [W.HWND, W.HWND, C.c_int, C.c_int, C.c_int, C.c_int, C.c_uint]


@WNDPROC
def _wndproc(h, msg, wp, lp):
    if msg == 0x0084:            # WM_NCHITTEST：透明，交给底下的 Qt 窗口
        return -1
    if msg == 0x0014:            # WM_ERASEBKGND：不擦（画面全由交换链给）
        return 1
    if msg == 0x000F:            # WM_PAINT
        u32.ValidateRect(h, None)
        return 0
    return u32.DefWindowProcW(h, msg, wp, lp)


class _WNDCLASS(C.Structure):
    _fields_ = [('style', C.c_uint), ('proc', WNDPROC), ('cls', C.c_int), ('wnd', C.c_int), ('inst', W.HINSTANCE),
                ('icon', W.HICON), ('cursor', W.HANDLE), ('brush', W.HBRUSH), ('menu', W.LPCWSTR), ('name', W.LPCWSTR)]


_registered = False


def overlay_window(parent):
    global _registered
    if not _registered:
        wc = _WNDCLASS(); wc.proc = _wndproc; wc.name = 'WorksGalaxySwap'
        u32.RegisterClassW(C.byref(wc))
        _registered = True
    # WS_CHILD | WS_VISIBLE | WS_DISABLED（不抢键盘焦点）
    return u32.CreateWindowExW(0, 'WorksGalaxySwap', '', 0x40000000 | 0x10000000 | 0x08000000, 0, 0, 1, 1,
                               parent, None, None, None)


# ---------- OpenGL 那边的互通函数 ----------
gl32.wglGetProcAddress.restype = C.c_void_p
gl32.wglGetProcAddress.argtypes = [C.c_char_p]


def _wgl(name, res, *args):
    p = gl32.wglGetProcAddress(name.encode())
    if not p:
        raise OSError(f'显卡驱动不支持 {name}')
    return C.WINFUNCTYPE(res, *args)(p)


class Presenter:
    """把 moderngl 画好的图送上屏幕。用法：target(w, h) 拿到要画的 framebuffer → 画 → present()。"""

    def __init__(self, ctx, parent_hwnd, vendor_hint=''):
        self.ctx = ctx
        self.hwnd = overlay_window(parent_hwnd)
        self.size = (0, 0)
        self.hdr = False            # 当前交换链是不是 HDR（浮点 scRGB）
        self.peak = 80.0            # 显示器峰值亮度（尼特）
        self.white = 80.0           # SDR 白色（尼特）
        self.swap = self.tex = self.gl_obj = None
        self.fbo = self.gl_tex = None
        self._probe = None
        self._open_device(vendor_hint)
        self.dx_open = _wgl('wglDXOpenDeviceNV', C.c_void_p, C.c_void_p)
        self.dx_reg = _wgl('wglDXRegisterObjectNV', C.c_void_p, C.c_void_p, C.c_void_p, C.c_uint, C.c_uint, C.c_uint)
        self.dx_unreg = _wgl('wglDXUnregisterObjectNV', W.BOOL, C.c_void_p, C.c_void_p)
        self.dx_lock = _wgl('wglDXLockObjectsNV', W.BOOL, C.c_void_p, C.c_int, C.POINTER(C.c_void_p))
        self.dx_unlock = _wgl('wglDXUnlockObjectsNV', W.BOOL, C.c_void_p, C.c_int, C.POINTER(C.c_void_p))
        self.gl_dev = self.dx_open(self.dev)
        if not self.gl_dev:
            raise OSError('wglDXOpenDeviceNV 失败')

    def _open_device(self, vendor_hint):
        """D3D11 设备要和 OpenGL 在同一块显卡上（按厂商名挑）。"""
        f = C.c_void_p()
        check(dxgi.CreateDXGIFactory2(0, C.byref(IID_FACTORY2), C.byref(f)), 'CreateDXGIFactory2')
        self.factory = f
        pick, i = None, 0
        want = {'nvidia': 0x10de, 'intel': 0x8086, 'amd': 0x1002, 'ati': 0x1002}
        vid = next((v for k, v in want.items() if k in vendor_hint.lower()), None)
        while True:
            a = C.c_void_p()
            if call(f, 12, i, C.byref(a), types=[C.c_uint, C.POINTER(C.c_void_p)]) < 0:
                break
            d = ADAPTER_DESC1(); call(a, 10, C.byref(d), types=[C.POINTER(ADAPTER_DESC1)])
            if pick is None and (vid is None or d.VendorId == vid):
                pick = a
            else:
                release(a)
            i += 1
        dev, dctx = C.c_void_p(), C.c_void_p()
        d3d11.D3D11CreateDevice.argtypes = [C.c_void_p, C.c_int, C.c_void_p, C.c_uint, C.c_void_p, C.c_uint, C.c_uint,
                                            C.POINTER(C.c_void_p), C.c_void_p, C.POINTER(C.c_void_p)]
        check(d3d11.D3D11CreateDevice(pick, 0 if pick else 1, None, 0x20, None, 0, 7, C.byref(dev), None, C.byref(dctx)),
              'D3D11CreateDevice')
        release(pick)
        self.dev, self.dctx = dev, dctx

    # ---------- 显示器 ----------
    def display_info(self):
        """窗口所在显示器：(HDR 开着没, 峰值尼特, SDR 白色尼特)。在 Windows 设置里开关 HDR 后旧的 DXGI 工厂会过期
        （IsCurrent 返回假），查到的还是老样子，所以过期了就新建一个再查。"""
        if self._probe is None or not call(self._probe, 13, res=W.BOOL, types=[]):
            release(self._probe); self._probe = C.c_void_p()
            if dxgi.CreateDXGIFactory2(0, C.byref(IID_FACTORY2), C.byref(self._probe)) < 0:
                self._probe = None
                return False, 80.0, 80.0
        u32.MonitorFromWindow.restype = W.HMONITOR
        u32.MonitorFromWindow.argtypes = [W.HWND, W.DWORD]
        mon = u32.MonitorFromWindow(self.hwnd, 2)           # MONITOR_DEFAULTTONEAREST
        found, i = None, 0
        while found is None:
            a = C.c_void_p()
            if call(self._probe, 12, i, C.byref(a), types=[C.c_uint, C.POINTER(C.c_void_p)]) < 0:
                break
            j = 0
            while found is None:
                o = C.c_void_p()
                if call(a, 7, j, C.byref(o), types=[C.c_uint, C.POINTER(C.c_void_p)]) < 0:
                    break
                o6 = C.c_void_p()
                if call(o, 0, C.byref(IID_OUTPUT6), C.byref(o6), types=[C.POINTER(GUID), C.POINTER(C.c_void_p)]) >= 0:
                    d = OUTPUT_DESC1(); call(o6, 27, C.byref(d), types=[C.POINTER(OUTPUT_DESC1)])
                    if d.Mon == mon:
                        found = d
                    release(o6)
                release(o); j += 1
            release(a); i += 1
        if found is None or found.ColorSpace != CS_HDR10:
            return False, 80.0, 80.0
        # 驱动报的峰值不一定靠谱（同一块屏有时报 1082、有时报 48000），离谱时按 1000 尼特算
        peak = found.MaxLum if 400 <= found.MaxLum <= 4000 else 1000.0
        return True, peak, (sdr_white(found.DeviceName) or 80.0)

    # ---------- 交换链 ----------
    def _make_swap(self, w, h, hdr):
        self._drop_shared()
        if self.swap is not None and hdr == self.hdr:
            # 只是尺寸变了（拖窗口边框）：原地改大小，比整个重建快、不闪
            check(call(self.swap, 13, 0, w, h, 0, 0, types=[C.c_uint] * 5), 'ResizeBuffers')
        else:
            self._drop_swap()
            desc = SWAP_DESC1(w, h, FMT_F16 if hdr else FMT_RGBA8, 0, SAMPLE(1, 0), 0x20, 2, 0, 4, 0, 0)
            sc = C.c_void_p()
            check(call(self.factory, 15, self.dev, self.hwnd, C.byref(desc), None, None, C.byref(sc),
                       types=[C.c_void_p, W.HWND, C.POINTER(SWAP_DESC1), C.c_void_p, C.c_void_p, C.POINTER(C.c_void_p)]),
                  'CreateSwapChainForHwnd')
            call(self.factory, 8, self.hwnd, 2, types=[W.HWND, C.c_uint])       # 不要 Alt+Enter 全屏
            s3 = C.c_void_p()
            check(call(sc, 0, C.byref(IID_SWAP3), C.byref(s3), types=[C.POINTER(GUID), C.POINTER(C.c_void_p)]), 'IDXGISwapChain3')
            release(sc)
            check(call(s3, 38, CS_SCRGB if hdr else CS_SRGB, types=[C.c_int]), 'SetColorSpace1')
            self.swap, self.hdr = s3, hdr
        # 共享纹理：OpenGL 往里画，再整块拷进交换链的后台缓冲
        td = TEX_DESC(w, h, 1, 1, FMT_F16 if hdr else FMT_RGBA8, SAMPLE(1, 0), 0, 0x20 | 0x8, 0, 0)
        tex = C.c_void_p()
        check(call(self.dev, 5, C.byref(td), None, C.byref(tex), types=[C.POINTER(TEX_DESC), C.c_void_p, C.POINTER(C.c_void_p)]),
              'CreateTexture2D')
        self.tex = tex
        name = C.c_uint()
        gl32.glGenTextures(1, C.byref(name))
        self.gl_name = name.value
        self.gl_obj = self.dx_reg(self.gl_dev, tex, self.gl_name, 0x0DE1, 2)      # GL_TEXTURE_2D, WGL_ACCESS_WRITE_DISCARD_NV
        if not self.gl_obj:
            raise OSError('wglDXRegisterObjectNV 失败')
        self.gl_tex = self.ctx.external_texture(self.gl_name, (w, h), 4, 0, 'f2' if hdr else 'f1')
        self.fbo = None             # 要等锁住共享纹理以后才能建（没锁时 framebuffer 不完整）
        self.size = (w, h)

    def _drop_shared(self):
        if self.gl_obj:
            self.dx_unreg(self.gl_dev, self.gl_obj); self.gl_obj = None
        if self.fbo is not None:
            self.fbo.release(); self.fbo = None
        if self.gl_tex is not None:
            gl32.glDeleteTextures(1, C.byref(C.c_uint(self.gl_name))); self.gl_tex = None
        release(self.tex); self.tex = None
        if self.swap:
            call(self.dctx, 110, res=None, types=[]); call(self.dctx, 111, res=None, types=[])   # ClearState、Flush：放掉对旧缓冲的引用

    def _drop_swap(self):
        self._drop_shared()
        release(self.swap); self.swap = None

    def target(self, x, y, w, h, want_hdr):
        """子窗口摆到 (x, y, w, h)（物理像素，相对父窗口）；需要时重建交换链。返回要画的 framebuffer（已锁住）。"""
        u32.SetWindowPos(self.hwnd, None, x, y, w, h, 0x0004 | 0x0010 | 0x0200)    # NOZORDER | NOACTIVATE | NOOWNERZORDER
        if (w, h) != self.size or want_hdr != self.hdr or self.swap is None:
            self._make_swap(w, h, want_hdr)
        self._lock = (C.c_void_p * 1)(self.gl_obj)
        self.dx_lock(self.gl_dev, 1, self._lock)
        if self.fbo is None:
            self.fbo = self.ctx.framebuffer(color_attachments=[self.gl_tex])
        return self.fbo

    def present(self, sync=1):
        self.dx_unlock(self.gl_dev, 1, self._lock)
        back = C.c_void_p()
        check(call(self.swap, 9, 0, C.byref(IID_TEX2D), C.byref(back), types=[C.c_uint, C.POINTER(GUID), C.POINTER(C.c_void_p)]),
              'GetBuffer')
        call(self.dctx, 47, back, self.tex, res=None, types=[C.c_void_p, C.c_void_p])     # CopyResource
        release(back)
        return call(self.swap, 8, sync, 0, types=[C.c_uint, C.c_uint])

    def close(self):
        self._drop_swap()
        if self.gl_dev:
            _wgl('wglDXCloseDeviceNV', W.BOOL, C.c_void_p)(self.gl_dev); self.gl_dev = None
        release(self.dctx); release(self.dev); release(self.factory); release(self._probe)
        u32.DestroyWindow(self.hwnd)


# ---------- 界面层：按钮、标题栏、对话框画成一张带透明度的图，叠在导图上 ----------
# 交换链的子窗口盖住了整个窗口，Qt 照常把控件画进自己的缓冲（被盖在底下看不见），这里另外把它们画一份。
# 哪里要重画靠拦截 Qt 的绘制事件知道（只重画变了的那块）。
from PySide6.QtCore import QObject, QEvent, QRect, QPoint, Qt as _Qt
from PySide6.QtGui import QImage, QPainter, QRegion
from PySide6.QtWidgets import QApplication, QWidget


class UiLayer(QObject):
    def __init__(self, top, skip):
        super().__init__(top)
        self.top, self.skip = top, skip
        self.img = None
        self.dirty = QRegion()
        self._busy = False
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Paint and not self._busy and isinstance(obj, QWidget) and obj is not self.skip:
            if obj.window() is self.top:
                r = e.rect()
                self.dirty += QRect(obj.mapTo(self.top, r.topLeft()), r.size())
        return False

    def capture(self, dpr):
        """有变化就重画变了的那块，返回 (图, 变了的矩形（物理像素）)；没变化返回 (图, None)。"""
        w, h = max(1, round(self.top.width() * dpr)), max(1, round(self.top.height() * dpr))
        if self.img is None or (self.img.width(), self.img.height()) != (w, h) or self.img.devicePixelRatio() != dpr:
            self.img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
            self.img.setDevicePixelRatio(dpr)
            self.img.fill(0)
            self.dirty = QRegion(self.top.rect())
        if self.dirty.isEmpty():
            return self.img, None
        b = self.dirty.boundingRect() & self.top.rect()       # 按包住所有变化的矩形整块重画
        self.dirty = QRegion()
        p = QPainter(self.img)
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.fillRect(b, _Qt.transparent)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        self._busy = True
        try:
            self.top.render(p, b.topLeft(), QRegion(b), QWidget.DrawChildren)
        finally:
            self._busy = False
        p.end()
        x0, y0 = max(0, int(b.left() * dpr) - 1), max(0, int(b.top() * dpr) - 1)
        x1, y1 = min(w, int((b.right() + 1) * dpr) + 2), min(h, int((b.bottom() + 1) * dpr) + 2)
        return self.img, (x0, y0, x1 - x0, y1 - y0)
