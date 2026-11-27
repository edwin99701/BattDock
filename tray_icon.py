"""BattDock 独立原生 Win32 系统托盘动态电池图标控制器。

设计目标（彻底根治 pystray 并发竞态、静默失败与重启漏注册问题）：
1. 独立消息窗口与线程生命周期：与主窗口/设置窗口完全解耦，主窗口最小化、隐藏、关闭或重建均不影响托盘图标。
2. 线程安全 RLock 保护：串行化所有图标更新、文案更新、状态查询与退出注销，杜绝并发 DestroyIcon 竞态。
3. 纯内存 32 位 ARGB HICON 生成（零磁盘临时 .ico 文件）：新图标注册成功后再释放旧 HICON，杜绝空句柄或闪烁。
4. Shell_NotifyIconW 返回值强校验 + 自动重试 + 自愈重建：
   - NIM_ADD 失败时自动退避重试（覆盖系统登录/自动更新重启/Explorer 繁忙场景）；
   - NIM_MODIFY 失败时自动回退 NIM_ADD 重新注册；
   - 监听 WM_TASKBARCREATED（Explorer 重启）与 WM_DISPLAYCHANGE（DPI/分辨率变化）并安全自愈；
   - 显式保留 uID=0，100% 兼容既有 Windows 11 NotifyIconSettings 的常驻置顶偏好（IsPromoted=1）。
5. 右键菜单现场按需构建：收到 WM_RBUTTONUP 时在托盘线程内实时计算菜单勾选态并立即清理 HMENU，零跨线程竞态。
6. 退出同步注销：stop() 先同步执行 NIM_DELETE 再退出消息循环，确保自动更新 os._exit(0) 前不留僵尸托盘图标。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import sys
import threading
import time
from typing import Any, Callable, Optional

from PIL import Image


@dataclass(frozen=True)
class TrayMenuEntry:
    """系统托盘右键菜单项定义。"""

    label: str = ""
    action: Optional[Callable[[], Any]] = None
    checked: Optional[Callable[[], bool]] = None
    default: bool = False
    enabled: bool = True
    separator: bool = False


# Win32 常量
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_DISPLAYCHANGE = 0x007E
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_USER = 0x0400
WM_TRAY_CALLBACK = WM_USER + 11
WM_TRAY_STOP = WM_USER + 12

WS_POPUP = 0x80000000

NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
NIF_INFO = 0x00000010

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002

MIIM_STATE = 0x00000001
MIIM_ID = 0x00000002
MIIM_STRING = 0x00000040
MIIM_FTYPE = 0x00000100

MFT_STRING = 0x00000000
MFT_SEPARATOR = 0x00000800

MFS_ENABLED = 0x00000000
MFS_DISABLED = 0x00000003
MFS_CHECKED = 0x00000008
MFS_DEFAULT = 0x00001000

TPM_RIGHTALIGN = 0x0008
TPM_BOTTOMALIGN = 0x0020
TPM_RETURNCMD = 0x0100

MSGFLT_ALLOW = 1
BI_BITFIELDS = 3
DIB_RGB_COLORS = 0


if sys.platform == "win32":
    # 使用独立 WinDLL 实例，避免与其他模块共享 ctypes.windll 全局 argtypes/restype 产生相互干扰
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _shell32 = ctypes.WinDLL("shell32", use_last_error=True)

    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    class _GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.ULONG),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", wintypes.BYTE * 8),
        ]

    class _VERSION_OR_TIMEOUT(ctypes.Union):
        _fields_ = [
            ("uTimeout", wintypes.UINT),
            ("uVersion", wintypes.UINT),
        ]

    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("hWnd", wintypes.HWND),
            ("uID", wintypes.UINT),
            ("uFlags", wintypes.UINT),
            ("uCallbackMessage", wintypes.UINT),
            ("hIcon", wintypes.HICON),
            ("szTip", wintypes.WCHAR * 128),
            ("dwState", wintypes.DWORD),
            ("dwStateMask", wintypes.DWORD),
            ("szInfo", wintypes.WCHAR * 256),
            ("version_or_timeout", _VERSION_OR_TIMEOUT),
            ("szInfoTitle", wintypes.WCHAR * 64),
            ("dwInfoFlags", wintypes.DWORD),
            ("guidItem", _GUID),
            ("hBalloonIcon", wintypes.HICON),
        ]
        _anonymous_ = ("version_or_timeout",)

    class _WNDCLASSEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT),
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
            ("hIconSm", wintypes.HICON),
        ]

    class _MENUITEMINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT),
            ("fMask", wintypes.UINT),
            ("fType", wintypes.UINT),
            ("fState", wintypes.UINT),
            ("wID", wintypes.UINT),
            ("hSubMenu", wintypes.HMENU),
            ("hbmpChecked", wintypes.HBITMAP),
            ("hbmpUnchecked", wintypes.HBITMAP),
            ("dwItemData", ctypes.c_size_t),
            ("dwTypeData", wintypes.LPCWSTR),
            ("cch", wintypes.UINT),
            ("hbmpItem", wintypes.HBITMAP),
        ]

    class _CIEXYZ(ctypes.Structure):
        _fields_ = [
            ("ciexyzX", wintypes.LONG),
            ("ciexyzY", wintypes.LONG),
            ("ciexyzZ", wintypes.LONG),
        ]

    class _CIEXYZTRIPLE(ctypes.Structure):
        _fields_ = [
            ("ciexyzRed", _CIEXYZ),
            ("ciexyzGreen", _CIEXYZ),
            ("ciexyzBlue", _CIEXYZ),
        ]

    class _BITMAPV5HEADER(ctypes.Structure):
        _fields_ = [
            ("bV5Size", wintypes.DWORD),
            ("bV5Width", wintypes.LONG),
            ("bV5Height", wintypes.LONG),
            ("bV5Planes", wintypes.WORD),
            ("bV5BitCount", wintypes.WORD),
            ("bV5Compression", wintypes.DWORD),
            ("bV5SizeImage", wintypes.DWORD),
            ("bV5XPelsPerMeter", wintypes.LONG),
            ("bV5YPelsPerMeter", wintypes.LONG),
            ("bV5ClrUsed", wintypes.DWORD),
            ("bV5ClrImportant", wintypes.DWORD),
            ("bV5RedMask", wintypes.DWORD),
            ("bV5GreenMask", wintypes.DWORD),
            ("bV5BlueMask", wintypes.DWORD),
            ("bV5AlphaMask", wintypes.DWORD),
            ("bV5CSType", wintypes.DWORD),
            ("bV5Endpoints", _CIEXYZTRIPLE),
            ("bV5GammaRed", wintypes.DWORD),
            ("bV5GammaGreen", wintypes.DWORD),
            ("bV5GammaBlue", wintypes.DWORD),
            ("bV5Intent", wintypes.DWORD),
            ("bV5ProfileData", wintypes.DWORD),
            ("bV5ProfileSize", wintypes.DWORD),
            ("bV5Reserved", wintypes.DWORD),
        ]

    class _ICONINFO(ctypes.Structure):
        _fields_ = [
            ("fIcon", wintypes.BOOL),
            ("xHotspot", wintypes.DWORD),
            ("yHotspot", wintypes.DWORD),
            ("hbmMask", wintypes.HBITMAP),
            ("hbmColor", wintypes.HBITMAP),
        ]

    _kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    _kernel32.GetModuleHandleW.restype = wintypes.HMODULE

    _user32.RegisterClassExW.argtypes = [ctypes.POINTER(_WNDCLASSEXW)]
    _user32.RegisterClassExW.restype = wintypes.ATOM
    _user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
    _user32.UnregisterClassW.restype = wintypes.BOOL
    _user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
    ]
    _user32.CreateWindowExW.restype = wintypes.HWND
    _user32.DestroyWindow.argtypes = [wintypes.HWND]
    _user32.DestroyWindow.restype = wintypes.BOOL
    _user32.IsWindow.argtypes = [wintypes.HWND]
    _user32.IsWindow.restype = wintypes.BOOL
    _user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _user32.DefWindowProcW.restype = LRESULT
    _user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    _user32.GetMessageW.restype = ctypes.c_int
    _user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    _user32.TranslateMessage.restype = wintypes.BOOL
    _user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    _user32.DispatchMessageW.restype = LRESULT
    _user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _user32.PostMessageW.restype = wintypes.BOOL
    _user32.PostQuitMessage.argtypes = [ctypes.c_int]
    _user32.PostQuitMessage.restype = None
    _user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
    _user32.RegisterWindowMessageW.restype = wintypes.UINT
    _user32.CreatePopupMenu.argtypes = []
    _user32.CreatePopupMenu.restype = wintypes.HMENU
    _user32.InsertMenuItemW.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.BOOL, ctypes.POINTER(_MENUITEMINFOW)]
    _user32.InsertMenuItemW.restype = wintypes.BOOL
    _user32.DestroyMenu.argtypes = [wintypes.HMENU]
    _user32.DestroyMenu.restype = wintypes.BOOL
    _user32.TrackPopupMenuEx.argtypes = [
        wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.HWND, ctypes.c_void_p,
    ]
    _user32.TrackPopupMenuEx.restype = wintypes.BOOL
    _user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _user32.SetForegroundWindow.restype = wintypes.BOOL
    _user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    _user32.GetCursorPos.restype = wintypes.BOOL
    _user32.GetDC.argtypes = [wintypes.HWND]
    _user32.GetDC.restype = wintypes.HDC
    _user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    _user32.ReleaseDC.restype = ctypes.c_int
    _user32.CreateIconIndirect.argtypes = [ctypes.POINTER(_ICONINFO)]
    _user32.CreateIconIndirect.restype = wintypes.HICON
    _user32.DestroyIcon.argtypes = [wintypes.HICON]
    _user32.DestroyIcon.restype = wintypes.BOOL
    try:
        _user32.ChangeWindowMessageFilterEx.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.DWORD, ctypes.c_void_p,
        ]
        _user32.ChangeWindowMessageFilterEx.restype = wintypes.BOOL
    except Exception:
        pass

    _gdi32.CreateDIBSection.argtypes = [
        wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD,
    ]
    _gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    _gdi32.CreateBitmap.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.UINT, wintypes.UINT, ctypes.c_void_p]
    _gdi32.CreateBitmap.restype = wintypes.HBITMAP
    _gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    _gdi32.DeleteObject.restype = wintypes.BOOL

    _shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
    _shell32.Shell_NotifyIconW.restype = wintypes.BOOL

    WM_TASKBARCREATED = int(_user32.RegisterWindowMessageW("TaskbarCreated") or 0)
else:
    WM_TASKBARCREATED = 0


def pil_image_to_hicon(image: Image.Image) -> int:
    """将 PIL RGBA 图像直接于内存中转换为 32 位 ARGB Win32 HICON（零磁盘写、零 GDI 位图泄漏）。"""
    if sys.platform != "win32" or image is None:
        return 0
    rgba = image.convert("RGBA")
    w, h = rgba.size
    if w <= 0 or h <= 0:
        return 0
    bgra_bytes = rgba.tobytes("raw", "BGRA")

    hdc = _user32.GetDC(None)
    hbm_color = None
    hbm_mask = None
    try:
        bih = _BITMAPV5HEADER()
        bih.bV5Size = ctypes.sizeof(_BITMAPV5HEADER)
        bih.bV5Width = w
        bih.bV5Height = -h  # 顶向下扫描，防止图像倒置
        bih.bV5Planes = 1
        bih.bV5BitCount = 32
        bih.bV5Compression = BI_BITFIELDS
        bih.bV5RedMask = 0x00FF0000
        bih.bV5GreenMask = 0x0000FF00
        bih.bV5BlueMask = 0x000000FF
        bih.bV5AlphaMask = 0xFF000000

        bits_ptr = ctypes.c_void_p()
        hbm_color = _gdi32.CreateDIBSection(
            hdc,
            ctypes.byref(bih),
            DIB_RGB_COLORS,
            ctypes.byref(bits_ptr),
            None,
            0,
        )
        if not hbm_color or not bits_ptr.value:
            return 0
        ctypes.memmove(bits_ptr.value, bgra_bytes, len(bgra_bytes))

        # 1bpp 全零掩码：32 位 ARGB 图标由 Alpha 通道决定透明度
        hbm_mask = _gdi32.CreateBitmap(w, h, 1, 1, None)
        if not hbm_mask:
            return 0

        ii = _ICONINFO()
        ii.fIcon = True
        ii.xHotspot = 0
        ii.yHotspot = 0
        ii.hbmMask = hbm_mask
        ii.hbmColor = hbm_color
        hicon = _user32.CreateIconIndirect(ctypes.byref(ii))
        return int(hicon or 0)
    finally:
        if hbm_color:
            _gdi32.DeleteObject(hbm_color)
        if hbm_mask:
            _gdi32.DeleteObject(hbm_mask)
        if hdc:
            _user32.ReleaseDC(None, hdc)


def destroy_hicon_safe(hicon: int) -> None:
    """安全释放 Win32 HICON 句柄（不抛异常）。"""
    if sys.platform == "win32" and hicon:
        try:
            _user32.DestroyIcon(wintypes.HICON(hicon))
        except Exception:
            pass


class TrayIconController:
    """高可靠、线程安全、支持失败重试与 Explorer 重启自愈的 Windows 系统托盘图标控制器。"""

    # 显式沿用 uID=0，确保老用户在 Windows 11 NotifyIconSettings 中已置顶的 IsPromoted=1 偏好无缝保留
    TRAY_UID = 0

    def __init__(
        self,
        name: str,
        initial_icon: Image.Image,
        title: str,
        menu_entries: list[TrayMenuEntry],
        on_left_click: Optional[Callable[[], Any]] = None,
        *,
        _notify_api: Optional[Callable[[int, Any], bool]] = None,
        _icon_factory: Optional[Callable[[Image.Image], int]] = None,
        _icon_destroyer: Optional[Callable[[int], None]] = None,
    ) -> None:
        self._name = str(name or "BattDock")
        self._image: Image.Image = initial_icon
        self._title: str = str(title or self._name)[:127]
        self._menu_entries: list[TrayMenuEntry] = list(menu_entries or [])
        self._on_left_click = on_left_click

        # 可注入底层 Win32 API 钩子，便于全自动生命周期单元测试
        self._notify_api = _notify_api or self._win32_shell_notify
        self._icon_factory = _icon_factory or pil_image_to_hicon
        self._icon_destroyer = _icon_destroyer or destroy_hicon_safe

        self._lock = threading.RLock()
        self._ready_event = threading.Event()
        self._stop_event = threading.Event()

        self._hwnd: int = 0
        self._hicon: int = 0
        self._running: bool = False
        self._registered: bool = False
        self._visible: bool = False
        self._thread: Optional[threading.Thread] = None
        self._retry_timer: Optional[threading.Timer] = None
        self._wndproc_ref: Any = None
        self._cls_name: str = ""

        # 健康与诊断统计
        self._add_attempts: int = 0
        self._add_failures: int = 0
        self._modify_failures: int = 0
        self._reregister_count: int = 0
        self._last_error: str = ""

    @staticmethod
    def _win32_shell_notify(code: int, nid: Any) -> bool:
        if sys.platform != "win32":
            return False
        return bool(_shell32.Shell_NotifyIconW(wintypes.DWORD(code), ctypes.byref(nid)))

    def _build_nid(
        self,
        flags: int,
        *,
        hicon: int = 0,
        tip: Optional[str] = None,
        info: Optional[str] = None,
        info_title: Optional[str] = None,
    ) -> Any:
        if sys.platform == "win32":
            nid = NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            nid.hWnd = wintypes.HWND(self._hwnd)
            nid.uID = self.TRAY_UID
            nid.uFlags = flags
            if flags & NIF_MESSAGE:
                nid.uCallbackMessage = WM_TRAY_CALLBACK
            if flags & NIF_ICON:
                nid.hIcon = wintypes.HICON(hicon)
            if (flags & NIF_TIP) and tip is not None:
                nid.szTip = str(tip)[:127]
            if (flags & NIF_INFO) and info is not None:
                nid.szInfo = str(info)[:255]
                nid.szInfoTitle = str(info_title or self._name)[:63]
            return nid
        return {
            "hWnd": self._hwnd,
            "uID": self.TRAY_UID,
            "uFlags": flags,
            "hIcon": hicon,
            "szTip": (tip or "")[:127],
            "szInfo": (info or "")[:255],
            "szInfoTitle": (info_title or self._name)[:63],
        }

    def start(self, wait_timeout: float = 1.5) -> bool:
        """启动独立托盘消息线程并尝试完成初始注册（幂等，绝不重复创建实例）。"""
        with self._lock:
            if self._running and self._thread is not None and self._thread.is_alive():
                return True
            self._stop_event.clear()
            self._ready_event.clear()
            t = threading.Thread(target=self._run_loop, name="BattDock-Tray", daemon=True)
            self._thread = t
            t.start()
        self._ready_event.wait(timeout=max(0.1, float(wait_timeout)))
        with self._lock:
            return self._running

    def _ensure_hicon_locked(self) -> int:
        if self._hicon:
            return self._hicon
        if self._image is None:
            return 0
        hicon = int(self._icon_factory(self._image) or 0)
        if hicon:
            self._hicon = hicon
        return self._hicon

    def _register_icon_locked(self, is_reregister: bool = False) -> bool:
        """向 Windows Explorer 注册托盘图标（校验返回值，失败记录原因）。"""
        if self._stop_event.is_set() or not self._hwnd:
            return False
        hicon = self._ensure_hicon_locked()
        if not hicon:
            self._last_error = "HICON 创建失败"
            self._add_failures += 1
            return False

        self._add_attempts += 1
        nid = self._build_nid(
            NIF_MESSAGE | NIF_ICON | NIF_TIP,
            hicon=hicon,
            tip=self._title,
        )
        ok = bool(self._notify_api(NIM_ADD, nid))
        if ok:
            self._registered = True
            self._visible = True
            self._last_error = ""
            if is_reregister:
                self._reregister_count += 1
            return True

        self._add_failures += 1
        err_code = ctypes.get_last_error() if sys.platform == "win32" else 0
        self._last_error = f"Shell_NotifyIcon(NIM_ADD) 失败 (err={err_code})"
        self._registered = False
        self._visible = False
        return False

    def _schedule_retry_locked(self, attempt: int = 1) -> None:
        """若首次 NIM_ADD 失败（如刚开机或自动更新重启瞬间 Explorer 忙碌），退避重试注册。"""
        if self._stop_event.is_set() or self._registered or attempt > 15:
            return
        if self._retry_timer is not None:
            try:
                self._retry_timer.cancel()
            except Exception:
                pass
        delays = (0.15, 0.25, 0.4, 0.6, 1.0, 1.5, 2.0)
        delay = delays[min(attempt - 1, len(delays) - 1)]

        def _retry_worker() -> None:
            with self._lock:
                self._retry_timer = None
                if self._stop_event.is_set() or self._registered or not self._running:
                    return
                if not self._register_icon_locked(is_reregister=True):
                    self._schedule_retry_locked(attempt + 1)

        timer = threading.Timer(delay, _retry_worker)
        timer.daemon = True
        self._retry_timer = timer
        timer.start()

    def set_icon(self, image: Image.Image) -> bool:
        """线程安全地更新动态电池图标（先创建新 HICON 并成功应用，再释放旧 HICON；若未注册则自愈补注册）。"""
        if image is None:
            return False
        with self._lock:
            self._image = image
            if self._stop_event.is_set():
                return False
            if not self._hwnd:
                # 窗口尚未创建完毕：已保存最新图像，待 _run_loop 完成初始化后自动呈现
                return False

            new_hicon = int(self._icon_factory(image) or 0)
            if not new_hicon:
                self._last_error = "新动态电池图标 HICON 创建失败"
                return False

            old_hicon = self._hicon
            if not self._registered:
                self._hicon = new_hicon
                if old_hicon and old_hicon != new_hicon:
                    self._icon_destroyer(old_hicon)
                ok = self._register_icon_locked(is_reregister=True)
                if not ok:
                    self._schedule_retry_locked(1)
                return ok

            nid = self._build_nid(NIF_ICON, hicon=new_hicon)
            ok = bool(self._notify_api(NIM_MODIFY, nid))
            if ok:
                self._hicon = new_hicon
                self._visible = True
                self._last_error = ""
                if old_hicon and old_hicon != new_hicon:
                    self._icon_destroyer(old_hicon)
                return True

            # NIM_MODIFY 失败（例如 Explorer 静默重启丢失图标）：立即尝试用新 HICON 自愈补注册
            self._modify_failures += 1
            self._hicon = new_hicon
            if old_hicon and old_hicon != new_hicon:
                self._icon_destroyer(old_hicon)
            re_ok = self._register_icon_locked(is_reregister=True)
            if not re_ok:
                self._schedule_retry_locked(1)
            return re_ok

    def set_title(self, title: str) -> bool:
        """线程安全地更新系统托盘悬停提示文本（支持最长 127 字符多设备摘要）。"""
        clean = str(title or self._name)[:127]
        with self._lock:
            self._title = clean
            if self._stop_event.is_set() or not self._hwnd:
                return False
            if not self._registered:
                ok = self._register_icon_locked(is_reregister=True)
                if not ok:
                    self._schedule_retry_locked(1)
                return ok
            nid = self._build_nid(NIF_TIP, tip=clean)
            ok = bool(self._notify_api(NIM_MODIFY, nid))
            if not ok:
                self._modify_failures += 1
                re_ok = self._register_icon_locked(is_reregister=True)
                if not re_ok:
                    self._schedule_retry_locked(1)
                return re_ok
            return True

    def notify(self, message: str, title: Optional[str] = None) -> bool:
        """发送 Windows 系统托盘通知气泡（用于低电量系统通知）。"""
        with self._lock:
            if self._stop_event.is_set() or not self._hwnd or not self._registered:
                return False
            nid = self._build_nid(
                NIF_INFO,
                info=str(message or ""),
                info_title=str(title or self._name),
            )
            return bool(self._notify_api(NIM_MODIFY, nid))

    def ensure_visible(self) -> bool:
        """主动自检并确保托盘图标已注册且可见（供定时自检或恢复调用）。"""
        with self._lock:
            if self._stop_event.is_set() or not self._running or not self._hwnd:
                return False
            if self._registered and self._visible and self._hicon:
                return True
            ok = self._register_icon_locked(is_reregister=True)
            if not ok:
                self._schedule_retry_locked(1)
            return ok

    def update_menu(self) -> None:
        """兼容接口：本控制器在每次右键弹出时实时计算勾选态并构建原生 HMENU，无需跨线程销毁重建。"""
        return

    def get_health_snapshot(self) -> dict[str, Any]:
        """返回托盘健康状态脱敏快照（写入诊断报告与自动化测试校验）。"""
        with self._lock:
            hwnd_valid = bool(
                self._hwnd
                and (sys.platform != "win32" or _user32.IsWindow(wintypes.HWND(self._hwnd)))
            )
            return {
                "running": bool(self._running),
                "registered": bool(self._registered),
                "visible": bool(self._visible),
                "hwnd_valid": hwnd_valid,
                "icon_handle_valid": bool(self._hicon),
                "uid": self.TRAY_UID,
                "add_attempts": int(self._add_attempts),
                "add_failures": int(self._add_failures),
                "modify_failures": int(self._modify_failures),
                "reregister_count": int(self._reregister_count),
                "last_error": self._last_error,
            }

    def _delete_icon_locked(self) -> None:
        if self._hwnd and (self._registered or self._visible):
            try:
                nid = self._build_nid(0)
                self._notify_api(NIM_DELETE, nid)
            except Exception:
                pass
        self._registered = False
        self._visible = False

    def stop(self, join_timeout: float = 0.8) -> None:
        """优雅且同步地注销托盘图标并退出消息线程（避免更新 os._exit(0) 前残留僵尸图标）。"""
        with self._lock:
            self._stop_event.set()
            if self._retry_timer is not None:
                try:
                    self._retry_timer.cancel()
                except Exception:
                    pass
                self._retry_timer = None
            # 立即同步发出 NIM_DELETE，确保即便主进程紧接着 os._exit(0) 也能干净卸载托盘图标
            self._delete_icon_locked()
            hwnd = self._hwnd
            thread = self._thread
        if sys.platform == "win32" and hwnd:
            try:
                _user32.PostMessageW(wintypes.HWND(hwnd), WM_TRAY_STOP, 0, 0)
            except Exception:
                pass
        if thread is not None and thread.is_alive() and thread.ident != threading.current_thread().ident:
            thread.join(timeout=max(0.05, float(join_timeout)))
        with self._lock:
            if self._hicon:
                self._icon_destroyer(self._hicon)
                self._hicon = 0
            self._running = False

    def _show_context_menu(self, hwnd: int) -> None:
        """在托盘消息线程内实时构建并展示右键菜单，选定后立即销毁 HMENU 并异步执行回调。"""
        if sys.platform != "win32":
            return
        with self._lock:
            entries = list(self._menu_entries)
        if not entries:
            return
        hmenu = _user32.CreatePopupMenu()
        if not hmenu:
            return
        actions: dict[int, Callable[[], Any]] = {}
        try:
            cmd_id = 1
            pos = 0
            for entry in entries:
                mii = _MENUITEMINFOW()
                mii.cbSize = ctypes.sizeof(_MENUITEMINFOW)
                if entry.separator:
                    mii.fMask = MIIM_FTYPE
                    mii.fType = MFT_SEPARATOR
                else:
                    is_checked = False
                    if entry.checked is not None:
                        try:
                            is_checked = bool(entry.checked())
                        except Exception:
                            is_checked = False
                    state = MFS_ENABLED if entry.enabled else MFS_DISABLED
                    if entry.default:
                        state |= MFS_DEFAULT
                    if is_checked:
                        state |= MFS_CHECKED
                    mii.fMask = MIIM_ID | MIIM_STRING | MIIM_STATE | MIIM_FTYPE
                    mii.fType = MFT_STRING
                    mii.fState = state
                    mii.wID = cmd_id
                    mii.dwTypeData = entry.label
                    if entry.action is not None:
                        actions[cmd_id] = entry.action
                    cmd_id += 1
                _user32.InsertMenuItemW(hmenu, pos, True, ctypes.byref(mii))
                pos += 1

            _user32.SetForegroundWindow(wintypes.HWND(hwnd))
            pt = wintypes.POINT()
            _user32.GetCursorPos(ctypes.byref(pt))
            selected = int(
                _user32.TrackPopupMenuEx(
                    hmenu,
                    TPM_RIGHTALIGN | TPM_BOTTOMALIGN | TPM_RETURNCMD,
                    pt.x,
                    pt.y,
                    wintypes.HWND(hwnd),
                    None,
                )
                or 0
            )
            # 按微软文档建议在 TrackPopupMenuEx 后投递空消息确保菜单焦点彻底退出
            _user32.PostMessageW(wintypes.HWND(hwnd), 0, 0, 0)
        finally:
            _user32.DestroyMenu(hmenu)

        fn = actions.get(selected)
        if fn is not None:
            threading.Thread(target=self._run_action_safe, args=(fn,), daemon=True).start()

    @staticmethod
    def _run_action_safe(fn: Callable[[], Any]) -> None:
        try:
            fn()
        except Exception:
            pass

    def _handle_shell_recreate(self) -> None:
        """处理 Explorer 重启（WM_TASKBARCREATED）或显示变化（WM_DISPLAYCHANGE）：保留现有 HICON 并直接自愈补注册。"""
        with self._lock:
            if self._stop_event.is_set() or not self._hwnd:
                return
            self._registered = False
            if not self._register_icon_locked(is_reregister=True):
                self._schedule_retry_locked(1)

    def _run_loop(self) -> None:
        if sys.platform != "win32":
            with self._lock:
                self._running = True
            self._ready_event.set()
            return

        hinst = _kernel32.GetModuleHandleW(None)
        cls_name = f"BattDockTray_{id(self)}"
        hwnd = 0
        registered_cls = False

        def _wnd_proc(h, msg, wp, lp):
            try:
                if msg == WM_TRAY_STOP:
                    _user32.PostQuitMessage(0)
                    return 0
                if msg == WM_TRAY_CALLBACK:
                    evt = int(lp) & 0xFFFF
                    if evt in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                        if self._on_left_click is not None:
                            threading.Thread(
                                target=self._run_action_safe,
                                args=(self._on_left_click,),
                                daemon=True,
                            ).start()
                        return 0
                    if evt == WM_RBUTTONUP:
                        self._show_context_menu(int(h))
                        return 0
                elif WM_TASKBARCREATED and msg == WM_TASKBARCREATED:
                    self._handle_shell_recreate()
                    return 0
                elif msg == WM_DISPLAYCHANGE:
                    # 显示分辨率或 DPI 缩放变化时仅确保图标在线，绝不先删除图标引发丢失风险
                    with self._lock:
                        if not self._stop_event.is_set() and self._hwnd and self._hicon:
                            nid = self._build_nid(NIF_ICON, hicon=self._hicon)
                            if not self._notify_api(NIM_MODIFY, nid):
                                self._handle_shell_recreate()
                    return 0
                elif msg == WM_DESTROY:
                    _user32.PostQuitMessage(0)
                    return 0
            except Exception:
                pass
            return _user32.DefWindowProcW(h, msg, wp, lp)

        cb = WNDPROC(_wnd_proc)
        self._wndproc_ref = cb
        try:
            wc = _WNDCLASSEXW()
            wc.cbSize = ctypes.sizeof(_WNDCLASSEXW)
            wc.lpfnWndProc = cb
            wc.hInstance = hinst
            wc.lpszClassName = cls_name
            atom = _user32.RegisterClassExW(ctypes.byref(wc))
            if not atom:
                with self._lock:
                    self._last_error = f"RegisterClassExW 失败 (err={ctypes.get_last_error()})"
                self._ready_event.set()
                return
            registered_cls = True
            self._cls_name = cls_name

            hwnd = int(
                _user32.CreateWindowExW(
                    0,
                    cls_name,
                    self._name,
                    WS_POPUP,
                    0,
                    0,
                    0,
                    0,
                    None,
                    None,
                    hinst,
                    None,
                )
                or 0
            )
            if not hwnd:
                with self._lock:
                    self._last_error = f"CreateWindowExW 失败 (err={ctypes.get_last_error()})"
                self._ready_event.set()
                return

            # 允许接收 Explorer 重启广播；在低权限或受限令牌下失败绝不中止托盘启动
            if WM_TASKBARCREATED:
                try:
                    _user32.ChangeWindowMessageFilterEx(
                        wintypes.HWND(hwnd),
                        WM_TASKBARCREATED,
                        MSGFLT_ALLOW,
                        None,
                    )
                except Exception:
                    pass

            with self._lock:
                self._hwnd = hwnd
                self._running = True
                if not self._register_icon_locked(is_reregister=False):
                    self._schedule_retry_locked(1)

            self._ready_event.set()

            msg = wintypes.MSG()
            while not self._stop_event.is_set():
                r = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if r <= 0:
                    break
                _user32.TranslateMessage(ctypes.byref(msg))
                _user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as exc:
            with self._lock:
                self._last_error = f"托盘消息循环异常: {exc}"
            self._ready_event.set()
        finally:
            with self._lock:
                if self._retry_timer is not None:
                    try:
                        self._retry_timer.cancel()
                    except Exception:
                        pass
                    self._retry_timer = None
                self._delete_icon_locked()
                if self._hicon:
                    self._icon_destroyer(self._hicon)
                    self._hicon = 0
                cur_hwnd = self._hwnd
                self._hwnd = 0
                self._running = False
            if cur_hwnd:
                try:
                    _user32.DestroyWindow(wintypes.HWND(cur_hwnd))
                except Exception:
                    pass
            if registered_cls:
                try:
                    _user32.UnregisterClassW(cls_name, hinst)
                except Exception:
                    pass
            self._wndproc_ref = None
