"""通用标准 USB HID Battery Strength (Usage Page 0x06, Usage 0x20) 只读电量适配器。

协议说明（独立只读 Python 实现，参考 MIT 许可项目 qu1ncky/BatteryTray）：
- 面向任意声明了标准 USB HID 电池字段（Generic Device Controls Page `0x06`, Usage `0x20` Battery Strength）
  的 2.4G 无线接收器（键盘、耳机、鼠标等），Windows 系统界面本身不展示该字段。
- 仅使用零读写权限句柄（`CreateFileW(..., 0, FILE_SHARE_READ | FILE_SHARE_WRITE, ...)`）执行纯只读
  `HidD_GetFeature` + `HidP_GetUsageValue`，绝不写入设备、不占用键鼠输入通道、不触发副作用。
- 自动跳过已由专用品牌适配器接管的厂商 VID 及 BLE GATT 设备（`{00001812-}` 交由蓝牙适配器处理）。
"""

from __future__ import annotations

import ctypes
import struct
import sys
import time
from ctypes import wintypes
from typing import Optional

from .base import (
    BatteryProvider,
    DeviceBattery,
    KIND_HEADSET,
    KIND_KEYBOARD,
    KIND_MOUSE,
    KIND_OTHER,
    STATUS_PROTOCOL,
    get_hid_report_lengths,
)

GENERIC_DEVICE_PAGE = 0x0006
BATTERY_STRENGTH_USAGE = 0x0020
HIDP_FEATURE = 2
HIDP_STATUS_SUCCESS = 0x00110000

# 已由专用品牌适配器覆盖的厂商 VID（避免重复查询或重复显示）
DEDICATED_VENDOR_IDS = {
    0x046D,  # Logitech
    0x1532,  # Razer
    0x1038,  # SteelSeries
    0x1B1C,  # Corsair
    0x03F0,  # HP / HyperX
    0x0951,  # Kingston / HyperX
    0x054C,  # Sony
    0x0B05,  # ASUS ROG
    0x3554,  # VGN / CompX
}

_BRAND_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("ikf", "iKF"),
    ("edifier", "Edifier"),
    ("hecate", "Edifier"),
    ("keychron", "Keychron"),
    ("nuphy", "NuPhy"),
    ("royal kludge", "Royal Kludge"),
    ("rk ", "Royal Kludge"),
    ("rk-", "Royal Kludge"),
    ("dareu", "DAREU"),
    ("akko", "Akko"),
    ("melgeek", "MelGeek"),
    ("lofree", "Lofree"),
    ("wobkey", "WOBKEY"),
    ("cidoo", "CIDOO"),
    ("leobog", "LEOBOG"),
    ("aula", "AULA"),
    ("ajazz", "AJAZZ"),
    ("mchose", "MCHOSE"),
    ("attack shark", "Attack Shark"),
    ("epomaker", "EPOMAKER"),
    ("moondrop", "MOONDROP"),
    ("rapoo", "Rapoo"),
    ("cherry", "CHERRY"),
    ("vgn", "VGN"),
    ("vxe", "VXE"),
    ("atk", "ATK"),
    ("jbl", "JBL"),
    ("bose", "Bose"),
    ("sennheiser", "Sennheiser"),
    ("jabra", "Jabra"),
    ("poly", "Poly"),
    ("alienware", "Alienware"),
    ("lenovo", "Lenovo"),
    ("xiaomi", "Xiaomi"),
    ("huawei", "HUAWEI"),
    ("dell", "Dell"),
    ("hp ", "HP"),
)


def scale_hid_battery_value(raw: int, logical_min: int, logical_max: int) -> Optional[int]:
    """按 HID 报告描述符中的 LogicalMin..LogicalMax 映射为 1..100%，0 或越界视为无效读数。"""
    lo, hi = (0, 100) if logical_max <= logical_min else (int(logical_min), int(logical_max))
    pct = int(round((int(raw) - lo) * 100.0 / float(hi - lo)))
    if 1 <= pct <= 100:
        return pct
    return None


def infer_standard_hid_brand_and_kind(
    product_name: str,
    usage_page: int = 0,
    usage: int = 0,
) -> tuple[str, str]:
    """根据产品名称与顶层 HID Usage 推断规范品牌名与设备类型。"""
    low = (product_name or "").strip().lower()
    brand = "Wireless"
    for kw, b in _BRAND_KEYWORDS:
        if kw in low:
            brand = b
            break

    kind = KIND_OTHER
    if any(k in low for k in ("ikf", "headset", "headphone", "audio", "earbud", "buds", "hecate", "moondrop", "耳机", "耳麦")):
        kind = KIND_HEADSET
    elif any(k in low for k in ("keyboard", "keychron", "nuphy", "royal kludge", "akko", "lofree", "melgeek", "wobkey", "cidoo", "leobog", "键盘")):
        kind = KIND_KEYBOARD
    elif any(k in low for k in ("mouse", "鼠标")):
        kind = KIND_MOUSE
    elif usage_page == 0x0001:
        if usage == 0x0002:
            kind = KIND_MOUSE
        elif usage == 0x0006:
            kind = KIND_KEYBOARD
    elif usage_page == 0x000C:
        kind = KIND_HEADSET
    return brand, kind


def read_standard_hid_battery_strength(path: bytes, feature_len: int) -> Optional[int]:
    """Windows 纯只读查询标准 HID Feature Report Battery Strength (0x06:0x20)。"""
    if sys.platform != "win32" or not path or feature_len <= 0:
        return None
    try:
        p_str = path.decode("utf-8", "ignore") if isinstance(path, (bytes, bytearray)) else str(path)
        k32 = ctypes.windll.kernel32
        hid_dll = ctypes.windll.hid

        k32.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
        ]
        k32.CreateFileW.restype = ctypes.c_void_p
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        k32.CloseHandle.restype = wintypes.BOOL

        hid_dll.HidD_GetPreparsedData.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        hid_dll.HidD_GetPreparsedData.restype = wintypes.BOOLEAN
        hid_dll.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
        hid_dll.HidD_FreePreparsedData.restype = wintypes.BOOLEAN
        hid_dll.HidD_GetFeature.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.ULONG]
        hid_dll.HidD_GetFeature.restype = wintypes.BOOLEAN
        hid_dll.HidP_GetSpecificValueCaps.argtypes = [
            ctypes.c_int,
            wintypes.USHORT,
            wintypes.USHORT,
            wintypes.USHORT,
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.USHORT),
            ctypes.c_void_p,
        ]
        hid_dll.HidP_GetSpecificValueCaps.restype = ctypes.c_long
        hid_dll.HidP_GetUsageValue.argtypes = [
            ctypes.c_int,
            wintypes.USHORT,
            wintypes.USHORT,
            wintypes.USHORT,
            ctypes.POINTER(wintypes.ULONG),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.ULONG,
        ]
        hid_dll.HidP_GetUsageValue.restype = ctypes.c_long

        invalid = ctypes.c_void_p(-1).value
        handle = k32.CreateFileW(p_str, 0, 3, None, 3, 0, None)
        if not handle or handle == invalid:
            return None
        try:
            pre = ctypes.c_void_p(0)
            if not hid_dll.HidD_GetPreparsedData(handle, ctypes.byref(pre)) or not pre.value:
                return None
            try:
                max_caps = 16
                # HIDP_VALUE_CAPS 固定 72 字节
                caps_buf = (ctypes.c_ubyte * (72 * max_caps))()
                count = wintypes.USHORT(max_caps)
                st = hid_dll.HidP_GetSpecificValueCaps(
                    HIDP_FEATURE,
                    GENERIC_DEVICE_PAGE,
                    0,
                    BATTERY_STRENGTH_USAGE,
                    caps_buf,
                    ctypes.byref(count),
                    pre,
                )
                if st != HIDP_STATUS_SUCCESS or count.value == 0:
                    return None

                raw_cap = bytes(caps_buf[:72])
                report_id = raw_cap[2]
                link_collection = struct.unpack_from("<H", raw_cap, 6)[0]
                logical_min = struct.unpack_from("<i", raw_cap, 40)[0]
                logical_max = struct.unpack_from("<i", raw_cap, 44)[0]

                rep_buf = (ctypes.c_ubyte * feature_len)()
                rep_buf[0] = report_id
                if not hid_dll.HidD_GetFeature(handle, rep_buf, feature_len):
                    return None

                val = wintypes.ULONG(0)
                st2 = hid_dll.HidP_GetUsageValue(
                    HIDP_FEATURE,
                    GENERIC_DEVICE_PAGE,
                    link_collection,
                    BATTERY_STRENGTH_USAGE,
                    ctypes.byref(val),
                    pre,
                    rep_buf,
                    feature_len,
                )
                if st2 != HIDP_STATUS_SUCCESS:
                    return None
                return scale_hid_battery_value(int(val.value), logical_min, logical_max)
            finally:
                hid_dll.HidD_FreePreparsedData(pre)
        finally:
            k32.CloseHandle(handle)
    except Exception:
        return None


class StandardHidBatteryProvider(BatteryProvider):
    """通用标准 USB HID 电池字段 (0x06:0x20) 兜底只读适配器（120 秒节流）。"""

    name = "standard_hid"
    brand = "Standard HID"
    THROTTLE_SEC = 120.0

    def __init__(self) -> None:
        self._last_poll_mono: float = 0.0
        self._cached: list[DeviceBattery] = []

    def poll(self, hid_snapshot: list[dict], force: bool = False) -> list[DeviceBattery]:
        now_mono = time.monotonic()
        if not force and self._last_poll_mono > 0 and (now_mono - self._last_poll_mono) < self.THROTTLE_SEC:
            return list(self._cached)

        out: list[DeviceBattery] = []
        seen_vp: set[tuple[int, int]] = set()
        for d in hid_snapshot:
            vid = int(d.get("vendor_id", 0))
            pid = int(d.get("product_id", 0))
            if vid == 0 or vid in DEDICATED_VENDOR_IDS or (vid, pid) in seen_vp:
                continue
            path = d.get("path")
            if not path:
                continue
            path_bytes = path if isinstance(path, (bytes, bytearray)) else str(path).encode("utf-8", "ignore")
            # 跳过 BLE HID（Windows 蓝牙服务已由 BluetoothBatteryProvider 处理）
            if b"{00001812-" in path_bytes.lower():
                continue
            _, _, feat_len = get_hid_report_lengths(path_bytes)
            if feat_len <= 0:
                continue
            pct = read_standard_hid_battery_strength(path_bytes, feat_len)
            if pct is None:
                continue
            seen_vp.add((vid, pid))
            prod = str(d.get("product_string") or "").strip() or f"HID {vid:04X}:{pid:04X}"
            brand, kind = infer_standard_hid_brand_and_kind(
                prod,
                int(d.get("usage_page", 0)),
                int(d.get("usage", 0)),
            )
            out.append(
                DeviceBattery(
                    device_id=f"stdhid:{vid:04x}:{pid:04x}",
                    name=prod,
                    brand=brand,
                    kind=kind,
                    connection_mode="2.4G",
                    vid=vid,
                    pid=pid,
                    connected=True,
                    online=True,
                    asleep=False,
                    percent=pct,
                    charging=False,
                    support_status=STATUS_PROTOCOL,
                    provider_name=self.name,
                )
            )
        self._last_poll_mono = now_mono
        self._cached = out
        return out
