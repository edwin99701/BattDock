"""外设电量监控工具：多品牌统一适配 + 主窗口/设置窗口双窗口 + 桌面悬浮窗 + Win10/11 全兼容。"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import threading
import time
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
    RESOURCE_DIR,
    AppConfig,
    FloatingWidgetConfig,
    get_device_pref,
    get_device_tiers,
    get_floating_config,
    is_autostart_enabled,
    load_config,
    normalize_tiers,
    resolve_effective_theme,
    save_config,
    set_autostart,
    set_device_pref,
)
from floating_widget import (
    DesktopFloatingWidget,
    EDGE_MARGIN,
    _try_win11_round_corners,
    draw_battery_icon,
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

if sys.platform == "win32":
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

WINDOW_TITLE = "外设电量"
SETTINGS_WINDOW_TITLE = "外设电量 - 设置"
ALERT_WINDOW_TITLE = "外设电量低提醒"

MAIN_DEFAULT_SIZE = (760, 480)
SETTINGS_DEFAULT_SIZE = (840, 742)
ALERT_SIZE = (296, 68)
ALERT_DURATION_SEC = 5.0


# ================= Windows 10 / 11 通用窗口辅助（不依赖 Win11 专属特效） =================

class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def _get_tray_work_area() -> tuple[int, int, int, int]:
    """获取系统托盘所在显示器的工作区 (left, top, right, bottom)，适配多显示器与不同 DPI。"""
    user32 = ctypes.windll.user32
    try:
        tray_hwnd = user32.FindWindowW("Shell_TrayWnd", None)
        if tray_hwnd:
            hmon = user32.MonitorFromWindow(wintypes.HWND(tray_hwnd), 2)
            if hmon:
                info = MONITORINFO()
                info.cbSize = ctypes.sizeof(MONITORINFO)
                if user32.GetMonitorInfoW(wintypes.HMONITOR(hmon), ctypes.byref(info)):
                    r = info.rcWork
                    return r.left, r.top, r.right, r.bottom
    except Exception:
        pass
    rect = wintypes.RECT()
    if user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
        return rect.left, rect.top, rect.right, rect.bottom
    return 0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1) - 48


def _get_work_area_for_window(hwnd: int) -> tuple[int, int, int, int]:
    if hwnd:
        user32 = ctypes.windll.user32
        try:
            hmon = user32.MonitorFromWindow(wintypes.HWND(hwnd), 2)
            if hmon:
                info = MONITORINFO()
                info.cbSize = ctypes.sizeof(MONITORINFO)
                if user32.GetMonitorInfoW(wintypes.HMONITOR(hmon), ctypes.byref(info)):
                    r = info.rcWork
                    return r.left, r.top, r.right, r.bottom
        except Exception:
            pass
    return _get_tray_work_area()


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


def _apply_window_chrome(hwnd: int, is_dark: bool) -> None:
    """Windows 10/11 通用轻量窗口装饰：能力检测式启用 Win11 圆角与深浅色边框，Win10 自动安全降级。"""
    if sys.platform != "win32" or not hwnd:
        return
    try:
        dwmapi = ctypes.windll.dwmapi
        dark_val = ctypes.c_int(1 if is_dark else 0)
        dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), 20, ctypes.byref(dark_val), ctypes.sizeof(dark_val))
    except Exception:
        pass
    _try_win11_round_corners(hwnd)


def ensure_app_ico() -> Optional[str]:
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
    mode = (dev.connection_mode or "").strip()
    if mode in ("2.4G", "休眠", "检测中", ""):
        if dev.brand == "Logitech":
            return "LIGHTSPEED 无线连接"
        return "2.4GHz 无线连接"
    if mode == "有线":
        return "USB 有线连接"
    if "蓝牙" in mode:
        return "蓝牙连接"
    return mode


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

        self._alert_window = None
        self._alert_timer: Optional[threading.Timer] = None
        self._alert_lock = threading.Lock()
        self._tray: Optional[pystray.Icon] = None
        self._stop_event = threading.Event()
        self._alerted_tiers: dict[str, set[int]] = {}
        self._last_alert_ts: dict[str, float] = {}
        self._last_cursor = _get_cursor_pos()

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
            d["display_name"] = display_name
            d["connection_label"] = _connection_label(dev)
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
        visible = [d for d in self.devices if not get_device_pref(self.cfg, d.device_id).hidden]
        pool = visible or self.devices
        with_pct = [d for d in pool if d.connected and d.percent is not None]
        if with_pct:
            best = min(with_pct, key=lambda d: int(d.percent or 100))
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

        return {
            "app_version": APP_VERSION,
            "app_author": APP_AUTHOR,
            "effective_theme": self._effective_theme(),
            "autostart": is_autostart_enabled(),
            "config": asdict(self.cfg),
            "devices": visible_devices,
            "all_devices": all_devices,
            "updated_str": updated_str,
            "auto_monitor": bool(self.cfg.auto_monitor),
            "main_maximized": self._main_maximized,
            "settings_maximized": self._settings_maximized,
        }

    def _push_state_to_ui(self) -> None:
        payload = json.dumps(self._build_state_dict(), ensure_ascii=False)
        for win in (self.window, self.settings_window):
            if win is not None:
                try:
                    win.evaluate_js(f"window.applyState && applyState({payload});")
                except Exception:
                    pass

    def _sync_floating_widget(self) -> None:
        fcfg = get_floating_config(self.cfg)
        dev, name = self._pick_floating_device()
        self.floating_widget.sync(fcfg, dev, name, self._effective_theme())

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

    def show_main_window(self) -> None:
        if self.window is None:
            return
        self._allow_show = True
        try:
            self.window.show()
            self.window.restore()
        except Exception:
            pass
        if self.hwnd:
            _apply_window_chrome(self.hwnd, self._effective_theme() == "dark")
            user32 = ctypes.windll.user32
            user32.ShowWindow(wintypes.HWND(self.hwnd), 9)
            user32.SetForegroundWindow(wintypes.HWND(self.hwnd))
        self._push_state_to_ui()

    def open_settings_window(self, section: str = "alerts") -> None:
        """打开或前置独立设置窗口（820 × 560，默认展示指定分页）。"""
        if self.settings_window is not None:
            try:
                self.settings_window.show()
                self.settings_window.restore()
                if self.settings_hwnd:
                    _apply_window_chrome(self.settings_hwnd, self._effective_theme() == "dark")
                    ctypes.windll.user32.ShowWindow(wintypes.HWND(self.settings_hwnd), 9)
                    ctypes.windll.user32.SetForegroundWindow(wintypes.HWND(self.settings_hwnd))
                self.settings_window.evaluate_js(f"window.switchSection && switchSection({json.dumps(section)});")
                self._push_state_to_ui()
                return
            except Exception:
                self.settings_window = None
                self.settings_hwnd = 0

        url = f"{UI_SETTINGS_HTML.as_uri()}#{section}"
        win = webview.create_window(
            title=SETTINGS_WINDOW_TITLE,
            url=url,
            width=SETTINGS_DEFAULT_SIZE[0],
            height=SETTINGS_DEFAULT_SIZE[1],
            min_size=(680, 460),
            frameless=True,
            easy_drag=False,
            transparent=False,
            resizable=True,
            js_api=_JsApi(self, "settings"),
        )
        self.settings_window = win

        def _on_settings_loaded():
            for _ in range(15):
                self.settings_hwnd = self._find_hwnd_for(win, SETTINGS_WINDOW_TITLE)
                if self.settings_hwnd:
                    break
                time.sleep(0.05)
            if self.settings_hwnd:
                _apply_window_chrome(self.settings_hwnd, self._effective_theme() == "dark")
            self._push_state_to_ui()

        def _on_settings_closed():
            self.settings_window = None
            self.settings_hwnd = 0
            self._settings_maximized = False

        win.events.loaded += _on_settings_loaded
        win.events.closed += _on_settings_closed

    def close_settings_window(self) -> None:
        win = self.settings_window
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass
        self.settings_window = None
        self.settings_hwnd = 0
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
        if target == "settings":
            self._settings_maximized = not is_max
        else:
            self._main_maximized = not is_max
        self._push_state_to_ui()

    def close_main_window(self) -> None:
        """按「关闭窗口时最小化至托盘」设置决定隐藏到托盘还是退出程序。"""
        if self.cfg.close_to_tray:
            self._allow_show = False
            if self.window is not None:
                try:
                    self.window.hide()
                except Exception:
                    pass
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
            "alerts_master_enabled",
            "custom_alerts_enabled",
            "popup_alert_enabled",
            "windows_notify_enabled",
            "sound_enabled",
            "repeat_alert_enabled",
            "show_progress_bar",
            "show_device_icon",
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
        if self.hwnd:
            _apply_window_chrome(self.hwnd, is_dark)
            if "topmost" in patch:
                wx, wy, ww, wh = _get_window_rect(self.hwnd)
                _set_window_pos(self.hwnd, wx, wy, ww, wh, topmost=self.cfg.topmost)
        if self.settings_hwnd:
            _apply_window_chrome(self.settings_hwnd, is_dark)

        self._push_state_to_ui()
        self._update_tray_visual()
        self._sync_floating_widget()
        return self._build_state_dict()

    def update_device_pref(self, device_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """更新单台设备独立配置（重命名、隐藏、暂停监控、排序、独立阈值）。"""
        if device_id and isinstance(updates, dict):
            set_device_pref(self.cfg, str(device_id), updates)
            self._alerted_tiers.pop(str(device_id), None)
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
            for pos, did in enumerate(ids):
                set_device_pref(self.cfg, did, {"order": pos * 10})
            save_config(self.cfg)
            self._push_state_to_ui()
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

    def refresh_now(self) -> None:
        threading.Thread(target=self._poll_once, daemon=True).start()

    # ================= 原生 WinForms 极速最高置顶低电量迷你弹窗 & 系统通知 =================

    def _close_alert_window(self) -> None:
        with self._alert_lock:
            if self._alert_timer is not None:
                self._alert_timer.cancel()
                self._alert_timer = None
            alert_form = self._alert_window
            self._alert_window = None
        if alert_form is not None:
            try:
                from System import Action

                def _do_close():
                    try:
                        if not alert_form.IsDisposed:
                            alert_form.Close()
                            alert_form.Dispose()
                    except Exception:
                        pass

                if getattr(alert_form, "InvokeRequired", False):
                    alert_form.BeginInvoke(Action(_do_close))
                else:
                    _do_close()
            except Exception:
                pass

    def _show_mini_alert(
        self,
        device_name: str,
        percent: int,
        kind: str = KIND_MOUSE,
        is_test: bool = False,
    ) -> None:
        """原生 WinForms 极速纯色无边框置顶迷你弹窗（0ms 响应、不抢游戏焦点、最高置顶、停留 5 秒）。"""
        self._close_alert_window()
        pct = max(0, min(100, int(percent)))
        kind_label = _kind_cn(kind)

        native_main = getattr(self.window, "native", None) if self.window is not None else None
        if native_main is None:
            return

        left, top, right, bottom = _get_tray_work_area()
        scale = _get_dpi_scale(self.hwnd) if self.hwnd else 1.0
        margin = int(round(EDGE_MARGIN * scale))
        aw = int(round(ALERT_SIZE[0] * scale))
        ah = int(round(ALERT_SIZE[1] * scale))
        ax = max(left + margin, right - aw - margin)
        ay = max(top + margin, bottom - ah - margin)

        def _create_on_ui_thread() -> None:
            try:
                import io
                import System.Windows.Forms as WinForms
                from System.Drawing import Color, ContentAlignment, Font, FontStyle, Image as GdiImage, Point, Size
                from System.IO import MemoryStream

                form = WinForms.Form()
                form.Text = ALERT_WINDOW_TITLE
                form.FormBorderStyle = getattr(WinForms.FormBorderStyle, "None")
                form.ShowInTaskbar = False
                form.TopMost = True
                form.StartPosition = WinForms.FormStartPosition.Manual
                form.BackColor = Color.FromArgb(24, 27, 34)
                form.Size = Size(aw, ah)
                form.Location = Point(ax, ay)

                icon_px = int(round(30 * scale))
                pil_ic = draw_battery_icon(size=icon_px, percent=pct, charging=False, connected=True)
                buf = io.BytesIO()
                pil_ic.save(buf, format="PNG")
                ms = MemoryStream(buf.getvalue())
                pic = WinForms.PictureBox()
                pic.Image = GdiImage.FromStream(ms)
                pic.SizeMode = WinForms.PictureBoxSizeMode.Zoom
                pic.BackColor = Color.Transparent
                pic.Size = Size(icon_px, icon_px)
                pic.Location = Point(int(round(12 * scale)), (ah - icon_px) // 2)
                form.Controls.Add(pic)

                btn_w = int(round(50 * scale))
                btn_h = int(round(24 * scale))
                btn = WinForms.Label()
                btn.Text = "知道了"
                btn.TextAlign = ContentAlignment.MiddleCenter
                btn.ForeColor = Color.FromArgb(235, 240, 248)
                btn.BackColor = Color.FromArgb(44, 49, 62)
                btn.Font = Font("Microsoft YaHei UI", 8.5, FontStyle.Regular)
                btn.Size = Size(btn_w, btn_h)
                btn.Location = Point(aw - btn_w - int(round(10 * scale)), (ah - btn_h) // 2)
                btn.Cursor = WinForms.Cursors.Hand
                btn.Click += lambda _s, _e: self._close_alert_window()
                form.Controls.Add(btn)

                text_x = int(round(48 * scale))
                text_w = aw - text_x - btn_w - int(round(16 * scale))

                title_lbl = WinForms.Label()
                title_lbl.Text = f"{kind_label}电量偏低 · 剩余 {pct}%" + (" (测试)" if is_test else "")
                title_lbl.ForeColor = Color.FromArgb(252, 165, 165) if pct <= 10 else Color.FromArgb(251, 146, 60)
                title_lbl.BackColor = Color.Transparent
                title_lbl.Font = Font("Microsoft YaHei UI", 9.0, FontStyle.Bold)
                title_lbl.AutoEllipsis = True
                title_lbl.Size = Size(text_w, int(round(20 * scale)))
                title_lbl.Location = Point(text_x, int(round(13 * scale)))
                form.Controls.Add(title_lbl)

                dev_lbl = WinForms.Label()
                dev_lbl.Text = device_name
                dev_lbl.ForeColor = Color.FromArgb(235, 240, 248)
                dev_lbl.BackColor = Color.Transparent
                dev_lbl.Font = Font("Microsoft YaHei UI", 8.5, FontStyle.Regular)
                dev_lbl.AutoEllipsis = True
                dev_lbl.Size = Size(text_w, int(round(19 * scale)))
                dev_lbl.Location = Point(text_x, int(round(35 * scale)))
                form.Controls.Add(dev_lbl)

                hwnd = int(form.Handle.ToInt64())
                user32 = ctypes.windll.user32
                GWL_EXSTYLE = -20
                ex = user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE)
                ex |= 0x00000008 | 0x08000000 | 0x00000080  # TOPMOST | NOACTIVATE | TOOLWINDOW
                user32.SetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE, ex)
                _try_win11_round_corners(hwnd)

                SWP_NOACTIVATE = 0x0010
                SWP_SHOWWINDOW = 0x0040
                user32.ShowWindow(wintypes.HWND(hwnd), 4)
                user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(-1), ax, ay, aw, ah, SWP_NOACTIVATE | SWP_SHOWWINDOW)

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

    def _dispatch_alert(self, device_name: str, percent: int, kind: str, is_test: bool = False) -> None:
        if self.cfg.sound_enabled:
            threading.Thread(target=play_alert_sound, args=(self.cfg.sound_name,), daemon=True).start()
        if self.cfg.popup_alert_enabled or is_test:
            threading.Thread(
                target=self._show_mini_alert,
                args=(device_name, percent, kind, is_test),
                daemon=True,
            ).start()
        if self.cfg.windows_notify_enabled and self._tray is not None:
            try:
                tag = "（测试）" if is_test else ""
                self._tray.notify(f"{device_name} 剩余电量 {percent}%", f"外设电量偏低{tag}")
            except Exception:
                pass

    def test_low_battery(self) -> None:
        dev, name = self._pick_floating_device()
        kind = dev.kind if dev else KIND_MOUSE
        self._dispatch_alert(name if dev else "VGN Dragonfly F2 Pro Max", 15, kind, is_test=True)

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
        self._dispatch_alert(pref.alias or dev.name, int(dev.percent or 0), dev.kind, is_test=False)

    def _update_tray_visual(self) -> None:
        if self._tray is None:
            return
        try:
            td, _name = self._pick_floating_device()
            if td is not None:
                self._tray.icon = draw_battery_icon(
                    size=64,
                    percent=td.percent,
                    charging=td.charging,
                    connected=td.connected,
                )
            else:
                self._tray.icon = draw_battery_icon(size=64, percent=None, charging=False, connected=False)

            if not self.devices:
                self._tray.title = "外设电量（未检测到外设）"
            else:
                lines = []
                for d in self.devices[:3]:
                    pref = get_device_pref(self.cfg, d.device_id)
                    nm = pref.alias or d.name
                    if d.percent is not None:
                        st = "已充满" if d.full else ("充电中" if d.charging else ("休眠" if d.asleep else d.connection_mode))
                        lines.append(f"{nm}: {d.percent}% ({st})")
                    else:
                        lines.append(f"{nm}: {'休眠' if d.asleep else '未知'}")
                if len(self.devices) > 3:
                    lines.append(f"…共 {len(self.devices)} 台外设")
                self._tray.title = "\n".join(lines)[:124]
        except Exception:
            pass

    def _start_tray(self) -> None:
        tray_menu = pystray.Menu(
            pystray.MenuItem("打开主窗口", lambda _i, _m: self.show_main_window(), default=True),
            pystray.MenuItem("设置", lambda _i, _m: self.open_settings_window("general")),
            pystray.MenuItem("测试低电量弹窗", lambda _i, _m: self.test_low_battery()),
            pystray.MenuItem("导出设备诊断报告", lambda _i, _m: threading.Thread(target=self.export_diagnostics, daemon=True).start()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出程序", lambda _i, _m: self.quit_app()),
        )
        self._tray = pystray.Icon(
            "VGNMouseBattery",
            draw_battery_icon(size=64, percent=None, charging=False, connected=False),
            "外设电量监控",
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
            if not self._allow_show and self.window is not None:
                try:
                    self.window.hide()
                except Exception:
                    pass

        self._push_state_to_ui()
        self._start_tray()
        self._sync_floating_widget()
        threading.Thread(target=self._poll_loop, daemon=True).start()
        threading.Thread(target=self._wakeup_watch_loop, daemon=True).start()
        threading.Thread(target=self._show_event_loop, daemon=True).start()

    def _show_event_loop(self) -> None:
        if sys.platform != "win32":
            return
        k32 = ctypes.windll.kernel32
        ev = k32.CreateEventW(None, False, False, "Local\\VGNMouseBatteryMonitor_ShowEvent")
        if not ev:
            return
        try:
            while not self._stop_event.is_set():
                if k32.WaitForSingleObject(wintypes.HANDLE(ev), 500) == 0:
                    self.show_main_window()
        finally:
            k32.CloseHandle(wintypes.HANDLE(ev))

    def run(self) -> None:
        ico_path = ensure_app_ico()
        self.window = webview.create_window(
            title=WINDOW_TITLE,
            url=UI_MAIN_HTML.as_uri(),
            width=max(580, int(self.cfg.width or MAIN_DEFAULT_SIZE[0])),
            height=max(380, int(self.cfg.height or MAIN_DEFAULT_SIZE[1])),
            min_size=(580, 380),
            frameless=True,
            easy_drag=False,
            transparent=False,
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

    def open_settings(self, section: str = "alerts") -> None:
        self._app.open_settings_window(section)

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        return self._app.update_settings(patch)

    def update_device_pref(self, device_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        return self._app.update_device_pref(device_id, updates)

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

    def quit_app(self) -> None:
        self._app.quit_app()


def _activate_existing_window() -> None:
    if sys.platform != "win32":
        return
    k32 = ctypes.windll.kernel32
    ev = k32.OpenEventW(0x0002, False, "Local\\VGNMouseBatteryMonitor_ShowEvent")
    if ev:
        k32.SetEvent(wintypes.HANDLE(ev))
        k32.CloseHandle(wintypes.HANDLE(ev))
        return
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, WINDOW_TITLE)
    if hwnd:
        user32.ShowWindow(wintypes.HWND(hwnd), 9)
        user32.SetForegroundWindow(wintypes.HWND(hwnd))


def _acquire_single_instance() -> Optional[int]:
    if sys.platform != "win32":
        return 1
    kernel32 = ctypes.windll.kernel32
    mutex = kernel32.CreateMutexW(None, False, "Local\\VGNMouseBatteryMonitor_SingleInstance")
    if kernel32.GetLastError() == 183:
        if mutex:
            kernel32.CloseHandle(mutex)
        return None
    return mutex


def main() -> None:
    start_hidden = "--background" in sys.argv
    mutex = _acquire_single_instance()
    if mutex is None:
        if not start_hidden:
            _activate_existing_window()
        return
    try:
        app = MouseBatteryApp(start_hidden=start_hidden)
        app.run()
    finally:
        if sys.platform == "win32" and mutex:
            ctypes.windll.kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    main()
