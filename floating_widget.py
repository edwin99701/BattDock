"""原生 WinForms 桌面悬浮窗与提示音播放（零 WebView2 额外开销，Windows 10/11 通用）。"""

from __future__ import annotations

import ctypes
from datetime import datetime
import io
import os
import sys
import threading
from ctypes import wintypes
from typing import Callable, Optional

from PIL import Image, ImageDraw

from app_config import FloatingWidgetConfig
from brand import APP_FLOATING_TITLE
from device_icons import render_device_icon_pil
from providers import DeviceBattery, KIND_EARBUDS, KIND_HEADSET, KIND_KEYBOARD, KIND_MOUSE
from providers.device_naming import format_device_subtitle

EDGE_MARGIN = 16

_FONT_FAMILY_CACHE: dict[bool, str] = {}


def resolve_winforms_font_family(*, numeric: bool = False) -> str:
    """选择本机已安装的最佳现代桌面字体（零外部下载，保证 Win10/11 中文清晰无宋体回退）。"""
    cached = _FONT_FAMILY_CACHE.get(numeric)
    if cached:
        return cached
    candidates = (
        ("Inter", "Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI")
        if numeric
        else ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI")
    )
    chosen = "Microsoft YaHei UI"
    try:
        from System.Drawing.Text import InstalledFontCollection

        installed = {f.Name for f in InstalledFontCollection().Families}
        for name in candidates:
            if name in installed:
                chosen = name
                break
    except Exception:
        chosen = "Microsoft YaHei UI"
    _FONT_FAMILY_CACHE[numeric] = chosen
    return chosen


QUNS_NOT_PRESENT = 1
QUNS_BUSY = 2
QUNS_RUNNING_D3D_FULL_SCREEN = 3
QUNS_PRESENTATION_MODE = 4
QUNS_ACCEPTS_NOTIFICATIONS = 5
QUNS_QUIET_TIME = 6
QUNS_APP = 7

WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
LWA_ALPHA = 0x00000002
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SWP_NOOWNERZORDER = 0x0200


def query_user_notification_state() -> int:
    """查询 Windows 当前前台通知/全屏状态（SHQueryUserNotificationState），零权限、微秒级。"""
    if sys.platform != "win32":
        return 0
    try:
        shell32 = ctypes.windll.shell32
        state = ctypes.c_int(0)
        hr = int(shell32.SHQueryUserNotificationState(ctypes.byref(state)))
        if hr == 0:
            return int(state.value)
    except Exception:
        pass
    return 0


def is_exclusive_fullscreen_active() -> bool:
    """仅当检测到 Direct3D 独占全屏游戏（QUNS_RUNNING_D3D_FULL_SCREEN=3）时返回 True。

    说明：不把 QUNS_BUSY(2) 一刀切判为全屏游戏，避免误伤普通最大化窗口或无边框窗口游戏。
    """
    return query_user_notification_state() == QUNS_RUNNING_D3D_FULL_SCREEN


def apply_non_activating_tool_style(hwnd: int, layered: bool = True) -> int:
    """以原生 Win32 方式锁死不抢焦点工具窗扩展样式（WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW）。

    规避 WinForms Form.Opacity / Form.TopMost 触发 UpdateStyles() 抹除手动写入扩展样式的缺陷，
    保证悬浮窗与低电量弹窗永远不抢占前台焦点、永远不进入 Alt+Tab 窗口切换列表。
    """
    if sys.platform != "win32" or not hwnd:
        return 0
    try:
        user32 = ctypes.windll.user32
        hw = wintypes.HWND(hwnd)
        if not user32.IsWindow(hw):
            return 0
        GWL_EXSTYLE = -20
        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongW.restype = wintypes.LONG
        user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
        user32.SetWindowLongW.restype = wintypes.LONG

        cur = int(user32.GetWindowLongW(hw, GWL_EXSTYLE)) & 0xFFFFFFFF
        desired = (cur | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE) & (~WS_EX_APPWINDOW & 0xFFFFFFFF)
        if layered:
            desired |= WS_EX_LAYERED
        if desired != cur:
            user32.SetWindowLongW(hw, GWL_EXSTYLE, ctypes.c_long(desired).value)
        return int(user32.GetWindowLongW(hw, GWL_EXSTYLE)) & 0xFFFFFFFF
    except Exception:
        return 0


def set_layered_window_alpha(hwnd: int, opacity: float) -> bool:
    """通过原生 SetLayeredWindowAttributes 设置窗体透明度（0.0–1.0），不触发 WinForms 样式覆盖。"""
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        hw = wintypes.HWND(hwnd)
        if not user32.IsWindow(hw):
            return False
        apply_non_activating_tool_style(hwnd, layered=True)
        alpha = max(0, min(255, int(round(max(0.0, min(1.0, float(opacity))) * 255.0))))
        user32.SetLayeredWindowAttributes.argtypes = [
            wintypes.HWND,
            wintypes.COLORREF,
            ctypes.c_ubyte,
            wintypes.DWORD,
        ]
        user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
        return bool(user32.SetLayeredWindowAttributes(hw, 0, alpha, LWA_ALPHA))
    except Exception:
        return False


def set_window_topmost_noactivate(
    hwnd: int,
    topmost: bool,
    x: Optional[int] = None,
    y: Optional[int] = None,
    w: Optional[int] = None,
    h: Optional[int] = None,
    show: bool = False,
) -> bool:
    """通过原生 SetWindowPos 独立置顶/降级且严格携带 SWP_NOACTIVATE | SWP_NOOWNERZORDER。

    确保仅目标窗口自身改变 Z-order，绝不连带主窗口/设置窗口/悬浮窗提升层级，也绝不抢占前台焦点。
    """
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        user32.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        user32.SetWindowPos.restype = wintypes.BOOL
        hw = wintypes.HWND(hwnd)
        if not user32.IsWindow(hw):
            return False
        flags = SWP_NOACTIVATE | SWP_NOOWNERZORDER
        if x is None or y is None:
            flags |= SWP_NOMOVE
            px, py = 0, 0
        else:
            px, py = int(x), int(y)
        if w is None or h is None:
            flags |= SWP_NOSIZE
            pw, ph = 0, 0
        else:
            pw, ph = int(w), int(h)
        if show:
            flags |= SWP_SHOWWINDOW
        z_after = wintypes.HWND(-1 if topmost else -2)
        return bool(user32.SetWindowPos(hw, z_after, px, py, pw, ph, flags))
    except Exception:
        return False


def is_windows_11() -> bool:
    """准确区分 Windows 11 (Build >= 22000) 与 Windows 10。"""
    if sys.platform != "win32":
        return False
    if os.environ.get("BATTDOCK_FORCE_WIN10_ROUND") == "1":
        return False
    try:
        return int(sys.getwindowsversion().build) >= 22000
    except Exception:
        return False


def _query_hwnd_dpi_scale(hwnd: int, fallback: float = 1.0) -> float:
    if sys.platform != "win32" or not hwnd:
        return float(fallback or 1.0)
    try:
        dpi = ctypes.windll.user32.GetDpiForWindow(wintypes.HWND(hwnd))
        if dpi and dpi > 0:
            return float(dpi) / 96.0
    except Exception:
        pass
    return float(fallback or 1.0)


def apply_window_rounded_corners(
    hwnd: int,
    radius_dip: int = 10,
    scale: float = 0.0,
    force_region: bool = False,
) -> str:
    """跨 Windows 10 / 11 统一窗口外轮廓圆角实现。

    - Windows 11 (>= 22000)：优先使用原生 DWM 圆角（自带系统抗锯齿阴影，零性能开销）。
    - Windows 10 (< 22000)：使用 Win32 64 位显式 HRGN 签名的 CreateRoundRectRgn + SetWindowRgn
      按当前显示器真实 DPI 缩放精确裁剪外轮廓，四角对称且零黑/白角边残留；
      最大化时自动调用 SetWindowRgn(hwnd, 0, True) 恢复满屏直角边缘。
    """
    if sys.platform != "win32" or not hwnd:
        return "noop"

    user32 = ctypes.windll.user32
    if is_windows_11() and not force_region:
        try:
            dwmapi = ctypes.windll.dwmapi
            corner = ctypes.c_int(2)  # DWMWCP_ROUND
            dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), 33, ctypes.byref(corner), ctypes.sizeof(corner))
            no_border = ctypes.c_uint(0xFFFFFFFE)
            dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), 34, ctypes.byref(no_border), ctypes.sizeof(no_border))
            return "win11_dwm"
        except Exception:
            pass

    try:
        # Windows 10 根治圆角外出现 1px 白色直角框（pywebview 默认 ExtendFrameIntoClientArea + DWMNCRP_ENABLED 所致）：
        # 显式关闭 DWM 非客户区矩形外框渲染并归零扩展边距，再应用对称 SetWindowRgn 裁切
        try:
            dwmapi = ctypes.windll.dwmapi
            ncrp_disabled = ctypes.c_int(1)  # DWMNCRP_DISABLED
            dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(hwnd), 2, ctypes.byref(ncrp_disabled), ctypes.sizeof(ncrp_disabled)
            )

            class _DwmMargins(ctypes.Structure):
                _fields_ = [
                    ("cxLeftWidth", ctypes.c_int),
                    ("cxRightWidth", ctypes.c_int),
                    ("cyTopHeight", ctypes.c_int),
                    ("cyBottomHeight", ctypes.c_int),
                ]

            zero_margins = _DwmMargins(0, 0, 0, 0)
            dwmapi.DwmExtendFrameIntoClientArea(wintypes.HWND(hwnd), ctypes.byref(zero_margins))
        except Exception:
            pass

        user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
        user32.SetWindowRgn.restype = ctypes.c_int

        if user32.IsIconic(wintypes.HWND(hwnd)):
            return "minimized_skip"

        if user32.IsZoomed(wintypes.HWND(hwnd)):
            user32.SetWindowRgn(wintypes.HWND(hwnd), wintypes.HRGN(0), True)
            return "win10_rgn_cleared"

        rect = wintypes.RECT()
        if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
            return "error"
        w = max(1, rect.right - rect.left)
        h = max(1, rect.bottom - rect.top)
        eff_scale = float(scale) if (scale and float(scale) > 0) else _query_hwnd_dpi_scale(hwnd, 1.0)
        diam = max(8, int(round(radius_dip * 2 * eff_scale)))

        gdi32 = ctypes.windll.gdi32
        gdi32.CreateRoundRectRgn.argtypes = [
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int
        ]
        gdi32.CreateRoundRectRgn.restype = wintypes.HRGN
        gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        gdi32.DeleteObject.restype = wintypes.BOOL

        # Win32 CreateRoundRectRgn 右/下坐标为开区间，传入 (0, 0, w + 1, h + 1) 可保证四边与四角像素完全对称
        hrgn = gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, diam, diam)
        if hrgn:
            # SetWindowRgn 接管区域句柄所有权，成功时不可再 DeleteObject
            if not user32.SetWindowRgn(wintypes.HWND(hwnd), hrgn, True):
                gdi32.DeleteObject(hrgn)
                return "error"
            return "win10_rgn"
    except Exception:
        return "error"
    return "noop"


def paint_winforms_rounded_border(graphics, width: int, height: int, radius_px: float, border_color) -> None:
    """在 WinForms 原生无边框窗口（悬浮窗 / 低电量弹窗）内绘制 1px 抗锯齿圆角细边，消除 Win10 锯齿感。"""
    try:
        from System.Drawing import Pen
        from System.Drawing.Drawing2D import GraphicsPath, SmoothingMode

        if width <= 4 or height <= 4:
            return
        d = max(4.0, min(float(radius_px) * 2.0, float(min(width, height) - 2)))
        x, y = 0.5, 0.5
        w, h = float(width) - 1.5, float(height) - 1.5
        path = GraphicsPath()
        path.AddArc(x, y, d, d, 180.0, 90.0)
        path.AddArc(x + w - d, y, d, d, 270.0, 90.0)
        path.AddArc(x + w - d, y + h - d, d, d, 0.0, 90.0)
        path.AddArc(x, y + h - d, d, d, 90.0, 90.0)
        path.CloseFigure()
        graphics.SmoothingMode = SmoothingMode.AntiAlias
        pen = Pen(border_color, 1.0)
        try:
            graphics.DrawPath(pen, path)
        finally:
            pen.Dispose()
            path.Dispose()
    except Exception:
        pass


def play_alert_sound(sound_name: str = "default") -> None:
    """播放轻量 Windows 原生系统提示音（无需额外音频文件或重型依赖）。"""
    if sys.platform != "win32":
        return
    try:
        import winsound

        sound_map = {
            "default": winsound.MB_ICONEXCLAMATION,
            "asterisk": winsound.MB_ICONASTERISK,
            "exclamation": winsound.MB_ICONHAND,
        }
        winsound.MessageBeep(sound_map.get(sound_name, winsound.MB_ICONEXCLAMATION))
    except Exception:
        pass


def draw_battery_icon(
    size: int = 64,
    percent: Optional[int] = 85,
    charging: bool = False,
    connected: bool = True,
    low_t1: int = 30,
    low_t2: int = 20,
    low_t3: int = 10,
    light_bg: bool = False,
) -> Image.Image:
    """高对比度矢量电池图标（用于托盘、悬浮窗与低电量迷你弹窗，兼容深浅背景）。"""
    scale = 4
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if not connected or percent is None:
        outline_col = (100, 116, 139, 235) if light_bg else (160, 170, 185, 230)
        inner_bg = (226, 232, 240, 180) if light_bg else (15, 23, 42, 85)
        fill_col = (148, 163, 184, 180)
        pct = 0
    else:
        outline_col = (51, 65, 85, 245) if light_bg else (248, 250, 252, 255)
        inner_bg = (226, 232, 240, 200) if light_bg else (15, 23, 42, 130)
        pct = max(0, min(100, int(percent)))
        if charging:
            fill_col = (34, 197, 94, 255)
        elif pct <= low_t3:
            fill_col = (239, 68, 68, 255)
        elif pct <= low_t2:
            fill_col = (245, 158, 11, 255)
        elif pct <= low_t1:
            fill_col = (234, 179, 8, 255)
        else:
            fill_col = (34, 197, 94, 255)

    stroke = max(scale, int(round(s * 0.085)))
    bx0 = int(round(s * 0.04))
    by0 = int(round(s * 0.16))
    bx1 = int(round(s * 0.84))
    by1 = int(round(s * 0.84))
    radius = max(2, int(round(s * 0.14)))

    draw.rounded_rectangle([bx0, by0, bx1, by1], radius=radius, fill=inner_bg, outline=outline_col, width=stroke)

    cap_x0 = bx1 + max(1, int(round(s * 0.03)))
    cap_x1 = int(round(s * 0.97))
    cap_y0 = int(round(s * 0.33))
    cap_y1 = int(round(s * 0.67))
    draw.rounded_rectangle([cap_x0, cap_y0, cap_x1, cap_y1], radius=max(1, int(round(s * 0.05))), fill=outline_col)

    inset = stroke + max(1, int(round(s * 0.035)))
    fx0 = bx0 + inset
    fy0 = by0 + inset
    fx1_max = bx1 - inset
    fy1 = by1 - inset
    if pct > 0 and fx1_max > fx0:
        min_w = max(2, int(round((fx1_max - fx0) * 0.09)))
        fw = max(min_w, int(round((fx1_max - fx0) * (pct / 100.0))))
        draw.rounded_rectangle(
            [fx0, fy0, min(fx1_max, fx0 + fw), fy1],
            radius=max(1, int(round(s * 0.05))),
            fill=fill_col,
        )

    if connected and charging:
        cx = (bx0 + bx1) / 2.0
        cy = (by0 + by1) / 2.0
        u = s * 0.042
        bolt = [
            (cx + 1.2 * u, cy - 4.4 * u),
            (cx - 2.6 * u, cy + 0.5 * u),
            (cx - 0.1 * u, cy + 0.5 * u),
            (cx - 1.2 * u, cy + 4.4 * u),
            (cx + 2.6 * u, cy - 0.5 * u),
            (cx + 0.1 * u, cy - 0.5 * u),
        ]
        draw.polygon(bolt, fill=(255, 255, 255, 255))

    return img.resize((size, size), Image.Resampling.LANCZOS)


def _try_win11_round_corners(hwnd: int, radius_dip: int = 10, scale: float = 1.0) -> str:
    """兼容别名：统一调用跨 Windows 10 / 11 圆角窗口实现。"""
    return apply_window_rounded_corners(hwnd, radius_dip=radius_dip, scale=scale)


class DesktopFloatingWidget:
    """轻量桌面悬浮窗（原生 WinForms 控件，Win10/11 通用圆角、统一实心设备图标、品牌精简展示与悬停详情）。"""

    SIZE_MAP = {
        "small": (156, 46),
        "medium": (188, 54),
        "large": (222, 62),
    }

    def __init__(
        self,
        get_native_host: Callable[[], object],
        get_work_area: Callable[[], tuple[int, int, int, int]],
        get_dpi_scale: Callable[[], float],
        on_position_saved: Callable[[int, int], None],
        on_double_click: Callable[[], None],
    ) -> None:
        self._get_host = get_native_host
        self._get_work_area = get_work_area
        self._get_dpi_scale = get_dpi_scale
        self._on_position_saved = on_position_saved
        self._on_double_click = on_double_click
        self._lock = threading.Lock()
        self._form = None
        self._pic = None
        self._name_lbl = None
        self._pct_lbl = None
        self._bar_bg = None
        self._bar_fill = None
        self._tooltip = None
        self._bar_timer = None
        self._bar_target_w = 0
        self._bar_current_w = 0
        self._last_icon_sig = None
        self._last_tooltip_text = ""
        self._last_layout_sig = None
        self._last_style_sig = None
        self._last_content_sig = None
        self._font_cache: dict[tuple[str, str], object] = {}
        self._suppressed_by_fullscreen = False
        self._locked = True
        self._dragging = False
        self._drag_origin_cursor = (0, 0)
        self._drag_origin_form = (0, 0)

    def _run_on_ui(self, fn: Callable[[], None]) -> None:
        host = self._get_host()
        if host is None:
            return
        try:
            from System import Action

            if getattr(host, "InvokeRequired", False):
                host.BeginInvoke(Action(fn))
            else:
                fn()
        except Exception:
            pass

    def close(self) -> None:
        def _do():
            with self._lock:
                t = self._bar_timer
                self._bar_timer = None
                f = self._form
                self._form = None
                self._pic = None
                self._name_lbl = None
                self._pct_lbl = None
                self._bar_bg = None
                self._bar_fill = None
                self._tooltip = None
                self._last_icon_sig = None
                self._last_tooltip_text = ""
                self._last_layout_sig = None
                self._last_style_sig = None
                self._last_content_sig = None
                self._suppressed_by_fullscreen = False
                fonts = list(self._font_cache.values())
                self._font_cache.clear()
            if t is not None:
                try:
                    t.Stop()
                    t.Dispose()
                except Exception:
                    pass
            if f is not None:
                try:
                    if not f.IsDisposed:
                        f.Close()
                        f.Dispose()
                except Exception:
                    pass
            for fnt in fonts:
                try:
                    fnt.Dispose()
                except Exception:
                    pass

        self._run_on_ui(_do)

    def _hide_for_fullscreen(self) -> None:
        """在 Direct3D 独占全屏游戏期间静默隐藏悬浮窗（不改用户配置、不销毁实例、不抢焦点）。"""
        def _do():
            f = self._form
            if f is None:
                return
            try:
                if f.IsDisposed:
                    return
                hwnd = int(f.Handle.ToInt64())
                if hwnd and ctypes.windll.user32.IsWindowVisible(wintypes.HWND(hwnd)):
                    ctypes.windll.user32.ShowWindow(wintypes.HWND(hwnd), SW_HIDE)
                self._suppressed_by_fullscreen = True
            except Exception:
                pass

        self._run_on_ui(_do)

    def sync(
        self,
        fcfg: FloatingWidgetConfig,
        device: Optional[DeviceBattery],
        display_name: str,
        theme: str,
        hover_detail: str = "",
        low_t1: int = 30,
        low_t2: int = 20,
        low_t3: int = 10,
        animations_enabled: bool = True,
    ) -> None:
        """根据配置与设备实时状态创建/更新/隐藏桌面悬浮窗。"""
        if not fcfg.enabled:
            self.close()
            return

        # Direct3D 独占全屏游戏期间自动静默避让，避免 Windows 10 DWM 切屏或露出白框；退出全屏后自动无感恢复
        if is_exclusive_fullscreen_active():
            self._hide_for_fullscreen()
            return

        scale = self._get_dpi_scale()
        base_w, base_h = self.SIZE_MAP.get(fcfg.size, self.SIZE_MAP["medium"])
        # 同品牌多设备补充型号或自定义长名时适度自适应加宽，默认品牌名保持紧凑无多余留白
        title = (display_name or (device.name if device else "未连接")).strip()
        extra_chars = max(0, len(title) - 11)
        if extra_chars > 0:
            base_w = min(base_w + extra_chars * 7, 300)
        w = int(round(base_w * scale))
        h = int(round(base_h * scale))
        left, top, right, bottom = self._get_work_area()
        margin = int(round(EDGE_MARGIN * scale))

        if fcfg.position_preset == "top_left":
            x, y = left + margin, top + margin
        elif fcfg.position_preset == "top_right":
            x, y = right - w - margin, top + margin
        elif fcfg.position_preset == "bottom_left":
            x, y = left + margin, bottom - h - margin
        elif fcfg.position_preset == "custom" and fcfg.x is not None and fcfg.y is not None:
            x = max(left, min(int(fcfg.x), right - w))
            y = max(top, min(int(fcfg.y), bottom - h))
        else:
            x, y = right - w - margin, bottom - h - margin

        is_dark = theme == "dark"
        is_stale = bool(device and (getattr(device, "stale", False) or not device.online))
        pct = None if (device is None or is_stale) else device.percent
        charging = bool(device.charging) if (device is not None and not is_stale) else False
        kind = device.kind if device else KIND_MOUSE
        pct_text = f"{pct}%" if pct is not None else "—"
        if charging and pct is not None:
            pct_text = f"⚡{pct}%"

        if not hover_detail:
            if device is not None:
                sub = format_device_subtitle(
                    device.connection_mode, device.connected, device.online,
                    device.asleep, device.charging, device.full, pct,
                )
                if is_stale and device.percent is not None:
                    last_ts = getattr(device, "last_success_ts", None) or device.timestamp
                    ts_s = datetime.fromtimestamp(last_ts).strftime("%H:%M") if last_ts else ""
                    ref_txt = f"上次 {device.percent}% ({ts_s})" if ts_s else f"上次 {device.percent}%"
                    hover_detail = f"{device.name}\n{sub} · {ref_txt}" if sub else f"{device.name}\n{ref_txt}"
                else:
                    hover_detail = f"{device.name}\n{sub} · {pct_text}" if sub else f"{device.name}\n{pct_text}"
            else:
                hover_detail = "BattDock · 当前未检测到已连接外设"

        def _do():
            try:
                import System.Windows.Forms as WinForms
                from System.Drawing import Color, ContentAlignment, Font, FontStyle, Image as GdiImage, Pen, Point, Size
                from System.IO import MemoryStream

                self._locked = bool(fcfg.locked)

                if self._form is None or self._form.IsDisposed:
                    form = WinForms.Form()
                    form.Text = APP_FLOATING_TITLE
                    form.FormBorderStyle = getattr(WinForms.FormBorderStyle, "None")
                    form.ShowInTaskbar = False
                    form.StartPosition = WinForms.FormStartPosition.Manual

                    pic = WinForms.PictureBox()
                    pic.SizeMode = WinForms.PictureBoxSizeMode.Zoom
                    pic.BackColor = Color.Transparent
                    form.Controls.Add(pic)

                    name_lbl = WinForms.Label()
                    name_lbl.BackColor = Color.Transparent
                    name_lbl.AutoEllipsis = True
                    form.Controls.Add(name_lbl)

                    pct_lbl = WinForms.Label()
                    pct_lbl.BackColor = Color.Transparent
                    pct_lbl.TextAlign = ContentAlignment.MiddleRight
                    form.Controls.Add(pct_lbl)

                    bar_bg = WinForms.Panel()
                    bar_fill = WinForms.Panel()
                    bar_bg.Controls.Add(bar_fill)
                    form.Controls.Add(bar_bg)

                    tt = WinForms.ToolTip()
                    tt.AutoPopDelay = 6000
                    tt.InitialDelay = 350
                    tt.ReshowDelay = 150
                    tt.ShowAlways = True

                    def _on_down(_s, e):
                        if self._locked:
                            return
                        if str(e.Button) == "Left":
                            self._dragging = True
                            pos = WinForms.Cursor.Position
                            self._drag_origin_cursor = (pos.X, pos.Y)
                            self._drag_origin_form = (form.Location.X, form.Location.Y)

                    def _on_move(_s, _e):
                        if not self._dragging or self._locked:
                            return
                        pos = WinForms.Cursor.Position
                        nx = self._drag_origin_form[0] + (pos.X - self._drag_origin_cursor[0])
                        ny = self._drag_origin_form[1] + (pos.Y - self._drag_origin_cursor[1])
                        form.Location = Point(nx, ny)

                    def _on_up(_s, _e):
                        if self._dragging:
                            self._dragging = False
                            self._on_position_saved(form.Location.X, form.Location.Y)

                    def _on_dbl(_s, _e):
                        self._on_double_click()

                    for ctrl in (form, pic, name_lbl, pct_lbl, bar_bg, bar_fill):
                        ctrl.MouseDown += _on_down
                        ctrl.MouseMove += _on_move
                        ctrl.MouseUp += _on_up
                        ctrl.DoubleClick += _on_dbl

                    def _on_paint(_s, pe):
                        try:
                            dark_now = bool(getattr(form, "_battdock_dark", False))
                            sc_now = float(getattr(form, "_battdock_scale", 1.0))
                            bcol = Color.FromArgb(46, 52, 68) if dark_now else Color.FromArgb(216, 222, 232)
                            paint_winforms_rounded_border(pe.Graphics, form.Width, form.Height, 10.0 * sc_now, bcol)
                        except Exception:
                            pass

                    def _on_rgn_sync(_s, _e):
                        try:
                            if form.IsDisposed or not form.Visible:
                                return
                            h_cur = int(form.Handle.ToInt64())
                            if h_cur and ctypes.windll.user32.IsWindowVisible(wintypes.HWND(h_cur)):
                                apply_window_rounded_corners(h_cur, radius_dip=10, scale=0.0)
                                form.Invalidate()
                        except Exception:
                            pass

                    form.Paint += _on_paint
                    form.SizeChanged += _on_rgn_sync
                    try:
                        form.DpiChanged += _on_rgn_sync
                    except Exception:
                        pass

                    self._form = form
                    self._pic = pic
                    self._name_lbl = name_lbl
                    self._pct_lbl = pct_lbl
                    self._bar_bg = bar_bg
                    self._bar_fill = bar_fill
                    self._tooltip = tt
                    self._last_layout_sig = None
                    self._last_style_sig = None
                    self._last_content_sig = None

                form = self._form
                hwnd = int(form.Handle.ToInt64())
                is_visible_now = bool(hwnd and ctypes.windll.user32.IsWindowVisible(wintypes.HWND(hwnd)))
                was_suppressed = self._suppressed_by_fullscreen
                self._suppressed_by_fullscreen = False

                target_opacity = max(0.4, min(1.0, int(fcfg.opacity) / 100.0))
                target_topmost = bool(fcfg.topmost)
                layout_sig = (w, h, x, y, round(scale, 3), fcfg.size)
                style_sig = (is_dark, target_topmost, round(target_opacity, 3), fcfg.size)
                content_sig = (title, pct_text, pct, charging, kind, low_t1, low_t2, low_t3, is_dark, fcfg.size)

                # 若已可见且全部状态均无变化，后台 25 秒轮询期间零 Win32/DWM/重绘扰动
                if (
                    is_visible_now
                    and not was_suppressed
                    and layout_sig == self._last_layout_sig
                    and style_sig == self._last_style_sig
                    and content_sig == self._last_content_sig
                    and hover_detail == self._last_tooltip_text
                ):
                    return

                setattr(form, "_battdock_dark", is_dark)
                setattr(form, "_battdock_scale", scale)

                style_changed = (style_sig != self._last_style_sig) or (not is_visible_now)
                layout_changed = (layout_sig != self._last_layout_sig) or (not is_visible_now)
                size_changed = (form.Size.Width != w or form.Size.Height != h)

                if style_changed:
                    form.BackColor = Color.FromArgb(26, 30, 39) if is_dark else Color.FromArgb(250, 251, 254)
                if size_changed:
                    form.Size = Size(w, h)
                if layout_changed and not self._dragging:
                    if form.Location.X != x or form.Location.Y != y:
                        form.Location = Point(x, y)

                pad = int(round(12 * scale))
                icon_px = int(round((18 if fcfg.size == "small" else (20 if fcfg.size == "medium" else 22)) * scale))
                top_row_y = int(round((8 if fcfg.size == "small" else 10) * scale))
                row_h = int(round(22 * scale))

                if layout_changed:
                    self._pic.Size = Size(icon_px, icon_px)
                    self._pic.Location = Point(pad, top_row_y + (row_h - icon_px) // 2)

                icon_sig = (kind, icon_px, is_dark)
                if icon_sig != self._last_icon_sig:
                    self._last_icon_sig = icon_sig
                    pil_ic = render_device_icon_pil(kind, size=icon_px, is_dark=is_dark)
                    buf = io.BytesIO()
                    pil_ic.save(buf, format="PNG")
                    old_img = self._pic.Image
                    self._pic.Image = GdiImage.FromStream(MemoryStream(buf.getvalue()))
                    if old_img is not None:
                        try:
                            old_img.Dispose()
                        except Exception:
                            pass

                pct_w = int(round(48 * scale))
                text_x = pad + icon_px + int(round(8 * scale))
                text_w = max(46, w - text_x - pct_w - pad)

                name_font_key = ("name", fcfg.size)
                name_font = self._font_cache.get(name_font_key)
                if name_font is None:
                    name_font = Font(
                        resolve_winforms_font_family(numeric=False),
                        8.8 if fcfg.size == "small" else (9.5 if fcfg.size == "medium" else 10.2),
                        FontStyle.Bold,
                    )
                    self._font_cache[name_font_key] = name_font

                pct_font_key = ("pct", fcfg.size)
                pct_font = self._font_cache.get(pct_font_key)
                if pct_font is None:
                    pct_font = Font(
                        resolve_winforms_font_family(numeric=True),
                        9.0 if fcfg.size == "small" else (9.8 if fcfg.size == "medium" else 10.5),
                        FontStyle.Bold,
                    )
                    self._font_cache[pct_font_key] = pct_font

                if content_sig != self._last_content_sig or layout_changed:
                    self._name_lbl.Text = title
                    self._name_lbl.ForeColor = Color.FromArgb(241, 245, 249) if is_dark else Color.FromArgb(24, 27, 34)
                    self._name_lbl.Font = name_font
                    self._name_lbl.Size = Size(text_w, row_h)
                    self._name_lbl.Location = Point(text_x, top_row_y)

                    self._pct_lbl.Text = pct_text
                    if pct is not None and not charging and pct <= low_t3:
                        p_col = Color.FromArgb(248, 113, 113) if is_dark else Color.FromArgb(220, 38, 38)
                    elif pct is not None and not charging and pct <= low_t2:
                        p_col = Color.FromArgb(251, 146, 60) if is_dark else Color.FromArgb(234, 88, 12)
                    elif pct is not None and not charging and pct <= low_t1:
                        p_col = Color.FromArgb(250, 204, 21) if is_dark else Color.FromArgb(202, 138, 4)
                    elif charging:
                        p_col = Color.FromArgb(74, 222, 128) if is_dark else Color.FromArgb(22, 163, 74)
                    else:
                        p_col = Color.FromArgb(241, 245, 249) if is_dark else Color.FromArgb(24, 27, 34)
                    self._pct_lbl.ForeColor = p_col
                    self._pct_lbl.Font = pct_font
                    self._pct_lbl.Size = Size(pct_w, row_h)
                    self._pct_lbl.Location = Point(w - pct_w - pad, top_row_y)

                    # 底部电量进度条与左右内容对齐，支持平滑宽度过渡
                    bar_h = max(4, int(round(5 * scale)))
                    bar_y = h - int(round((10 if fcfg.size == "small" else 12) * scale))
                    bar_w = max(60, w - pad * 2)
                    self._bar_bg.Location = Point(pad, bar_y)
                    self._bar_bg.Size = Size(bar_w, bar_h)
                    self._bar_bg.BackColor = Color.FromArgb(49, 56, 71) if is_dark else Color.FromArgb(226, 232, 240)

                    target_fill_w = int(round(bar_w * (max(0, min(100, pct)) / 100.0))) if pct is not None else 0
                    if pct is None:
                        f_col = Color.FromArgb(148, 163, 184)
                    elif charging or pct > low_t1:
                        f_col = Color.FromArgb(34, 197, 94)
                    elif pct > low_t2:
                        f_col = Color.FromArgb(234, 179, 8)
                    elif pct > low_t3:
                        f_col = Color.FromArgb(245, 158, 11)
                    else:
                        f_col = Color.FromArgb(239, 68, 68)
                    self._bar_fill.BackColor = f_col
                    self._bar_fill.Location = Point(0, 0)

                    if not animations_enabled or not is_visible_now or self._bar_current_w == 0:
                        self._bar_current_w = target_fill_w
                        self._bar_target_w = target_fill_w
                        self._bar_fill.Size = Size(target_fill_w, bar_h)
                    elif target_fill_w != self._bar_target_w:
                        self._bar_target_w = target_fill_w
                        if self._bar_timer is not None:
                            try:
                                self._bar_timer.Stop()
                                self._bar_timer.Dispose()
                            except Exception:
                                pass
                        start_w = self._bar_current_w
                        steps = 10
                        step_idx = [0]
                        tmr = WinForms.Timer()
                        tmr.Interval = 18

                        def _step_bar(_s, _e):
                            step_idx[0] += 1
                            if self._bar_fill is None or self._form is None or self._form.IsDisposed:
                                tmr.Stop()
                                tmr.Dispose()
                                return
                            t = min(1.0, step_idx[0] / float(steps))
                            eased = 1.0 - (1.0 - t) ** 3
                            cur = int(round(start_w + (self._bar_target_w - start_w) * eased))
                            self._bar_current_w = cur
                            self._bar_fill.Size = Size(cur, bar_h)
                            if t >= 1.0:
                                tmr.Stop()
                                tmr.Dispose()
                                self._bar_timer = None

                        tmr.Tick += _step_bar
                        self._bar_timer = tmr
                        tmr.Start()
                    else:
                        self._bar_fill.Size = Size(self._bar_current_w, bar_h)

                if self._tooltip is not None and hover_detail != self._last_tooltip_text:
                    self._last_tooltip_text = hover_detail
                    for ctrl in (form, self._pic, self._name_lbl, self._pct_lbl, self._bar_bg, self._bar_fill):
                        self._tooltip.SetToolTip(ctrl, hover_detail)

                # 使用纯 Win32 扩展样式 + SetLayeredWindowAttributes + SetWindowPos(SWP_NOACTIVATE)，
                # 全程锁死 WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_LAYERED，杜绝抢焦点与 Alt+Tab 残留
                if style_changed or not is_visible_now:
                    apply_non_activating_tool_style(hwnd, layered=True)
                    set_layered_window_alpha(hwnd, target_opacity)
                    form.Invalidate()
                if size_changed or not is_visible_now:
                    apply_window_rounded_corners(hwnd, radius_dip=10, scale=scale)
                if not is_visible_now:
                    ctypes.windll.user32.ShowWindow(wintypes.HWND(hwnd), SW_SHOWNOACTIVATE)
                    set_window_topmost_noactivate(
                        hwnd,
                        target_topmost,
                        x=x,
                        y=y,
                        w=w,
                        h=h,
                        show=True,
                    )
                elif style_changed:
                    set_window_topmost_noactivate(hwnd, target_topmost, show=False)

                self._last_layout_sig = layout_sig
                self._last_style_sig = style_sig
                self._last_content_sig = content_sig
            except Exception:
                pass

        self._run_on_ui(_do)
