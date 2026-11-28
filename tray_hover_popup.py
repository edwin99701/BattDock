"""BattDock 系统托盘悬停紧凑电量浮层（原生 WinForms + Win32 非激活工具窗，Win10/11 通用）。

核心设计原则：
1. 独立非激活工具窗：全程使用 WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_LAYERED，
   通过 SetLayeredWindowAttributes 与 SetWindowPos(SWP_NOACTIVATE | SWP_NOOWNERZORDER) 控制显隐与过渡动画，
   绝不抢占前台焦点、绝不进入 Alt+Tab、绝不产生任务栏按钮、绝不连带主/设置/悬浮窗置顶。
2. 零子控件闪烁与零白屏：整窗单表面双缓冲 GDI+ 绘制，复用 device_icons.py 统一黑白实心设备图标与
   resolve_winforms_font_family() 现代桌面字体栈，Direct3D 独占全屏游戏期间静默避让。
3. Win10 / Win11 统一视觉与原生圆角兼容：
   - Windows 11：原生 DWMWCP_ROUND 圆角 + 原生 DWMWA_BORDER_COLOR 细边（自带柔和系统阴影）；
   - Windows 10：禁用 DWMNCRP_DISABLED 并清零 ExtendFrame，结合 CreateRoundRectRgn + SetWindowRgn 裁切与
     1px 抗锯齿圆角细边，四角干净无白底/黑角残留。
4. 精准锚定与可靠回退：优先依据 Shell_NotifyIconGetRect 锚定真实托盘图标位置，自动适配 100%–200% DPI、
   多显示器（含负坐标副屏）、Win10 四向任务栏、任务栏自动隐藏及 Win10/11 托盘折叠区，并严格钳制于工作区内。
5. 零新增轮询线程：直接复用统一设备管理层最新状态快照，悬停不触发任何额外 HID/蓝牙查询。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import io
import math
import sys
import threading
import time
from typing import Any, Callable, Optional

from PIL import Image, ImageDraw, ImageFont

from device_icons import canonical_device_icon_kind, render_device_icon_pil
from floating_widget import (
    SW_HIDE,
    SW_SHOWNOACTIVATE,
    apply_non_activating_tool_style,
    apply_window_rounded_corners,
    is_exclusive_fullscreen_active,
    is_windows_11,
    paint_winforms_rounded_border,
    resolve_winforms_font_family,
    set_layered_window_alpha,
    set_window_topmost_noactivate,
)
from providers.base import KIND_OTHER

# 紧凑视觉规范常量（逻辑 DIP）
POPUP_MIN_WIDTH_DIP = 220
POPUP_MAX_WIDTH_DIP = 320
POPUP_ROW_HEIGHT_DIP = 32
POPUP_PAD_X_DIP = 12
POPUP_PAD_Y_DIP = 8
POPUP_RADIUS_DIP = 9
POPUP_ICON_DIP = 16
POPUP_ICON_GAP_DIP = 9
POPUP_VALUE_GAP_DIP = 12
POPUP_BOLT_SLOT_DIP = 13
POPUP_MAX_VISIBLE_ROWS = 6
POPUP_ANCHOR_GAP_DIP = 8
POPUP_WORKAREA_MARGIN_DIP = 8

SHOW_DELAY_SEC = 0.30
HIDE_DELAY_SEC = 0.20
FADE_IN_MS = 135
FADE_OUT_MS = 105
HOVER_POLL_MS = 55

_OVERFLOW_CLASS_NAMES = (
    "NotifyIconOverflowWindow",
    "TopLevelWindowForOverflowXamlIsland",
    "Xaml_WindowedPopupClass",
)


@dataclass(frozen=True)
class TrayHoverRow:
    """托盘悬停浮层单行设备渲染数据模型（直接由统一设备快照构建）。"""

    device_id: str
    kind: str
    name: str
    percent: Optional[int]
    charging: bool
    full: bool
    connected: bool
    online: bool
    asleep: bool
    stale: bool
    alert_level: str  # normal | tier1 | tier2 | tier3 | charging | full | offline | sleep | unknown
    value_text: str   # 如 "75%"、"100%"、"休眠"、"离线"、"—"
    show_bolt: bool


def build_tray_hover_rows(
    devices: list[Any],
    aliases: Optional[dict[str, str]] = None,
    tier_lookup: Optional[Callable[[str], tuple[int, int, int]]] = None,
    hidden_ids: Optional[set[str]] = None,
) -> list[TrayHoverRow]:
    """将统一设备管理层的 DeviceBattery 列表转换为紧凑悬停浮层行列表（绝不伪造实时电量）。"""
    from providers.device_naming import resolve_tray_hover_device_names

    hidden = hidden_ids or set()
    visible_devs = [d for d in (devices or []) if str(getattr(d, "device_id", "")) not in hidden]
    if not visible_devs:
        return []

    names = resolve_tray_hover_device_names(visible_devs, aliases=aliases)
    rows: list[TrayHoverRow] = []
    for dev, disp_name in zip(visible_devs, names):
        did = str(getattr(dev, "device_id", "") or "")
        connected = bool(getattr(dev, "connected", False))
        online = bool(getattr(dev, "online", False))
        asleep = bool(getattr(dev, "asleep", False))
        stale = bool(getattr(dev, "stale", False))
        raw_pct = getattr(dev, "percent", None)
        charging = bool(getattr(dev, "charging", False))
        full = bool(getattr(dev, "full", False))

        is_inactive = (not connected) or (not online) or asleep or stale or (raw_pct is None)
        if not connected:
            rows.append(
                TrayHoverRow(
                    device_id=did,
                    kind=canonical_device_icon_kind(getattr(dev, "kind", KIND_OTHER)),
                    name=disp_name,
                    percent=None,
                    charging=False,
                    full=False,
                    connected=False,
                    online=False,
                    asleep=False,
                    stale=stale,
                    alert_level="offline",
                    value_text="离线",
                    show_bolt=False,
                )
            )
            continue

        if asleep:
            rows.append(
                TrayHoverRow(
                    device_id=did,
                    kind=canonical_device_icon_kind(getattr(dev, "kind", KIND_OTHER)),
                    name=disp_name,
                    percent=None,
                    charging=False,
                    full=False,
                    connected=True,
                    online=False,
                    asleep=True,
                    stale=stale,
                    alert_level="sleep",
                    value_text="休眠",
                    show_bolt=False,
                )
            )
            continue

        if is_inactive:
            rows.append(
                TrayHoverRow(
                    device_id=did,
                    kind=canonical_device_icon_kind(getattr(dev, "kind", KIND_OTHER)),
                    name=disp_name,
                    percent=None,
                    charging=False,
                    full=False,
                    connected=connected,
                    online=False,
                    asleep=False,
                    stale=True,
                    alert_level="unknown",
                    value_text="—",
                    show_bolt=False,
                )
            )
            continue

        pct = max(0, min(100, int(raw_pct)))
        t1, t2, t3 = tier_lookup(did) if tier_lookup is not None else (30, 20, 10)
        is_full = bool(full)
        show_bolt = bool(charging) and (not is_full)
        if is_full:
            level = "full"
        elif charging:
            level = "charging"
        elif pct <= t3:
            level = "tier3"
        elif pct <= t2:
            level = "tier2"
        elif pct <= t1:
            level = "tier1"
        else:
            level = "normal"

        rows.append(
            TrayHoverRow(
                device_id=did,
                kind=canonical_device_icon_kind(getattr(dev, "kind", KIND_OTHER)),
                name=disp_name,
                percent=pct,
                charging=charging,
                full=is_full,
                connected=True,
                online=True,
                asleep=False,
                stale=False,
                alert_level=level,
                value_text=f"{pct}%",
                show_bolt=show_bolt,
            )
        )
    return rows


def compute_popup_logical_size(
    rows: list[TrayHoverRow],
    measure_text_dip: Optional[Callable[[str, bool], float]] = None,
) -> tuple[int, int, int, bool]:
    """计算浮层紧凑逻辑尺寸 (width_dip, height_dip, visible_rows, scrollable)。

    宽度在 220–320 DIP 之间按内容自适应；高度按真实设备数收紧，超出 POPUP_MAX_VISIBLE_ROWS 时限高滚动。
    """
    eff_rows = rows if rows else [
        TrayHoverRow(
            device_id="",
            kind=KIND_OTHER,
            name="暂无已连接设备",
            percent=None,
            charging=False,
            full=False,
            connected=False,
            online=False,
            asleep=False,
            stale=False,
            alert_level="unknown",
            value_text="—",
            show_bolt=False,
        )
    ]

    any_bolt = any(r.show_bolt for r in eff_rows)
    scrollable = len(eff_rows) > POPUP_MAX_VISIBLE_ROWS
    vis_count = min(len(eff_rows), POPUP_MAX_VISIBLE_ROWS)

    def _default_measure(txt: str, is_num: bool) -> float:
        total = 0.0
        for ch in txt:
            if ord(ch) > 127:
                total += 12.5
            elif ch.isupper():
                total += 8.2
            elif ch.isdigit() or ch == "%":
                total += 7.8 if is_num else 7.4
            elif ch == " ":
                total += 4.2
            else:
                total += 6.6
        return total

    mfn = measure_text_dip or _default_measure
    max_name_w = max((mfn(r.name, False) for r in eff_rows), default=90.0)
    max_val_w = max((mfn(r.value_text, True) for r in eff_rows), default=32.0)
    max_val_w = max(max_val_w, 34.0)

    bolt_w = POPUP_BOLT_SLOT_DIP if any_bolt else 0
    scroll_w = 8 if scrollable else 0
    needed_w = (
        POPUP_PAD_X_DIP * 2
        + POPUP_ICON_DIP
        + POPUP_ICON_GAP_DIP
        + math.ceil(max_name_w)
        + POPUP_VALUE_GAP_DIP
        + math.ceil(max_val_w)
        + bolt_w
        + scroll_w
    )
    width_dip = max(POPUP_MIN_WIDTH_DIP, min(POPUP_MAX_WIDTH_DIP, int(needed_w)))
    height_dip = POPUP_PAD_Y_DIP * 2 + vis_count * POPUP_ROW_HEIGHT_DIP
    return width_dip, height_dip, vis_count, scrollable


def compute_hover_popup_rect(
    icon_rect: Optional[tuple[int, int, int, int]],
    cursor_pos: tuple[int, int],
    popup_size: tuple[int, int],
    monitor_rect: tuple[int, int, int, int],
    work_area: tuple[int, int, int, int],
    scale: float = 1.0,
    overflow_rect: Optional[tuple[int, int, int, int]] = None,
) -> tuple[int, int]:
    """根据托盘图标真实屏幕矩形计算悬停浮层物理坐标 (x, y)。

    完整覆盖：
    - Windows 10/11 底部任务栏、Win10 顶部/左侧/右侧任务栏；
    - 任务栏自动隐藏（work_area == monitor_rect 时自动向屏幕内侧弹出）；
    - Win10/11 托盘折叠区（优先在折叠面板外侧展开不遮挡图标）；
    - 多显示器（支持负坐标副屏）与 100%–200% DPI 缩放；
    - 严格钳制在当前显示器可用工作区内，杜绝越界或随机跳动。
    """
    sc = max(0.75, float(scale or 1.0))
    pw, ph = max(1, int(popup_size[0])), max(1, int(popup_size[1]))
    ml, mt, mr, mb = map(int, monitor_rect)
    wl, wt, wr, wb = map(int, work_area)
    cx, cy = int(cursor_pos[0]), int(cursor_pos[1])

    gap = max(6, int(round(POPUP_ANCHOR_GAP_DIP * sc)))
    margin = max(6, int(round(POPUP_WORKAREA_MARGIN_DIP * sc)))

    # 校验 icon_rect 是否有效且接近当前悬停光标（防范折叠区返回陈旧或主任务栏占位坐标）
    anchor: Optional[tuple[int, int, int, int]] = None
    if icon_rect is not None:
        il, it, ir, ib = map(int, icon_rect)
        if ir > il and ib > it:
            tol = max(48, int(round(44 * sc)))
            if (il - tol) <= cx <= (ir + tol) and (it - tol) <= cy <= (ib + tol):
                anchor = (il, it, ir, ib)
    if anchor is None:
        half = max(10, int(round(12 * sc)))
        anchor = (cx - half, cy - half, cx + half, cy + half)

    al, at, ar, ab = anchor
    acx = (al + ar) // 2
    acy = (at + ab) // 2

    # 检测任务栏方向：先看 work_area 相对 monitor_rect 缩进边，若为自动隐藏任务栏则按图标靠近哪条屏幕边判定
    if wb < mb - 4:
        edge = "bottom"
    elif wt > mt + 4:
        edge = "top"
    elif wl > ml + 4:
        edge = "left"
    elif wr < mr - 4:
        edge = "right"
    else:
        dists = {
            "bottom": abs(mb - ab),
            "top": abs(at - mt),
            "left": abs(al - ml),
            "right": abs(mr - ar),
        }
        edge = min(dists, key=dists.get)

    if overflow_rect is not None:
        ol, ot, or_, ob = map(int, overflow_rect)
        if edge in ("bottom", "top"):
            # 折叠面板通常靠近右下/右上，优先向左展开，空间不足则向右或向上/下展开
            if ol - gap - pw >= wl + margin:
                x = ol - gap - pw
                y = acy - ph // 2
            elif or_ + gap + pw <= wr - margin:
                x = or_ + gap
                y = acy - ph // 2
            elif edge == "bottom" and ot - gap - ph >= wt + margin:
                x = acx - pw // 2
                y = ot - gap - ph
            else:
                x = acx - pw // 2
                y = ob + gap
        else:
            if edge == "left":
                x = or_ + gap
                y = acy - ph // 2
            else:
                x = ol - gap - pw
                y = acy - ph // 2
    else:
        if edge == "bottom":
            x = acx - pw // 2
            y = min(at, wb) - gap - ph
        elif edge == "top":
            x = acx - pw // 2
            y = max(ab, wt) + gap
        elif edge == "left":
            x = max(ar, wl) + gap
            y = acy - ph // 2
        else:
            x = min(al, wr) - gap - pw
            y = acy - ph // 2

    # 严格钳制在当前显示器可用工作区内
    min_x = wl + margin
    max_x = max(min_x, wr - margin - pw)
    min_y = wt + margin
    max_y = max(min_y, wb - margin - ph)
    x = max(min_x, min(int(x), max_x))
    y = max(min_y, min(int(y), max_y))
    return (x, y)


def is_point_in_rect(pt: tuple[int, int], rect: Optional[tuple[int, int, int, int]], pad: int = 0) -> bool:
    if rect is None:
        return False
    x, y = int(pt[0]), int(pt[1])
    l, t, r, b = map(int, rect)
    return (l - pad) <= x <= (r + pad) and (t - pad) <= y <= (b + pad)


def is_point_in_bridge_corridor(
    pt: tuple[int, int],
    icon_rect: Optional[tuple[int, int, int, int]],
    popup_rect: Optional[tuple[int, int, int, int]],
    pad: int = 6,
) -> bool:
    """判定光标是否处于托盘图标与浮层之间的短暂过渡走廊内，避免移动去滚轮浏览列表时提前误关。"""
    if icon_rect is None or popup_rect is None:
        return False
    il, it, ir, ib = map(int, icon_rect)
    pl, pt_, pr, pb = map(int, popup_rect)
    # 水平或垂直包围带（仅覆盖两矩形之间狭小间隙，避免过大导致移开很久不隐藏）
    if pb <= it:
        corridor = (min(il, pl) - pad, pb - pad, max(ir, pr) + pad, it + pad)
    elif pt_ >= ib:
        corridor = (min(il, pl) - pad, ib - pad, max(ir, pr) + pad, pt_ + pad)
    elif pr <= il:
        corridor = (pr - pad, min(it, pt_) - pad, il + pad, max(ib, pb) + pad)
    elif pl >= ir:
        corridor = (ir - pad, min(it, pt_) - pad, pl + pad, max(ib, pb) + pad)
    else:
        return False
    return is_point_in_rect(pt, corridor, pad=0)


class TrayHoverStateMachine:
    """纯时间驱动的托盘悬停防抖状态机（300ms 延迟显示、200ms 离开收起、快速划过零闪烁）。"""

    def __init__(
        self,
        show_delay_sec: float = SHOW_DELAY_SEC,
        hide_delay_sec: float = HIDE_DELAY_SEC,
    ) -> None:
        self.show_delay_sec = max(0.05, float(show_delay_sec))
        self.hide_delay_sec = max(0.05, float(hide_delay_sec))
        self.state: str = "idle"  # idle | pending_show | visible | pending_hide
        self.enter_mono: float = 0.0
        self.last_tray_move_mono: float = 0.0
        self.leave_mono: float = 0.0
        self.anchor_icon_rect: Optional[tuple[int, int, int, int]] = None
        self.last_cursor: tuple[int, int] = (0, 0)

    def on_tray_move(
        self,
        now_mono: float,
        cursor_pos: tuple[int, int],
        icon_rect: Optional[tuple[int, int, int, int]],
    ) -> None:
        self.last_tray_move_mono = float(now_mono)
        self.last_cursor = (int(cursor_pos[0]), int(cursor_pos[1]))
        if icon_rect is not None:
            self.anchor_icon_rect = tuple(map(int, icon_rect))
        elif self.anchor_icon_rect is None:
            x, y = self.last_cursor
            self.anchor_icon_rect = (x - 12, y - 12, x + 12, y + 12)

        if self.state == "idle":
            self.state = "pending_show"
            self.enter_mono = float(now_mono)
            self.leave_mono = 0.0
        elif self.state == "pending_hide":
            self.state = "visible"
            self.leave_mono = 0.0

    def tick(
        self,
        now_mono: float,
        cursor_pos: tuple[int, int],
        *,
        popup_rect: Optional[tuple[int, int, int, int]] = None,
        icon_pad: int = 6,
    ) -> Optional[str]:
        """推进状态机；返回 'show' | 'hide' | None。"""
        now = float(now_mono)
        pt = (int(cursor_pos[0]), int(cursor_pos[1]))
        self.last_cursor = pt

        over_icon = is_point_in_rect(pt, self.anchor_icon_rect, pad=icon_pad) or (
            (now - self.last_tray_move_mono) <= 0.11
        )

        if self.state == "pending_show":
            if not over_icon:
                self.state = "idle"
                self.enter_mono = 0.0
                return None
            if (now - self.enter_mono) >= self.show_delay_sec:
                self.state = "visible"
                self.leave_mono = 0.0
                return "show"
            return None

        if self.state in ("visible", "pending_hide"):
            over_popup = is_point_in_rect(pt, popup_rect, pad=4)
            over_bridge = is_point_in_bridge_corridor(pt, self.anchor_icon_rect, popup_rect, pad=6)
            if over_icon or over_popup or over_bridge:
                self.state = "visible"
                self.leave_mono = 0.0
                return None
            if self.state == "visible":
                self.state = "pending_hide"
                self.leave_mono = now
                return None
            if (now - self.leave_mono) >= self.hide_delay_sec:
                self.state = "idle"
                self.enter_mono = 0.0
                self.leave_mono = 0.0
                return "hide"
            return None

        return None

    def force_hide(self) -> bool:
        """立即取消待显示或隐藏已显示浮层；返回先前是否处于可见态。"""
        was_visible = self.state in ("visible", "pending_hide")
        self.state = "idle"
        self.enter_mono = 0.0
        self.leave_mono = 0.0
        return was_visible


def _palette(is_dark: bool) -> dict[str, tuple[int, int, int]]:
    if is_dark:
        return {
            "bg": (31, 35, 46),
            "border": (52, 59, 77),
            "text": (241, 245, 249),
            "muted": (126, 135, 153),
            "icon": (241, 245, 249),
            "icon_muted": (110, 121, 140),
            "normal": (241, 245, 249),
            "charging": (74, 222, 128),
            "full": (74, 222, 128),
            "tier1": (250, 204, 21),
            "tier2": (251, 146, 60),
            "tier3": (248, 113, 113),
            "scroll_thumb": (92, 102, 124),
        }
    return {
        "bg": (255, 255, 255),
        "border": (218, 224, 234),
        "text": (24, 27, 34),
        "muted": (138, 146, 162),
        "icon": (17, 24, 39),
        "icon_muted": (148, 163, 184),
        "normal": (24, 27, 34),
        "charging": (22, 163, 74),
        "full": (22, 163, 74),
        "tier1": (202, 138, 4),
        "tier2": (234, 88, 12),
        "tier3": (220, 38, 38),
        "scroll_thumb": (196, 204, 218),
    }


def _row_value_rgb(row: TrayHoverRow, pal: dict[str, tuple[int, int, int]]) -> tuple[int, int, int]:
    if row.alert_level in ("offline", "sleep", "unknown"):
        return pal["muted"]
    return pal.get(row.alert_level, pal["normal"])


def _query_monitor_metrics_for_point(pt: tuple[int, int]) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int], float]:
    """查询指定物理屏幕点所在显示器的 (monitor_rect, work_area, dpi_scale)。"""
    if sys.platform != "win32":
        return (0, 0, 1920, 1080), (0, 0, 1920, 1040), 1.0
    try:
        user32 = ctypes.windll.user32

        class _MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        class _PT(ctypes.Structure):
            _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

        user32.MonitorFromPoint.argtypes = [_PT, wintypes.DWORD]
        user32.MonitorFromPoint.restype = wintypes.HANDLE
        hmon = user32.MonitorFromPoint(_PT(int(pt[0]), int(pt[1])), 2)  # MONITOR_DEFAULTTONEAREST
        mi = _MONITORINFO()
        mi.cbSize = ctypes.sizeof(_MONITORINFO)
        if hmon and user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            mrect = (int(mi.rcMonitor.left), int(mi.rcMonitor.top), int(mi.rcMonitor.right), int(mi.rcMonitor.bottom))
            wrect = (int(mi.rcWork.left), int(mi.rcWork.top), int(mi.rcWork.right), int(mi.rcWork.bottom))
        else:
            w = int(user32.GetSystemMetrics(0) or 1920)
            h = int(user32.GetSystemMetrics(1) or 1080)
            mrect = (0, 0, w, h)
            wrect = (0, 0, w, max(1, h - 40))

        scale = 1.0
        if hmon:
            try:
                shcore = ctypes.windll.shcore
                dx = ctypes.c_uint(96)
                dy = ctypes.c_uint(96)
                if shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dx), ctypes.byref(dy)) == 0 and dx.value:
                    scale = float(dx.value) / 96.0
            except Exception:
                pass
        return mrect, wrect, max(1.0, scale)
    except Exception:
        return (0, 0, 1920, 1080), (0, 0, 1920, 1040), 1.0


def _detect_overflow_window_rect(pt: tuple[int, int]) -> Optional[tuple[int, int, int, int]]:
    """检测光标当前是否位于 Windows 10/11 托盘折叠弹出面板内，若是则返回该面板屏幕矩形。"""
    if sys.platform != "win32":
        return None
    try:
        user32 = ctypes.windll.user32

        class _PT(ctypes.Structure):
            _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

        user32.WindowFromPoint.argtypes = [_PT]
        user32.WindowFromPoint.restype = wintypes.HWND
        hwnd = user32.WindowFromPoint(_PT(int(pt[0]), int(pt[1])))
        if not hwnd:
            return None
        # 向上回溯到顶层窗口检查窗口类名
        GA_ROOT = 2
        root = user32.GetAncestor(hwnd, GA_ROOT) or hwnd
        buf = ctypes.create_unicode_buffer(128)
        user32.GetClassNameW(root, buf, 128)
        cls_name = buf.value or ""
        if cls_name in _OVERFLOW_CLASS_NAMES or "Overflow" in cls_name:
            rc = wintypes.RECT()
            if user32.GetWindowRect(root, ctypes.byref(rc)):
                if rc.right > rc.left and rc.bottom > rc.top:
                    return (int(rc.left), int(rc.top), int(rc.right), int(rc.bottom))
    except Exception:
        pass
    return None


def _apply_win11_border_color(hwnd: int, rgb: tuple[int, int, int]) -> None:
    """Windows 11 原生 DWMWA_BORDER_COLOR 细边着色（Win10 静默跳过）。"""
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


class TrayHoverPopup:
    """系统托盘悬停紧凑电量浮层控制器（单实例复用，零焦点抢占，零轮询开销）。"""

    def __init__(
        self,
        get_native_host: Callable[[], Any],
        get_rows_snapshot: Callable[[], list[TrayHoverRow]],
        get_theme: Callable[[], str],
        get_animations_enabled: Callable[[], bool],
        is_enabled: Callable[[], bool],
        is_menu_open: Optional[Callable[[], bool]] = None,
    ) -> None:
        self._get_native_host = get_native_host
        self._get_rows_snapshot = get_rows_snapshot
        self._get_theme = get_theme
        self._get_animations_enabled = get_animations_enabled
        self._is_enabled = is_enabled
        self._is_menu_open = is_menu_open or (lambda: False)

        self._lock = threading.RLock()
        self._sm = TrayHoverStateMachine(SHOW_DELAY_SEC, HIDE_DELAY_SEC)
        self._closed = False

        # WinForms UI 线程持有对象
        self._form = None
        self._hwnd: int = 0
        self._visible_logical: bool = False
        self._rows: list[TrayHoverRow] = []
        self._scroll_offset: int = 0
        self._is_dark: bool = False
        self._scale: float = 1.0
        self._popup_rect: Optional[tuple[int, int, int, int]] = None
        self._font_cache: dict[tuple[str, int], Any] = {}
        self._icon_cache: dict[tuple[str, int, bool, bool], Any] = {}
        self._hover_timer = None
        self._fade_timer = None
        self._current_alpha: float = 0.0
        self._watch_thread_timer: Optional[threading.Timer] = None

    def _run_on_ui(self, fn: Callable[[], None]) -> bool:
        host = self._get_native_host()
        if host is None or getattr(host, "IsDisposed", True):
            return False
        try:
            from System import Action

            if getattr(host, "InvokeRequired", False):
                host.BeginInvoke(Action(fn))
            else:
                fn()
            return True
        except Exception:
            return False

    def on_tray_hover_move(
        self,
        cursor_pos: tuple[int, int],
        icon_rect: Optional[tuple[int, int, int, int]],
    ) -> None:
        """由 TrayIconController 在收到 WM_MOUSEMOVE 时调用（非阻塞、微秒级）。"""
        if self._closed or not self._is_enabled() or self._is_menu_open():
            return
        if is_exclusive_fullscreen_active():
            self.hide(instant=True)
            return
        now = time.monotonic()
        with self._lock:
            was_idle = self._sm.state == "idle"
            self._sm.on_tray_move(now, cursor_pos, icon_rect)
        if was_idle:
            self._schedule_watch_tick()

    def _schedule_watch_tick(self) -> None:
        with self._lock:
            if self._closed or self._sm.state == "idle":
                self._watch_thread_timer = None
                return
            if self._watch_thread_timer is not None and self._watch_thread_timer.is_alive():
                return
            t = threading.Timer(HOVER_POLL_MS / 1000.0, self._on_watch_tick)
            t.daemon = True
            self._watch_thread_timer = t
            t.start()

    def _on_watch_tick(self) -> None:
        with self._lock:
            self._watch_thread_timer = None
            if self._closed or self._sm.state == "idle":
                return
            if not self._is_enabled() or self._is_menu_open() or is_exclusive_fullscreen_active():
                was_vis = self._sm.force_hide()
                if was_vis:
                    self._run_on_ui(lambda: self._hide_on_ui(instant=True))
                return

            pt = wintypes.POINT()
            if sys.platform == "win32" and ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
                cur_pos = (int(pt.x), int(pt.y))
            else:
                cur_pos = self._sm.last_cursor

            action = self._sm.tick(
                time.monotonic(),
                cur_pos,
                popup_rect=self._popup_rect if self._visible_logical else None,
                icon_pad=max(6, int(round(6 * self._scale))),
            )
            anchor_rect = self._sm.anchor_icon_rect
            keep_watching = self._sm.state != "idle"

        if action == "show":
            self._show_or_refresh(cur_pos, anchor_rect)
        elif action == "hide":
            self._run_on_ui(lambda: self._hide_on_ui(instant=False))

        if keep_watching:
            self._schedule_watch_tick()

    def sync_if_visible(self) -> None:
        """设备电量/充电状态/主题变更时，若浮层当前可见则即时刷新（绝不主动弹出）。"""
        with self._lock:
            if self._closed or not self._visible_logical or self._sm.state not in ("visible", "pending_hide"):
                return
            if not self._is_enabled() or is_exclusive_fullscreen_active():
                self._sm.force_hide()
                self._run_on_ui(lambda: self._hide_on_ui(instant=True))
                return
            cur_pos = self._sm.last_cursor
            anchor_rect = self._sm.anchor_icon_rect
        self._show_or_refresh(cur_pos, anchor_rect, is_refresh=True)

    def hide(self, instant: bool = True) -> None:
        """立即隐藏或取消待显示的浮层（点击托盘、打开右键菜单、唤出主窗口或关闭设置开关时调用）。"""
        with self._lock:
            t = self._watch_thread_timer
            self._watch_thread_timer = None
            if t is not None:
                try:
                    t.cancel()
                except Exception:
                    pass
            self._sm.force_hide()
            need_ui_hide = self._visible_logical or self._form is not None
        if need_ui_hide:
            self._run_on_ui(lambda: self._hide_on_ui(instant=instant))

    def close(self) -> None:
        """退出程序时彻底销毁窗口并释放所有 GDI 字体、位图与定时器资源。"""
        with self._lock:
            self._closed = True
            t = self._watch_thread_timer
            self._watch_thread_timer = None
            if t is not None:
                try:
                    t.cancel()
                except Exception:
                    pass
            self._sm.force_hide()

        def _dispose_on_ui() -> None:
            self._stop_fade_timer_ui()
            if self._form is not None:
                try:
                    if not self._form.IsDisposed:
                        if self._hwnd:
                            set_window_topmost_noactivate(self._hwnd, False, show=False)
                        self._form.Close()
                        self._form.Dispose()
                except Exception:
                    pass
                self._form = None
                self._hwnd = 0
            self._visible_logical = False
            self._popup_rect = None
            for fnt in self._font_cache.values():
                try:
                    fnt.Dispose()
                except Exception:
                    pass
            self._font_cache.clear()
            for img in self._icon_cache.values():
                try:
                    img.Dispose()
                except Exception:
                    pass
            self._icon_cache.clear()

        self._run_on_ui(_dispose_on_ui)

    def _stop_fade_timer_ui(self) -> None:
        if self._fade_timer is not None:
            try:
                self._fade_timer.Stop()
                self._fade_timer.Dispose()
            except Exception:
                pass
            self._fade_timer = None

    def _get_font_ui(self, role: str, scale: float):
        from System.Drawing import Font, FontStyle, GraphicsUnit

        pt_px = max(10, int(round((12.5 if role == "name" else 12.5) * scale)))
        key = (role, pt_px)
        cached = self._font_cache.get(key)
        if cached is not None:
            return cached
        family = resolve_winforms_font_family(numeric=(role == "pct"))
        style = FontStyle.Bold if role == "pct" else FontStyle.Regular
        fnt = Font(family, float(pt_px), style, GraphicsUnit.Pixel)
        self._font_cache[key] = fnt
        return fnt

    def _get_icon_ui(self, kind: str, px: int, is_dark: bool, muted: bool):
        from System.Drawing import Image as GdiImage
        from System.IO import MemoryStream

        key = (kind, int(px), bool(is_dark), bool(muted))
        cached = self._icon_cache.get(key)
        if cached is not None:
            return cached
        pal = _palette(is_dark)
        rgb = pal["icon_muted"] if muted else pal["icon"]
        pil_img = render_device_icon_pil(kind, size=max(12, int(px)), is_dark=is_dark, color=(rgb[0], rgb[1], rgb[2], 255))
        buf = io.BytesIO()
        pil_img.save(buf, format="PNG")
        gdi_img = GdiImage.FromStream(MemoryStream(buf.getvalue()))
        self._icon_cache[key] = gdi_img
        return gdi_img

    def _show_or_refresh(
        self,
        cursor_pos: tuple[int, int],
        anchor_rect: Optional[tuple[int, int, int, int]],
        is_refresh: bool = False,
    ) -> None:
        if self._closed or not self._is_enabled() or is_exclusive_fullscreen_active():
            return
        rows = self._get_rows_snapshot()
        is_dark = self._get_theme() == "dark"
        anim_on = bool(self._get_animations_enabled())
        mrect, wrect, scale = _query_monitor_metrics_for_point(cursor_pos)
        overflow_rect = _detect_overflow_window_rect(cursor_pos)

        def _do_ui() -> None:
            try:
                import System.Windows.Forms as WinForms
                from System.Drawing import (
                    Color,
                    Graphics,
                    Point,
                    PointF,
                    RectangleF,
                    Size,
                    SolidBrush,
                    StringAlignment,
                    StringFormat,
                    StringFormatFlags,
                    StringTrimming,
                )
                from System.Drawing.Drawing2D import GraphicsPath, SmoothingMode
                from System.Drawing.Text import TextRenderingHint

                self._rows = list(rows)
                self._is_dark = is_dark
                self._scale = scale
                max_scroll = max(0, len(self._rows) - POPUP_MAX_VISIBLE_ROWS)
                self._scroll_offset = max(0, min(self._scroll_offset, max_scroll))

                if self._form is None or self._form.IsDisposed:
                    form = WinForms.Form()
                    form.Text = "BattDock 托盘电量"
                    form.FormBorderStyle = getattr(WinForms.FormBorderStyle, "None")
                    form.ShowInTaskbar = False
                    form.StartPosition = WinForms.FormStartPosition.Manual
                    # 开启双缓冲避免任意重绘闪白
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

                    def _on_wheel(_s, e) -> None:
                        try:
                            max_sc = max(0, len(self._rows) - POPUP_MAX_VISIBLE_ROWS)
                            if max_sc <= 0:
                                return
                            delta = int(getattr(e, "Delta", 0) or 0)
                            if delta < 0:
                                self._scroll_offset = min(max_sc, self._scroll_offset + 1)
                            elif delta > 0:
                                self._scroll_offset = max(0, self._scroll_offset - 1)
                            form.Invalidate()
                        except Exception:
                            pass

                    def _on_paint(_s, pe) -> None:
                        try:
                            self._paint_surface(pe.Graphics, form.Width, form.Height)
                        except Exception:
                            pass

                    form.MouseWheel += _on_wheel
                    form.Paint += _on_paint
                    self._form = form
                    self._hwnd = int(form.Handle.ToInt64())

                form = self._form
                hwnd = int(form.Handle.ToInt64())
                self._hwnd = hwnd

                # 使用真实 WinForms 字体精确测量逻辑宽度，按内容在 220–320 DIP 自适应
                name_font = self._get_font_ui("name", scale)
                pct_font = self._get_font_ui("pct", scale)

                def _measure_dip(txt: str, is_num: bool) -> float:
                    try:
                        sz = WinForms.TextRenderer.MeasureText(txt, pct_font if is_num else name_font)
                        return float(sz.Width) / scale
                    except Exception:
                        return float(len(txt)) * 8.0

                w_dip, h_dip, _vis, _sc = compute_popup_logical_size(self._rows, measure_text_dip=_measure_dip)
                pw = max(160, int(round(w_dip * scale)))
                ph = max(40, int(round(h_dip * scale)))

                px, py = compute_hover_popup_rect(
                    icon_rect=anchor_rect,
                    cursor_pos=cursor_pos,
                    popup_size=(pw, ph),
                    monitor_rect=mrect,
                    work_area=wrect,
                    scale=scale,
                    overflow_rect=overflow_rect,
                )

                pal = _palette(is_dark)
                bg_rgb = pal["bg"]
                form.BackColor = Color.FromArgb(bg_rgb[0], bg_rgb[1], bg_rgb[2])

                was_visible = bool(self._visible_logical and ctypes.windll.user32.IsWindowVisible(wintypes.HWND(hwnd)))
                size_changed = form.Width != pw or form.Height != ph
                if size_changed:
                    form.Size = Size(pw, ph)
                if form.Location.X != px or form.Location.Y != py:
                    form.Location = Point(px, py)

                apply_non_activating_tool_style(hwnd, layered=True)
                apply_window_rounded_corners(hwnd, radius_dip=POPUP_RADIUS_DIP, scale=scale)
                _apply_win11_border_color(hwnd, pal["border"])

                self._popup_rect = (px, py, px + pw, py + ph)
                self._visible_logical = True
                form.Invalidate()

                if was_visible and is_refresh:
                    set_window_topmost_noactivate(hwnd, True, x=px, y=py, w=pw, h=ph, show=False)
                    return

                self._stop_fade_timer_ui()
                if anim_on and not was_visible:
                    self._current_alpha = 0.0
                    set_layered_window_alpha(hwnd, 0.0)
                    ctypes.windll.user32.ShowWindow(wintypes.HWND(hwnd), SW_SHOWNOACTIVATE)
                    set_window_topmost_noactivate(hwnd, True, x=px, y=py, w=pw, h=ph, show=True)
                    self._animate_alpha_ui(hwnd, 0.0, 1.0, FADE_IN_MS)
                else:
                    self._current_alpha = 1.0
                    set_layered_window_alpha(hwnd, 1.0)
                    ctypes.windll.user32.ShowWindow(wintypes.HWND(hwnd), SW_SHOWNOACTIVATE)
                    set_window_topmost_noactivate(hwnd, True, x=px, y=py, w=pw, h=ph, show=True)
            except Exception:
                pass

        self._run_on_ui(_do_ui)

    def _hide_on_ui(self, instant: bool = False) -> None:
        try:
            self._stop_fade_timer_ui()
            if self._form is None or self._form.IsDisposed or not self._hwnd:
                self._visible_logical = False
                self._popup_rect = None
                return
            hwnd = self._hwnd
            self._visible_logical = False
            self._popup_rect = None
            anim_on = (not instant) and bool(self._get_animations_enabled())
            is_vis = bool(ctypes.windll.user32.IsWindowVisible(wintypes.HWND(hwnd)))
            if not is_vis:
                return

            def _finish_hide() -> None:
                try:
                    set_window_topmost_noactivate(hwnd, False, show=False)
                    ctypes.windll.user32.ShowWindow(wintypes.HWND(hwnd), SW_HIDE)
                    self._current_alpha = 0.0
                except Exception:
                    pass

            if anim_on:
                start_a = self._current_alpha if self._current_alpha > 0.05 else 1.0
                self._animate_alpha_ui(hwnd, start_a, 0.0, FADE_OUT_MS, on_done=_finish_hide)
            else:
                _finish_hide()
        except Exception:
            pass

    def _animate_alpha_ui(
        self,
        hwnd: int,
        start_alpha: float,
        end_alpha: float,
        duration_ms: int,
        on_done: Optional[Callable[[], None]] = None,
    ) -> None:
        import System.Windows.Forms as WinForms

        self._stop_fade_timer_ui()
        start_t = time.monotonic()
        dur_s = max(0.03, float(duration_ms) / 1000.0)
        tmr = WinForms.Timer()
        tmr.Interval = 15

        def _tick(_s, _e) -> None:
            if self._form is None or self._form.IsDisposed:
                self._stop_fade_timer_ui()
                return
            prog = min(1.0, (time.monotonic() - start_t) / dur_s)
            eased = 1.0 - (1.0 - prog) ** 3 if end_alpha > start_alpha else prog * prog
            alpha = start_alpha + (end_alpha - start_alpha) * eased
            self._current_alpha = alpha
            set_layered_window_alpha(hwnd, alpha)
            if prog >= 1.0:
                self._stop_fade_timer_ui()
                self._current_alpha = end_alpha
                set_layered_window_alpha(hwnd, end_alpha)
                if on_done is not None:
                    on_done()

        tmr.Tick += _tick
        self._fade_timer = tmr
        tmr.Start()

    def _paint_surface(self, g, width: int, height: int) -> None:
        """双缓冲单表面绘制整张紧凑电量浮层（零子控件、抗锯齿图标与清晰的电量右对齐排版）。"""
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
        from System.Drawing.Drawing2D import InterpolationMode, SmoothingMode
        from System.Drawing.Text import TextRenderingHint

        sc = self._scale
        pal = _palette(self._is_dark)
        g.SmoothingMode = SmoothingMode.AntiAlias
        g.InterpolationMode = InterpolationMode.HighQualityBicubic
        g.TextRenderingHint = TextRenderingHint.ClearTypeGridFit

        bg_brush = SolidBrush(Color.FromArgb(*pal["bg"]))
        try:
            g.FillRectangle(bg_brush, 0, 0, width, height)
        finally:
            bg_brush.Dispose()

        rows = self._rows if self._rows else [
            TrayHoverRow(
                device_id="",
                kind=KIND_OTHER,
                name="暂无已连接设备",
                percent=None,
                charging=False,
                full=False,
                connected=False,
                online=False,
                asleep=False,
                stale=False,
                alert_level="unknown",
                value_text="—",
                show_bolt=False,
            )
        ]

        total_rows = len(rows)
        scrollable = total_rows > POPUP_MAX_VISIBLE_ROWS
        visible_rows = rows[self._scroll_offset : self._scroll_offset + POPUP_MAX_VISIBLE_ROWS]
        any_bolt = any(r.show_bolt for r in rows)

        pad_x = int(round(POPUP_PAD_X_DIP * sc))
        pad_y = int(round(POPUP_PAD_Y_DIP * sc))
        row_h = int(round(POPUP_ROW_HEIGHT_DIP * sc))
        icon_px = max(14, int(round(POPUP_ICON_DIP * sc)))
        icon_gap = int(round(POPUP_ICON_GAP_DIP * sc))
        val_gap = int(round(POPUP_VALUE_GAP_DIP * sc))
        bolt_slot = int(round(POPUP_BOLT_SLOT_DIP * sc)) if any_bolt else 0
        scroll_slot = int(round(7 * sc)) if scrollable else 0

        name_font = self._get_font_ui("name", sc)
        pct_font = self._get_font_ui("pct", sc)

        # 右侧数值列宽度按当前列表最大值紧凑计算（中文状态如「休眠」「离线」使用中文字体避免缺字）
        val_col_w = int(round(38 * sc))
        try:
            import System.Windows.Forms as WinForms

            max_vw = max(
                int(
                    WinForms.TextRenderer.MeasureText(
                        r.value_text,
                        pct_font if r.value_text.isascii() else name_font,
                    ).Width
                )
                for r in rows
            )
            val_col_w = max(int(round(34 * sc)), max_vw + int(round(3 * sc)))
        except Exception:
            pass

        right_edge = width - pad_x - scroll_slot
        bolt_x = right_edge - bolt_slot
        val_x = bolt_x - val_col_w
        name_x = pad_x + icon_px + icon_gap
        name_w = max(40, val_x - val_gap - name_x)

        sf_left = StringFormat()
        sf_left.Alignment = StringAlignment.Near
        sf_left.LineAlignment = StringAlignment.Center
        sf_left.Trimming = StringTrimming.EllipsisCharacter
        sf_left.FormatFlags = StringFormatFlags.NoWrap

        sf_right = StringFormat()
        sf_right.Alignment = StringAlignment.Far
        sf_right.LineAlignment = StringAlignment.Center
        sf_right.FormatFlags = StringFormatFlags.NoWrap

        try:
            for idx, row in enumerate(visible_rows):
                ry = pad_y + idx * row_h
                is_inactive = row.alert_level in ("offline", "sleep", "unknown")

                # 1. 统一黑白实心设备类型图标
                gdi_icon = self._get_icon_ui(row.kind, icon_px, self._is_dark, is_inactive)
                iy = ry + (row_h - icon_px) // 2
                g.DrawImage(gdi_icon, pad_x, iy, icon_px, icon_px)

                # 2. 简洁设备名称（自定义名称优先，过长优雅省略）
                name_rgb = pal["muted"] if is_inactive else pal["text"]
                nb = SolidBrush(Color.FromArgb(*name_rgb))
                try:
                    g.DrawString(row.name, name_font, nb, RectangleF(float(name_x), float(ry), float(name_w), float(row_h)), sf_left)
                finally:
                    nb.Dispose()

                # 3. 电量百分比或中文状态（右对齐，数字用等宽清晰字体，中文状态用中文字体零缺字）
                val_rgb = _row_value_rgb(row, pal)
                val_font = pct_font if row.value_text.isascii() else name_font
                vb = SolidBrush(Color.FromArgb(*val_rgb))
                try:
                    g.DrawString(row.value_text, val_font, vb, RectangleF(float(val_x), float(ry), float(val_col_w), float(row_h)), sf_right)
                    # 4. 充电小闪电（纯矢量抗锯齿绘制，不依赖系统 Emoji 字体）
                    if row.show_bolt:
                        bcx = float(bolt_x) + float(bolt_slot) * 0.56
                        bcy = float(ry) + float(row_h) * 0.5
                        u = 1.05 * sc
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

            # 5. 设备较多时的极简细滚动指示条
            if scrollable:
                track_top = float(pad_y + int(round(3 * sc)))
                track_h = float(max(20, height - pad_y * 2 - int(round(6 * sc))))
                thumb_h = max(18.0 * sc, track_h * (float(POPUP_MAX_VISIBLE_ROWS) / float(total_rows)))
                max_sc = max(1, total_rows - POPUP_MAX_VISIBLE_ROWS)
                thumb_y = track_top + (track_h - thumb_h) * (float(self._scroll_offset) / float(max_sc))
                thumb_w = max(2.5, 3.0 * sc)
                thumb_x = float(width - int(round(6 * sc)))
                sb = SolidBrush(Color.FromArgb(165, *pal["scroll_thumb"]))
                try:
                    g.FillRectangle(sb, thumb_x, thumb_y, thumb_w, thumb_h)
                finally:
                    sb.Dispose()

            # 6. Win10 绘制 1px 抗锯齿圆角细边（Win11 由原生 DWMWA_BORDER_COLOR 负责）
            if not is_windows_11():
                bcol = Color.FromArgb(*pal["border"])
                paint_winforms_rounded_border(g, width, height, float(POPUP_RADIUS_DIP) * sc, bcol)
        finally:
            sf_left.Dispose()
            sf_right.Dispose()


def render_hover_popup_pil(
    rows: list[TrayHoverRow],
    *,
    is_dark: bool = False,
    scale: float = 1.0,
) -> Image.Image:
    """高保真离屏预览渲染器（用于跨主题/多设备/多 DPI 自动化视觉验收与截图，与线上布局完全同源）。"""
    sc = max(1.0, float(scale or 1.0))
    pal = _palette(is_dark)

    def _load_font(numeric: bool, px: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        candidates = (
            [r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\msyhbd.ttc"]
            if numeric
            else [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\segoeui.ttf"]
        )
        if numeric:
            candidates = [r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\segoeui.ttf"]
        for path in candidates:
            try:
                return ImageFont.truetype(path, px)
            except Exception:
                continue
        return ImageFont.load_default()

    name_px = max(11, int(round(12.5 * sc)))
    pct_px = max(11, int(round(12.5 * sc)))
    name_font = _load_font(False, name_px)
    pct_font = _load_font(True, pct_px)

    tmp_draw = ImageDraw.Draw(Image.new("RGBA", (10, 10)))

    def _measure_dip(txt: str, is_num: bool) -> float:
        fnt = pct_font if (is_num and txt.isascii()) else name_font
        bb = tmp_draw.textbbox((0, 0), txt, font=fnt)
        return float(bb[2] - bb[0]) / sc

    eff_rows = rows if rows else [
        TrayHoverRow(
            device_id="",
            kind=KIND_OTHER,
            name="暂无已连接设备",
            percent=None,
            charging=False,
            full=False,
            connected=False,
            online=False,
            asleep=False,
            stale=False,
            alert_level="unknown",
            value_text="—",
            show_bolt=False,
        )
    ]
    w_dip, h_dip, vis_cnt, scrollable = compute_popup_logical_size(eff_rows, measure_text_dip=_measure_dip)
    pw = int(round(w_dip * sc))
    ph = int(round(h_dip * sc))

    # 2x 超采样抗锯齿卡片边框与圆角
    ss = 2
    img = Image.new("RGBA", (pw * ss, ph * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r_px = int(round(POPUP_RADIUS_DIP * sc * ss))
    d.rounded_rectangle(
        [0, 0, pw * ss - 1, ph * ss - 1],
        radius=r_px,
        fill=(*pal["bg"], 255),
        outline=(*pal["border"], 255),
        width=max(1, ss),
    )
    out = img.resize((pw, ph), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(out)

    any_bolt = any(r.show_bolt for r in eff_rows)
    pad_x = int(round(POPUP_PAD_X_DIP * sc))
    pad_y = int(round(POPUP_PAD_Y_DIP * sc))
    row_h = int(round(POPUP_ROW_HEIGHT_DIP * sc))
    icon_px = max(14, int(round(POPUP_ICON_DIP * sc)))
    icon_gap = int(round(POPUP_ICON_GAP_DIP * sc))
    val_gap = int(round(POPUP_VALUE_GAP_DIP * sc))
    bolt_slot = int(round(POPUP_BOLT_SLOT_DIP * sc)) if any_bolt else 0
    scroll_slot = int(round(7 * sc)) if scrollable else 0

    max_vw = max(
        int(tmp_draw.textbbox((0, 0), r.value_text, font=(pct_font if r.value_text.isascii() else name_font))[2])
        for r in eff_rows
    )
    val_col_w = max(int(round(34 * sc)), max_vw + int(round(2 * sc)))
    right_edge = pw - pad_x - scroll_slot
    bolt_x = right_edge - bolt_slot
    val_right = bolt_x
    name_x = pad_x + icon_px + icon_gap
    max_name_px = max(40, val_right - val_col_w - val_gap - name_x)

    for idx, row in enumerate(eff_rows[:vis_cnt]):
        ry = pad_y + idx * row_h
        is_inactive = row.alert_level in ("offline", "sleep", "unknown")
        ic_rgb = pal["icon_muted"] if is_inactive else pal["icon"]
        ic = render_device_icon_pil(row.kind, size=icon_px, is_dark=is_dark, color=(*ic_rgb, 255))
        out.paste(ic, (pad_x, ry + (row_h - icon_px) // 2), ic)

        # 超长名称省略
        nm = row.name
        while len(nm) > 2 and (tmp_draw.textbbox((0, 0), nm, font=name_font)[2] > max_name_px):
            nm = nm[:-2].rstrip() + "…"
        nb = tmp_draw.textbbox((0, 0), nm, font=name_font)
        nh = nb[3] - nb[1]
        ny = ry + (row_h - nh) // 2 - nb[1]
        draw.text((name_x, ny), nm, font=name_font, fill=(*(pal["muted"] if is_inactive else pal["text"]), 255))

        v_font = pct_font if row.value_text.isascii() else name_font
        vb = tmp_draw.textbbox((0, 0), row.value_text, font=v_font)
        vw = vb[2] - vb[0]
        vh = vb[3] - vb[1]
        vy = ry + (row_h - vh) // 2 - vb[1]
        vrgb = _row_value_rgb(row, pal)
        draw.text((val_right - vw, vy), row.value_text, font=v_font, fill=(*vrgb, 255))

        if row.show_bolt:
            # 4x 超采样绘制清晰闪电
            bcx = bolt_x + bolt_slot * 0.58
            bcy = ry + row_h * 0.5
            u = 1.05 * sc
            pts = [
                (bcx + 1.1 * u, bcy - 4.8 * u),
                (bcx - 2.6 * u, bcy + 0.6 * u),
                (bcx - 0.1 * u, bcy + 0.6 * u),
                (bcx - 1.1 * u, bcy + 4.8 * u),
                (bcx + 2.6 * u, bcy - 0.6 * u),
                (bcx + 0.1 * u, bcy - 0.6 * u),
            ]
            draw.polygon(pts, fill=(*vrgb, 255))

    if scrollable:
        track_top = pad_y + int(round(3 * sc))
        track_h = max(20, ph - pad_y * 2 - int(round(6 * sc)))
        thumb_h = max(int(round(18 * sc)), int(round(track_h * (vis_cnt / float(len(eff_rows))))))
        tx = pw - int(round(6 * sc))
        tw = max(2, int(round(3 * sc)))
        draw.rounded_rectangle([tx, track_top, tx + tw, track_top + thumb_h], radius=tw, fill=(*pal["scroll_thumb"], 180))

    return out
