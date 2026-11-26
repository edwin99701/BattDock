"""原生 WinForms 桌面悬浮窗与提示音播放（零 WebView2 额外开销，Windows 10/11 通用）。"""

from __future__ import annotations

import ctypes
import io
import sys
import threading
from ctypes import wintypes
from typing import Callable, Optional

from PIL import Image, ImageDraw

from app_config import FloatingWidgetConfig
from brand import APP_FLOATING_TITLE
from providers import DeviceBattery, KIND_EARBUDS, KIND_HEADSET, KIND_KEYBOARD, KIND_MOUSE

EDGE_MARGIN = 16


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


def _try_win11_round_corners(hwnd: int) -> None:
    """能力检测式启用 Win11 圆角；Windows 10 上静默忽略，绝不产生黑边或报错。"""
    if sys.platform != "win32" or not hwnd:
        return
    try:
        dwmapi = ctypes.windll.dwmapi
        corner = ctypes.c_int(2)  # DWMWCP_ROUND
        dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), 33, ctypes.byref(corner), ctypes.sizeof(corner))
        no_border = ctypes.c_uint(0xFFFFFFFE)
        dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), 34, ctypes.byref(no_border), ctypes.sizeof(no_border))
    except Exception:
        pass


class DesktopFloatingWidget:
    """轻量桌面悬浮窗（使用主窗体 UI 线程的原生 WinForms 控件，Win10/11 通用，内存占用极低）。"""

    SIZE_MAP = {
        "small": (208, 46),
        "medium": (256, 54),
        "large": (296, 62),
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
                f = self._form
                self._form = None
                self._pic = None
                self._name_lbl = None
                self._pct_lbl = None
                self._bar_bg = None
                self._bar_fill = None
            if f is not None:
                try:
                    if not f.IsDisposed:
                        f.Close()
                        f.Dispose()
                except Exception:
                    pass

        self._run_on_ui(_do)

    def sync(
        self,
        fcfg: FloatingWidgetConfig,
        device: Optional[DeviceBattery],
        display_name: str,
        theme: str,
    ) -> None:
        """根据配置与设备实时状态创建/更新/隐藏桌面悬浮窗。"""
        if not fcfg.enabled:
            self.close()
            return

        scale = self._get_dpi_scale()
        base_w, base_h = self.SIZE_MAP.get(fcfg.size, self.SIZE_MAP["medium"])
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
        pct = device.percent if device else None
        charging = bool(device.charging) if device else False
        online = bool(device.online) if device else False
        asleep = bool(device.asleep) if device else False
        title = display_name or (device.name if device else "未连接外设")
        pct_text = f"{pct}%" if pct is not None else "—"
        if charging and pct is not None:
            pct_text = f"⚡{pct}%"

        def _do():
            try:
                import System.Windows.Forms as WinForms
                from System.Drawing import Color, ContentAlignment, Font, FontStyle, Image as GdiImage, Point, Size
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

                    self._form = form
                    self._pic = pic
                    self._name_lbl = name_lbl
                    self._pct_lbl = pct_lbl
                    self._bar_bg = bar_bg
                    self._bar_fill = bar_fill

                form = self._form
                form.TopMost = bool(fcfg.topmost)
                form.Opacity = max(0.4, min(1.0, int(fcfg.opacity) / 100.0))
                form.BackColor = Color.FromArgb(30, 34, 43) if is_dark else Color.FromArgb(250, 251, 254)
                form.Size = Size(w, h)
                if not self._dragging:
                    form.Location = Point(x, y)

                pad = int(round(10 * scale))
                icon_px = int(round(22 * scale))
                self._pic.Size = Size(icon_px, icon_px)
                self._pic.Location = Point(pad, (h - icon_px) // 2)
                pil_ic = draw_battery_icon(
                    size=icon_px,
                    percent=pct,
                    charging=charging,
                    connected=online or asleep,
                    light_bg=(not is_dark),
                )
                buf = io.BytesIO()
                pil_ic.save(buf, format="PNG")
                self._pic.Image = GdiImage.FromStream(MemoryStream(buf.getvalue()))

                pct_w = int(round(48 * scale))
                text_x = pad + icon_px + int(round(8 * scale))
                text_w = max(60, w - text_x - pct_w - pad)

                self._name_lbl.Text = title
                self._name_lbl.ForeColor = Color.FromArgb(241, 245, 249) if is_dark else Color.FromArgb(26, 29, 36)
                self._name_lbl.Font = Font("Microsoft YaHei UI", 8.5 if fcfg.size == "small" else 9.0, FontStyle.Bold)
                self._name_lbl.Size = Size(text_w, int(round(20 * scale)))
                self._name_lbl.Location = Point(text_x, int(round(9 * scale)))

                self._pct_lbl.Text = pct_text
                if pct is not None and not charging and pct <= 10:
                    p_col = Color.FromArgb(239, 68, 68)
                elif pct is not None and not charging and pct <= 20:
                    p_col = Color.FromArgb(234, 88, 12)
                elif charging:
                    p_col = Color.FromArgb(22, 163, 74)
                else:
                    p_col = Color.FromArgb(241, 245, 249) if is_dark else Color.FromArgb(26, 29, 36)
                self._pct_lbl.ForeColor = p_col
                self._pct_lbl.Font = Font("Microsoft YaHei UI", 9.0 if fcfg.size == "small" else 10.0, FontStyle.Bold)
                self._pct_lbl.Size = Size(pct_w, int(round(22 * scale)))
                self._pct_lbl.Location = Point(w - pct_w - pad, (h - int(round(22 * scale))) // 2)

                bar_h = max(4, int(round(5 * scale)))
                bar_y = h - int(round(13 * scale))
                self._bar_bg.Location = Point(text_x, bar_y)
                self._bar_bg.Size = Size(text_w, bar_h)
                self._bar_bg.BackColor = Color.FromArgb(51, 57, 71) if is_dark else Color.FromArgb(228, 232, 240)

                fill_w = int(round(text_w * (max(0, min(100, pct)) / 100.0))) if pct is not None else 0
                self._bar_fill.Location = Point(0, 0)
                self._bar_fill.Size = Size(fill_w, bar_h)
                if pct is None:
                    f_col = Color.FromArgb(148, 163, 184)
                elif charging or pct > 30:
                    f_col = Color.FromArgb(34, 197, 94)
                elif pct > 20:
                    f_col = Color.FromArgb(234, 179, 8)
                elif pct > 10:
                    f_col = Color.FromArgb(245, 158, 11)
                else:
                    f_col = Color.FromArgb(239, 68, 68)
                self._bar_fill.BackColor = f_col

                hwnd = int(form.Handle.ToInt64())
                _try_win11_round_corners(hwnd)
                if not form.Visible:
                    user32 = ctypes.windll.user32
                    GWL_EXSTYLE = -20
                    ex = user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE)
                    ex |= 0x00000080  # WS_EX_TOOLWINDOW
                    user32.SetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE, ex)
                    user32.ShowWindow(wintypes.HWND(hwnd), 4)  # SW_SHOWNOACTIVATE
            except Exception:
                pass

        self._run_on_ui(_do)
