"""统一外设电量数据模型、协议适配器基类与安全 HID 辅助函数。"""

from __future__ import annotations

import ctypes
import math
import struct
import sys
import time
from abc import ABC, abstractmethod
from ctypes import wintypes
from dataclasses import asdict, dataclass, field
from typing import Optional

import hid

# 设备类型常量
KIND_MOUSE = "mouse"
KIND_HEADSET = "headset"
KIND_EARBUDS = "earbuds"
KIND_KEYBOARD = "keyboard"
KIND_OTHER = "other"

# 兼容性验证状态（严格区分三类，绝不虚报真实硬件验证）
STATUS_VERIFIED = "verified_hardware"   # 已在真实硬件上验证
STATUS_PROTOCOL = "protocol_ready"      # 协议已实现，待实机验证
STATUS_UNSUPPORTED = "unsupported"      # 暂不支持读取真实电量


@dataclass
class SubBattery:
    """分体式设备独立电量（如 AirPods / Sony INZONE Buds 的左耳、右耳、充电盒）。"""

    left_percent: Optional[int] = None
    left_charging: bool = False
    right_percent: Optional[int] = None
    right_charging: bool = False
    case_percent: Optional[int] = None
    case_charging: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DeviceBattery:
    """跨品牌、跨协议的统一设备电量快照。"""

    device_id: str
    name: str
    brand: str
    kind: str = KIND_MOUSE
    connection_mode: str = "2.4G"
    vid: Optional[int] = None
    pid: Optional[int] = None
    connected: bool = True
    online: bool = False
    asleep: bool = False
    percent: Optional[int] = None  # None 表示未知/未响应，绝不用 0 冒充离线
    charging: bool = False
    full: bool = False
    voltage_mv: Optional[int] = None
    sub_batteries: Optional[SubBattery] = None
    support_status: str = STATUS_PROTOCOL
    status_detail: str = ""
    provider_name: str = ""
    raw_name: str = ""  # 底层硬件/协议原始上报名称（保留用于诊断与追溯）
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


class BatteryProvider(ABC):
    """所有品牌/协议适配器的统一抽象基类。"""

    name: str = "base"
    brand: str = "Generic"

    @abstractmethod
    def poll(self, hid_snapshot: list[dict]) -> list[DeviceBattery]:
        """根据共享 HID 快照返回当前检测到的设备电量列表（禁止向未知设备盲发写入）。"""

    def stop(self) -> None:
        """可选释放后台监听器或常驻只读句柄（如 BLE Watcher / Sony PULSE 3D）。"""

    def on_device_change(self) -> None:
        """硬件热插拔拓扑变更时触发，供常驻句柄类适配器安全释放旧句柄。"""

    def on_power_resume(self) -> None:
        """系统进入休眠/挂起或从休眠唤醒时触发，供常驻句柄类适配器彻底释放句柄。"""


# ================= Windows 安全 HID 能力查询（只读，不向设备发送任何报文） =================

class _HIDP_CAPS(ctypes.Structure):
    _fields_ = [
        ("Usage", ctypes.c_ushort),
        ("UsagePage", ctypes.c_ushort),
        ("InputReportByteLength", ctypes.c_ushort),
        ("OutputReportByteLength", ctypes.c_ushort),
        ("FeatureReportByteLength", ctypes.c_ushort),
        ("Reserved", ctypes.c_ushort * 17),
        ("NumberLinkCollectionNodes", ctypes.c_ushort),
        ("NumberInputButtonCaps", ctypes.c_ushort),
        ("NumberInputValueCaps", ctypes.c_ushort),
        ("NumberInputDataIndices", ctypes.c_ushort),
        ("NumberOutputButtonCaps", ctypes.c_ushort),
        ("NumberOutputValueCaps", ctypes.c_ushort),
        ("NumberOutputDataIndices", ctypes.c_ushort),
        ("NumberFeatureButtonCaps", ctypes.c_ushort),
        ("NumberFeatureValueCaps", ctypes.c_ushort),
        ("NumberFeatureDataIndices", ctypes.c_ushort),
    ]


_CAPS_CACHE: dict[bytes, tuple[int, int, int]] = {}
_OUT_RID_CACHE: dict[bytes, Optional[int]] = {}
_HIDP_OUTPUT = 1
_HIDP_STATUS_SUCCESS = 0x00110000


def clear_hid_caps_cache() -> None:
    """硬件热插拔或系统唤醒后清空 HID 报表长度与 Report ID 只读缓存。"""
    _CAPS_CACHE.clear()
    _OUT_RID_CACHE.clear()


def _configure_win32_hid_api(k32, hidd) -> None:
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
    hidd.HidD_GetPreparsedData.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    hidd.HidD_GetPreparsedData.restype = wintypes.BOOLEAN
    hidd.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
    hidd.HidD_FreePreparsedData.restype = wintypes.BOOLEAN
    hidd.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    hidd.HidP_GetCaps.restype = ctypes.c_long


def get_hid_report_lengths(path: bytes) -> tuple[int, int, int]:
    """只读查询某 HID 集合的 (input_len, output_len, feature_len)，失败返回 (0, 0, 0)。"""
    if path in _CAPS_CACHE:
        return _CAPS_CACHE[path]
    if sys.platform != "win32" or not path:
        return (0, 0, 0)
    try:
        p = path.decode("utf-8", "ignore") if isinstance(path, (bytes, bytearray)) else str(path)
        k32 = ctypes.windll.kernel32
        hidd = ctypes.windll.hid
        _configure_win32_hid_api(k32, hidd)
        handle = k32.CreateFileW(p, 0, 3, None, 3, 0, None)  # 无读写访问权限，仅读描述符
        if not handle or handle == ctypes.c_void_p(-1).value:
            return (0, 0, 0)
        try:
            pp = ctypes.c_void_p()
            if not hidd.HidD_GetPreparsedData(ctypes.c_void_p(handle), ctypes.byref(pp)) or not pp.value:
                return (0, 0, 0)
            try:
                caps = _HIDP_CAPS()
                if hidd.HidP_GetCaps(pp, ctypes.byref(caps)) == _HIDP_STATUS_SUCCESS:
                    res = (
                        int(caps.InputReportByteLength),
                        int(caps.OutputReportByteLength),
                        int(caps.FeatureReportByteLength),
                    )
                    _CAPS_CACHE[path] = res
                    return res
            finally:
                hidd.HidD_FreePreparsedData(pp)
        finally:
            k32.CloseHandle(ctypes.c_void_p(handle))
    except Exception:
        pass
    return (0, 0, 0)


def get_hid_output_report_id(path: bytes) -> Optional[int]:
    """只读查询某 HID 集合的输出报告 Report ID（0 表示无编号报告，需补前导 0x00；None 表示无输出报告或查询失败）。"""
    if path in _OUT_RID_CACHE:
        return _OUT_RID_CACHE[path]
    if sys.platform != "win32" or not path:
        return None
    try:
        p = path.decode("utf-8", "ignore") if isinstance(path, (bytes, bytearray)) else str(path)
        k32 = ctypes.windll.kernel32
        hidd = ctypes.windll.hid
        _configure_win32_hid_api(k32, hidd)
        hidd.HidP_GetValueCaps.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(wintypes.USHORT), ctypes.c_void_p]
        hidd.HidP_GetValueCaps.restype = ctypes.c_long
        hidd.HidP_GetButtonCaps.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(wintypes.USHORT), ctypes.c_void_p]
        hidd.HidP_GetButtonCaps.restype = ctypes.c_long

        handle = k32.CreateFileW(p, 0, 3, None, 3, 0, None)
        if not handle or handle == ctypes.c_void_p(-1).value:
            return None
        try:
            pp = ctypes.c_void_p()
            if not hidd.HidD_GetPreparsedData(ctypes.c_void_p(handle), ctypes.byref(pp)) or not pp.value:
                return None
            try:
                caps = _HIDP_CAPS()
                if hidd.HidP_GetCaps(pp, ctypes.byref(caps)) != _HIDP_STATUS_SUCCESS:
                    return None
                if int(caps.OutputReportByteLength) <= 0:
                    _OUT_RID_CACHE[path] = None
                    return None

                # HIDP_VALUE_CAPS / HIDP_BUTTON_CAPS 均固定 72 字节，Byte[2] 为 ReportID
                val_cnt = int(caps.NumberOutputValueCaps)
                if val_cnt > 0:
                    n = min(val_cnt, 32)
                    buf = (ctypes.c_ubyte * (72 * n))()
                    cnt = wintypes.USHORT(n)
                    if hidd.HidP_GetValueCaps(_HIDP_OUTPUT, buf, ctypes.byref(cnt), pp) == _HIDP_STATUS_SUCCESS and cnt.value > 0:
                        rid = int(buf[2])
                        _OUT_RID_CACHE[path] = rid
                        return rid

                btn_cnt = int(caps.NumberOutputButtonCaps)
                if btn_cnt > 0:
                    n = min(btn_cnt, 32)
                    buf = (ctypes.c_ubyte * (72 * n))()
                    cnt = wintypes.USHORT(n)
                    if hidd.HidP_GetButtonCaps(_HIDP_OUTPUT, buf, ctypes.byref(cnt), pp) == _HIDP_STATUS_SUCCESS and cnt.value > 0:
                        rid = int(buf[2])
                        _OUT_RID_CACHE[path] = rid
                        return rid

                # 有 OutputReportByteLength 但描述符未声明编号项，按无 Report ID (0x00) 处理
                _OUT_RID_CACHE[path] = 0
                return 0
            finally:
                hidd.HidD_FreePreparsedData(pp)
        finally:
            k32.CloseHandle(ctypes.c_void_p(handle))
    except Exception:
        pass
    return None


def get_hid_input_report(path: bytes, report_id: int, report_len: int) -> Optional[list[int]]:
    """Windows 只读控制通道 HidD_GetInputReport（零读写权限占用，兼容 Airoha RACE / Alienware / Apple Magic Keyboard）。"""
    if sys.platform != "win32" or not path or report_len < 2:
        return None
    try:
        p = path.decode("utf-8", "ignore") if isinstance(path, (bytes, bytearray)) else str(path)
        k32 = ctypes.windll.kernel32
        hidd = ctypes.windll.hid
        _configure_win32_hid_api(k32, hidd)
        hidd.HidD_GetInputReport.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.ULONG]
        hidd.HidD_GetInputReport.restype = wintypes.BOOLEAN

        handle = k32.CreateFileW(p, 0, 3, None, 3, 0, None)
        if not handle or handle == ctypes.c_void_p(-1).value:
            return None
        try:
            buf = (ctypes.c_ubyte * int(report_len))()
            buf[0] = int(report_id) & 0xFF
            if hidd.HidD_GetInputReport(ctypes.c_void_p(handle), buf, int(report_len)):
                return list(buf)
        finally:
            k32.CloseHandle(ctypes.c_void_p(handle))
    except Exception:
        pass
    return None


def pad_report(length: int, data: list[int] | tuple[int, ...]) -> list[int]:
    """将报文用 0x00 补齐或截断到指定长度。"""
    buf = list(data[:length])
    if len(buf) < length:
        buf.extend([0] * (length - len(buf)))
    return buf


def build_hid_output_report(
    payload: list[int] | tuple[int, ...],
    out_len: int,
    output_report_id: Optional[int] = None,
) -> list[int]:
    """按集合真实 output_report_id 与输出长度自动构造 Windows HID 写入帧（无编号报告自动补前导 0x00）。"""
    data = [int(b) & 0xFF for b in payload]
    if output_report_id is not None:
        rid = int(output_report_id) & 0xFF
        if rid == 0:
            if not data or data[0] != 0x00:
                data = [0x00] + data
        elif not data or data[0] != rid:
            data = [rid] + data
    elif out_len in (9, 17, 21, 33, 65) and data and data[0] != 0x00:
        # 非 Windows 或未查到描述符时的 N+1 长度兜底：补前导 Report ID 0x00
        data = [0x00] + data
    target_len = max(int(out_len), len(data)) if int(out_len) > 0 else len(data)
    return pad_report(target_len, data)


def hid_drain(dev: hid.device, read_len: int = 64, max_reads: int = 4, timeout_ms: int = 10) -> None:
    """清空 HID 接收缓冲区内的残留事件包。"""
    for _ in range(max_reads):
        try:
            if not dev.read(read_len, timeout_ms):
                break
        except OSError:
            break


def round_half_up(value: float) -> int:
    """标准四舍五入（半入整，避免 Python round() 的银行家向偶舍入偏差）。"""
    v = float(value)
    if v >= 0.0:
        return int(math.floor(v + 0.5))
    return -int(math.floor(-v + 0.5))


def map_range(value: int, in_min: int, in_max: int, out_min: int = 0, out_max: int = 100) -> int:
    """线性区间映射并限幅到 [out_min, out_max]（标准四舍五入）。"""
    if in_max <= in_min:
        return out_min
    ratio = (value - in_min) / float(in_max - in_min)
    mapped = round_half_up(out_min + ratio * (out_max - out_min))
    return max(out_min, min(out_max, mapped))


def interpolate_voltage(mv: int, table: list[tuple[int, int]]) -> int:
    """根据降序 (mV, percent) 曲线表分段线性插值计算电量百分比（标准四舍五入）。"""
    if not table:
        return 0
    if mv >= table[0][0]:
        return table[0][1]
    if mv <= table[-1][0]:
        return table[-1][1]
    for i in range(len(table) - 1):
        v_hi, p_hi = table[i]
        v_lo, p_lo = table[i + 1]
        if v_lo <= mv <= v_hi:
            if v_hi == v_lo:
                return p_hi
            ratio = (mv - v_lo) / float(v_hi - v_lo)
            return max(0, min(100, round_half_up(p_lo + ratio * (p_hi - p_lo))))
    return 0
