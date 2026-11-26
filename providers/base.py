"""统一外设电量数据模型、协议适配器基类与安全 HID 辅助函数。"""

from __future__ import annotations

import ctypes
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
        """可选释放后台监听器（如 BLE Watcher）。"""


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
        k32.CreateFileW.restype = ctypes.c_void_p
        handle = k32.CreateFileW(p, 0, 3, None, 3, 0, None)  # 无读写访问权限，仅读描述符
        if handle in (None, ctypes.c_void_p(-1).value):
            return (0, 0, 0)
        try:
            pp = ctypes.c_void_p()
            if not hidd.HidD_GetPreparsedData(ctypes.c_void_p(handle), ctypes.byref(pp)):
                return (0, 0, 0)
            try:
                caps = _HIDP_CAPS()
                if hidd.HidP_GetCaps(pp, ctypes.byref(caps)) == 0x00110000:
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


def pad_report(length: int, data: list[int] | tuple[int, ...]) -> list[int]:
    """将报文用 0x00 补齐或截断到指定长度。"""
    buf = list(data[:length])
    if len(buf) < length:
        buf.extend([0] * (length - len(buf)))
    return buf


def hid_drain(dev: hid.device, read_len: int = 64, max_reads: int = 4, timeout_ms: int = 10) -> None:
    """清空 HID 接收缓冲区内的残留事件包。"""
    for _ in range(max_reads):
        try:
            if not dev.read(read_len, timeout_ms):
                break
        except OSError:
            break


def map_range(value: int, in_min: int, in_max: int, out_min: int = 0, out_max: int = 100) -> int:
    """线性区间映射并限幅到 [out_min, out_max]。"""
    if in_max <= in_min:
        return out_min
    ratio = (value - in_min) / float(in_max - in_min)
    mapped = int(round(out_min + ratio * (out_max - out_min)))
    return max(out_min, min(out_max, mapped))


def interpolate_voltage(mv: int, table: list[tuple[int, int]]) -> int:
    """根据降序 (mV, percent) 曲线表分段线性插值计算电量百分比。"""
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
            return max(0, min(100, int(round(p_lo + ratio * (p_hi - p_lo)))))
    return 0
