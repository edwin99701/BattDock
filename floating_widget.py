"""原生 WinForms 桌面悬浮窗与提示音播放（零 WebView2 额外开销，Windows 10/11 通用）。"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from datetime import datetime
import io
import math
import os
import sys
import threading
import time
from ctypes import wintypes
from typing import Callable, Optional

from PIL import Image, ImageDraw, ImageFont

from app_config import FloatingWidgetConfig
from brand import APP_FLOATING_TITLE
from device_icons import canonical_device_icon_kind, render_device_icon_pil
from providers import DeviceBattery, KIND_EARBUDS, KIND_HEADSET, KIND_KEYBOARD, KIND_MOUSE, KIND_OTHER
from providers.device_naming import format_device_subtitle

EDGE_MARGIN = 16
SNAP_THRESHOLD = 14
FLOATING_RADIUS_DIP = 10
FLOATING_MAX_DEVICES = 6

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
    full: bool = False,
) -> Image.Image:
    """按目标物理像素绘制细描边电池，填充长度与充电标记分别绘制。"""
    size = max(16, int(size or 64))
    online = connected and percent is not None
    pct = max(0, min(100, int(percent))) if online else 0
    if not online:
        color = (112, 112, 112)
    elif charging or full or pct > low_t1:
        color = (43, 199, 45) if light_bg else (51, 211, 48)
    elif pct <= low_t3:
        color = (240, 32, 35)
    elif pct <= low_t2:
        color = (255, 137, 6)
    else:
        color = (255, 213, 0)

    ss = 8
    grid = size * ss
    cap_w = max(2, round(size * 0.10)) * ss
    right = grid - cap_w
    body_h = round(size * 0.50) * ss
    top = (grid - body_h) // 2
    bottom = top + body_h
    cap_h = round(body_h * 0.43)
    cap_top = (grid - cap_h) // 2
    stroke = max(ss, round(grid * 0.040))
    radius = round(body_h * 0.31)
    contrast_edge = round(ss * 0.62) if light_bg else 0
    outline = (246, 246, 246, 255)
    edge = (83, 83, 83, 255)
    transparent = (0, 0, 0, 0)

    image = Image.new("RGBA", (grid, grid), transparent)
    draw = ImageDraw.Draw(image)
    # 浅色任务栏加细灰色外缘，保留参考图的浅色主线。
    draw.rounded_rectangle((0, top, right - 1, bottom - 1),
                           radius=radius, fill=edge if light_bg else outline)
    if light_bg:
        e = contrast_edge
        draw.rounded_rectangle((e, top + e, right - 1 - e, bottom - 1 - e),
                               radius=radius - e, fill=outline)
    inset = contrast_edge + stroke
    draw.rounded_rectangle((inset, top + inset, right - 1 - inset, bottom - 1 - inset),
                           radius=radius - inset, fill=transparent)

    cap = (right + ss // 4, cap_top, grid - 1, cap_top + cap_h - 1)
    draw.rounded_rectangle(cap, radius=cap_w // 2, fill=edge if light_bg else outline)
    if light_bg:
        e = contrast_edge
        draw.rounded_rectangle((cap[0] + e, cap[1] + e, cap[2] - e, cap[3] - e),
                               radius=max(0, cap_w // 2 - e), fill=outline)

    # 四舍五入仅作用于超采样网格。灰色内腔用于表达读数未知。
    inset += round(grid * 0.018)
    fill_right = right - inset
    if pct or not online:
        fill = Image.new("RGBA", image.size, transparent)
        fill_draw = ImageDraw.Draw(fill)
        fill_draw.rounded_rectangle((inset, top + inset, fill_right - 1, bottom - inset - 1),
                                    radius=max(0, radius - inset), fill=(*color, 255))
        if online and pct < 100:
            clip_x = inset + round((fill_right - inset) * pct / 100)
            fill_draw.rectangle((clip_x, top, fill_right - 1, bottom - 1), fill=transparent)
        image.alpha_composite(fill)

    if online and charging and not full:
        # 白色细边围住黑色闪电，闪电固定在电池内腔中央。
        cx = right / 2
        cy = grid / 2
        bolt_w = grid * 0.30
        bolt_h = min(grid * 0.46, body_h - 2 * inset + 2 * ss)
        bolt = [
            (round(cx + x * bolt_w), round(cy + y * bolt_h))
            for x, y in ((0.26, -0.50), (-0.50, 0.06), (-0.08, 0.06),
                         (-0.26, 0.50), (0.50, -0.08), (0.08, -0.08))
        ]
        overlay = Image.new("RGBA", image.size, transparent)
        bolt_draw = ImageDraw.Draw(overlay)
        bolt_draw.line(bolt + [bolt[0]], fill=(255, 255, 255, 255),
                       width=max(ss + 2, round(grid * 0.063)), joint="curve")
        bolt_draw.polygon(bolt, fill=(0, 0, 0, 255))
        # 充电笔画只能落在内腔区域，外框和正极不随状态改变。
        upper, lower = top + contrast_edge + stroke, bottom - contrast_edge - stroke
        image.alpha_composite(overlay.crop((0, upper, right, lower)), (0, upper))

    return image.resize((size, size), Image.Resampling.BOX)


def _try_win11_round_corners(hwnd: int, radius_dip: int = 10, scale: float = 1.0) -> str:
    """兼容别名：统一调用跨 Windows 10 / 11 圆角窗口实现。"""
    return apply_window_rounded_corners(hwnd, radius_dip=radius_dip, scale=scale)


def _apply_win11_border_color_rgb(hwnd: int, rgb: tuple[int, int, int]) -> None:
    """Windows 11 原生 DWMWA_BORDER_COLOR 细边着色（与悬停浮层统一；Win10 静默跳过）。"""
    if sys.platform != "win32" or not hwnd or not is_windows_11():
        return
    try:
        r, g, b = map(int, rgb)
        colorref = ctypes.c_uint((b << 16) | (g << 8) | r)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            34,  # DWMWA_BORDER_COLOR
            ctypes.byref(colorref),
            ctypes.sizeof(colorref),
        )
    except Exception:
        pass


@dataclass(frozen=True)
class FloatingDeviceItem:
    """桌面悬浮窗单台设备渲染条目（保留设备图标、名称、百分比、圆角进度条与充电状态）。"""

    device_id: str
    kind: str
    label: str
    percent: Optional[int]
    charging: bool
    full: bool
    connected: bool
    online: bool
    asleep: bool
    stale: bool
    low_t1: int = 30
    low_t2: int = 20
    low_t3: int = 10
    hover_detail: str = ""

    @property
    def is_inactive(self) -> bool:
        return (not self.connected) or (not self.online) or self.asleep or self.stale or (self.percent is None)

    @property
    def show_bolt(self) -> bool:
        return (not self.is_inactive) and self.charging and (not self.full)

    @property
    def value_text(self) -> str:
        if not self.connected:
            return "离线"
        if self.asleep:
            return "休眠"
        if self.is_inactive:
            return "—"
        return f"{max(0, min(100, int(self.percent)))}%"


def _floating_palette(is_dark: bool) -> dict[str, tuple[int, int, int]]:
    """低对比中性色表面与高对比电量状态色。"""
    if is_dark:
        return {
            "bg": (37, 37, 37),
            "border": (73, 73, 73),
            "text": (248, 248, 248),
            "muted": (181, 181, 181),
            "icon": (248, 248, 248),
            "icon_muted": (156, 156, 156),
            "track": (74, 74, 74),
            "normal_pct": (248, 248, 248),
            "normal_bar": (87, 196, 128),
            "charging": (111, 222, 151),
            "charging_bar": (61, 210, 119),
            "tier1": (255, 210, 101),
            "tier2": (255, 158, 96),
            "tier3": (255, 137, 137),
            "bar_t1": (244, 191, 68),
            "bar_t2": (249, 137, 71),
            "bar_t3": (255, 114, 124),
        }
    return {
        "bg": (249, 249, 249),
        "border": (212, 212, 212),
        "text": (30, 30, 30),
        "muted": (91, 91, 91),
        "icon": (30, 30, 30),
        "icon_muted": (108, 108, 108),
        "track": (222, 222, 222),
        "normal_pct": (30, 30, 30),
        "normal_bar": (23, 136, 75),
        "charging": (10, 110, 57),
        "charging_bar": (19, 154, 79),
        "tier1": (129, 84, 0),
        "tier2": (162, 62, 13),
        "tier3": (179, 36, 43),
        "bar_t1": (176, 116, 0),
        "bar_t2": (209, 90, 27),
        "bar_t3": (203, 44, 59),
    }


def _floating_item_colors(
    item: FloatingDeviceItem,
    pal: dict[str, tuple[int, int, int]],
) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """返回 (百分比颜色, 进度条填充颜色)。"""
    if item.is_inactive:
        return pal["muted"], pal["muted"]
    pct = max(0, min(100, int(item.percent or 0)))
    if item.charging or item.full:
        return pal["charging"], pal["charging_bar"]
    if pct <= item.low_t3:
        return pal["tier3"], pal["bar_t3"]
    if pct <= item.low_t2:
        return pal["tier2"], pal["bar_t2"]
    if pct <= item.low_t1:
        return pal["tier1"], pal["bar_t1"]
    return pal["normal_pct"], pal["normal_bar"]


def compute_floating_logical_size(
    size_key: str,
    items: list[FloatingDeviceItem],
) -> tuple[int, int, dict[str, int]]:
    """计算桌面悬浮窗统一逻辑尺寸 (width_dip, height_dip, metrics)，原生支持单设备与多设备同时显示。"""
    metrics_map = {
        "small": {
            "min_w": 204,
            "max_w": 276,
            "pad_x": 12,
            "pad_y": 10,
            "item_h": 30,
            "item_gap": 9,
            "icon": 16,
            "bar_h": 4,
            "name_px": 12,
            "pct_px": 13,
        },
        "medium": {
            "min_w": 232,
            "max_w": 304,
            "pad_x": 14,
            "pad_y": 12,
            "item_h": 34,
            "item_gap": 10,
            "icon": 18,
            "bar_h": 5,
            "name_px": 13,
            "pct_px": 14,
        },
        "large": {
            "min_w": 262,
            "max_w": 332,
            "pad_x": 15,
            "pad_y": 13,
            "item_h": 38,
            "item_gap": 11,
            "icon": 20,
            "bar_h": 6,
            "name_px": 14,
            "pct_px": 15,
        },
    }
    m = metrics_map.get(size_key, metrics_map["medium"])
    vis = (items or [])[:FLOATING_MAX_DEVICES]
    count = max(1, len(vis))

    longest = max((len(it.label or "") for it in vis), default=8)
    extra = max(0, longest - 14) * 6
    w_dip = max(m["min_w"], min(m["max_w"], m["min_w"] + extra))
    h_dip = m["pad_y"] * 2 + count * m["item_h"] + max(0, count - 1) * m["item_gap"]
    return int(w_dip), int(h_dip), m


def snap_floating_position(
    x: int,
    y: int,
    w: int,
    h: int,
    work_area: tuple[int, int, int, int],
    scale: float = 1.0,
) -> tuple[int, int]:
    """拖拽松手后执行工作区钳制与边缘磁性吸附（保留用户自由定位与边缘对齐手感）。"""
    wl, wt, wr, wb = map(int, work_area)
    margin = int(round(EDGE_MARGIN * max(1.0, float(scale or 1.0))))
    snap = int(round(SNAP_THRESHOLD * max(1.0, float(scale or 1.0))))

    nx = max(wl, min(int(x), max(wl, wr - w)))
    ny = max(wt, min(int(y), max(wt, wb - h)))

    if abs(nx - (wl + margin)) <= snap or nx < wl + margin:
        nx = wl + margin
    elif abs((nx + w) - (wr - margin)) <= snap or (nx + w) > wr - margin:
        nx = max(wl, wr - w - margin)

    if abs(ny - (wt + margin)) <= snap or ny < wt + margin:
        ny = wt + margin
    elif abs((ny + h) - (wb - margin)) <= snap or (ny + h) > wb - margin:
        ny = max(wt, wb - h - margin)

    return (nx, ny)


class DesktopFloatingWidget:
    """统一 Windows 原生电池风格的桌面悬浮窗（单/多设备圆角进度条、零焦点抢占、Win10/11 通用）。"""

    SIZE_MAP = {
        "small": (204, 56),
        "medium": (232, 64),
        "large": (262, 70),
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
        self._tooltip = None
        self._bar_timer = None
        self._fade_timer = None
        self._items: list[FloatingDeviceItem] = []
        self._size_key: str = "medium"
        self._metrics: dict[str, int] = {}
        self._is_dark: bool = False
        self._scale: float = 1.0
        self._bar_ratios: dict[str, float] = {}
        self._bar_targets: dict[str, float] = {}
        self._last_tooltip_text = ""
        self._last_layout_sig = None
        self._last_style_sig = None
        self._last_content_sig = None
        self._font_cache: dict[tuple[str, int], object] = {}
        self._icon_cache: dict[tuple[str, int, bool, bool], object] = {}
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

    def _stop_timers_ui(self) -> None:
        for attr in ("_bar_timer", "_fade_timer"):
            t = getattr(self, attr, None)
            setattr(self, attr, None)
            if t is not None:
                try:
                    t.Stop()
                    t.Dispose()
                except Exception:
                    pass

    def close(self) -> None:
        def _do():
            with self._lock:
                f = self._form
                self._form = None
                self._tooltip = None
                self._items = []
                self._bar_ratios.clear()
                self._bar_targets.clear()
                self._last_tooltip_text = ""
                self._last_layout_sig = None
                self._last_style_sig = None
                self._last_content_sig = None
                self._suppressed_by_fullscreen = False
                fonts = list(self._font_cache.values())
                self._font_cache.clear()
                icons = list(self._icon_cache.values())
                self._icon_cache.clear()
            self._stop_timers_ui()
            if f is not None:
                try:
                    if not f.IsDisposed:
                        try:
                            hwnd = int(f.Handle.ToInt64())
                            if hwnd:
                                set_window_topmost_noactivate(hwnd, False, show=False)
                        except Exception:
                            pass
                        f.Close()
                        f.Dispose()
                except Exception:
                    pass
            for fnt in fonts:
                try:
                    fnt.Dispose()
                except Exception:
                    pass
            for ic in icons:
                try:
                    ic.Dispose()
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

    def _get_font_ui(self, role: str, px: int):
        from System.Drawing import Font, FontStyle, GraphicsUnit

        key = (role, int(px))
        cached = self._font_cache.get(key)
        if cached is not None:
            return cached
        family = resolve_winforms_font_family(numeric=(role == "pct"))
        style = FontStyle.Bold if role == "pct" else FontStyle.Regular
        fnt = Font(family, float(max(10, int(px))), style, GraphicsUnit.Pixel)
        self._font_cache[key] = fnt
        return fnt

    def _get_icon_ui(self, kind: str, px: int, is_dark: bool, muted: bool):
        from System.Drawing import Image as GdiImage
        from System.IO import MemoryStream

        canon = canonical_device_icon_kind(kind)
        key = (canon, int(px), bool(is_dark), bool(muted))
        cached = self._icon_cache.get(key)
        if cached is not None:
            return cached
        pal = _floating_palette(is_dark)
        rgb = pal["icon_muted"] if muted else pal["icon"]
        pil_ic = render_device_icon_pil(canon, size=max(12, int(px)), is_dark=is_dark, color=(*rgb, 255))
        buf = io.BytesIO()
        pil_ic.save(buf, format="PNG")
        gdi_img = GdiImage.FromStream(MemoryStream(buf.getvalue()))
        self._icon_cache[key] = gdi_img
        return gdi_img

    @staticmethod
    def _add_rounded_rect_path(path, x: float, y: float, w: float, h: float, r: float) -> None:
        if w <= 0.5 or h <= 0.5:
            return
        d = min(max(0.0, r * 2.0), w, h)
        if d < 1.0:
            from System.Drawing import RectangleF

            path.AddRectangle(RectangleF(x, y, w, h))
            return
        path.AddArc(x, y, d, d, 180.0, 90.0)
        path.AddArc(x + w - d, y, d, d, 270.0, 90.0)
        path.AddArc(x + w - d, y + h - d, d, d, 0.0, 90.0)
        path.AddArc(x, y + h - d, d, d, 90.0, 90.0)
        path.CloseFigure()

    def _paint_surface_ui(self, g, width: int, height: int) -> None:
        """双缓冲单表面绘制统一风格的桌面悬浮窗（保留设备图标、名称、百分比、精致圆角进度条与充电闪电）。"""
        from System.Drawing import (
            Color,
            PointF,
            RectangleF,
            SolidBrush,
            StringAlignment,
            StringFormat,
            StringFormatFlags,
            StringTrimming,
        )
        from System.Drawing.Drawing2D import GraphicsPath, InterpolationMode, SmoothingMode
        from System.Drawing.Text import TextRenderingHint

        sc = self._scale
        pal = _floating_palette(self._is_dark)
        m = self._metrics
        g.SmoothingMode = SmoothingMode.AntiAlias
        g.InterpolationMode = InterpolationMode.HighQualityBicubic
        g.TextRenderingHint = TextRenderingHint.ClearTypeGridFit

        bg_b = SolidBrush(Color.FromArgb(*pal["bg"]))
        try:
            g.FillRectangle(bg_b, 0, 0, width, height)
        finally:
            bg_b.Dispose()

        items = self._items if self._items else [
            FloatingDeviceItem(
                device_id="_empty",
                kind=KIND_MOUSE,
                label="未连接外设",
                percent=None,
                charging=False,
                full=False,
                connected=False,
                online=False,
                asleep=False,
                stale=False,
            )
        ]

        pad_x = int(round(m["pad_x"] * sc))
        pad_y = int(round(m["pad_y"] * sc))
        item_h = int(round(m["item_h"] * sc))
        icon_px = max(14, int(round(m["icon"] * sc)))
        bar_h = max(4, int(round(m["bar_h"] * sc)))
        icon_gap = int(round(9 * sc))
        bolt_slot = round(12 * sc)

        name_font = self._get_font_ui("name", int(round(m["name_px"] * sc)))
        pct_font = self._get_font_ui("pct", int(round(m["pct_px"] * sc)))

        sf_left = StringFormat()
        sf_left.Alignment = StringAlignment.Near
        sf_left.LineAlignment = StringAlignment.Center
        sf_left.Trimming = StringTrimming.EllipsisCharacter
        sf_left.FormatFlags = StringFormatFlags.NoWrap

        sf_right = StringFormat()
        sf_right.Alignment = StringAlignment.Far
        sf_right.LineAlignment = StringAlignment.Center
        sf_right.Trimming = getattr(StringTrimming, "None")
        sf_right.FormatFlags = StringFormatFlags.NoWrap

        val_col_w = int(round(44 * sc))
        right_edge = width - pad_x
        val_x = right_edge - val_col_w
        name_x = pad_x + icon_px + icon_gap
        name_w = max(1, val_x - bolt_slot - round(6 * sc) - name_x)
        bar_w = right_edge - name_x

        try:
            for idx, item in enumerate(items[:FLOATING_MAX_DEVICES]):
                iy0 = pad_y + round(idx * (m["item_h"] + m["item_gap"]) * sc)
                top_row_h = item_h - bar_h - round(5 * sc)
                bar_y = iy0 + item_h - bar_h

                # 1. 统一黑白实心设备图标
                gdi_ic = self._get_icon_ui(item.kind, icon_px, self._is_dark, item.is_inactive)
                g.DrawImage(gdi_ic, pad_x, iy0 + (top_row_h - icon_px) // 2, icon_px, icon_px)

                # 2. 设备名称
                name_rgb = pal["muted"] if item.is_inactive else pal["text"]
                nb = SolidBrush(Color.FromArgb(*name_rgb))
                try:
                    g.DrawString(item.label, name_font, nb, RectangleF(float(name_x), float(iy0), float(name_w), float(top_row_h)), sf_left)
                finally:
                    nb.Dispose()

                # 电量列保持右对齐，充电闪电显示在百分比左侧。
                pct_rgb, bar_rgb = _floating_item_colors(item, pal)
                v_font = pct_font if item.value_text.isascii() else name_font
                vb = SolidBrush(Color.FromArgb(*pct_rgb))
                try:
                    g.DrawString(item.value_text, v_font, vb, RectangleF(val_x, iy0, val_col_w, top_row_h), sf_right)
                    if item.show_bolt:
                        text_width = g.MeasureString(item.value_text, v_font).Width
                        bcx = right_edge - text_width - bolt_slot * 0.45
                        bcy = float(iy0) + float(top_row_h) * 0.5
                        u = sc
                        pts = [
                            PointF(bcx + 1.1 * u, bcy - 4.8 * u),
                            PointF(bcx - 2.6 * u, bcy + 0.6 * u),
                            PointF(bcx - 0.1 * u, bcy + 0.6 * u),
                            PointF(bcx - 1.1 * u, bcy + 4.8 * u),
                            PointF(bcx + 2.6 * u, bcy - 0.6 * u),
                            PointF(bcx + 0.1 * u, bcy - 0.6 * u),
                        ]
                        g.FillPolygon(vb, pts)
                finally:
                    vb.Dispose()

                # 4. 精致胶囊圆角电量进度条（轨道 + 实心平滑填充）
                radius_bar = float(bar_h) * 0.5
                track_path = GraphicsPath()
                track_b = SolidBrush(Color.FromArgb(*pal["track"]))
                try:
                    self._add_rounded_rect_path(track_path, float(name_x), float(bar_y), float(bar_w), float(bar_h), radius_bar)
                    g.FillPath(track_b, track_path)
                finally:
                    track_b.Dispose()
                    track_path.Dispose()

                ratio = self._bar_ratios.get(item.device_id, 0.0 if item.is_inactive else max(0.0, min(1.0, float(item.percent or 0) / 100.0)))
                if ratio > 0.005 and not item.is_inactive:
                    fill_w = max(1.0, bar_w * ratio)
                    fill_path = GraphicsPath()
                    fill_b = SolidBrush(Color.FromArgb(*bar_rgb))
                    try:
                        self._add_rounded_rect_path(fill_path, float(name_x), float(bar_y), fill_w, float(bar_h), min(radius_bar, fill_w / 2))
                        g.FillPath(fill_b, fill_path)
                    finally:
                        fill_b.Dispose()
                        fill_path.Dispose()

            # 5. Win10 绘制 1px 抗锯齿圆角细边（Win11 由原生 DWMWA_BORDER_COLOR 负责）
            if not is_windows_11():
                bcol = Color.FromArgb(*pal["border"])
                paint_winforms_rounded_border(g, width, height, float(FLOATING_RADIUS_DIP) * sc, bcol)
        finally:
            sf_left.Dispose()
            sf_right.Dispose()

    def _animate_fade_in_ui(self, hwnd: int, target_opacity: float, duration_ms: int = 140) -> None:
        import System.Windows.Forms as WinForms

        if self._fade_timer is not None:
            try:
                self._fade_timer.Stop()
                self._fade_timer.Dispose()
            except Exception:
                pass
            self._fade_timer = None

        start_t = time.monotonic()
        dur_s = max(0.04, float(duration_ms) / 1000.0)
        tmr = WinForms.Timer()
        tmr.Interval = 15

        def _tick(_s, _e) -> None:
            if self._form is None or self._form.IsDisposed:
                try:
                    tmr.Stop()
                    tmr.Dispose()
                except Exception:
                    pass
                self._fade_timer = None
                return
            prog = min(1.0, (time.monotonic() - start_t) / dur_s)
            eased = 1.0 - (1.0 - prog) ** 3
            set_layered_window_alpha(hwnd, target_opacity * eased)
            if prog >= 1.0:
                tmr.Stop()
                tmr.Dispose()
                self._fade_timer = None
                set_layered_window_alpha(hwnd, target_opacity)

        tmr.Tick += _tick
        self._fade_timer = tmr
        tmr.Start()

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
        items: Optional[list[FloatingDeviceItem]] = None,
    ) -> None:
        """根据配置与设备实时状态创建/更新/隐藏桌面悬浮窗（同时兼容单设备与多设备列表）。"""
        if not fcfg.enabled:
            self.close()
            return

        # Direct3D 独占全屏游戏期间自动静默避让，避免 Windows 10 DWM 切屏或露出白框；退出全屏后自动无感恢复
        if is_exclusive_fullscreen_active():
            self._hide_for_fullscreen()
            return

        # 构建最终渲染条目列表（传入 items 时原生多设备显示；未传时完全兼容既有单设备调用）
        if items is not None:
            render_items = list(items)[:FLOATING_MAX_DEVICES]
        else:
            is_stale = bool(device and (getattr(device, "stale", False) or not device.online))
            pct = None if (device is None or is_stale) else device.percent
            chg = bool(device.charging) if (device is not None and not is_stale) else False
            full = bool(device.full) if (device is not None and not is_stale) else False
            title = (display_name or (device.name if device else "未连接外设")).strip()
            render_items = [
                FloatingDeviceItem(
                    device_id=(device.device_id if device else "_empty"),
                    kind=(device.kind if device else KIND_MOUSE),
                    label=title,
                    percent=pct,
                    charging=chg,
                    full=full,
                    connected=bool(device.connected) if device is not None else False,
                    online=bool(device.online) if device is not None else False,
                    asleep=bool(device.asleep) if device is not None else False,
                    stale=is_stale,
                    low_t1=low_t1,
                    low_t2=low_t2,
                    low_t3=low_t3,
                    hover_detail=hover_detail,
                )
            ]

        if not render_items:
            render_items = [
                FloatingDeviceItem(
                    device_id="_empty",
                    kind=KIND_MOUSE,
                    label="未连接外设",
                    percent=None,
                    charging=False,
                    full=False,
                    connected=False,
                    online=False,
                    asleep=False,
                    stale=False,
                    hover_detail="BattDock · 当前未检测到已连接外设",
                )
            ]

        if not hover_detail:
            details = [it.hover_detail for it in render_items if it.hover_detail]
            if details:
                hover_detail = "\n".join(details)
            elif device is not None:
                is_stale_d = bool(getattr(device, "stale", False) or not device.online)
                pct_d = None if is_stale_d else device.percent
                sub = format_device_subtitle(
                    device.connection_mode, device.connected, device.online,
                    device.asleep, device.charging, device.full, pct_d,
                )
                pct_txt = f"{pct_d}%" if pct_d is not None else "—"
                hover_detail = f"{device.name}\n{sub} · {pct_txt}" if sub else f"{device.name} · {pct_txt}"
            else:
                hover_detail = "BattDock · 当前未检测到已连接外设"

        scale = max(1.0, float(self._get_dpi_scale() or 1.0))
        base_w, base_h, metrics = compute_floating_logical_size(fcfg.size, render_items)
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
            x = max(left, min(int(fcfg.x), max(left, right - w)))
            y = max(top, min(int(fcfg.y), max(top, bottom - h)))
        else:
            x, y = right - w - margin, bottom - h - margin

        is_dark = theme == "dark"

        def _do():
            try:
                import System.Windows.Forms as WinForms
                from System.Drawing import Color, Point, Size

                self._locked = bool(fcfg.locked)

                if self._form is None or self._form.IsDisposed:
                    form = WinForms.Form()
                    form.Text = APP_FLOATING_TITLE
                    form.FormBorderStyle = getattr(WinForms.FormBorderStyle, "None")
                    form.ShowInTaskbar = False
                    form.StartPosition = WinForms.FormStartPosition.Manual
                    try:
                        from System.Reflection import BindingFlags

                        prop = form.GetType().GetProperty(
                            "DoubleBuffered",
                            BindingFlags.Instance | BindingFlags.NonPublic,
                        )
                        if prop is not None:
                            prop.SetValue(form, True, None)
                    except Exception:
                        pass

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
                            wa = self._get_work_area()
                            sx, sy = snap_floating_position(
                                form.Location.X,
                                form.Location.Y,
                                form.Width,
                                form.Height,
                                wa,
                                scale=self._scale,
                            )
                            form.Location = Point(sx, sy)
                            self._on_position_saved(sx, sy)

                    def _on_dbl(_s, _e):
                        self._on_double_click()

                    def _on_paint(_s, pe):
                        try:
                            self._paint_surface_ui(pe.Graphics, form.Width, form.Height)
                        except Exception:
                            pass

                    def _on_rgn_sync(_s, _e):
                        try:
                            if form.IsDisposed or not form.Visible:
                                return
                            h_cur = int(form.Handle.ToInt64())
                            if h_cur and ctypes.windll.user32.IsWindowVisible(wintypes.HWND(h_cur)):
                                apply_window_rounded_corners(h_cur, radius_dip=FLOATING_RADIUS_DIP, scale=0.0)
                                form.Invalidate()
                        except Exception:
                            pass

                    form.MouseDown += _on_down
                    form.MouseMove += _on_move
                    form.MouseUp += _on_up
                    form.DoubleClick += _on_dbl
                    form.Paint += _on_paint
                    form.SizeChanged += _on_rgn_sync
                    try:
                        form.DpiChanged += _on_rgn_sync
                    except Exception:
                        pass

                    self._form = form
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
                layout_sig = (w, h, x, y, round(scale, 3), fcfg.size, len(render_items))
                style_sig = (is_dark, target_topmost, round(target_opacity, 3), fcfg.size)
                content_sig = tuple(
                    (it.device_id, it.kind, it.label, it.percent, it.charging, it.full, it.connected, it.online, it.asleep, it.stale, it.low_t1, it.low_t2, it.low_t3)
                    for it in render_items
                )

                # 若已可见且全部状态无变化，后台 25 秒轮询期间零 Win32/DWM/重绘扰动
                if (
                    is_visible_now
                    and not was_suppressed
                    and layout_sig == self._last_layout_sig
                    and style_sig == self._last_style_sig
                    and content_sig == self._last_content_sig
                    and hover_detail == self._last_tooltip_text
                ):
                    return

                self._items = render_items
                self._size_key = fcfg.size
                self._metrics = metrics
                self._is_dark = is_dark
                self._scale = scale
                setattr(form, "_battdock_dark", is_dark)
                setattr(form, "_battdock_scale", scale)

                pal = _floating_palette(is_dark)
                style_changed = (style_sig != self._last_style_sig) or (not is_visible_now)
                layout_changed = (layout_sig != self._last_layout_sig) or (not is_visible_now)
                size_changed = (form.Size.Width != w or form.Size.Height != h)

                if style_changed:
                    form.BackColor = Color.FromArgb(*pal["bg"])
                if size_changed:
                    form.Size = Size(w, h)
                if layout_changed and not self._dragging:
                    if form.Location.X != x or form.Location.Y != y:
                        form.Location = Point(x, y)

                # 平滑更新各设备进度条填充比例
                new_targets: dict[str, float] = {}
                need_anim = False
                for it in render_items:
                    tr = 0.0 if it.is_inactive else max(0.0, min(1.0, float(it.percent or 0) / 100.0))
                    new_targets[it.device_id] = tr
                    if it.device_id not in self._bar_ratios or not animations_enabled or not is_visible_now:
                        self._bar_ratios[it.device_id] = tr
                    elif abs(self._bar_ratios[it.device_id] - tr) > 0.005:
                        need_anim = True
                # 清理已移除设备的缓存键
                for stale_id in list(self._bar_ratios.keys()):
                    if stale_id not in new_targets:
                        self._bar_ratios.pop(stale_id, None)
                self._bar_targets = new_targets

                if need_anim:
                    if self._bar_timer is not None:
                        try:
                            self._bar_timer.Stop()
                            self._bar_timer.Dispose()
                        except Exception:
                            pass
                        self._bar_timer = None
                    start_ratios = dict(self._bar_ratios)
                    steps = 10
                    step_idx = [0]
                    tmr = WinForms.Timer()
                    tmr.Interval = 18

                    def _step_bars(_s, _e):
                        step_idx[0] += 1
                        if self._form is None or self._form.IsDisposed:
                            tmr.Stop()
                            tmr.Dispose()
                            self._bar_timer = None
                            return
                        t = min(1.0, step_idx[0] / float(steps))
                        eased = 1.0 - (1.0 - t) ** 3
                        for did, tr in self._bar_targets.items():
                            sr = start_ratios.get(did, tr)
                            self._bar_ratios[did] = sr + (tr - sr) * eased
                        self._form.Invalidate()
                        if t >= 1.0:
                            tmr.Stop()
                            tmr.Dispose()
                            self._bar_timer = None

                    tmr.Tick += _step_bars
                    self._bar_timer = tmr
                    tmr.Start()

                if self._tooltip is not None and hover_detail != self._last_tooltip_text:
                    self._last_tooltip_text = hover_detail
                    self._tooltip.SetToolTip(form, hover_detail)

                # 纯 Win32 扩展样式 + SetLayeredWindowAttributes + SetWindowPos(SWP_NOACTIVATE)
                if style_changed or not is_visible_now:
                    apply_non_activating_tool_style(hwnd, layered=True)
                    _apply_win11_border_color_rgb(hwnd, pal["border"])
                if size_changed or not is_visible_now:
                    apply_window_rounded_corners(hwnd, radius_dip=FLOATING_RADIUS_DIP, scale=scale)
                form.Invalidate()

                if not is_visible_now:
                    if animations_enabled:
                        set_layered_window_alpha(hwnd, 0.0)
                    else:
                        set_layered_window_alpha(hwnd, target_opacity)
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
                    if animations_enabled:
                        self._animate_fade_in_ui(hwnd, target_opacity, duration_ms=140)
                else:
                    if style_changed:
                        set_layered_window_alpha(hwnd, target_opacity)
                        set_window_topmost_noactivate(hwnd, target_topmost, show=False)

                self._last_layout_sig = layout_sig
                self._last_style_sig = style_sig
                self._last_content_sig = content_sig
            except Exception:
                pass

        self._run_on_ui(_do)


def render_floating_widget_pil(
    items: list[FloatingDeviceItem],
    *,
    size_key: str = "medium",
    is_dark: bool = False,
    scale: float = 1.0,
) -> Image.Image:
    """高保真离屏渲染桌面悬浮窗（与线上 WinForms 布局/颜色/进度条完全同源，用于多 DPI 视觉核验）。"""
    sc = max(1.0, float(scale or 1.0))
    pal = _floating_palette(is_dark)
    w_dip, h_dip, m = compute_floating_logical_size(size_key, items)
    pw = int(round(w_dip * sc))
    ph = int(round(h_dip * sc))

    ss = 2
    bg_img = Image.new("RGBA", (pw * ss, ph * ss), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bg_img)
    bd.rounded_rectangle(
        [0, 0, pw * ss - 1, ph * ss - 1],
        radius=int(round(FLOATING_RADIUS_DIP * sc * ss)),
        fill=(*pal["bg"], 255),
        outline=(*pal["border"], 255),
        width=max(1, ss),
    )
    out = bg_img.resize((pw, ph), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(out)

    def _load_f(numeric: bool, px: int):
        cands = (
            [r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\segoeui.ttf"]
            if numeric
            else [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\segoeui.ttf"]
        )
        for p in cands:
            try:
                return ImageFont.truetype(p, px)
            except Exception:
                continue
        return ImageFont.load_default()

    name_font = _load_f(False, max(10, int(round(m["name_px"] * sc))))
    pct_font = _load_f(True, max(10, int(round(m["pct_px"] * sc))))

    eff_items = (items or [])[:FLOATING_MAX_DEVICES] or [
        FloatingDeviceItem("_empty", KIND_MOUSE, "未连接外设", None, False, False, False, False, False, False)
    ]
    pad_x = int(round(m["pad_x"] * sc))
    pad_y = int(round(m["pad_y"] * sc))
    item_h = int(round(m["item_h"] * sc))
    icon_px = max(14, int(round(m["icon"] * sc)))
    bar_h = max(4, int(round(m["bar_h"] * sc)))
    icon_gap = int(round(9 * sc))
    bolt_slot = round(12 * sc)
    right_edge = pw - pad_x
    name_x = pad_x + icon_px + icon_gap
    bar_w = right_edge - name_x
    max_name_w = right_edge - round(44 * sc) - bolt_slot - round(6 * sc) - name_x

    for idx, item in enumerate(eff_items):
        iy0 = pad_y + round(idx * (m["item_h"] + m["item_gap"]) * sc)
        top_row_h = item_h - bar_h - round(5 * sc)
        bar_y = iy0 + item_h - bar_h

        ic_rgb = pal["icon_muted"] if item.is_inactive else pal["icon"]
        ic = render_device_icon_pil(item.kind, size=icon_px, is_dark=is_dark, color=(*ic_rgb, 255))
        out.alpha_composite(ic, (pad_x, iy0 + (top_row_h - icon_px) // 2))

        v_font = pct_font if item.value_text.isascii() else name_font
        vb = draw.textbbox((0, 0), item.value_text, font=v_font)
        vw, vh = vb[2] - vb[0], vb[3] - vb[1]
        pct_rgb, bar_rgb = _floating_item_colors(item, pal)
        draw.text((right_edge - vw, iy0 + (top_row_h - vh) // 2 - vb[1]), item.value_text, font=v_font, fill=(*pct_rgb, 255))

        if item.show_bolt:
            bcx = right_edge - vw - bolt_slot * 0.5
            bcy = iy0 + top_row_h * 0.5
            u = sc
            pts = [
                (bcx + 1.1 * u, bcy - 4.8 * u),
                (bcx - 2.6 * u, bcy + 0.6 * u),
                (bcx - 0.1 * u, bcy + 0.6 * u),
                (bcx - 1.1 * u, bcy + 4.8 * u),
                (bcx + 2.6 * u, bcy - 0.6 * u),
                (bcx + 0.1 * u, bcy - 0.6 * u),
            ]
            draw.polygon(pts, fill=(*pct_rgb, 255))

        nm = item.label
        while len(nm) > 2 and draw.textbbox((0, 0), nm, font=name_font)[2] > max_name_w:
            nm = nm[:-2].rstrip() + "…"
        nb = draw.textbbox((0, 0), nm, font=name_font)
        nh = nb[3] - nb[1]
        draw.text((name_x, iy0 + (top_row_h - nh) // 2 - nb[1]), nm, font=name_font, fill=(*(pal["muted"] if item.is_inactive else pal["text"]), 255))

        # 胶囊圆角进度条（2x 超采样抗锯齿）
        bar_img = Image.new("RGBA", (bar_w * 2, bar_h * 2), (0, 0, 0, 0))
        bdr = ImageDraw.Draw(bar_img)
        r2 = bar_h
        bdr.rounded_rectangle([0, 0, bar_w * 2 - 1, bar_h * 2 - 1], radius=r2, fill=(*pal["track"], 255))
        if not item.is_inactive and (item.percent or 0) > 0:
            ratio = max(0.0, min(1.0, float(item.percent or 0) / 100.0))
            fw2 = max(2, round(bar_w * 2 * ratio))
            bdr.rounded_rectangle([0, 0, fw2 - 1, bar_h * 2 - 1], radius=r2, fill=(*bar_rgb, 255))
        bar_rs = bar_img.resize((bar_w, bar_h), Image.Resampling.LANCZOS)
        out.alpha_composite(bar_rs, (name_x, bar_y))

    return out
