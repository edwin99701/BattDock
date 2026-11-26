"""外设电量监控工具：多品牌统一适配 + 主窗口/设置窗口双窗口 + 桌面悬浮窗 + Win10/11 全兼容。"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from ctypes import wintypes
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pystray
import webview

from app_config import (
    APP_AUTHOR,
    APP_DIR,
    APP_VERSION,
    DATA_DIR,
    IS_FROZEN,
    RESOURCE_DIR,
    AppConfig,
    FloatingWidgetConfig,
    get_device_pref,
    get_device_tiers,
    get_floating_config,
    is_autostart_enabled,
    load_config,
    migrate_legacy_autostart,
    normalize_tiers,
    resolve_effective_animations,
    resolve_effective_theme,
    save_config,
    set_autostart,
    set_device_pref,
)
from brand import (
    APP_ALERT_TITLE,
    APP_MAIN_TITLE,
    APP_NAME,
    APP_SETTINGS_TITLE,
    APP_TRAY_NAME,
    APP_USER_MODEL_ID,
    LEGACY_EXE_NAME,
    LEGACY_MUTEX_NAME,
    LEGACY_SHOW_EVENT_NAME,
    MUTEX_NAME,
    SHOW_EVENT_NAME,
)
from updater import (
    GITHUB_REPO_URL,
    RELEASES_PAGE_URL,
    check_for_update,
    download_update_asset,
    extract_and_verify_update,
    launch_windows_updater,
    verify_downloaded_sha256,
)
from device_icons import get_device_icons_svg_map, render_device_icon_pil
from floating_widget import (
    DesktopFloatingWidget,
    EDGE_MARGIN,
    _try_win11_round_corners,
    apply_window_rounded_corners,
    draw_battery_icon,
    is_windows_11,
    paint_winforms_rounded_border,
    play_alert_sound,
)
from providers import (
    DeviceBattery,
    DeviceManager,
    KIND_EARBUDS,
    KIND_HEADSET,
    KIND_KEYBOARD,
    KIND_MOUSE,
    STATUS_PROTOCOL,
    STATUS_UNSUPPORTED,
    STATUS_VERIFIED,
)
from providers.device_naming import (
    format_alert_device_name,
    format_connection_mode_cn,
    format_device_subtitle,
    resolve_compact_device_label,
)

if sys.platform == "win32":
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

UI_MAIN_HTML = RESOURCE_DIR / "ui" / "index.html"
UI_SETTINGS_HTML = RESOURCE_DIR / "ui" / "settings.html"
APP_ICON_ICO = RESOURCE_DIR / "assets" / "app_icon.ico"

WINDOW_TITLE = APP_MAIN_TITLE
SETTINGS_WINDOW_TITLE = APP_SETTINGS_TITLE
ALERT_WINDOW_TITLE = APP_ALERT_TITLE

MAIN_DEFAULT_SIZE = (760, 480)
SETTINGS_DEFAULT_SIZE = (840, 742)
ALERT_SIZE = (324, 68)
ALERT_DURATION_SEC = 5.0


# ================= Windows 10 / 11 通用窗口辅助（不依赖 Win11 专属特效） =================

class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def _get_dpi_scale_for_monitor(hmon: int) -> float:
    """获取指定显示器的 DPI 缩放比例（支持 Win10/11 多显示器不同 DPI）。"""
    if sys.platform != "win32" or not hmon:
        return 1.0
    try:
        dpi_x = ctypes.c_uint(96)
        dpi_y = ctypes.c_uint(96)
        res = ctypes.windll.shcore.GetDpiForMonitor(
            wintypes.HMONITOR(hmon), 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y)
        )
        if res == 0 and dpi_x.value > 0:
            return dpi_x.value / 96.0
    except Exception:
        pass
    try:
        dpi = ctypes.windll.user32.GetDpiForSystem()
        if dpi > 0:
            return dpi / 96.0
    except Exception:
        pass
    return 1.0


def _get_monitor_work_area_and_scale(hmon: int) -> tuple[tuple[int, int, int, int], float]:
    """获取指定显示器的可用工作区 (left, top, right, bottom) 与 DPI 缩放比。"""
    user32 = ctypes.windll.user32
    if hmon:
        try:
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(wintypes.HMONITOR(hmon), ctypes.byref(info)):
                r = info.rcWork
                return (r.left, r.top, r.right, r.bottom), _get_dpi_scale_for_monitor(hmon)
        except Exception:
            pass
    rect = wintypes.RECT()
    if user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
        return (rect.left, rect.top, rect.right, rect.bottom), _get_dpi_scale_for_monitor(0)
    return (0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1) - 48), 1.0


def _get_current_monitor_work_area_and_scale() -> tuple[tuple[int, int, int, int], float]:
    """获取当前显示器（优先当前鼠标指针所在屏幕，其次托盘屏幕）的工作区与缩放比。"""
    user32 = ctypes.windll.user32
    try:
        pt = wintypes.POINT()
        if user32.GetCursorPos(ctypes.byref(pt)):
            hmon = user32.MonitorFromPoint(pt, 2)  # MONITOR_DEFAULTTONEAREST
            if hmon:
                return _get_monitor_work_area_and_scale(hmon)
    except Exception:
        pass
    try:
        tray_hwnd = user32.FindWindowW("Shell_TrayWnd", None)
        if tray_hwnd:
            hmon = user32.MonitorFromWindow(wintypes.HWND(tray_hwnd), 2)
            if hmon:
                return _get_monitor_work_area_and_scale(hmon)
    except Exception:
        pass
    return _get_monitor_work_area_and_scale(0)


def _get_window_monitor_work_area_and_scale(hwnd: int) -> tuple[tuple[int, int, int, int], float]:
    """获取指定窗口所在显示器的可用工作区与缩放比。"""
    if hwnd:
        try:
            hmon = ctypes.windll.user32.MonitorFromWindow(wintypes.HWND(hwnd), 2)
            if hmon:
                return _get_monitor_work_area_and_scale(hmon)
        except Exception:
            pass
    return _get_current_monitor_work_area_and_scale()


def _compute_centered_rect(
    work_area: tuple[int, int, int, int],
    win_w: int,
    win_h: int,
    anchor_rect: Optional[tuple[int, int, int, int]] = None,
) -> tuple[int, int, int, int]:
    """计算严格居中且不超出工作区、不被任务栏遮挡的物理坐标 (x, y, w, h)。"""
    wl, wt, wr, wb = work_area
    avail_w = max(320, wr - wl)
    avail_h = max(240, wb - wt)
    eff_w = min(int(win_w), avail_w)
    eff_h = min(int(win_h), avail_h)

    if anchor_rect is not None:
        ax, ay, aw, ah = anchor_rect
        x = ax + (aw - eff_w) // 2
        y = ay + (ah - eff_h) // 2
    else:
        x = wl + (avail_w - eff_w) // 2
        y = wt + (avail_h - eff_h) // 2

    x = max(wl, min(x, wr - eff_w))
    y = max(wt, min(y, wb - eff_h))
    return int(x), int(y), int(eff_w), int(eff_h)


def _get_tray_work_area() -> tuple[int, int, int, int]:
    """获取系统托盘所在显示器的工作区 (left, top, right, bottom)，供悬浮窗与低电量迷你弹窗使用。"""
    user32 = ctypes.windll.user32
    try:
        tray_hwnd = user32.FindWindowW("Shell_TrayWnd", None)
        if tray_hwnd:
            hmon = user32.MonitorFromWindow(wintypes.HWND(tray_hwnd), 2)
            if hmon:
                work, _ = _get_monitor_work_area_and_scale(hmon)
                return work
    except Exception:
        pass
    work, _ = _get_monitor_work_area_and_scale(0)
    return work


def _get_work_area_for_window(hwnd: int) -> tuple[int, int, int, int]:
    work, _ = _get_window_monitor_work_area_and_scale(hwnd)
    return work


def _get_cursor_pos() -> tuple[int, int]:
    pt = wintypes.POINT()
    if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
        return pt.x, pt.y
    return 0, 0


def _get_window_rect(hwnd: int) -> tuple[int, int, int, int]:
    rect = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect))
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def _get_dpi_scale(hwnd: int) -> float:
    try:
        dpi = ctypes.windll.user32.GetDpiForWindow(wintypes.HWND(hwnd))
        if dpi > 0:
            return dpi / 96.0
    except Exception:
        pass
    return 1.0


def _set_window_pos(hwnd: int, x: int, y: int, w: int, h: int, topmost: Optional[bool] = None) -> None:
    SWP_NOACTIVATE = 0x0010
    SWP_NOZORDER = 0x0004
    flags = SWP_NOACTIVATE
    z_after = wintypes.HWND(0)
    if topmost is None:
        flags |= SWP_NOZORDER
    else:
        z_after = wintypes.HWND(-1 if topmost else -2)
    ctypes.windll.user32.SetWindowPos(
        wintypes.HWND(hwnd),
        z_after,
        int(x),
        int(y),
        int(w),
        int(h),
        flags,
    )


def _apply_window_chrome(hwnd: int, is_dark: bool, radius_dip: int = 10) -> None:
    """Windows 10/11 通用轻量窗口装饰：Win11 使用原生 DWM 圆角，Win10 使用高 DPI 兼容外轮廓区域圆角。"""
    if sys.platform != "win32" or not hwnd:
        return
    try:
        dwmapi = ctypes.windll.dwmapi
        dark_val = ctypes.c_int(1 if is_dark else 0)
        dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), 20, ctypes.byref(dark_val), ctypes.sizeof(dark_val))
    except Exception:
        pass
    apply_window_rounded_corners(hwnd, radius_dip=radius_dip, scale=_get_dpi_scale(hwnd))


def _sync_native_form_backcolor(win: Optional[webview.Window], is_dark: bool) -> None:
    """同步 WinForms 容器背景色，防止 Windows 10 缩放或切换主题瞬间透出异色边缘。"""
    if win is None or sys.platform != "win32":
        return
    native = getattr(win, "native", None)
    if native is None:
        return
    try:
        from System import Action
        from System.Drawing import Color

        col = Color.FromArgb(21, 24, 32) if is_dark else Color.FromArgb(245, 246, 250)

        def _apply():
            try:
                if not native.IsDisposed:
                    native.BackColor = col
            except Exception:
                pass

        if getattr(native, "InvokeRequired", False):
            native.BeginInvoke(Action(_apply))
        else:
            _apply()
    except Exception:
        pass


def _attach_rounded_resize_hook(win: Optional[webview.Window], radius_dip: int = 10) -> None:
    """在 WinForms 窗口尺寸、显隐、最大化/还原及 DPI 变化时自动重算圆角外轮廓（确保 Win10 全场景零残留）。"""
    if win is None or sys.platform != "win32":
        return
    native = getattr(win, "native", None)
    if native is None or getattr(native, "_battdock_rgn_hooked", False):
        return
    try:
        def _on_rgn_refresh(_s, _e):
            try:
                if native.IsDisposed:
                    return
                hwnd = int(native.Handle.ToInt64())
                if hwnd:
                    apply_window_rounded_corners(hwnd, radius_dip=radius_dip, scale=_get_dpi_scale(hwnd))
            except Exception:
                pass

        native.SizeChanged += _on_rgn_refresh
        native.Resize += _on_rgn_refresh
        native.VisibleChanged += _on_rgn_refresh
        try:
            native.DpiChanged += _on_rgn_refresh
        except Exception:
            pass
        setattr(native, "_battdock_rgn_hooked", True)
    except Exception:
        pass


_FLICKER_PATCH_INSTALLED = False


def _install_flicker_free_patch() -> None:
    """在 WinForms BrowserForm 创建瞬间设置 Opacity=0，待页面首帧与精确居中全部就绪后再原子显现。

    彻底消除两类闪烁：
    1. WebView2 冷初始化期间先露出空白纯色框再刷出页面；
    2. WinForms 切换 frameless 时尺寸微缩后二次调整位置/大小造成的跳动，以及 hidden=True 时
       pywebview 内部 Show()/Hide() 引发的一瞬闪现。
    """
    global _FLICKER_PATCH_INSTALLED
    if _FLICKER_PATCH_INSTALLED or sys.platform != "win32":
        return
    try:
        from webview.platforms import winforms

        orig_init = winforms.BrowserView.BrowserForm.__init__

        def _patched_init(form_self, window, cache_dir):
            orig_init(form_self, window, cache_dir)
            try:
                form_self.Opacity = 0.0
            except Exception:
                pass

        winforms.BrowserView.BrowserForm.__init__ = _patched_init
        _FLICKER_PATCH_INSTALLED = True
    except Exception:
        pass


_FORM_ANIM_TIMERS: dict[int, object] = {}


def _cancel_form_animation(native_form) -> None:
    """取消某 WinForms 窗体上正在运行的过渡定时器，防止快速操作动画堆积。"""
    if native_form is None:
        return
    key = id(native_form)
    timer = _FORM_ANIM_TIMERS.pop(key, None)
    if timer is not None:
        try:
            timer.Stop()
            timer.Dispose()
        except Exception:
            pass


def _animate_form_transition(
    native_form,
    start_opacity: float,
    end_opacity: float,
    duration_ms: int,
    start_pos: Optional[tuple[int, int]] = None,
    end_pos: Optional[tuple[int, int]] = None,
    on_complete=None,
) -> None:
    """在 WinForms UI 线程运行轻量非阻塞 Ease-Out 过渡动画（16ms 步进，随时可打断）。"""
    if native_form is None:
        return
    _cancel_form_animation(native_form)
    try:
        if native_form.IsDisposed:
            return
    except Exception:
        return

    if duration_ms <= 0:
        try:
            if end_pos is not None:
                from System.Drawing import Point
                native_form.Location = Point(int(end_pos[0]), int(end_pos[1]))
            native_form.Opacity = max(0.0, min(1.0, float(end_opacity)))
            if on_complete:
                on_complete()
        except Exception:
            pass
        return

    try:
        import System.Windows.Forms as WinForms
        from System.Drawing import Point

        key = id(native_form)
        t0 = time.perf_counter()
        dur_sec = max(0.05, duration_ms / 1000.0)
        if start_pos is not None:
            native_form.Location = Point(int(start_pos[0]), int(start_pos[1]))
        native_form.Opacity = max(0.0, min(1.0, float(start_opacity)))

        timer = WinForms.Timer()
        timer.Interval = 16

        def _tick(_s, _e):
            try:
                if native_form.IsDisposed:
                    _cancel_form_animation(native_form)
                    return
                p = min(1.0, (time.perf_counter() - t0) / dur_sec)
                # Cubic Ease-Out: 自然顺滑、无弹簧回弹
                eased = 1.0 - (1.0 - p) ** 3
                cur_op = start_opacity + (end_opacity - start_opacity) * eased
                native_form.Opacity = max(0.0, min(1.0, cur_op))
                if start_pos is not None and end_pos is not None:
                    cx = int(round(start_pos[0] + (end_pos[0] - start_pos[0]) * eased))
                    cy = int(round(start_pos[1] + (end_pos[1] - start_pos[1]) * eased))
                    native_form.Location = Point(cx, cy)
                if p >= 1.0:
                    _cancel_form_animation(native_form)
                    if on_complete:
                        on_complete()
            except Exception:
                _cancel_form_animation(native_form)

        timer.Tick += _tick
        _FORM_ANIM_TIMERS[key] = timer
        timer.Start()
    except Exception:
        try:
            native_form.Opacity = max(0.0, min(1.0, float(end_opacity)))
            if on_complete:
                on_complete()
        except Exception:
            pass


def _set_form_visibility(
    win: Optional[webview.Window],
    visible: bool,
    opacity: float = 1.0,
    activate: bool = False,
    fade_ms: int = 0,
) -> None:
    """在 WinForms UI 线程原子控制窗体显隐，并支持非阻塞淡入/淡出（随时可打断）。"""
    if win is None:
        return
    native = getattr(win, "native", None)
    if native is None:
        return

    def _do():
        try:
            if native.IsDisposed:
                return
            _cancel_form_animation(native)
            if visible:
                if fade_ms > 0 and opacity > 0.05:
                    native.Opacity = 0.0
                    if not native.Visible:
                        native.Show()
                    if activate:
                        native.Activate()
                    _animate_form_transition(native, 0.0, opacity, fade_ms)
                else:
                    if not native.Visible:
                        native.Show()
                    native.Opacity = max(0.0, min(1.0, float(opacity)))
                    if activate:
                        native.Activate()
            else:
                if fade_ms > 0 and native.Visible and float(native.Opacity) > 0.05:
                    def _hide_after():
                        try:
                            if not native.IsDisposed:
                                native.Opacity = 0.0
                                native.Hide()
                        except Exception:
                            pass
                    _animate_form_transition(native, float(native.Opacity), 0.0, fade_ms, on_complete=_hide_after)
                else:
                    native.Opacity = 0.0
                    if native.Visible:
                        native.Hide()
        except Exception:
            pass

    try:
        from System import Action

        if getattr(native, "InvokeRequired", False):
            native.Invoke(Action(_do))
        else:
            _do()
    except Exception:
        pass


def _run_on_form_ui(win: Optional[webview.Window], fn) -> None:
    if win is None:
        return
    native = getattr(win, "native", None)
    if native is None:
        return
    try:
        from System import Action

        if getattr(native, "InvokeRequired", False):
            native.Invoke(Action(fn))
        else:
            fn()
    except Exception:
        pass


def ensure_app_ico() -> Optional[str]:
    """返回应用/文件夹 EXE 图标路径（优先保留定制的新软件 Logo 图标，不覆写已有文件）。"""
    if APP_ICON_ICO.exists() and APP_ICON_ICO.stat().st_size > 100:
        return str(APP_ICON_ICO)
    try:
        APP_ICON_ICO.parent.mkdir(parents=True, exist_ok=True)
        base = draw_battery_icon(size=256, percent=85, charging=False, connected=True)
        base.save(
            APP_ICON_ICO,
            format="ICO",
            sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)],
        )
        return str(APP_ICON_ICO)
    except Exception:
        return None


def _kind_cn(kind: str) -> str:
    return {
        KIND_MOUSE: "鼠标",
        KIND_HEADSET: "耳机",
        KIND_EARBUDS: "耳机",
        KIND_KEYBOARD: "键盘",
    }.get(kind, "外设")


def _connection_label(dev: DeviceBattery) -> str:
    """规范化中文连接方式（绝不展示品牌技术词，无法确认则返回空字符串）。"""
    return format_connection_mode_cn(dev.connection_mode)


def _support_label(status: str) -> str:
    return {
        STATUS_VERIFIED: "已真机验证",
        STATUS_PROTOCOL: "协议已实现待实测",
        STATUS_UNSUPPORTED: "暂不支持",
    }.get(status, "协议已实现待实测")


# ================= 三级/自定义低电量提醒状态机（含重复提醒冷却与单设备独立配置） =================

def evaluate_tiered_alerts(
    devices: list[DeviceBattery],
    cfg: AppConfig,
    alerted_map: dict[str, set[int]],
    last_alert_ts: Optional[dict[str, float]] = None,
    now_ts: Optional[float] = None,
) -> list[tuple[DeviceBattery, int]]:
    """评估本轮需要提醒的设备列表 [(device, threshold), ...]。"""
    now = time.time() if now_ts is None else now_ts
    triggered: list[tuple[DeviceBattery, int]] = []
    if not cfg.alerts_master_enabled:
        return triggered

    for dev in devices:
        tiers = get_device_tiers(cfg, dev.device_id)
        seen = alerted_map.setdefault(dev.device_id, set())

        if not tiers or not dev.connected or not dev.online or dev.asleep or dev.percent is None:
            continue

        if dev.charging:
            seen.clear()
            if last_alert_ts is not None:
                last_alert_ts.pop(dev.device_id, None)
            continue

        pct = int(dev.percent)
        for t in list(seen):
            if pct >= t + 5:
                seen.discard(t)

        # 1. 检查是否触及新的未提醒档位
        pending = [t for t in tiers if pct <= t and t not in seen]
        if pending:
            for t in pending:
                seen.add(t)
            most_urgent = min(pending)
            if last_alert_ts is not None:
                last_alert_ts[dev.device_id] = now
            triggered.append((dev, most_urgent))
            continue

        # 2. 若用户开启了重复提醒且电量持续低于任意启用阈值，到达冷却间隔后再次提醒
        if cfg.repeat_alert_enabled and last_alert_ts is not None:
            active_hits = [t for t in tiers if pct <= t]
            if active_hits:
                interval_sec = max(60, int(cfg.repeat_interval_min) * 60)
                prev_ts = last_alert_ts.get(dev.device_id, 0.0)
                if now - prev_ts >= interval_sec:
                    last_alert_ts[dev.device_id] = now
                    triggered.append((dev, min(active_hits)))

    return triggered


# ================= 主应用控制器 =================

class MouseBatteryApp:
    def __init__(self, start_hidden: bool = False) -> None:
        self.cfg: AppConfig = load_config()
        self.start_hidden = start_hidden
        self._allow_show = not start_hidden
        self.manager = DeviceManager()
        self.devices: list[DeviceBattery] = []
        self._known_devices: dict[str, DeviceBattery] = {}
        self._last_poll_ts: float = 0.0

        self.window: Optional[webview.Window] = None
        self.settings_window: Optional[webview.Window] = None
        self.hwnd: int = 0
        self.settings_hwnd: int = 0
        self._main_maximized = False
        self._settings_maximized = False
        self._main_revealed = False
        self._settings_ready = False
        self._settings_pending_reveal = False
        self._reveal_lock = threading.Lock()

        self._alert_window = None
        self._alert_timer: Optional[threading.Timer] = None
        self._alert_lock = threading.Lock()
        self._tray: Optional[pystray.Icon] = None
        self._stop_event = threading.Event()
        self._alerted_tiers: dict[str, set[int]] = {}
        self._last_alert_ts: dict[str, float] = {}
        self._last_cursor = _get_cursor_pos()

        # 软件在线更新状态（线程安全，推送给主窗口与设置窗口）
        self._update_lock = threading.Lock()
        self._update_cancel = threading.Event()
        self._last_update_check_mono: float = 0.0
        self._last_tray_icon_key: Optional[tuple[Any, ...]] = None
        self._last_tray_title: str = ""
        self._update_state: dict[str, Any] = {
            "status": "idle",  # idle | checking | up_to_date | available | downloading | verifying | preparing | restarting | error
            "current_version": APP_VERSION,
            "latest_version": "",
            "has_update": False,
            "dismissed": False,
            "release_url": RELEASES_PAGE_URL,
            "release_notes": "",
            "summary_items": [],
            "important_notice": "",
            "asset_name": "",
            "asset_url": "",
            "asset_size": 0,
            "sha256_url": "",
            "progress": 0,
            "downloaded_mb": 0.0,
            "total_mb": 0.0,
            "message": "",
            "checked_at": "",
            "can_auto_install": bool(IS_FROZEN),
        }

        # 拖拽状态（按窗口名区分）
        self._drag_state: dict[str, tuple[tuple[int, int], tuple[int, int], tuple[int, int]]] = {}

        # 桌面悬浮窗管理器
        self.floating_widget = DesktopFloatingWidget(
            get_native_host=lambda: getattr(self.window, "native", None) if self.window is not None else None,
            get_work_area=_get_tray_work_area,
            get_dpi_scale=lambda: _get_dpi_scale(self.hwnd) if self.hwnd else 1.0,
            on_position_saved=self._on_floating_position_saved,
            on_double_click=self.show_main_window,
        )

    def _effective_theme(self) -> str:
        return resolve_effective_theme(self.cfg.theme)

    def _effective_animations(self) -> bool:
        return resolve_effective_animations(self.cfg.animations_enabled)

    def _sorted_devices(self, include_hidden: bool = False) -> list[dict[str, Any]]:
        """生成带独立偏好、排序、状态配色与提醒阈值的统一前端设备列表。"""
        items: list[tuple[int, int, str, dict[str, Any]]] = []
        for idx, dev in enumerate(self.devices):
            pref = get_device_pref(self.cfg, dev.device_id)
            if not include_hidden and pref.hidden:
                continue
            tiers = get_device_tiers(self.cfg, dev.device_id)
            display_name = pref.alias or dev.name
            d = dev.to_dict()
            d["original_name"] = dev.name
            d["raw_name"] = dev.raw_name or dev.name
            d["display_name"] = display_name
            d["connection_label"] = _connection_label(dev)
            d["subtitle"] = format_device_subtitle(
                connection_mode=dev.connection_mode,
                connected=dev.connected,
                online=dev.online,
                asleep=dev.asleep,
                charging=dev.charging,
                full=dev.full,
                percent=dev.percent,
            )
            d["support_label"] = _support_label(dev.support_status)
            d["pref"] = asdict(pref)
            d["effective_tiers"] = tiers
            d["alert_level"] = self._compute_alert_level(dev, tiers)
            items.append((pref.order, idx, dev.device_id, d))
        items.sort(key=lambda x: (x[0], x[1], x[2]))
        return [x[3] for x in items]

    def _compute_alert_level(self, dev: DeviceBattery, tiers: list[int]) -> str:
        """返回 normal | tier1 | tier2 | tier3 | charging | offline | unknown。"""
        if not dev.connected or (not dev.online and not dev.asleep):
            return "offline"
        if dev.asleep:
            return "offline"
        if dev.percent is None:
            return "unknown"
        if dev.charging:
            return "charging"
        pct = int(dev.percent)
        # 按 3 级规则阈值判断色阶
        t1 = int(self.cfg.tier_rules[0]["threshold"]) if len(self.cfg.tier_rules) > 0 else 30
        t2 = int(self.cfg.tier_rules[1]["threshold"]) if len(self.cfg.tier_rules) > 1 else 20
        t3 = int(self.cfg.tier_rules[2]["threshold"]) if len(self.cfg.tier_rules) > 2 else 10
        if tiers:
            sorted_t = sorted(tiers, reverse=True)
            if len(sorted_t) >= 3:
                t1, t2, t3 = sorted_t[0], sorted_t[1], sorted_t[-1]
            elif len(sorted_t) == 2:
                t1, t2, t3 = sorted_t[0], sorted_t[1], min(10, sorted_t[1])
            elif len(sorted_t) == 1:
                t1 = t2 = t3 = sorted_t[0]
        if pct <= t3:
            return "tier3"
        if pct <= t2:
            return "tier2"
        if pct <= t1:
            return "tier1"
        return "normal"

    def _pick_floating_device(self) -> tuple[Optional[DeviceBattery], str]:
        fcfg = get_floating_config(self.cfg)
        if fcfg.device_id and fcfg.device_id != "auto":
            for d in self.devices:
                if d.device_id == fcfg.device_id:
                    pref = get_device_pref(self.cfg, d.device_id)
                    return d, (pref.alias or d.name)
        ordered_objs = sorted(
            enumerate(self.devices),
            key=lambda pair: (get_device_pref(self.cfg, pair[1].device_id).order, pair[0], pair[1].device_id),
        )
        ordered_devices = [d for _, d in ordered_objs]
        visible = [d for d in ordered_devices if not get_device_pref(self.cfg, d.device_id).hidden]
        pool = visible or ordered_devices
        with_pct = [d for d in pool if d.connected and d.percent is not None]
        if with_pct:
            # 保持用户排序优先（同等电量或非极低电量时严格遵循用户设备顺序）
            best = min(with_pct, key=lambda d: (int(d.percent or 100), pool.index(d)))
            return best, (get_device_pref(self.cfg, best.device_id).alias or best.name)
        if pool:
            return pool[0], (get_device_pref(self.cfg, pool[0].device_id).alias or pool[0].name)
        return None, "未连接外设"

    def _build_state_dict(self) -> dict[str, Any]:
        updated_str = ""
        if self._last_poll_ts > 0:
            updated_str = f"今天 {datetime.fromtimestamp(self._last_poll_ts).strftime('%H:%M')}"

        visible_devices = self._sorted_devices(include_hidden=False)
        all_devices = self._sorted_devices(include_hidden=True)

        with self._update_lock:
            upd_snapshot = dict(self._update_state)

        return {
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "app_author": APP_AUTHOR,
            "is_win11": is_windows_11(),
            "effective_theme": self._effective_theme(),
            "effective_animations": self._effective_animations(),
            "autostart": is_autostart_enabled(),
            "config": asdict(self.cfg),
            "devices": visible_devices,
            "all_devices": all_devices,
            "device_icons": get_device_icons_svg_map(20),
            "updated_str": updated_str,
            "auto_monitor": bool(self.cfg.auto_monitor),
            "main_maximized": self._main_maximized,
            "settings_maximized": self._settings_maximized,
            "github_repo_url": GITHUB_REPO_URL,
            "releases_page_url": RELEASES_PAGE_URL,
            "update_state": upd_snapshot,
        }

    def _push_state_to_ui(self) -> None:
        payload = json.dumps(self._build_state_dict(), ensure_ascii=False)
        for win in (self.window, self.settings_window):
            if win is not None:
                try:
                    win.evaluate_js(f"window.applyState && applyState({payload});")
                except Exception:
                    pass

    def _get_active_tier_thresholds(self, device_id: Optional[str] = None) -> tuple[int, int, int]:
        """读取当前生效的三级低电量阈值（支持单设备覆盖与用户自定义阈值）。"""
        rules = self.cfg.tier_rules if isinstance(self.cfg.tier_rules, list) else []
        t1 = int(rules[0]["threshold"]) if len(rules) > 0 else 30
        t2 = int(rules[1]["threshold"]) if len(rules) > 1 else 20
        t3 = int(rules[2]["threshold"]) if len(rules) > 2 else 10
        if device_id:
            pref = get_device_pref(self.cfg, device_id)
            if pref.custom_tiers_enabled and pref.custom_tiers:
                st = sorted(normalize_tiers(pref.custom_tiers), reverse=True)
                if len(st) >= 3:
                    return st[0], st[1], st[-1]
                if len(st) == 2:
                    return st[0], st[1], min(10, st[1])
                if len(st) == 1:
                    return st[0], st[0], st[0]
        return t1, t2, t3

    def _resolve_alert_tier(self, percent: int, device_id: Optional[str] = None) -> tuple[int, str]:
        """根据实际生效阈值判定低电量提醒等级与规范中文标题。"""
        t1, t2, t3 = self._get_active_tier_thresholds(device_id)
        if percent <= t3:
            return (3, "电量紧急")
        if percent <= t2:
            return (2, "电量不足")
        if percent <= t1:
            return (1, "电量偏低")
        return (1, "电量偏低")

    def _sync_floating_widget(self) -> None:
        fcfg = get_floating_config(self.cfg)
        dev, _full_name = self._pick_floating_device()
        pref = get_device_pref(self.cfg, dev.device_id) if dev is not None else None
        compact_label = resolve_compact_device_label(
            dev,
            self.devices,
            custom_label=fcfg.custom_label,
            alias=(pref.alias if pref else ""),
        )
        t1, t2, t3 = self._get_active_tier_thresholds(dev.device_id if dev else None)
        hover_detail = ""
        if dev is not None:
            sub = format_device_subtitle(
                dev.connection_mode, dev.connected, dev.online,
                dev.asleep, dev.charging, dev.full, dev.percent,
            )
            pct_s = f"{dev.percent}%" if dev.percent is not None else "—"
            hover_detail = f"{dev.name}\n{sub} · {pct_s}" if sub else f"{dev.name}\n{pct_s}"
        self.floating_widget.sync(
            fcfg,
            dev,
            compact_label,
            self._effective_theme(),
            hover_detail=hover_detail,
            low_t1=t1,
            low_t2=t2,
            low_t3=t3,
            animations_enabled=self._effective_animations(),
        )

    def _on_floating_position_saved(self, x: int, y: int) -> None:
        fcfg = get_floating_config(self.cfg)
        fcfg.position_preset = "custom"
        fcfg.x = int(x)
        fcfg.y = int(y)
        self.cfg.floating = asdict(fcfg)
        save_config(self.cfg)
        self._push_state_to_ui()

    def _find_hwnd_for(self, win: Optional[webview.Window], title: str) -> int:
        if win is not None:
            native = getattr(win, "native", None)
            if native is not None:
                try:
                    return int(native.Handle.ToInt64())
                except Exception:
                    try:
                        return int(native.Handle)
                    except Exception:
                        pass
        return int(ctypes.windll.user32.FindWindowW(None, title) or 0)

    # ================= 窗口控制（主窗口 & 独立设置窗口） =================

    def _compute_main_initial_logical_bounds(self) -> tuple[int, int, int, int]:
        """计算主窗口首次创建时的逻辑坐标与尺寸 (log_x, log_y, log_w, log_h)，首帧直接居中无闪烁。"""
        work, scale = _get_current_monitor_work_area_and_scale()
        log_w = max(580, int(self.cfg.width or MAIN_DEFAULT_SIZE[0]))
        log_h = max(380, int(self.cfg.height or MAIN_DEFAULT_SIZE[1]))
        phys_w = int(round(log_w * scale))
        phys_h = int(round(log_h * scale))
        px, py, pw, ph = _compute_centered_rect(work, phys_w, phys_h)
        return (
            int(round(px / scale)),
            int(round(py / scale)),
            max(580, int(round(pw / scale))),
            max(380, int(round(ph / scale))),
        )

    def _center_main_hwnd(self) -> None:
        """将主窗口无闪烁居中对齐到当前显示器可用工作区。"""
        if not self.hwnd:
            return
        user32 = ctypes.windll.user32
        work, scale = _get_current_monitor_work_area_and_scale()
        if user32.IsZoomed(wintypes.HWND(self.hwnd)):
            user32.ShowWindow(wintypes.HWND(self.hwnd), 9)
            self._main_maximized = False
        _wx, _wy, ww, wh = _get_window_rect(self.hwnd)
        if ww < 300 or wh < 200:
            ww = int(round(max(580, int(self.cfg.width or MAIN_DEFAULT_SIZE[0])) * scale))
            wh = int(round(max(380, int(self.cfg.height or MAIN_DEFAULT_SIZE[1])) * scale))
        px, py, pw, ph = _compute_centered_rect(work, ww, wh)
        _set_window_pos(self.hwnd, px, py, pw, ph, topmost=self.cfg.topmost)

    def _compute_settings_target_phys_rect(self) -> tuple[int, int, int, int, float]:
        """计算设置窗口的目标物理矩形 (px, py, pw, ph, scale)：以主窗口为基准居中且严格限在工作区内。"""
        user32 = ctypes.windll.user32
        anchor: Optional[tuple[int, int, int, int]] = None
        if self.hwnd and user32.IsWindowVisible(wintypes.HWND(self.hwnd)) and not user32.IsIconic(wintypes.HWND(self.hwnd)):
            anchor = _get_window_rect(self.hwnd)
            work, scale = _get_window_monitor_work_area_and_scale(self.hwnd)
        else:
            work, scale = _get_current_monitor_work_area_and_scale()

        phys_w = int(round(SETTINGS_DEFAULT_SIZE[0] * scale))
        phys_h = int(round(SETTINGS_DEFAULT_SIZE[1] * scale))
        px, py, pw, ph = _compute_centered_rect(work, phys_w, phys_h, anchor_rect=anchor)
        return px, py, pw, ph, scale

    def _theme_bg_hex(self) -> str:
        return "#151820" if self._effective_theme() == "dark" else "#F5F6FA"

    def _reveal_main_if_needed(self) -> None:
        """在主窗口完成精确居中与首帧渲染后，播放 180ms 轻量淡入（关闭动画时瞬显）。"""
        with self._reveal_lock:
            if self._main_revealed or not self._allow_show or self.window is None:
                return
            self._main_revealed = True
        if self.hwnd:
            self._center_main_hwnd()
            _apply_window_chrome(self.hwnd, self._effective_theme() == "dark")
        fade = 180 if self._effective_animations() else 0
        _set_form_visibility(self.window, visible=True, opacity=1.0, activate=True, fade_ms=fade)

    def _reveal_settings_if_needed(self) -> None:
        """在设置窗口完成定位与常规设置页渲染后，播放 220ms 淡入 + 8px 内容轻位移。"""
        with self._reveal_lock:
            if not self._settings_pending_reveal or self.settings_window is None:
                return
            self._settings_pending_reveal = False
            self._settings_ready = True
        if self.settings_hwnd:
            px, py, pw, ph, _ = self._compute_settings_target_phys_rect()
            _set_window_pos(self.settings_hwnd, px, py, pw, ph)
            _apply_window_chrome(self.settings_hwnd, self._effective_theme() == "dark")
        anim = self._effective_animations()
        if anim and self.settings_window is not None:
            try:
                self.settings_window.evaluate_js("window.playWindowEnter && playWindowEnter();")
            except Exception:
                pass
        _set_form_visibility(self.settings_window, visible=True, opacity=1.0, activate=True, fade_ms=220 if anim else 0)

    def on_ui_ready(self, target: str) -> None:
        """前端首帧渲染完毕（双 requestAnimationFrame）后的就绪通知，触发无闪烁显现。"""
        if target == "settings":
            self._reveal_settings_if_needed()
        else:
            self._reveal_main_if_needed()

    def show_main_window(self) -> None:
        """从系统托盘重新打开主窗口：隐藏态先对齐精确居中坐标，再 180ms 淡入显现。"""
        if self.window is None:
            return
        self._allow_show = True
        with self._reveal_lock:
            self._main_revealed = True
        if self.hwnd:
            self._center_main_hwnd()
            _apply_window_chrome(self.hwnd, self._effective_theme() == "dark")
        self._push_state_to_ui()
        fade = 180 if self._effective_animations() else 0
        _set_form_visibility(self.window, visible=True, opacity=1.0, activate=True, fade_ms=fade)
        if self.hwnd:
            ctypes.windll.user32.SetForegroundWindow(wintypes.HWND(self.hwnd))

    def open_settings_window(self, section: str = "general") -> None:
        """打开或前置独立设置窗口：默认进入“常规设置”，以主窗口为基准居中显示且零闪烁。"""
        target_sec = section or "general"
        px, py, pw, ph, scale = self._compute_settings_target_phys_rect()

        # 若设置窗口实例已存在（隐藏复用），先保持 Opacity=0 完成切页、同步状态与精准居中，再一次性显现
        if self.settings_window is not None:
            try:
                native = getattr(self.settings_window, "native", None)
                if native is not None and not native.IsDisposed:
                    _set_form_visibility(self.settings_window, visible=True, opacity=0.0, activate=False)
                    if self.settings_hwnd:
                        if ctypes.windll.user32.IsZoomed(wintypes.HWND(self.settings_hwnd)):
                            ctypes.windll.user32.ShowWindow(wintypes.HWND(self.settings_hwnd), 9)
                            self._settings_maximized = False
                        _set_window_pos(self.settings_hwnd, px, py, pw, ph)
                        _apply_window_chrome(self.settings_hwnd, self._effective_theme() == "dark")
                    payload = json.dumps(self._build_state_dict(), ensure_ascii=False)
                    with self._reveal_lock:
                        self._settings_pending_reveal = True
                    self.settings_window.evaluate_js(
                        f"window.switchSection && switchSection({json.dumps(target_sec)}, true);"
                        f"window.applyState && applyState({payload});"
                        f"requestAnimationFrame(()=>requestAnimationFrame(()=>window.pywebview?.api?.ui_ready()));"
                    )
                    threading.Timer(0.15, self._reveal_settings_if_needed).start()
                    return
            except Exception:
                self.settings_window = None
                self.settings_hwnd = 0

        # 首次创建设置窗口：通过 Opacity=0 预渲染，等首帧就绪后再一次性显现
        log_x = int(round(px / scale))
        log_y = int(round(py / scale))
        log_w = max(680, int(round(pw / scale)))
        log_h = max(460, int(round(ph / scale)))

        with self._reveal_lock:
            self._settings_ready = False
            self._settings_pending_reveal = True

        url = f"{UI_SETTINGS_HTML.as_uri()}#{target_sec}"
        win = webview.create_window(
            title=SETTINGS_WINDOW_TITLE,
            url=url,
            width=log_w,
            height=log_h,
            x=log_x,
            y=log_y,
            min_size=(680, 460),
            frameless=True,
            easy_drag=False,
            transparent=False,
            background_color=self._theme_bg_hex(),
            resizable=True,
            js_api=_JsApi(self, "settings"),
        )
        self.settings_window = win

        def _on_settings_loaded():
            for _ in range(20):
                self.settings_hwnd = self._find_hwnd_for(win, SETTINGS_WINDOW_TITLE)
                if self.settings_hwnd:
                    break
                time.sleep(0.04)
            if self.settings_hwnd:
                _apply_window_chrome(self.settings_hwnd, self._effective_theme() == "dark")
                tpx, tpy, tpw, tph, _ = self._compute_settings_target_phys_rect()
                _set_window_pos(self.settings_hwnd, tpx, tpy, tpw, tph)
                apply_window_rounded_corners(self.settings_hwnd, radius_dip=10, scale=_get_dpi_scale(self.settings_hwnd))
                _attach_rounded_resize_hook(win, radius_dip=10)
            self._push_state_to_ui()
            # 兜底定时器：若前端回调异常延迟，最迟 0.8s 自动显现，绝不卡死
            threading.Timer(0.8, self._reveal_settings_if_needed).start()

        def _on_settings_closed():
            self.settings_window = None
            self.settings_hwnd = 0
            self._settings_maximized = False
            self._settings_ready = False

        win.events.loaded += _on_settings_loaded
        win.events.closed += _on_settings_closed

    def close_settings_window(self) -> None:
        """140ms 平滑淡出后隐藏并复用设置窗口实例（快速重开时自动取消淡出并无缝衔接）。"""
        if self.settings_window is not None:
            fade = 140 if self._effective_animations() else 0
            _set_form_visibility(self.settings_window, visible=False, opacity=0.0, fade_ms=fade)
            self._settings_maximized = False

    def minimize_window(self, target: str = "main") -> None:
        win = self.settings_window if target == "settings" else self.window
        hwnd = self.settings_hwnd if target == "settings" else self.hwnd
        if win is not None:
            try:
                win.minimize()
                return
            except Exception:
                pass
        if hwnd:
            ctypes.windll.user32.ShowWindow(wintypes.HWND(hwnd), 6)

    def toggle_maximize(self, target: str = "main") -> None:
        hwnd = self.settings_hwnd if target == "settings" else self.hwnd
        if not hwnd:
            return
        user32 = ctypes.windll.user32
        is_max = bool(user32.IsZoomed(wintypes.HWND(hwnd)))
        user32.ShowWindow(wintypes.HWND(hwnd), 9 if is_max else 3)  # SW_RESTORE / SW_MAXIMIZE
        apply_window_rounded_corners(hwnd, radius_dip=10, scale=_get_dpi_scale(hwnd))
        if target == "settings":
            self._settings_maximized = not is_max
        else:
            self._main_maximized = not is_max
        self._push_state_to_ui()

    def close_main_window(self) -> None:
        """按「关闭窗口时最小化至托盘」设置决定隐藏到托盘还是退出程序。"""
        if self.cfg.close_to_tray:
            self._allow_show = False
            _set_form_visibility(self.window, visible=False, opacity=0.0)
        else:
            self.quit_app()

    def begin_drag(self, target: str, _sx: int, _sy: int) -> None:
        hwnd = self.settings_hwnd if target == "settings" else self.hwnd
        if not hwnd:
            return
        if ctypes.windll.user32.IsZoomed(wintypes.HWND(hwnd)):
            return
        self._drag_state[target] = (_get_cursor_pos(), _get_window_rect(hwnd)[:2], _get_window_rect(hwnd)[2:])

    def drag_move(self, target: str, _sx: int, _sy: int) -> None:
        hwnd = self.settings_hwnd if target == "settings" else self.hwnd
        state = self._drag_state.get(target)
        if not hwnd or not state:
            return
        (cx0, cy0), (wx0, wy0), (ww, wh) = state
        cx, cy = _get_cursor_pos()
        _set_window_pos(hwnd, wx0 + (cx - cx0), wy0 + (cy - cy0), ww, wh)

    def end_drag(self, target: str) -> None:
        self._drag_state.pop(target, None)
        if target == "main" and self.hwnd:
            wx, wy, ww, wh = _get_window_rect(self.hwnd)
            left, top, right, bottom = _get_work_area_for_window(self.hwnd)
            nx = max(left - ww + 120, min(wx, right - 120))
            ny = max(top, min(wy, bottom - 60))
            _set_window_pos(self.hwnd, nx, ny, ww, wh)
            self.cfg.x = nx
            self.cfg.y = ny
            save_config(self.cfg)

    # ================= 设置更新接口（自动保存并即时生效） =================

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        """批量更新常规/提醒/外观/悬浮窗配置，立即保存并推送给所有窗口与悬浮窗。"""
        if not isinstance(patch, dict):
            return self._build_state_dict()

        if "autostart" in patch:
            set_autostart(bool(patch["autostart"]), self.cfg.start_minimized_to_tray)

        if "start_minimized_to_tray" in patch:
            self.cfg.start_minimized_to_tray = bool(patch["start_minimized_to_tray"])
            if is_autostart_enabled():
                set_autostart(True, self.cfg.start_minimized_to_tray)

        simple_bools = (
            "close_to_tray",
            "auto_monitor",
            "auto_check_updates",
            "alerts_master_enabled",
            "custom_alerts_enabled",
            "popup_alert_enabled",
            "windows_notify_enabled",
            "sound_enabled",
            "repeat_alert_enabled",
            "show_progress_bar",
            "show_device_icon",
            "animations_enabled",
            "topmost",
        )
        for key in simple_bools:
            if key in patch:
                setattr(self.cfg, key, bool(patch[key]))

        if "poll_interval_sec" in patch:
            self.cfg.poll_interval_sec = max(10, min(300, int(patch["poll_interval_sec"])))
        if "repeat_interval_min" in patch:
            self.cfg.repeat_interval_min = max(1, min(120, int(patch["repeat_interval_min"])))
        if "ui_scale" in patch:
            self.cfg.ui_scale = max(85, min(135, int(patch["ui_scale"])))

        for key in ("theme", "color_scheme", "list_density", "sound_name"):
            if key in patch and isinstance(patch[key], str):
                setattr(self.cfg, key, patch[key])

        if "tier_rules" in patch and isinstance(patch["tier_rules"], list):
            cleaned_rules = []
            for r in patch["tier_rules"][:3]:
                if isinstance(r, dict):
                    cleaned_rules.append(
                        {
                            "id": str(r.get("id", "tier")),
                            "label": str(r.get("label", "电量提醒")),
                            "threshold": max(1, min(95, int(r.get("threshold", 20)))),
                            "enabled": bool(r.get("enabled", True)),
                            "color": str(r.get("color", "yellow")),
                        }
                    )
            if len(cleaned_rules) == 3:
                self.cfg.tier_rules = cleaned_rules
                self._alerted_tiers.clear()

        if "custom_thresholds" in patch and isinstance(patch["custom_thresholds"], list):
            self.cfg.custom_thresholds = normalize_tiers(patch["custom_thresholds"])
            self._alerted_tiers.clear()

        if "floating" in patch and isinstance(patch["floating"], dict):
            fcfg = get_floating_config(self.cfg)
            for fk, fv in patch["floating"].items():
                if hasattr(fcfg, fk):
                    if fk == "opacity":
                        setattr(fcfg, fk, max(40, min(100, int(fv))))
                    elif fk in ("enabled", "topmost", "locked"):
                        setattr(fcfg, fk, bool(fv))
                    else:
                        setattr(fcfg, fk, fv)
            self.cfg.floating = asdict(fcfg)

        save_config(self.cfg)

        # 应用窗口深浅色与置顶状态
        is_dark = self._effective_theme() == "dark"
        _sync_native_form_backcolor(self.window, is_dark)
        _sync_native_form_backcolor(self.settings_window, is_dark)
        if self.hwnd:
            if "topmost" in patch:
                wx, wy, ww, wh = _get_window_rect(self.hwnd)
                _set_window_pos(self.hwnd, wx, wy, ww, wh, topmost=self.cfg.topmost)
            _apply_window_chrome(self.hwnd, is_dark)
        if self.settings_hwnd:
            _apply_window_chrome(self.settings_hwnd, is_dark)

        self._push_state_to_ui()
        self._update_tray_visual()
        self._sync_floating_widget()
        return self._build_state_dict()

    def update_device_pref(self, device_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """更新单台设备独立配置（重命名、隐藏、暂停监控、排序、独立阈值）。"""
        if device_id and isinstance(updates, dict):
            clean_updates = dict(updates)
            if "custom_tiers" in clean_updates and isinstance(clean_updates["custom_tiers"], list):
                raw_t = [max(1, min(95, int(v))) for v in clean_updates["custom_tiers"] if isinstance(v, (int, float))]
                # 保证严格递减顺序（t1 > t2 > t3），避免无效重复档位
                clean_updates["custom_tiers"] = sorted(set(raw_t), reverse=True)
            set_device_pref(self.cfg, str(device_id), clean_updates)
            self._alerted_tiers.pop(str(device_id), None)
            save_config(self.cfg)
            self._push_state_to_ui()
            self._update_tray_visual()
            self._sync_floating_widget()
        return self._build_state_dict()

    def reorder_devices(self, device_ids: list[str]) -> dict[str, Any]:
        """按拖拽后的 device_id 列表保存设备显示顺序，并立即同步主窗口与悬浮窗。"""
        if not isinstance(device_ids, list) or not device_ids:
            return self._build_state_dict()
        ordered_now = [d["device_id"] for d in self._sorted_devices(include_hidden=True)]
        seen: set[str] = set()
        merged: list[str] = []
        for did in device_ids:
            s = str(did)
            if s in ordered_now and s not in seen:
                seen.add(s)
                merged.append(s)
        for did in ordered_now:
            if did not in seen:
                seen.add(did)
                merged.append(did)
        for pos, did in enumerate(merged):
            set_device_pref(self.cfg, did, {"order": pos * 10})
        save_config(self.cfg)
        self._push_state_to_ui()
        self._update_tray_visual()
        self._sync_floating_widget()
        return self._build_state_dict()

    def move_device_order(self, device_id: str, direction: int) -> dict[str, Any]:
        """上下调整设备在主列表中的显示顺序。"""
        ordered = self._sorted_devices(include_hidden=True)
        ids = [d["device_id"] for d in ordered]
        if device_id not in ids:
            return self._build_state_dict()
        idx = ids.index(device_id)
        target_idx = idx + (-1 if direction < 0 else 1)
        if 0 <= target_idx < len(ids):
            ids[idx], ids[target_idx] = ids[target_idx], ids[idx]
            return self.reorder_devices(ids)
        return self._build_state_dict()

    def preview_sound(self, sound_name: str = "default") -> None:
        threading.Thread(target=play_alert_sound, args=(sound_name,), daemon=True).start()

    def export_diagnostics(self) -> dict[str, Any]:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"diagnostics_{ts}.json"
        report = self.manager.export_diagnostics()
        payload = json.dumps(report, ensure_ascii=False, indent=2)
        target = APP_DIR / filename
        try:
            target.write_text(payload, encoding="utf-8")
        except OSError:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            target = DATA_DIR / filename
            target.write_text(payload, encoding="utf-8")
        return {"ok": True, "path": str(target), "filename": target.name}

    def read_doc_file(self, doc_name: str) -> dict[str, Any]:
        """读取项目内只读说明文档（仅限白名单 Markdown，防止路径遍历）。"""
        allowed = {
            "SUPPORTED_DEVICES.md": "支持设备清单",
            "THIRD_PARTY_LICENSES.md": "第三方许可说明",
            "CHANGELOG.md": "更新日志",
        }
        if doc_name not in allowed:
            return {"ok": False, "title": "未知文档", "content": "不支持读取该文件。"}
        for base in (APP_DIR, RESOURCE_DIR):
            p = base / doc_name
            if p.exists():
                try:
                    return {"ok": True, "title": allowed[doc_name], "content": p.read_text(encoding="utf-8")}
                except Exception:
                    pass
        return {"ok": False, "title": allowed[doc_name], "content": f"未找到 {doc_name} 文件。"}

    def open_project_folder(self) -> None:
        try:
            os.startfile(str(APP_DIR))
        except Exception:
            pass

    def open_external_url(self, url: str) -> bool:
        """安全打开白名单内的 GitHub 项目与 Release 页面。"""
        target = (url or "").strip()
        if not target.startswith(GITHUB_REPO_URL):
            target = RELEASES_PAGE_URL
        try:
            return bool(webbrowser.open(target))
        except Exception:
            return False

    def _set_update_state(self, **kwargs: Any) -> dict[str, Any]:
        with self._update_lock:
            self._update_state.update(kwargs)
            snap = dict(self._update_state)
        self._push_state_to_ui()
        return snap

    def check_updates(self, silent: bool = False) -> dict[str, Any]:
        """后台异步检查 GitHub Releases 最新稳定版本（含轻量防高频请求冷却）。"""
        now_mono = time.monotonic()
        with self._update_lock:
            if self._update_state["status"] in ("checking", "downloading", "verifying", "preparing", "restarting"):
                return dict(self._update_state)
            if not silent and self._last_update_check_mono > 0 and (now_mono - self._last_update_check_mono) < 4.0 and self._update_state["status"] in ("up_to_date", "available"):
                self._update_state["dismissed"] = False
                snap = dict(self._update_state)
                self._push_state_to_ui()
                return snap
            self._last_update_check_mono = now_mono
            if not silent:
                self._update_state["status"] = "checking"
                self._update_state["dismissed"] = False
                self._update_state["message"] = "正在检查更新…"
                self._update_state["progress"] = 0
        if not silent:
            self._push_state_to_ui()

        def _worker() -> None:
            res = check_for_update(APP_VERSION)
            now_str = datetime.now().strftime("%H:%M")
            if not res.ok:
                if silent:
                    with self._update_lock:
                        if self._update_state["status"] == "checking":
                            self._update_state["status"] = "idle"
                    return
                self._set_update_state(
                    status="error",
                    message=res.error or "更新失败，请重试",
                    checked_at=now_str,
                )
                return

            if res.has_update:
                self._set_update_state(
                    status="available",
                    latest_version=res.latest_version,
                    has_update=True,
                    dismissed=False,
                    release_url=res.release_url,
                    release_notes=res.release_notes,
                    summary_items=res.summary_items,
                    important_notice=res.important_notice,
                    asset_name=res.asset_name,
                    asset_url=res.asset_url,
                    asset_size=res.asset_size,
                    sha256_url=res.sha256_url,
                    progress=0,
                    message=f"发现新版本 v{res.latest_version}",
                    checked_at=now_str,
                )
            else:
                self._set_update_state(
                    status="up_to_date",
                    latest_version=res.latest_version or APP_VERSION,
                    has_update=False,
                    dismissed=False,
                    release_url=res.release_url,
                    release_notes=res.release_notes,
                    summary_items=res.summary_items,
                    important_notice=res.important_notice,
                    asset_name=res.asset_name,
                    asset_url=res.asset_url,
                    asset_size=res.asset_size,
                    sha256_url=res.sha256_url,
                    progress=0,
                    message="已是最新版本",
                    checked_at=now_str,
                )

        threading.Thread(target=_worker, daemon=True).start()
        with self._update_lock:
            return dict(self._update_state)

    def dismiss_update_notice(self) -> dict[str, Any]:
        """用户点击「稍后更新」后收起更新卡片与底栏提醒胶囊（可随时再次点击检查更新）。"""
        return self._set_update_state(dismissed=True)

    def download_and_install_update(self) -> dict[str, Any]:
        """完整在线更新链路：下载 -> 校验 SHA-256 与 ZIP -> 准备安装 -> 安全退出并自动覆盖重启新版。"""
        with self._update_lock:
            st = dict(self._update_state)
            if st["status"] in ("downloading", "verifying", "preparing", "restarting"):
                return st
            asset_url = str(st.get("asset_url") or "")
            asset_name = str(st.get("asset_name") or "BattDock-update.zip")
            asset_size = int(st.get("asset_size") or 0)
            sha256_url = str(st.get("sha256_url") or "")
            release_url = str(st.get("release_url") or RELEASES_PAGE_URL)

        if not asset_url:
            return self._set_update_state(
                status="error",
                progress=0,
                message="未找到可用的 Windows 更新包，请前往下载页手动更新",
            )

        if not IS_FROZEN:
            self.open_external_url(release_url)
            return self._set_update_state(
                status="available",
                message="当前为源码开发模式，已在浏览器打开 Release 页面",
            )

        self._update_cancel.clear()
        self._set_update_state(
            status="downloading",
            dismissed=False,
            progress=0,
            downloaded_mb=0.0,
            total_mb=round(asset_size / (1024 * 1024), 2) if asset_size else 0.0,
            message="正在下载更新…",
        )

        def _worker() -> None:
            work_root = Path(tempfile.gettempdir()) / f"BattDockUpdate_{os.getpid()}"
            zip_path = work_root / asset_name
            extract_dir = work_root / "extracted"
            last_push = [0.0, -1]

            def _on_prog(done: int, total: int) -> None:
                now = time.monotonic()
                pct = int(min(99, round(done * 100 / total))) if total > 0 else 0
                if pct != last_push[1] and (now - last_push[0] >= 0.2 or pct >= 99):
                    last_push[0] = now
                    last_push[1] = pct
                    done_mb = round(done / (1024 * 1024), 1)
                    tot_mb = round(total / (1024 * 1024), 1) if total > 0 else 0.0
                    msg = f"正在下载更新… {pct}%（{done_mb:.1f} / {tot_mb:.1f} MB）" if tot_mb > 0 else f"正在下载更新…（{done_mb:.1f} MB）"
                    self._set_update_state(
                        status="downloading",
                        progress=pct,
                        downloaded_mb=done_mb,
                        total_mb=tot_mb,
                        message=msg,
                    )

            try:
                download_update_asset(
                    asset_url=asset_url,
                    dest_zip=zip_path,
                    expected_size=asset_size,
                    on_progress=_on_prog,
                    cancel_event=self._update_cancel,
                )
                self._set_update_state(status="verifying", progress=100, message="正在校验文件…")
                if sha256_url:
                    sha_ok = verify_downloaded_sha256(zip_path, asset_name, sha256_url)
                    if sha_ok is False:
                        raise ValueError("安装包 SHA-256 校验失败，已中止更新")
                self._set_update_state(status="preparing", progress=100, message="正在准备安装…")
                staged_dir = extract_and_verify_update(zip_path, extract_dir)
                self._set_update_state(status="restarting", progress=100, message="正在重启软件…")
                launch_windows_updater(
                    staged_dir=staged_dir,
                    target_dir=APP_DIR,
                    pid=os.getpid(),
                    work_root=work_root,
                )
                time.sleep(0.35)
                self.quit_app()
                # 确保 WebView2 / CLR 子线程立即释放全部 DLL 文件锁，让更新脚本顺利覆盖并重启新版
                os._exit(0)
            except Exception as e:
                cancelled = self._update_cancel.is_set()
                self._set_update_state(
                    status="available" if cancelled else "error",
                    progress=0,
                    message="已取消下载更新" if cancelled else f"更新失败，请重试（{e}）",
                )

        threading.Thread(target=_worker, daemon=True).start()
        with self._update_lock:
            return dict(self._update_state)

    def cancel_update_download(self) -> None:
        self._update_cancel.set()

    def refresh_now(self) -> None:
        threading.Thread(target=self._poll_once, daemon=True).start()

    # ================= 原生 WinForms 极速最高置顶低电量迷你弹窗 & 系统通知 =================

    def _close_alert_window(self, instant: bool = False) -> None:
        with self._alert_lock:
            if self._alert_timer is not None:
                self._alert_timer.cancel()
                self._alert_timer = None
            alert_form = self._alert_window
            self._alert_window = None
        if alert_form is not None:
            fade_ms = 0 if (instant or not self._effective_animations()) else 140
            try:
                from System import Action

                def _dispose_now():
                    try:
                        _cancel_form_animation(alert_form)
                        if not alert_form.IsDisposed:
                            alert_form.Close()
                            alert_form.Dispose()
                    except Exception:
                        pass

                def _do_close():
                    try:
                        if alert_form.IsDisposed:
                            return
                        if fade_ms > 0 and alert_form.Visible and float(alert_form.Opacity) > 0.05:
                            _animate_form_transition(alert_form, float(alert_form.Opacity), 0.0, fade_ms, on_complete=_dispose_now)
                        else:
                            _dispose_now()
                    except Exception:
                        _dispose_now()

                if getattr(alert_form, "InvokeRequired", False):
                    alert_form.BeginInvoke(Action(_do_close))
                else:
                    _do_close()
            except Exception:
                pass

    def _show_mini_alert(
        self,
        device_label: str,
        percent: int,
        kind: str = KIND_MOUSE,
        is_test: bool = False,
        device_id: Optional[str] = None,
        full_device_name: str = "",
    ) -> None:
        """原生 WinForms 紧凑自适应低电量迷你弹窗（统一黑白实心设备图标、完整标准设备名、三级动态着色、Win10/11 圆角）。"""
        self._close_alert_window(instant=True)
        pct = max(0, min(100, int(percent)))
        tier_lvl, tier_title = self._resolve_alert_tier(pct, device_id=device_id)
        is_dark = self._effective_theme() == "dark"
        anim_on = self._effective_animations()
        full_name = (full_device_name or device_label or "").strip() or "未知外设"

        native_main = getattr(self.window, "native", None) if self.window is not None else None
        if native_main is None:
            return

        left, top, right, bottom = _get_tray_work_area()
        scale = _get_dpi_scale(self.hwnd) if self.hwnd else 1.0
        margin = int(round(EDGE_MARGIN * scale))
        work_w = max(260, right - left - margin * 2)

        def _create_on_ui_thread() -> None:
            try:
                import io
                import System.Windows.Forms as WinForms
                from System.Drawing import Color, ContentAlignment, Font, FontStyle, Image as GdiImage, Point, Size
                from System.Drawing.Drawing2D import GraphicsPath, SmoothingMode
                from System.IO import MemoryStream

                title_text = f"{tier_title} · 剩余 {pct}%"
                title_font = Font("Microsoft YaHei UI", 9.0, FontStyle.Bold)
                dev_font = Font("Microsoft YaHei UI", 8.6, FontStyle.Regular)
                btn_font = Font("Microsoft YaHei UI", 8.2, FontStyle.Regular)

                # 紧凑参考参数（按当前显示器 DPI 动态缩放）
                pad_x = int(round(11 * scale))
                icon_px = int(round(22 * scale))
                gap_icon = int(round(9 * scale))
                gap_btn = int(round(11 * scale))
                btn_w = int(round(50 * scale))
                btn_h = int(round(25 * scale))
                ah = int(round(56 * scale))
                min_aw = int(round(250 * scale))
                max_aw = min(int(round(360 * scale)), work_w)

                # 按实际字体与文本宽度动态计算紧凑宽度（不因固定大宽造成留白，也不整体缩小字体）
                t_flags = WinForms.TextFormatFlags.SingleLine | WinForms.TextFormatFlags.NoPadding
                w_line1 = int(WinForms.TextRenderer.MeasureText(title_text, title_font, Size(1000, 40), t_flags).Width)
                disp_name = device_label or full_name
                w_line2 = int(WinForms.TextRenderer.MeasureText(disp_name, dev_font, Size(1000, 40), t_flags).Width)
                chrome_w = pad_x + icon_px + gap_icon + gap_btn + btn_w + pad_x + int(round(6 * scale))
                aw = max(min_aw, min(max_aw, chrome_w + max(w_line1, w_line2)))

                ax = max(left + margin, min(right - aw - margin, right - aw - margin))
                ay = max(top + margin, min(bottom - ah - margin, bottom - ah - margin))

                form = WinForms.Form()
                form.Text = ALERT_WINDOW_TITLE
                form.FormBorderStyle = getattr(WinForms.FormBorderStyle, "None")
                form.ShowInTaskbar = False
                form.TopMost = True
                form.StartPosition = WinForms.FormStartPosition.Manual
                form.BackColor = Color.FromArgb(24, 27, 35) if is_dark else Color.FromArgb(252, 253, 255)
                form.Size = Size(aw, ah)
                form.Location = Point(ax, ay)

                # 1px 抗锯齿圆角外细边，确保 Win10/11 均精致清晰无毛刺
                border_col = Color.FromArgb(46, 52, 68) if is_dark else Color.FromArgb(216, 222, 232)
                def _on_form_paint(_s, pe):
                    paint_winforms_rounded_border(pe.Graphics, form.Width, form.Height, 8.0 * scale, border_col)
                form.Paint += _on_form_paint

                # 左侧：统一黑白实心设备图标（严格单色，不随电量等级变色）
                pil_ic = render_device_icon_pil(kind, size=icon_px, is_dark=is_dark)
                buf = io.BytesIO()
                pil_ic.save(buf, format="PNG")
                ms = MemoryStream(buf.getvalue())
                pic = WinForms.PictureBox()
                pic.Image = GdiImage.FromStream(ms)
                pic.SizeMode = WinForms.PictureBoxSizeMode.Zoom
                pic.BackColor = Color.Transparent
                pic.Size = Size(icon_px, icon_px)
                pic.Location = Point(pad_x, (ah - icon_px) // 2)
                form.Controls.Add(pic)

                # 右侧：紧凑圆角「知道了」按钮（带轻量悬停底色反馈）
                btn_bg_norm = Color.FromArgb(44, 49, 62) if is_dark else Color.FromArgb(236, 240, 246)
                btn_bg_hover = Color.FromArgb(56, 63, 79) if is_dark else Color.FromArgb(224, 230, 240)
                btn = WinForms.Label()
                btn.Text = "知道了"
                btn.TextAlign = ContentAlignment.MiddleCenter
                btn.ForeColor = Color.FromArgb(235, 240, 248) if is_dark else Color.FromArgb(30, 41, 59)
                btn.BackColor = btn_bg_norm
                btn.Font = btn_font
                btn.Size = Size(btn_w, btn_h)
                btn.Location = Point(aw - btn_w - pad_x, (ah - btn_h) // 2)
                btn.Cursor = WinForms.Cursors.Hand
                btn.Click += lambda _s, _e: self._close_alert_window()
                btn.MouseEnter += lambda _s, _e: setattr(btn, "BackColor", btn_bg_hover)
                btn.MouseLeave += lambda _s, _e: setattr(btn, "BackColor", btn_bg_norm)
                form.Controls.Add(btn)
                try:
                    apply_window_rounded_corners(int(btn.Handle.ToInt64()), radius_dip=6, scale=scale, force_region=True)
                except Exception:
                    pass

                text_x = pad_x + icon_px + gap_icon
                text_w = max(80, aw - text_x - btn_w - gap_btn - pad_x)

                # 第一行：三级提醒文案与状态色（浅色使用高对比清晰黄/橙/红，深色柔和明亮）
                if tier_lvl == 3:
                    t_col = Color.FromArgb(248, 113, 113) if is_dark else Color.FromArgb(220, 38, 38)
                elif tier_lvl == 2:
                    t_col = Color.FromArgb(251, 146, 60) if is_dark else Color.FromArgb(234, 88, 12)
                else:
                    t_col = Color.FromArgb(250, 204, 21) if is_dark else Color.FromArgb(180, 126, 0)

                line1_h = int(round(19 * scale))
                line2_h = int(round(18 * scale))
                line_gap = int(round(2 * scale))
                block_top = max(int(round(6 * scale)), (ah - (line1_h + line_gap + line2_h)) // 2)

                title_lbl = WinForms.Label()
                title_lbl.Text = title_text
                title_lbl.ForeColor = t_col
                title_lbl.BackColor = Color.Transparent
                title_lbl.Font = title_font
                title_lbl.AutoEllipsis = True
                title_lbl.Size = Size(text_w, line1_h)
                title_lbl.Location = Point(text_x, block_top)
                form.Controls.Add(title_lbl)

                # 第二行：完整标准设备名称（正常文字颜色；仅极端超长时优雅省略并支持悬停查看完整名）
                dev_lbl = WinForms.Label()
                dev_lbl.Text = disp_name
                dev_lbl.ForeColor = Color.FromArgb(232, 237, 245) if is_dark else Color.FromArgb(30, 41, 59)
                dev_lbl.BackColor = Color.Transparent
                dev_lbl.Font = dev_font
                dev_lbl.AutoEllipsis = True
                dev_lbl.Size = Size(text_w, line2_h)
                dev_lbl.Location = Point(text_x, block_top + line1_h + line_gap)
                form.Controls.Add(dev_lbl)

                if disp_name != full_name or w_line2 > text_w:
                    tt = WinForms.ToolTip()
                    tt.AutoPopDelay = 5000
                    tt.InitialDelay = 250
                    tt.ShowAlways = True
                    tt.SetToolTip(dev_lbl, full_name)
                    tt.SetToolTip(form, full_name)

                hwnd = int(form.Handle.ToInt64())
                user32 = ctypes.windll.user32
                GWL_EXSTYLE = -20
                ex = user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE)
                ex |= 0x00000008 | 0x08000000 | 0x00000080  # TOPMOST | NOACTIVATE | TOOLWINDOW
                user32.SetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE, ex)
                apply_window_rounded_corners(hwnd, radius_dip=8, scale=scale)

                SWP_NOACTIVATE = 0x0010
                SWP_SHOWWINDOW = 0x0040
                slide_offset = int(round(10 * scale)) if anim_on else 0
                start_y = ay + slide_offset
                form.Opacity = 0.0 if anim_on else 1.0
                user32.ShowWindow(wintypes.HWND(hwnd), 4)
                user32.SetWindowPos(
                    wintypes.HWND(hwnd),
                    wintypes.HWND(-1),
                    ax,
                    start_y,
                    aw,
                    ah,
                    SWP_NOACTIVATE | SWP_SHOWWINDOW,
                )
                if anim_on:
                    _animate_form_transition(form, 0.0, 1.0, 220, start_pos=(ax, start_y), end_pos=(ax, ay))

                with self._alert_lock:
                    self._alert_window = form

                timer = threading.Timer(ALERT_DURATION_SEC, self._close_alert_window)
                timer.daemon = True
                with self._alert_lock:
                    self._alert_timer = timer
                timer.start()
            except Exception:
                pass

        try:
            from System import Action

            if getattr(native_main, "InvokeRequired", False):
                native_main.BeginInvoke(Action(_create_on_ui_thread))
            else:
                _create_on_ui_thread()
        except Exception:
            pass

    def _dispatch_alert(
        self,
        device_label: str,
        percent: int,
        kind: str,
        is_test: bool = False,
        device_id: Optional[str] = None,
        full_device_name: str = "",
    ) -> None:
        if self.cfg.sound_enabled:
            threading.Thread(target=play_alert_sound, args=(self.cfg.sound_name,), daemon=True).start()
        if self.cfg.popup_alert_enabled or is_test:
            threading.Thread(
                target=self._show_mini_alert,
                args=(device_label, percent, kind, is_test, device_id, full_device_name),
                daemon=True,
            ).start()
        if self.cfg.windows_notify_enabled and self._tray is not None:
            try:
                _lvl, tier_title = self._resolve_alert_tier(int(percent), device_id=device_id)
                notify_name = full_device_name or device_label
                self._tray.notify(f"{notify_name} · 剩余电量 {percent}%", f"{APP_NAME} · {tier_title}")
            except Exception:
                pass

    def test_low_battery(self) -> None:
        dev, _name = self._pick_floating_device()
        kind = dev.kind if dev else KIND_MOUSE
        pref = get_device_pref(self.cfg, dev.device_id) if dev else None
        disp_name, full_name = format_alert_device_name(dev, alias=(pref.alias if pref else ""))
        self._dispatch_alert(
            disp_name,
            15,
            kind,
            is_test=True,
            device_id=(dev.device_id if dev else None),
            full_device_name=full_name,
        )

    def quit_app(self) -> None:
        self._stop_event.set()
        self._close_alert_window()
        self.floating_widget.close()
        self.manager.stop()
        if self._tray is not None:
            try:
                self._tray.stop()
            except Exception:
                pass
        if self.settings_window is not None:
            try:
                self.settings_window.destroy()
            except Exception:
                pass
        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass

    # ================= 后台轮询与唤醒监测 =================

    def _poll_once(self) -> None:
        devices = self.manager.poll()
        self.devices = devices
        for d in devices:
            self._known_devices[d.device_id] = d
        self._last_poll_ts = time.time()
        self._push_state_to_ui()
        self._update_tray_visual()
        self._sync_floating_widget()
        self._check_low_batteries(devices)

    def _poll_loop(self) -> None:
        # 启动后立即执行首轮扫描
        self._poll_once()
        while not self._stop_event.is_set():
            interval = max(10, int(self.cfg.poll_interval_sec))
            self._stop_event.wait(interval)
            if self._stop_event.is_set():
                break
            if self.cfg.auto_monitor:
                self._poll_once()

    def _wakeup_watch_loop(self) -> None:
        while not self._stop_event.is_set():
            pos = _get_cursor_pos()
            if pos != self._last_cursor:
                self._last_cursor = pos
                if self.cfg.auto_monitor and any(
                    d.kind == KIND_MOUSE and d.connected and (d.asleep or d.percent is None)
                    for d in self.devices
                ):
                    self._poll_once()
            self._stop_event.wait(1.8)

    def _check_low_batteries(self, devices: list[DeviceBattery]) -> None:
        triggered = evaluate_tiered_alerts(devices, self.cfg, self._alerted_tiers, self._last_alert_ts)
        if not triggered:
            return
        dev, _tier = min(triggered, key=lambda pair: int(pair[0].percent or 100))
        pref = get_device_pref(self.cfg, dev.device_id)
        disp_name, full_name = format_alert_device_name(dev, alias=pref.alias)
        self._dispatch_alert(
            disp_name,
            int(dev.percent or 0),
            dev.kind,
            is_test=False,
            device_id=dev.device_id,
            full_device_name=full_name,
        )

    def _update_tray_visual(self) -> None:
        """托盘栏始终使用动态矢量电池图标，仅在电量或设备状态实际变化时重绘图标与提示文本。"""
        if self._tray is None:
            return
        try:
            td, _name = self._pick_floating_device()
            rules = self.cfg.tier_rules if isinstance(self.cfg.tier_rules, list) else []
            t1 = int(rules[0]["threshold"]) if len(rules) > 0 else 30
            t2 = int(rules[1]["threshold"]) if len(rules) > 1 else 20
            t3 = int(rules[2]["threshold"]) if len(rules) > 2 else 10
            icon_key = (
                (td.percent, bool(td.charging), bool(td.connected), t1, t2, t3)
                if td is not None
                else (None, False, False, t1, t2, t3)
            )
            if icon_key != self._last_tray_icon_key:
                self._last_tray_icon_key = icon_key
                self._tray.icon = draw_battery_icon(
                    size=64,
                    percent=icon_key[0],
                    charging=icon_key[1],
                    connected=icon_key[2],
                    low_t1=t1,
                    low_t2=t2,
                    low_t3=t3,
                )

            if not self.devices:
                next_title = f"{APP_NAME}（未检测到外设）"
            else:
                lines = []
                for d in self.devices[:3]:
                    pref = get_device_pref(self.cfg, d.device_id)
                    nm = pref.alias or d.name
                    sub = format_device_subtitle(
                        d.connection_mode, d.connected, d.online, d.asleep, d.charging, d.full, d.percent
                    )
                    if d.percent is not None:
                        lines.append(f"{nm}: {d.percent}% ({sub})" if sub else f"{nm}: {d.percent}%")
                    else:
                        lines.append(f"{nm}: — ({sub})" if sub else f"{nm}: —")
                if len(self.devices) > 3:
                    lines.append(f"…共 {len(self.devices)} 台外设")
                next_title = "\n".join(lines)[:124]

            if next_title != self._last_tray_title:
                self._last_tray_title = next_title
                self._tray.title = next_title
        except Exception:
            pass

    def _start_tray(self) -> None:
        tray_menu = pystray.Menu(
            pystray.MenuItem(f"打开 {APP_NAME}", lambda _i, _m: self.show_main_window(), default=True),
            pystray.MenuItem("设置", lambda _i, _m: self.open_settings_window("general")),
            pystray.MenuItem(
                "检查更新",
                lambda _i, _m: (self.open_settings_window("about"), self.check_updates(silent=False)),
            ),
            pystray.MenuItem("测试低电量弹窗", lambda _i, _m: self.test_low_battery()),
            pystray.MenuItem("导出设备诊断报告", lambda _i, _m: threading.Thread(target=self.export_diagnostics, daemon=True).start()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出程序", lambda _i, _m: self.quit_app()),
        )
        self._tray = pystray.Icon(
            APP_TRAY_NAME,
            draw_battery_icon(size=64, percent=None, charging=False, connected=False),
            APP_NAME,
            tray_menu,
        )
        threading.Thread(target=self._tray.run, daemon=True).start()

    def _on_window_loaded(self) -> None:
        for _ in range(15):
            self.hwnd = self._find_hwnd_for(self.window, WINDOW_TITLE)
            if self.hwnd:
                break
            time.sleep(0.05)

        if self.hwnd:
            _apply_window_chrome(self.hwnd, self._effective_theme() == "dark")
            # WinForms frameless 模式初始化时会裁掉非客户区尺寸，此时窗口 Opacity=0，恢复精确目标尺寸并校准居中完全不可见
            work, scale = _get_window_monitor_work_area_and_scale(self.hwnd)
            target_w = int(round(max(580, int(self.cfg.width or MAIN_DEFAULT_SIZE[0])) * scale))
            target_h = int(round(max(380, int(self.cfg.height or MAIN_DEFAULT_SIZE[1])) * scale))
            tpx, tpy, tpw, tph = _compute_centered_rect(work, target_w, target_h)
            _set_window_pos(self.hwnd, tpx, tpy, tpw, tph, topmost=self.cfg.topmost)
            apply_window_rounded_corners(self.hwnd, radius_dip=10, scale=scale)
            _attach_rounded_resize_hook(self.window, radius_dip=10)
            if not self._allow_show:
                _set_form_visibility(self.window, visible=False, opacity=0.0)

        self._push_state_to_ui()
        if self._allow_show:
            # 兜底定时器：确保最迟 0.8s 显现，正常情况下由前端 ui_ready() 在首帧就绪时立刻显现
            threading.Timer(0.8, self._reveal_main_if_needed).start()
        self._start_tray()
        self._sync_floating_widget()
        threading.Thread(target=self._poll_loop, daemon=True).start()
        threading.Thread(target=self._wakeup_watch_loop, daemon=True).start()
        threading.Thread(target=self._show_event_loop, daemon=True).start()
        if self.cfg.auto_check_updates:
            threading.Timer(12.0, lambda: self.check_updates(silent=True)).start()

    def _show_event_loop(self) -> None:
        if sys.platform != "win32":
            return
        k32 = ctypes.windll.kernel32
        ev_new = k32.CreateEventW(None, False, False, SHOW_EVENT_NAME)
        ev_old = k32.CreateEventW(None, False, False, LEGACY_SHOW_EVENT_NAME)
        handles = [h for h in (ev_new, ev_old) if h]
        if not handles:
            return
        arr = (wintypes.HANDLE * len(handles))(*handles)
        try:
            while not self._stop_event.is_set():
                res = k32.WaitForMultipleObjects(len(handles), arr, False, 500)
                if 0 <= res < len(handles):
                    self.show_main_window()
        finally:
            for h in handles:
                k32.CloseHandle(wintypes.HANDLE(h))

    def run(self) -> None:
        _install_flicker_free_patch()
        ico_path = ensure_app_ico()
        log_x, log_y, log_w, log_h = self._compute_main_initial_logical_bounds()
        self.window = webview.create_window(
            title=WINDOW_TITLE,
            url=UI_MAIN_HTML.as_uri(),
            width=log_w,
            height=log_h,
            x=log_x,
            y=log_y,
            min_size=(580, 380),
            frameless=True,
            easy_drag=False,
            transparent=False,
            background_color=self._theme_bg_hex(),
            hidden=self.start_hidden,
            on_top=self.cfg.topmost,
            resizable=True,
            js_api=_JsApi(self, "main"),
        )
        webview.start(func=self._on_window_loaded, gui="edgechromium", icon=ico_path, debug=False)


class _JsApi:
    """暴露给前端主窗口与设置窗口的统一安全 API 桥。"""

    def __init__(self, app: MouseBatteryApp, target: str) -> None:
        self._app = app
        self._target = target

    def get_initial_state(self) -> dict[str, Any]:
        return self._app._build_state_dict()

    def ui_ready(self) -> None:
        self._app.on_ui_ready(self._target)

    def begin_drag(self, sx: int, sy: int) -> None:
        self._app.begin_drag(self._target, sx, sy)

    def drag_move(self, sx: int, sy: int) -> None:
        self._app.drag_move(self._target, sx, sy)

    def end_drag(self) -> None:
        self._app.end_drag(self._target)

    def minimize_window(self) -> None:
        self._app.minimize_window(self._target)

    def toggle_maximize(self) -> None:
        self._app.toggle_maximize(self._target)

    def close_window(self) -> None:
        if self._target == "settings":
            self._app.close_settings_window()
        else:
            self._app.close_main_window()

    def open_settings(self, section: str = "general") -> None:
        self._app.open_settings_window(section or "general")

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        return self._app.update_settings(patch)

    def update_device_pref(self, device_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        return self._app.update_device_pref(device_id, updates)

    def reorder_devices(self, device_ids: list[str]) -> dict[str, Any]:
        return self._app.reorder_devices(device_ids)

    def move_device_order(self, device_id: str, direction: int) -> dict[str, Any]:
        return self._app.move_device_order(device_id, direction)

    def refresh_now(self) -> None:
        self._app.refresh_now()

    def test_low_battery(self) -> None:
        self._app.test_low_battery()

    def preview_sound(self, sound_name: str = "default") -> None:
        self._app.preview_sound(sound_name)

    def export_diagnostics(self) -> dict[str, Any]:
        return self._app.export_diagnostics()

    def read_doc_file(self, doc_name: str) -> dict[str, Any]:
        return self._app.read_doc_file(doc_name)

    def open_project_folder(self) -> None:
        self._app.open_project_folder()

    def open_external_url(self, url: str) -> bool:
        return self._app.open_external_url(url)

    def check_updates(self, silent: bool = False) -> dict[str, Any]:
        return self._app.check_updates(silent=bool(silent))

    def dismiss_update_notice(self) -> dict[str, Any]:
        return self._app.dismiss_update_notice()

    def download_and_install_update(self) -> dict[str, Any]:
        return self._app.download_and_install_update()

    def cancel_update_download(self) -> None:
        self._app.cancel_update_download()

    def quit_app(self) -> None:
        self._app.quit_app()


def _activate_existing_window() -> None:
    if sys.platform != "win32":
        return
    k32 = ctypes.windll.kernel32
    for ev_name in (SHOW_EVENT_NAME, LEGACY_SHOW_EVENT_NAME):
        ev = k32.OpenEventW(0x0002, False, ev_name)
        if ev:
            k32.SetEvent(wintypes.HANDLE(ev))
            k32.CloseHandle(wintypes.HANDLE(ev))
            return
    user32 = ctypes.windll.user32
    for title in (WINDOW_TITLE, "外设电量"):
        hwnd = user32.FindWindowW(None, title)
        if hwnd:
            user32.ShowWindow(wintypes.HWND(hwnd), 9)
            user32.SetForegroundWindow(wintypes.HWND(hwnd))
            return


def _acquire_single_instance() -> Optional[list[int]]:
    """同时获取新旧单实例互斥量，确保 BattDock 与旧版 VGNMouseBattery 绝不同时运行。"""
    if sys.platform != "win32":
        return [1]
    k32 = ctypes.windll.kernel32
    acquired: list[int] = []
    for name in (MUTEX_NAME, LEGACY_MUTEX_NAME):
        m = k32.CreateMutexW(None, False, name)
        if k32.GetLastError() == 183:
            if m:
                k32.CloseHandle(m)
            for h in acquired:
                k32.CloseHandle(h)
            return None
        if m:
            acquired.append(m)
    return acquired


def _schedule_legacy_cleanup() -> None:
    """从旧版 VGNMouseBattery 升级迁移后，延迟清理同目录下的临时旧版桥接程序。"""
    if not IS_FROZEN:
        return
    cur_exe = Path(sys.executable).resolve()
    legacy_exe = cur_exe.with_name(LEGACY_EXE_NAME)
    if legacy_exe == cur_exe or not legacy_exe.is_file():
        return

    def _clean() -> None:
        for _ in range(10):
            try:
                if legacy_exe.exists():
                    legacy_exe.unlink()
                break
            except OSError:
                time.sleep(0.5)

    threading.Timer(2.0, _clean).start()


def main() -> None:
    start_hidden = "--background" in sys.argv
    mutexes = _acquire_single_instance()
    if mutexes is None:
        if not start_hidden:
            _activate_existing_window()
        return
    try:
        if IS_FROZEN:
            migrate_legacy_autostart()
            if "--cleanup-legacy-exe" in sys.argv:
                _schedule_legacy_cleanup()
        app = MouseBatteryApp(start_hidden=start_hidden)
        app.run()
    finally:
        if sys.platform == "win32":
            for h in mutexes:
                ctypes.windll.kernel32.CloseHandle(h)


if __name__ == "__main__":
    main()
