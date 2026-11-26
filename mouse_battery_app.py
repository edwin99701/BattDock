"""通用 Windows 无线外设电量监控工具：多品牌统一适配 + 系统托盘 + Windows 11 原生毛玻璃主窗口。"""

from __future__ import annotations

import ctypes
import json
import sys
import threading
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from typing import Optional

import pystray
import webview
from PIL import Image, ImageDraw

from app_config import (
    APP_DIR,
    DATA_DIR,
    DEFAULT_ALERT_TIERS,
    RESOURCE_DIR,
    AppConfig,
    get_device_tiers,
    is_autostart_enabled,
    load_config,
    save_config,
    set_autostart,
    set_device_tiers,
)
from providers import (
    DeviceBattery,
    DeviceManager,
    KIND_EARBUDS,
    KIND_HEADSET,
    KIND_KEYBOARD,
    KIND_MOUSE,
)

if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

UI_HTML = RESOURCE_DIR / "ui" / "index.html"
APP_ICON_ICO = RESOURCE_DIR / "assets" / "app_icon.ico"
WINDOW_TITLE = "无线外设电量监控"
ALERT_WINDOW_TITLE = "外设电量低提醒"
APP_SIZE = (356, 580)
ALERT_SIZE = (296, 68)
ALERT_DURATION_SEC = 5.0
EDGE_MARGIN = 16


# ================= Windows 11 原生 DWM 玻璃与窗口辅助 =================

class MARGINS(ctypes.Structure):
    _fields_ = [
        ("cxLeftWidth", ctypes.c_int),
        ("cxRightWidth", ctypes.c_int),
        ("cyTopHeight", ctypes.c_int),
        ("cyBottomHeight", ctypes.c_int),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def _get_tray_work_area() -> tuple[int, int, int, int]:
    """获取系统托盘所在显示器的工作区 (left, top, right, bottom)，自动避开任务栏并适配多显示器。"""
    user32 = ctypes.windll.user32
    try:
        tray_hwnd = user32.FindWindowW("Shell_TrayWnd", None)
        if tray_hwnd:
            MONITOR_DEFAULTTONEAREST = 2
            hmon = user32.MonitorFromWindow(wintypes.HWND(tray_hwnd), MONITOR_DEFAULTTONEAREST)
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
    sw = user32.GetSystemMetrics(0)
    sh = user32.GetSystemMetrics(1)
    return 0, 0, sw, sh - 48


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


def _apply_windows_glass(hwnd: int, native_form=None) -> dict:
    """启用 Windows 11 原生桌面级 Desktop Acrylic 实时毛玻璃与圆角，并关闭多余的 DWM 外边框。"""
    status = {"backcolor": False, "extend": -1, "corner": -1, "border_none": -1, "backdrop": -1}
    if sys.platform != "win32" or not hwnd:
        return status
    dwmapi = ctypes.windll.dwmapi

    if native_form is not None:
        try:
            from System import Action
            from System.Drawing import Color

            def _set_black():
                native_form.BackColor = Color.Black

            if getattr(native_form, "InvokeRequired", False):
                native_form.Invoke(Action(_set_black))
            else:
                _set_black()
            status["backcolor"] = True
        except Exception:
            pass

    try:
        margins = MARGINS(-1, -1, -1, -1)
        dwmapi.DwmExtendFrameIntoClientArea.argtypes = [wintypes.HWND, ctypes.POINTER(MARGINS)]
        dwmapi.DwmExtendFrameIntoClientArea.restype = ctypes.c_long
        status["extend"] = int(dwmapi.DwmExtendFrameIntoClientArea(wintypes.HWND(hwnd), ctypes.byref(margins)))
    except Exception:
        pass

    try:
        dark = ctypes.c_int(1)
        dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), 20, ctypes.byref(dark), ctypes.sizeof(dark))
    except Exception:
        pass

    try:
        corner = ctypes.c_int(2)
        dwmapi.DwmSetWindowAttribute.argtypes = [wintypes.HWND, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
        dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
        status["corner"] = int(dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), 33, ctypes.byref(corner), ctypes.sizeof(corner)))
    except Exception:
        pass

    try:
        no_border = ctypes.c_uint(0xFFFFFFFE)
        status["border_none"] = int(dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), 34, ctypes.byref(no_border), ctypes.sizeof(no_border)))
    except Exception:
        pass

    try:
        backdrop = ctypes.c_int(3)
        status["backdrop"] = int(dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), 38, ctypes.byref(backdrop), ctypes.sizeof(backdrop)))
    except Exception:
        pass

    return status


# ================= 矢量透明电池托盘图标 & 多尺寸 ICO =================

def draw_battery_icon(
    size: int = 64,
    percent: Optional[int] = 85,
    charging: bool = False,
    connected: bool = True,
) -> Image.Image:
    """高对比度饱满矢量电池轮廓（透明背景，16/20/24px 明暗任务栏均清晰）。"""
    scale = 4
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if not connected or percent is None:
        outline_col = (180, 190, 204, 220)
        inner_bg = (15, 23, 42, 95)
        fill_col = (148, 163, 184, 180)
        pct = 0
    else:
        outline_col = (248, 250, 252, 255)
        inner_bg = (15, 23, 42, 130)
        pct = max(0, min(100, int(percent)))
        if charging:
            fill_col = (34, 211, 106, 255)
        elif pct <= 10:
            fill_col = (239, 68, 68, 255)
        elif pct <= 20:
            fill_col = (245, 158, 11, 255)
        elif pct <= 30:
            fill_col = (250, 204, 21, 255)
        else:
            fill_col = (34, 211, 106, 255)

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


def ensure_app_ico() -> Optional[str]:
    """生成多尺寸 Windows ICO 图标资源（16/20/24/32/48/64/256），供任务栏与程序图标使用。"""
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
        KIND_EARBUDS: "耳塞",
        KIND_KEYBOARD: "键盘",
    }.get(kind, "外设")


# ================= 三级低电量防抖评估（独立纯逻辑，便于测试） =================

def evaluate_tiered_alerts(
    devices: list[DeviceBattery],
    cfg: AppConfig,
    alerted_map: dict[str, set[int]],
) -> list[tuple[DeviceBattery, int]]:
    """根据每台设备的独立三级阈值（默认 30/20/10%）评估本次应触发的提醒列表 [(device, tier), ...]。"""
    triggered: list[tuple[DeviceBattery, int]] = []
    for dev in devices:
        tiers = get_device_tiers(cfg, dev.device_id)
        seen = alerted_map.setdefault(dev.device_id, set())

        if not tiers or not dev.connected or not dev.online or dev.asleep or dev.percent is None:
            continue

        # 充电中自动重置所有已触发档位
        if dev.charging:
            seen.clear()
            continue

        pct = int(dev.percent)
        # 滞回防抖：电量回升至某档位 +5% 以上时，解除该档位的已触发标记
        for t in list(seen):
            if pct >= t + 5:
                seen.discard(t)

        # 查找本次新触及的档位
        pending = [t for t in tiers if pct <= t and t not in seen]
        if pending:
            for t in pending:
                seen.add(t)
            # 同一时刻跨越多级（如刚启动即为 15%）时，只弹出最紧急（最低阈值）的一条，防止弹窗轰炸
            most_urgent = min(pending)
            triggered.append((dev, most_urgent))

    return triggered


# ================= 主应用控制器 =================

class MouseBatteryApp:
    def __init__(self, start_hidden: bool = False) -> None:
        self.cfg: AppConfig = load_config()
        self.start_hidden = start_hidden
        self._allow_show = not start_hidden
        self.manager = DeviceManager()
        self.devices: list[DeviceBattery] = []
        self._last_poll_ts: float = 0.0
        self.window: Optional[webview.Window] = None
        self._alert_window = None
        self._alert_timer: Optional[threading.Timer] = None
        self._alert_lock = threading.Lock()
        self.hwnd: int = 0
        self._tray: Optional[pystray.Icon] = None
        self._stop_event = threading.Event()
        self._alerted_tiers: dict[str, set[int]] = {}
        self._last_cursor = _get_cursor_pos()

        # 拖拽状态
        self._drag_cursor_origin = (0, 0)
        self._drag_win_origin = (0, 0)
        self._drag_win_size = APP_SIZE

    def _active_device(self) -> Optional[DeviceBattery]:
        if not self.devices:
            return None
        if self.cfg.selected_device_id:
            for d in self.devices:
                if d.device_id == self.cfg.selected_device_id:
                    return d
        return self.devices[0]

    def _tray_device(self) -> Optional[DeviceBattery]:
        """托盘图标优先显示当前选中的设备；若当前设备无读数则优先显示电量最低的在线设备。"""
        active = self._active_device()
        if active is not None and active.percent is not None:
            return active
        with_pct = [d for d in self.devices if d.connected and d.percent is not None]
        if with_pct:
            return min(with_pct, key=lambda d: int(d.percent or 100))
        return active

    def _app_phys_size(self) -> tuple[int, int]:
        scale = _get_dpi_scale(self.hwnd)
        return int(round(APP_SIZE[0] * scale)), int(round(APP_SIZE[1] * scale))

    def _build_state_dict(self) -> dict:
        active = self._active_device()
        ts_str = ""
        ts_val = active.timestamp if (active and active.timestamp > 0) else self._last_poll_ts
        if ts_val > 0:
            ts_str = datetime.fromtimestamp(ts_val).strftime("%H:%M:%S")

        dev_list = []
        for d in self.devices:
            item = d.to_dict()
            item["alert_tiers"] = get_device_tiers(self.cfg, d.device_id)
            dev_list.append(item)

        active_id = active.device_id if active else ""
        active_tiers = get_device_tiers(self.cfg, active_id) if active_id else list(DEFAULT_ALERT_TIERS)

        return {
            "lock_position": self.cfg.lock_position,
            "topmost": self.cfg.topmost,
            "autostart": is_autostart_enabled(),
            "selected_device_id": active_id,
            "devices": dev_list,
            "active_device": active.to_dict() if active else None,
            "active_alert_tiers": active_tiers,
            "updated_str": ts_str,
        }

    def _push_state_to_ui(self) -> None:
        if self.window is None:
            return
        payload = json.dumps(self._build_state_dict(), ensure_ascii=False)
        try:
            self.window.evaluate_js(f"window.applyState && applyState({payload});")
        except Exception:
            pass

    def _show_ui_toast(self, msg: str) -> None:
        if self.window is None:
            return
        safe_msg = json.dumps(msg, ensure_ascii=False)
        try:
            self.window.evaluate_js(f"window.showToast && showToast({safe_msg});")
        except Exception:
            pass

    def _find_hwnd(self) -> int:
        if self.window is not None:
            native = getattr(self.window, "native", None)
            if native is not None:
                try:
                    return int(native.Handle.ToInt64())
                except Exception:
                    try:
                        return int(native.Handle)
                    except Exception:
                        pass
        return int(ctypes.windll.user32.FindWindowW(None, WINDOW_TITLE) or 0)

    # ================= 窗口显示 / 最小化 / 隐藏到托盘 =================

    def _compute_main_position(self) -> tuple[int, int, int, int]:
        aw, ah = self._app_phys_size()
        scale = _get_dpi_scale(self.hwnd) if self.hwnd else 1.0
        margin = int(round(EDGE_MARGIN * scale))
        left, top, right, bottom = _get_tray_work_area()

        if not self.cfg.lock_position and self.cfg.x is not None and self.cfg.y is not None:
            w_left, w_top, w_right, w_bottom = _get_work_area_for_window(self.hwnd)
            x = max(w_left, min(self.cfg.x, w_right - aw))
            y = max(w_top, min(self.cfg.y, w_bottom - ah))
        else:
            x = max(left, right - aw - margin)
            y = max(top, bottom - ah - margin)
        return x, y, aw, ah

    def show_main_window(self) -> None:
        if self.window is None:
            return
        self._allow_show = True
        native = getattr(self.window, "native", None)
        try:
            self.window.show()
            self.window.restore()
        except Exception:
            pass
        if self.hwnd:
            _apply_windows_glass(self.hwnd, native)
            x, y, aw, ah = self._compute_main_position()
            _set_window_pos(self.hwnd, x, y, aw, ah, topmost=self.cfg.topmost)
            user32 = ctypes.windll.user32
            user32.ShowWindow(wintypes.HWND(self.hwnd), 9)  # SW_RESTORE
            user32.SetForegroundWindow(wintypes.HWND(self.hwnd))
        self._push_state_to_ui()

    def minimize_window(self) -> None:
        if self.window is None:
            return
        try:
            self.window.minimize()
        except Exception:
            if self.hwnd:
                ctypes.windll.user32.ShowWindow(wintypes.HWND(self.hwnd), 6)

    def hide_to_tray(self) -> None:
        self._allow_show = False
        if self.window is not None:
            try:
                self.window.hide()
            except Exception:
                pass

    # ================= JS -> Python API =================

    def get_initial_state(self) -> dict:
        return self._build_state_dict()

    def select_device(self, device_id: str) -> None:
        self.cfg.selected_device_id = str(device_id)
        save_config(self.cfg)
        self._push_state_to_ui()
        self._update_tray_visual()

    def set_device_tiers(self, device_id: str, tiers: list[int]) -> None:
        target_id = str(device_id) if device_id else (self._active_device().device_id if self._active_device() else "")
        if not target_id:
            return
        set_device_tiers(self.cfg, target_id, list(tiers))
        self._alerted_tiers.pop(target_id, None)
        save_config(self.cfg)
        self._push_state_to_ui()
        self._update_tray_visual()

    def export_diagnostics(self) -> dict:
        """导出脱敏 JSON 设备诊断报告。"""
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
        self._show_ui_toast(f"诊断报告已导出：{target.name}")
        return {"ok": True, "path": str(target), "filename": target.name}

    def begin_drag(self, _sx: int, _sy: int) -> None:
        if self.cfg.lock_position or not self.hwnd:
            return
        self._drag_cursor_origin = _get_cursor_pos()
        wx, wy, ww, wh = _get_window_rect(self.hwnd)
        self._drag_win_origin = (wx, wy)
        self._drag_win_size = (ww, wh)

    def drag_move(self, _sx: int, _sy: int) -> None:
        if self.cfg.lock_position or not self.hwnd:
            return
        cx, cy = _get_cursor_pos()
        dx = cx - self._drag_cursor_origin[0]
        dy = cy - self._drag_cursor_origin[1]
        _set_window_pos(
            self.hwnd,
            self._drag_win_origin[0] + dx,
            self._drag_win_origin[1] + dy,
            self._drag_win_size[0],
            self._drag_win_size[1],
        )

    def end_drag(self) -> None:
        if self.cfg.lock_position or not self.hwnd:
            return
        wx, wy, ww, wh = _get_window_rect(self.hwnd)
        left, top, right, bottom = _get_work_area_for_window(self.hwnd)
        nx = max(left, min(wx, right - ww))
        ny = max(top, min(wy, bottom - wh))
        _set_window_pos(self.hwnd, nx, ny, ww, wh)
        self.cfg.x = nx
        self.cfg.y = ny
        save_config(self.cfg)

    def set_lock_position(self, value: bool) -> None:
        self.cfg.lock_position = bool(value)
        save_config(self.cfg)
        if self.cfg.lock_position and self.hwnd:
            x, y, aw, ah = self._compute_main_position()
            _set_window_pos(self.hwnd, x, y, aw, ah, topmost=self.cfg.topmost)
        self._push_state_to_ui()

    def set_topmost(self, value: bool) -> None:
        self.cfg.topmost = bool(value)
        save_config(self.cfg)
        if self.hwnd:
            wx, wy, ww, wh = _get_window_rect(self.hwnd)
            _set_window_pos(self.hwnd, wx, wy, ww, wh, topmost=self.cfg.topmost)
        self._push_state_to_ui()

    def set_autostart(self, value: bool) -> None:
        set_autostart(bool(value))
        self._push_state_to_ui()

    def refresh_now(self) -> None:
        threading.Thread(target=self._poll_once, daemon=True).start()

    # ================= 原生 WinForms 极速最高置顶低电量迷你弹窗 =================

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

        if self.hwnd:
            user32 = ctypes.windll.user32
            if user32.IsWindowVisible(wintypes.HWND(self.hwnd)) and not user32.IsIconic(wintypes.HWND(self.hwnd)):
                mx, my, mw, mh = _get_window_rect(self.hwnd)
                gap = int(round(10 * scale))
                candidate_y = my - ah - gap
                if candidate_y >= top + margin:
                    ay = candidate_y
                    ax = max(left + margin, min(mx + mw - aw, right - aw - margin))

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
                form.BackColor = Color.FromArgb(24, 27, 34)  # 纯色深灰黑，无毛玻璃、无描边
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
                dwmapi = ctypes.windll.dwmapi
                GWL_EXSTYLE = -20
                ex = user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE)
                ex |= 0x00000008 | 0x08000000 | 0x00000080  # TOPMOST | NOACTIVATE | TOOLWINDOW
                user32.SetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE, ex)

                try:
                    corner = ctypes.c_int(2)
                    dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), 33, ctypes.byref(corner), ctypes.sizeof(corner))
                    no_border = ctypes.c_uint(0xFFFFFFFE)
                    dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), 34, ctypes.byref(no_border), ctypes.sizeof(no_border))
                except Exception:
                    pass

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

    def test_low_battery(self) -> None:
        """独立测试低电量通知：使用测试电量 15% + 当前选中设备真实名，不打开主窗口、不影响冷却。"""
        active = self._active_device()
        name = active.name if active else "VGN Dragonfly F2 Pro Max"
        kind = active.kind if active else KIND_MOUSE
        self._show_mini_alert(name, 15, kind=kind, is_test=True)

    def quit_app(self) -> None:
        self._stop_event.set()
        self._close_alert_window()
        self.manager.stop()
        if self._tray is not None:
            try:
                self._tray.stop()
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
        self._last_poll_ts = time.time()
        # 若之前选中的设备已断开，自动切回首台设备但不覆盖配置中未来重连偏好
        self._push_state_to_ui()
        self._update_tray_visual()
        self._check_low_batteries(devices)

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            self._poll_once()
            any_online = any(d.online and d.percent is not None for d in self.devices)
            interval = max(8, self.cfg.poll_interval_sec) if any_online else 10
            self._stop_event.wait(interval)

    def _wakeup_watch_loop(self) -> None:
        while not self._stop_event.is_set():
            pos = _get_cursor_pos()
            if pos != self._last_cursor:
                self._last_cursor = pos
                if any(d.kind == KIND_MOUSE and d.connected and (d.asleep or d.percent is None) for d in self.devices):
                    self._poll_once()
            self._stop_event.wait(1.5)

    def _check_low_batteries(self, devices: list[DeviceBattery]) -> None:
        triggered = evaluate_tiered_alerts(devices, self.cfg, self._alerted_tiers)
        if not triggered:
            return
        # 若同轮多台设备同时触发，先展示电量最紧急的一台
        dev, _tier = min(triggered, key=lambda pair: int(pair[0].percent or 100))
        threading.Thread(
            target=self._show_mini_alert,
            args=(dev.name, int(dev.percent or 0), dev.kind, False),
            daemon=True,
        ).start()

    def _update_tray_visual(self) -> None:
        if self._tray is None:
            return
        try:
            td = self._tray_device()
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
                self._tray.title = "无线外设电量监控（未检测到外设）"
            else:
                lines = []
                for d in self.devices[:3]:
                    if d.percent is not None:
                        st = "已充满" if d.full else ("充电中" if d.charging else ("休眠" if d.asleep else d.connection_mode))
                        lines.append(f"{d.name}: {d.percent}% ({st})")
                    else:
                        st = "休眠" if d.asleep else "未知"
                        lines.append(f"{d.name}: {st}")
                if len(self.devices) > 3:
                    lines.append(f"…共 {len(self.devices)} 台外设")
                tooltip = "\n".join(lines)
                self._tray.title = tooltip[:124]
        except Exception:
            pass

    def _start_tray(self) -> None:
        tray_menu = pystray.Menu(
            pystray.MenuItem("打开主窗口", lambda _i, _m: self.show_main_window(), default=True),
            pystray.MenuItem("测试低电量弹窗", lambda _i, _m: self.test_low_battery()),
            pystray.MenuItem("导出设备诊断报告", lambda _i, _m: threading.Thread(target=self.export_diagnostics, daemon=True).start()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出程序", lambda _i, _m: self.quit_app()),
        )
        self._tray = pystray.Icon(
            "VGNMouseBattery",
            draw_battery_icon(size=64, percent=None, charging=False, connected=False),
            "无线外设电量监控",
            tray_menu,
        )
        threading.Thread(target=self._tray.run, daemon=True).start()

    def _on_window_loaded(self) -> None:
        for _ in range(12):
            self.hwnd = self._find_hwnd()
            if self.hwnd:
                break
            time.sleep(0.05)

        if self.hwnd:
            native = getattr(self.window, "native", None)
            _apply_windows_glass(self.hwnd, native)
            x, y, aw, ah = self._compute_main_position()
            _set_window_pos(self.hwnd, x, y, aw, ah, topmost=self.cfg.topmost)
            if not self._allow_show and self.window is not None:
                try:
                    self.window.hide()
                except Exception:
                    pass

        self._push_state_to_ui()
        self._start_tray()
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
                res = k32.WaitForSingleObject(wintypes.HANDLE(ev), 500)
                if res == 0:
                    self.show_main_window()
        finally:
            k32.CloseHandle(wintypes.HANDLE(ev))

    def run(self) -> None:
        if self.start_hidden:
            try:
                from webview.platforms import edgechromium

                _orig_nav = edgechromium.EdgeChrome.on_navigation_start

                def _safe_nav(ec_self, sender, args):
                    if ec_self.pywebview_window.transparent and getattr(ec_self.pywebview_window, "hidden", False):
                        return
                    return _orig_nav(ec_self, sender, args)

                edgechromium.EdgeChrome.on_navigation_start = _safe_nav
            except Exception:
                pass
        ico_path = ensure_app_ico()
        self.window = webview.create_window(
            title=WINDOW_TITLE,
            url=UI_HTML.as_uri(),
            width=APP_SIZE[0],
            height=APP_SIZE[1],
            frameless=True,
            easy_drag=False,
            transparent=True,
            hidden=self.start_hidden,
            on_top=self.cfg.topmost,
            resizable=False,
            js_api=_JsApi(self),
        )
        webview.start(func=self._on_window_loaded, gui="edgechromium", icon=ico_path, debug=False)


class _JsApi:
    """仅暴露给前端 JS 的干净接口桥。"""

    def __init__(self, app: MouseBatteryApp) -> None:
        self._app = app

    def get_initial_state(self) -> dict:
        return self._app.get_initial_state()

    def select_device(self, device_id: str) -> None:
        self._app.select_device(device_id)

    def set_device_tiers(self, device_id: str, tiers: list[int]) -> None:
        self._app.set_device_tiers(device_id, tiers)

    def export_diagnostics(self) -> dict:
        return self._app.export_diagnostics()

    def begin_drag(self, sx: int, sy: int) -> None:
        self._app.begin_drag(sx, sy)

    def drag_move(self, sx: int, sy: int) -> None:
        self._app.drag_move(sx, sy)

    def end_drag(self) -> None:
        self._app.end_drag()

    def minimize_window(self) -> None:
        self._app.minimize_window()

    def hide_to_tray(self) -> None:
        self._app.hide_to_tray()

    def set_lock_position(self, value: bool) -> None:
        self._app.set_lock_position(value)

    def set_topmost(self, value: bool) -> None:
        self._app.set_topmost(value)

    def set_autostart(self, value: bool) -> None:
        self._app.set_autostart(value)

    def refresh_now(self) -> None:
        self._app.refresh_now()

    def test_low_battery(self) -> None:
        self._app.test_low_battery()

    def quit_app(self) -> None:
        self._app.quit_app()


def _activate_existing_window() -> None:
    if sys.platform != "win32":
        return
    k32 = ctypes.windll.kernel32
    EVENT_MODIFY_STATE = 0x0002
    ev = k32.OpenEventW(EVENT_MODIFY_STATE, False, "Local\\VGNMouseBatteryMonitor_ShowEvent")
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
