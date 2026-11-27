"""多品牌无线键盘只读 HID 电量适配器（CompX BY / SONiX / Evision / Semico / MCHOSE / Alienware / Apple Magic Keyboard）。

协议参考说明（独立只读 Python 实现，严禁写入设置/灯光/固件）：
- 协议字段规范参考自 MIT 许可开源项目 `qu1ncky/BatteryTray` 与 `JKWTCN/BatteryMonitor`，
  详情记录于 `THIRD_PARTY_LICENSES.md`。
- 键盘电量变化较慢且部分 2.4G 接收器（如 CompX FA09 / Evision 320F:5088 / MCHOSE K87 V3）在高频轮询时会重置休眠计时，
  因此本适配器内置键盘低打扰节流策略（在线常规轮询默认每 180 秒查询一次，手动刷新立即穿透）。
"""

from __future__ import annotations

import ctypes
import sys
import time
from typing import Optional

import hid

from .base import (
    BatteryProvider,
    DeviceBattery,
    KIND_KEYBOARD,
    STATUS_PROTOCOL,
    get_hid_input_report,
    get_hid_report_lengths,
    hid_drain,
    make_cached_device,
    pad_report,
)

# ================= 1. CompX BY 2.4G 无线键盘 (Report ID 0x13, 20B, FF02:0002) =================
# 覆盖 AULA F75 / F75 Max、MCHOSE G75/G87/K87/K99/G98/X75/Z75/GX87、VGN V98 Pro V3/V87 V2/N75 V2/V108、Redragon Horus Pro

COMPX_KB_RECEIVERS: dict[tuple[int, int], tuple[str, str, bool, bool]] = {
    # (vid, pid): (默认型号名, 品牌, 是否支持型号查询0x05, 是否共享ID需精确20B匹配)
    (0x3554, 0xFA09): ("2.4G 无线键盘", "AULA / MCHOSE", True, False),
    (0x3554, 0xFB40): ("AULA F75 Max", "AULA", False, True),
    (0x41E4, 0x2001): ("MCHOSE 无线键盘", "MCHOSE", True, True),
    (0x05AC, 0x024F): ("无线键盘", "MCHOSE / AULA", True, True),
    (0x258A, 0x024F): ("VGN V98 Pro V3", "VGN", False, True),
    (0x258A, 0x027F): ("VGN V98 Pro V3", "VGN", False, True),
    (0x258A, 0x027B): ("VGN V87 V2", "VGN", False, True),
    (0x391D, 0x2A01): ("VGN N75 V2", "VGN", False, True),
    (0x391D, 0x2A02): ("VGN V108", "VGN", False, True),
}

COMPX_KB_MODEL_CODES: dict[bytes, tuple[str, str]] = {
    bytes([0x03, 0x00, 0x00, 0x00, 0x02, 0x1C]): ("MCHOSE G87", "MCHOSE"),
    bytes([0x03, 0x00, 0x00, 0x00, 0x00, 0x77]): ("MCHOSE K99", "MCHOSE"),
    bytes([0x03, 0x00, 0x00, 0x00, 0x01, 0xDF]): ("MCHOSE K99 V2", "MCHOSE"),
    bytes([0x03, 0x00, 0x00, 0x00, 0x01, 0x32]): ("MCHOSE G98", "MCHOSE"),
    bytes([0x03, 0x00, 0x00, 0x00, 0x00, 0xD6]): ("MCHOSE X75", "MCHOSE"),
    bytes([0x0A, 0x00, 0x00, 0x00, 0x00, 0x03]): ("MCHOSE G98 Pro", "MCHOSE"),
    bytes([0x03, 0x00, 0x00, 0x00, 0x01, 0xC6]): ("MCHOSE X75 V2", "MCHOSE"),
    bytes([0x03, 0x00, 0x00, 0x00, 0x01, 0x15]): ("MCHOSE G75 Pro", "MCHOSE"),
    bytes([0x0A, 0x00, 0x00, 0x00, 0x00, 0x18]): ("MCHOSE G98 V2", "MCHOSE"),
    bytes([0x0A, 0x00, 0x00, 0x00, 0x00, 0x2B]): ("MCHOSE UT98", "MCHOSE"),
    bytes([0x0A, 0x00, 0x00, 0x00, 0x00, 0x01]): ("MCHOSE Z75", "MCHOSE"),
    bytes([0x0A, 0x00, 0x00, 0x00, 0x00, 0x09]): ("MCHOSE Z75S", "MCHOSE"),
    bytes([0x03, 0x00, 0x00, 0x00, 0x01, 0xC7]): ("MCHOSE KX75", "MCHOSE"),
    bytes([0x03, 0x00, 0x00, 0x00, 0x01, 0x74]): ("MCHOSE GX87", "MCHOSE"),
    bytes([0x03, 0x00, 0x00, 0x00, 0x01, 0xED]): ("MCHOSE GX87 V2", "MCHOSE"),
    bytes([0x03, 0x00, 0x00, 0x00, 0x01, 0x35]): ("MCHOSE K87", "MCHOSE"),
    bytes([0x03, 0x00, 0x00, 0x00, 0x03, 0x35]): ("MCHOSE G75 V2", "MCHOSE"),
    bytes([0x0A, 0x00, 0x00, 0x00, 0x00, 0x34]): ("MCHOSE G87 V2", "MCHOSE"),
    bytes([0x03, 0x00, 0x00, 0x00, 0x00, 0x6A]): ("Redragon Horus Pro", "Redragon"),
    bytes([0x03, 0x00, 0x00, 0x00, 0x03, 0xDA]): ("Redragon Horus Pro V2", "Redragon"),
}


def build_compx_kb_request(cmd: int) -> list[int]:
    frame = [0x13, cmd & 0xFF, 0x01] + [0x00] * 17
    frame[19] = sum(frame[:19]) & 0xFF
    return frame


def parse_compx_kb_battery(raw: list[int] | bytes) -> Optional[tuple[int, bool]]:
    """解析 CompX BY 键盘 20 字节 Report 0x13 电量回包 -> (percent, charging)。"""
    r = list(raw)
    if len(r) < 20 or r[0] != 0x13 or (r[1] & 0x7F) != 0x4A:
        return None
    if not any(r[4:19]):
        return None
    pct = int(r[5])
    if not (1 <= pct <= 100):
        return None
    charging = (r[6] >> 4) == 1
    return (pct, charging)


def parse_compx_kb_model(raw: list[int] | bytes) -> Optional[tuple[str, str]]:
    """解析 CompX BY 键盘 0x05 型号编码回包 -> (model_name, brand)。"""
    r = bytes(raw)
    if len(r) < 20 or r[0] != 0x13 or (r[1] & 0x7F) != 0x05:
        return None
    for off in (5, 4):
        code = r[off : off + 6]
        if code in COMPX_KB_MODEL_CODES:
            return COMPX_KB_MODEL_CODES[code]
    return None


# ================= 2. SONiX 2.4G 无线键盘 (33B, FF60:0061 / FF80:0001) =================
# 覆盖 Attack Shark X85、EWEADN X87、AJAZZ AK820 Pro / MAX、AULA F87 Pro V2 / F99 MAX、EPOMAKER EA75

SONIX_DONGLES: dict[tuple[int, int], tuple[int, int, bool]] = {
    # (vid, pid): (usage_page, usage, shared_requires_iface3)
    (0x0C45, 0xFEFE): (0xFF60, 0x0061, False),
    (0x0C45, 0xFDFD): (0xFF60, 0x0061, False),
    (0x0C45, 0xFEFC): (0xFF80, 0x0001, False),
    (0x05AC, 0x024F): (0xFF60, 0x0061, True),  # 仅限 Interface 3，绝不误触 QMK/VIA Interface 1
}


def build_sonix_battery_request() -> list[int]:
    r = [0x00] * 33
    r[1] = 0x20
    r[2] = 0x01
    r[32] = sum(r[:32]) & 0xFF
    return r


def build_sonix_info_request() -> list[int]:
    r = [0x00] * 33
    r[1] = 0xAA
    r[2] = 0x10
    r[3] = 0x18
    return r


def parse_sonix_battery_reply(raw: list[int] | bytes) -> Optional[int]:
    """解析 SONiX `20 01 00 LL` 回包（兼容含/不含前导 Report ID 0x00）。"""
    r = list(raw)
    off = 1 if (len(r) >= 5 and r[0] == 0x00 and r[1] == 0x20) else 0
    if len(r) < off + 4:
        return None
    if r[off] != 0x20 or r[off + 1] != 0x01 or r[off + 2] != 0x00:
        return None
    pct = int(r[off + 3])
    return pct if 1 <= pct <= 100 else None


def parse_sonix_info_reply(raw: list[int] | bytes) -> Optional[int]:
    """解析 SONiX `55 10 ... [25/26]=LL` 设备信息回包（兼容含/不含前导 Report ID 0x00）。"""
    r = list(raw)
    if len(r) >= 27 and r[0] == 0x00 and r[1] == 0x55 and r[2] == 0x10:
        pct = int(r[26])
        return pct if 1 <= pct <= 100 else None
    if len(r) >= 26 and r[0] == 0x55 and r[1] == 0x10:
        pct = int(r[25])
        return pct if 1 <= pct <= 100 else None
    return None


# ================= 3. Evision 方案无线键盘 (Report ID 0x04, FF1C:0092, cmd 0x1A) =================
# 覆盖 CHERRY MX 3.0S / 2.0S / PIXIU 75、ATK V75X / Z87、VGN S99 / V98 Pro / N75 Pro / VXE75 / VXE V87、AJAZZ AK992

EVISION_KEYBOARDS: dict[tuple[int, int], tuple[str, str, str, bool, int]] = {
    # (vid, pid): (name, brand, mode_profile, is_wired, required_iface or -1)
    (0x046A, 0x00EA): ("CHERRY MX 3.0S Wireless", "CHERRY", "cherry", False, -1),
    (0x046A, 0x00E3): ("CHERRY MX 3.0S Wireless", "CHERRY", "cherry", True, -1),
    (0x046A, 0x01E4): ("CHERRY PIXIU 75", "CHERRY", "cherry", False, -1),
    (0x046A, 0x01AC): ("CHERRY MX 2.0S Wireless", "CHERRY", "cherry_mx2", False, -1),
    (0x046A, 0x01E0): ("CHERRY MX 2.0S WL Pro", "CHERRY", "cherry_mx2", False, 1),
    (0x046A, 0x01DE): ("CHERRY MX 2.0S WL Pro", "CHERRY", "cherry_mx2", True, 1),
    (0x373B, 0x1012): ("ATK Z87", "ATK", "atk", False, -1),
    (0x320F, 0x50C3): ("AJAZZ AK992", "AJAZZ", "atk", False, 1),
}

EVISION_5088_NAMES: dict[str, tuple[str, str, str]] = {
    "atk v75x 2.4g dongle": ("ATK V75X", "ATK", "atk"),
    "atk v75x": ("ATK V75X", "ATK", "atk"),
    "vgn s99 2.4g dongle": ("VGN S99", "VGN", "vgn"),
    "vgn s99": ("VGN S99", "VGN", "vgn"),
    "vgn v98pro v2 2.4g dongle": ("VGN V98 Pro V2", "VGN", "vgn"),
    "vgn v98pro v2": ("VGN V98 Pro V2", "VGN", "vgn"),
    "vgn v98 pro 2.4g dongle": ("VGN V98 Pro", "VGN", "vgn"),
    "vgn v98pro": ("VGN V98 Pro", "VGN", "vgn"),
    "vgn n75 pro 2.4g dongle": ("VGN N75 Pro", "VGN", "vgn"),
    "vgn n75 pro": ("VGN N75 Pro", "VGN", "vgn"),
    "vgn vxe75 v2 2.4g dongle": ("VGN VXE75 V2", "VGN", "vgn"),
    "vgn vxe75 v2": ("VGN VXE75 V2", "VGN", "vgn"),
    "vgn vxe75 2.4g dongle": ("VGN VXE75", "VGN", "vgn"),
    "vgn vxe75": ("VGN VXE75", "VGN", "vgn"),
    "vxe v87 2.4g dongle": ("VXE V87", "VXE", "vgn"),
    "vxe v87": ("VXE V87", "VXE", "vgn"),
    "vxe v87 rgb": ("VXE V87", "VXE", "vgn"),
}


def build_evision_request(profile: str, counter_val: int = 1, report_len: int = 64) -> tuple[list[int], int]:
    """构造 Evision 0x04 / 0x1A 电量只读请求，返回 (frame, tag)。"""
    if profile == "cherry":
        args = [0x03, 0x00, 0x00, 0x55]
        tag = (0x1A + sum(args)) & 0xFFFF
    elif profile == "cherry_mx2":
        args = [0x06]
        tag = (0x1A + 0x06) & 0xFFFF
    elif profile == "vgn":
        args = [0x06]
        tag = 0
    else:  # atk
        args = []
        tag = ((counter_val % 0xFFFF) + 1) & 0xFFFF
    pkt = [0x04, tag & 0xFF, (tag >> 8) & 0xFF, 0x1A] + args
    return pad_report(report_len, pkt), tag


def parse_evision_reply(raw: list[int] | bytes, profile: str, tag: int) -> Optional[tuple[bool, Optional[int], bool]]:
    """解析 Evision 0x04 回包 -> (online, percent, charging)，None 表示非目标回包。"""
    r = list(raw)
    if len(r) < 10 or r[0] != 0x04:
        return None
    if profile == "cherry":
        if r[3] != 0x1A:
            return None
        lvl, pwr = int(r[8]), int(r[9])
        return (True, lvl, pwr != 0) if 1 <= lvl <= 100 else (False, None, False)

    if r[1] != (tag & 0xFF) or r[2] != ((tag >> 8) & 0xFF):
        return None
    if r[3] == 0xFF:
        return (False, None, False)  # 休眠
    expected_arg = 0x06 if profile in ("cherry_mx2", "vgn") else None
    if r[3] != 0x1A or r[5] != 0x00 or r[6] != 0x00:
        return None
    if expected_arg is not None and r[4] != expected_arg:
        return None
    lvl, pwr = int(r[8]), int(r[9])
    if 1 <= lvl <= 100 and pwr <= 2:
        return (True, lvl, pwr != 0)
    return (False, None, False)


# ================= 4. Semico 三模 / MCHOSE K87 V3 / Alienware / Apple Magic Keyboard =================

def parse_semico_reply(raw: list[int] | bytes) -> Optional[tuple[bool, Optional[int]]]:
    """解析 Semico `AA 55 CC 33 0E LL SS` -> (online, percent)。"""
    r = list(raw)
    off = 1 if (len(r) >= 8 and r[0] == 0x00 and r[1] == 0xAA) else 0
    if len(r) < off + 7 or r[off : off + 5] != [0xAA, 0x55, 0xCC, 0x33, 0x0E]:
        return None
    lvl, status = int(r[off + 5]), int(r[off + 6])
    if status == 0:
        return (False, None)
    if 1 <= lvl <= 100 and 1 <= status <= 3:
        return (True, lvl)
    return None


def build_mchose_k87_v3_request() -> list[int]:
    pkt = [0x4D, 0x01, 0x01, 0x00, 0x00, 0x09, 0x00, 0x00]
    crc = 0
    for b in pkt[2:]:
        crc ^= b
    pkt.append(crc)
    return pad_report(64, pkt)


def parse_mchose_k87_v3_reply(raw: list[int] | bytes) -> Optional[tuple[bool, Optional[int], bool]]:
    """解析 MCHOSE K87 V3 Report 0x4D 回包 -> (online, percent, charging)。"""
    r = list(raw)
    if len(r) < 10 or r[0] != 0x4D or r[4:6] != [0x00, 0x09]:
        return None
    length = int(r[3])
    if len(r) <= 8 + length:
        return None
    data = r[8 : 8 + length]
    if data == [0xFF]:
        return (False, None, False)
    if length < 20 or data[:4] != [0x37, 0x38, 0x23, 0x20]:
        return None
    crc = 0
    for b in r[2 : 8 + length]:
        crc ^= b
    if r[8 + length] != crc:
        return None
    if data[10] == 0:
        return (False, None, False)
    lvl = int(data[12])
    if 1 <= lvl <= 100:
        return (True, lvl, data[11] == 1)
    return (False, None, False)


def parse_alienware_kb_reply(raw: list[int] | bytes) -> Optional[tuple[int, bool]]:
    """解析 Alienware Pro Wireless Keyboard `0E A1 LL SS` 回包 -> (percent, charging)。"""
    r = list(raw)
    off = 1 if (len(r) >= 5 and r[0] == 0x00 and r[1] == 0x0E) else 0
    if len(r) < off + 4 or r[off] != 0x0E or r[off + 1] != 0xA1:
        return None
    lvl = int(r[off + 2])
    if 1 <= lvl <= 100:
        return (lvl, r[off + 3] == 0x04)
    return None


# ================= 5. Rongyuan (荣元) 2.4G 无线键盘平台 (Feature 0xF7, FFFF:0002) & URX Core75 (VIA 08 00 07) =================
RONGYUAN_RECEIVERS: set[tuple[int, int]] = {
    (0x0DB0, 0x197E), (0x0DB0, 0x8E9A), (0x145F, 0x0376), (0x145F, 0x038D), (0x14A5, 0xC045),
    (0x25AA, 0x2008), (0x25AA, 0x4008), (0x25AA, 0x4018),
    (0x3151, 0x4011), (0x3151, 0x4014), (0x3151, 0x4017), (0x3151, 0x4021), (0x3151, 0x4027), (0x3151, 0x402D), (0x3151, 0x4038),
    (0x3151, 0x5006), (0x3151, 0x5007), (0x3151, 0x5008), (0x3151, 0x5020), (0x3151, 0x5026), (0x3151, 0x502B), (0x3151, 0x5031),
    (0x3151, 0x5037), (0x3151, 0x5038), (0x3151, 0x503D), (0x3151, 0x503F), (0x3151, 0x5040), (0x3151, 0x5042), (0x3151, 0x5045),
    (0x3151, 0x504B), (0x3151, 0x504E), (0x3151, 0x5050), (0x3151, 0x5052), (0x3151, 0x5055), (0x3151, 0x505A),
    (0x342D, 0xE3E0), (0x342D, 0xE3E1), (0x342D, 0xE3E2), (0x342D, 0xE3E6), (0x342D, 0xE3E7), (0x342D, 0xE3E8),
    (0x342D, 0xE3F5), (0x342D, 0xE3F6), (0x342D, 0xE3F7), (0x342D, 0xE3FB), (0x342D, 0xE3FC), (0x342D, 0xE3FD),
    (0x347A, 0xA302), (0x347A, 0xA305),
    (0x374A, 0xA205), (0x374A, 0xA217), (0x374A, 0xA220), (0x374A, 0xA223), (0x374A, 0xA226), (0x374A, 0xA229),
    (0x374A, 0xA234), (0x374A, 0xA237), (0x374A, 0xA251), (0x374A, 0xA263), (0x374A, 0xA268),
    (0x374A, 0xA311), (0x374A, 0xA314), (0x374A, 0xA319), (0x374A, 0xA322), (0x374A, 0xA329), (0x374A, 0xA355),
    (0x379A, 0x1804), (0x379A, 0x1807), (0x38A9, 0x0002),
    (0x38EE, 0x0000), (0x38EE, 0x0002), (0x38EE, 0x0004), (0x38EE, 0x0039),
    (0x391D, 0x1A04), (0x391D, 0x1A08), (0x391D, 0x1A0E), (0x391D, 0x1A13), (0x391D, 0x1A25), (0x391D, 0x1A2B),
    (0x391D, 0x1A34), (0x391D, 0x2017), (0x391D, 0x2A05),
    (0x39AB, 0x7000), (0x39AB, 0x7003), (0x39AB, 0x7006), (0x39AB, 0x7007), (0x39AB, 0x7008), (0x39AB, 0x7009),
}


def parse_rongyuan_status(raw: list[int] | bytes) -> Optional[dict[str, Optional[int] | bool]]:
    """解析荣元 2.4G 接收器 Feature 0xF7 回包 `[00, canRead, kbBat, mouseBat, kbOffline, mouseOffline, canSend]`。"""
    r = list(raw)
    if len(r) < 7:
        return None
    if not any(r[2:7]):
        return None
    kb_online = r[4] == 0
    mouse_online = r[5] == 0
    kb_pct = int(r[2]) if (kb_online and 1 <= r[2] <= 100) else None
    mouse_pct = int(r[3]) if (mouse_online and 1 <= r[3] <= 100) else None
    return {
        "kb_online": kb_online,
        "kb_percent": kb_pct,
        "mouse_online": mouse_online,
        "mouse_percent": mouse_pct,
    }


def parse_urx_via_battery(raw: list[int] | bytes) -> Optional[int]:
    """解析 URX Core75 VIA `08 00 07 LL` 回包 -> percent。"""
    r = list(raw)
    off = 1 if (len(r) >= 5 and r[0] == 0x00 and r[1] == 0x08) else 0
    if len(r) < off + 4 or r[off : off + 3] != [0x08, 0x00, 0x07]:
        return None
    lvl = int(r[off + 3])
    return lvl if 1 <= lvl <= 100 else None


APPLE_MAGIC_KB_PIDS: dict[int, str] = {
    0x0267: "Apple Magic Keyboard",
    0x026C: "Apple Magic Keyboard with Numeric Keypad",
    0x029C: "Apple Magic Keyboard",
    0x029A: "Apple Magic Keyboard with Touch ID",
    0x029F: "Apple Magic Keyboard with Touch ID and Numeric Keypad",
    0x0320: "Apple Magic Keyboard",
    0x0321: "Apple Magic Keyboard with Touch ID",
    0x0322: "Apple Magic Keyboard with Touch ID and Numeric Keypad",
}


def parse_apple_magic_keyboard_report(raw: list[int] | bytes) -> Optional[tuple[int, bool, bool]]:
    """解析 Apple Magic Keyboard Input Report 0x90 (`90 SS LL`) -> (percent, charging, full)。"""
    r = list(raw)
    if len(r) < 3 or r[0] != 0x90:
        return None
    status, level = int(r[1]), int(r[2])
    if not (1 <= level <= 100):
        return None
    charger = bool(status & 0x02)
    return (level, charger and level < 100, charger and level == 100)


def _get_win32_input_report(path: bytes, report_id: int, report_len: int) -> Optional[list[int]]:
    """兼容别名：调用 providers.base.get_hid_input_report 只读控制通道。"""
    return get_hid_input_report(path, report_id, report_len)


def _infer_kb_brand(name: str, fallback: str) -> str:
    low = name.lower()
    for kw, b in (
        ("aula", "AULA"),
        ("mchose", "MCHOSE"),
        ("vgn", "VGN"),
        ("vxe", "VXE"),
        ("atk", "ATK"),
        ("ajazz", "AJAZZ"),
        ("attack shark", "Attack Shark"),
        ("epomaker", "EPOMAKER"),
        ("eweadn", "EWEADN"),
        ("cherry", "CHERRY"),
        ("redragon", "Redragon"),
        ("alienware", "Alienware"),
        ("apple", "Apple"),
        ("magic keyboard", "Apple"),
    ):
        if kw in low:
            return b
    return fallback


class WirelessKeyboardsProvider(BatteryProvider):
    """统一多品牌无线键盘只读适配器（内置低打扰节流，避免频繁唤醒休眠键盘）。"""

    name = "wireless_keyboards"
    brand = "Wireless Keyboards"
    THROTTLE_ONLINE_SEC = 180.0  # 键盘耗电缓慢，在线放电每 3 分钟自动查询一次；手动刷新立即穿透
    THROTTLE_CHARGING_SEC = 30.0  # 充电期间缩短至 30 秒，确保充电状态与电量及时同步

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, DeviceBattery]] = {}
        self._compx_models: dict[bytes, tuple[str, str]] = {}
        self._sonix_form: dict[bytes, int] = {}
        self._proven_shared: set[str] = set()
        self._evision_counter: int = 1

    def on_device_change(self) -> None:
        self._cache.clear()
        self._compx_models.clear()
        self._sonix_form.clear()
        self._proven_shared.clear()

    def on_power_resume(self) -> None:
        self._cache.clear()

    def _get_throttled(self, dev_id: str, now_mono: float, force: bool) -> Optional[DeviceBattery]:
        if force:
            return None
        entry = self._cache.get(dev_id)
        if entry is None:
            return None
        ts_mono, cached = entry
        limit = self.THROTTLE_CHARGING_SEC if cached.charging else self.THROTTLE_ONLINE_SEC
        if cached.online and (now_mono - ts_mono) < limit:
            return make_cached_device(
                cached,
                connected=True,
                online=True,
                asleep=False,
                stale=False,
                failure_reason="throttled",
                preserve_charging=True,
            )
        return None

    def _remember(self, dev: DeviceBattery, now_mono: float) -> DeviceBattery:
        if dev.online and not dev.stale:
            if dev.last_success_ts is None:
                dev.last_success_ts = dev.timestamp
            self._cache[dev.device_id] = (now_mono, dev)
        return dev

    def _fallback_asleep(
        self,
        dev_id: str,
        prev_entry: Optional[tuple[float, DeviceBattery]],
        *,
        name: str,
        brand: str,
        vid: int,
        pid: int,
        connection_mode: str = "休眠",
        status_detail: str = "休眠中",
    ) -> DeviceBattery:
        if prev_entry is not None:
            return make_cached_device(
                prev_entry[1],
                connected=True,
                online=False,
                asleep=True,
                connection_mode=connection_mode,
                status_detail=status_detail,
                stale=True,
                failure_reason="device_asleep_or_read_failed",
                preserve_charging=True,
            )
        now_ts = time.time()
        return DeviceBattery(
            device_id=dev_id,
            name=name,
            brand=brand,
            kind=KIND_KEYBOARD,
            connection_mode=connection_mode,
            vid=vid,
            pid=pid,
            connected=True,
            online=False,
            asleep=True,
            percent=None,
            support_status=STATUS_PROTOCOL,
            status_detail=status_detail,
            provider_name=self.name,
            timestamp=now_ts,
            last_success_ts=None,
            from_cache=False,
            stale=True,
        )

    def _poll_compx_keyboards(self, hid_snapshot: list[dict], now_mono: float, force: bool) -> list[DeviceBattery]:
        out: list[DeviceBattery] = []
        grouped: dict[tuple[int, int], list[dict]] = {}
        for d in hid_snapshot:
            vid = int(d.get("vendor_id", 0))
            pid = int(d.get("product_id", 0))
            if (vid, pid) not in COMPX_KB_RECEIVERS:
                continue
            if int(d.get("usage_page", 0)) != 0xFF02 or int(d.get("usage", 0)) != 0x0002:
                continue
            path = d.get("path")
            if not path:
                continue
            _dn, _db, _am, shared = COMPX_KB_RECEIVERS[(vid, pid)]
            in_len, out_len, _ = get_hid_report_lengths(path)
            if shared:
                if in_len != 20 or out_len != 20:
                    continue
            elif in_len < 20 or out_len < 20:
                continue
            grouped.setdefault((vid, pid), []).append(d)

        for (vid, pid), colls in grouped.items():
            default_name, default_brand, ask_model, shared = COMPX_KB_RECEIVERS[(vid, pid)]
            dev_id = f"kb-compx:{vid:04x}:{pid:04x}"
            cached = self._get_throttled(dev_id, now_mono, force)
            if cached is not None:
                out.append(cached)
                continue

            parsed = None
            hit_entry = colls[0]
            for d in colls:
                path = d["path"]
                dev = hid.device()
                try:
                    dev.open_path(path)
                    hid_drain(dev, 20, 4, 5)
                    if ask_model and path not in self._compx_models:
                        dev.write(build_compx_kb_request(0x05))
                        for _ in range(6):
                            raw_m = dev.read(20, 220)
                            if not raw_m:
                                break
                            if not any(raw_m):
                                continue
                            m_info = parse_compx_kb_model(raw_m)
                            if m_info:
                                self._compx_models[path] = m_info
                                break
                    dev.write(build_compx_kb_request(0x4A))
                    for _ in range(8):
                        raw = dev.read(20, 260)
                        if not raw:
                            break
                        if not any(raw):
                            continue
                        parsed = parse_compx_kb_battery(raw)
                        if parsed is not None:
                            hit_entry = d
                            break
                    if parsed is not None:
                        break
                except OSError:
                    continue
                finally:
                    try:
                        dev.close()
                    except Exception:
                        pass

            if parsed is not None:
                self._proven_shared.add(dev_id)
            elif shared and dev_id not in self._proven_shared:
                continue

            hit_path = hit_entry["path"]
            prod_str = str(hit_entry.get("product_string") or "").strip()
            if hit_path in self._compx_models:
                name, brand = self._compx_models[hit_path]
            elif prod_str and prod_str.lower() not in ("2.4g wireless receiver", "2.4g dongle", "usb receiver"):
                name = prod_str
                brand = _infer_kb_brand(prod_str, default_brand)
            else:
                name, brand = default_name, default_brand

            prev = self._cache.get(dev_id)
            if parsed is not None:
                pct, chg = parsed
                now_ts = time.time()
                item = DeviceBattery(
                    device_id=dev_id,
                    name=name,
                    brand=brand,
                    kind=KIND_KEYBOARD,
                    connection_mode="有线" if chg else "2.4G",
                    vid=vid,
                    pid=pid,
                    connected=True,
                    online=True,
                    asleep=False,
                    percent=pct,
                    charging=chg and pct < 100,
                    full=chg and pct >= 100,
                    support_status=STATUS_PROTOCOL,
                    provider_name=self.name,
                    timestamp=now_ts,
                    last_success_ts=now_ts,
                    from_cache=False,
                    stale=False,
                )
                out.append(self._remember(item, now_mono))
            else:
                out.append(self._fallback_asleep(dev_id, prev, name=name, brand=brand, vid=vid, pid=pid))
        return out

    def _poll_sonix_keyboards(self, hid_snapshot: list[dict], now_mono: float, force: bool) -> list[DeviceBattery]:
        out: list[DeviceBattery] = []
        grouped: dict[tuple[int, int], list[dict]] = {}
        for d in hid_snapshot:
            vid = int(d.get("vendor_id", 0))
            pid = int(d.get("product_id", 0))
            if (vid, pid) not in SONIX_DONGLES:
                continue
            req_up, req_u, shared = SONIX_DONGLES[(vid, pid)]
            if int(d.get("usage_page", 0)) != req_up or int(d.get("usage", 0)) != req_u:
                continue
            if shared and int(d.get("interface_number", -1)) != 3:
                continue
            path = d.get("path")
            if not path:
                continue
            in_len, out_len, _ = get_hid_report_lengths(path)
            if in_len != 33 or out_len != 33:
                continue
            grouped.setdefault((vid, pid), []).append(d)

        for (vid, pid), colls in grouped.items():
            _req_up, _req_u, shared = SONIX_DONGLES[(vid, pid)]
            dev_id = f"kb-sonix:{vid:04x}:{pid:04x}"
            cached = self._get_throttled(dev_id, now_mono, force)
            if cached is not None:
                out.append(cached)
                continue

            pct: Optional[int] = None
            hit_entry = colls[0]
            for d in colls:
                path = d["path"]
                forms = [self._sonix_form[path]] if path in self._sonix_form else [0, 1]
                dev = hid.device()
                try:
                    dev.open_path(path)
                    for form in forms:
                        hid_drain(dev, 33, 4, 5)
                        req = build_sonix_battery_request() if form == 0 else build_sonix_info_request()
                        dev.write(req)
                        for _ in range(6):
                            raw = dev.read(33, 220)
                            if not raw:
                                break
                            if not any(raw):
                                continue
                            val = parse_sonix_battery_reply(raw) if form == 0 else parse_sonix_info_reply(raw)
                            if val is not None:
                                pct = val
                                self._sonix_form[path] = form
                                hit_entry = d
                                break
                        if pct is not None:
                            break
                    if pct is not None:
                        break
                except OSError:
                    continue
                finally:
                    try:
                        dev.close()
                    except Exception:
                        pass

            if pct is not None:
                self._proven_shared.add(dev_id)
            elif shared and dev_id not in self._proven_shared:
                continue

            prod = str(hit_entry.get("product_string") or "").strip()
            name = prod if (prod and prod.lower() not in ("2.4g dongle", "2.4g wireless receiver")) else "SONiX 2.4G 无线键盘"
            brand = _infer_kb_brand(name, "SONiX")
            prev = self._cache.get(dev_id)
            if pct is not None:
                now_ts = time.time()
                item = DeviceBattery(
                    device_id=dev_id,
                    name=name,
                    brand=brand,
                    kind=KIND_KEYBOARD,
                    connection_mode="2.4G",
                    vid=vid,
                    pid=pid,
                    connected=True,
                    online=True,
                    asleep=False,
                    percent=pct,
                    support_status=STATUS_PROTOCOL,
                    status_detail="",
                    provider_name=self.name,
                    timestamp=now_ts,
                    last_success_ts=now_ts,
                    from_cache=False,
                    stale=False,
                )
                out.append(self._remember(item, now_mono))
            else:
                out.append(self._fallback_asleep(dev_id, prev, name=name, brand=brand, vid=vid, pid=pid))
        return out

    def _poll_evision_keyboards(self, hid_snapshot: list[dict], now_mono: float, force: bool) -> list[DeviceBattery]:
        out: list[DeviceBattery] = []
        grouped: dict[tuple[int, int], tuple[str, str, str, bool, bool, list[dict]]] = {}
        for d in hid_snapshot:
            vid = int(d.get("vendor_id", 0))
            pid = int(d.get("product_id", 0))
            if int(d.get("usage_page", 0)) != 0xFF1C or int(d.get("usage", 0)) != 0x0092:
                continue
            path = d.get("path")
            if not path:
                continue
            in_len, out_len, _ = get_hid_report_lengths(path)
            prod = str(d.get("product_string") or "").strip()
            prod_low = prod.lower()

            if (vid, pid) in EVISION_KEYBOARDS:
                name, brand, profile, is_wired, req_if = EVISION_KEYBOARDS[(vid, pid)]
                if req_if >= 0 and int(d.get("interface_number", -1)) != req_if:
                    continue
                if in_len != 64 or out_len != 64:
                    continue
                if (vid, pid) == (0x373B, 0x1012) and prod_low != "atk z87 dongle":
                    continue
                shared = (vid == 0x320F) or (vid == 0x373B)
            elif vid == 0x320F and pid in (0x5088, 0x5055) and prod_low in EVISION_5088_NAMES:
                if in_len < 32 or out_len < 32:
                    continue
                name, brand, profile = EVISION_5088_NAMES[prod_low]
                is_wired = pid == 0x5055
                shared = True
            else:
                continue

            entry = grouped.setdefault((vid, pid), (name, brand, profile, is_wired, shared, []))
            entry[5].append(d)

        for (vid, pid), (name, brand, profile, is_wired, shared, colls) in grouped.items():
            dev_id = f"kb-evision:{vid:04x}:{pid:04x}"
            cached = self._get_throttled(dev_id, now_mono, force)
            if cached is not None:
                out.append(cached)
                continue

            parsed = None
            for d in colls:
                path = d["path"]
                in_len, out_len, _ = get_hid_report_lengths(path)
                self._evision_counter = (self._evision_counter % 0xFFFE) + 1
                req, tag = build_evision_request(profile, self._evision_counter, out_len)
                dev = hid.device()
                try:
                    dev.open_path(path)
                    hid_drain(dev, in_len, 4, 5)
                    dev.write(req)
                    for _ in range(8):
                        raw = dev.read(in_len, 240)
                        if not raw:
                            break
                        if not any(raw):
                            continue
                        parsed = parse_evision_reply(raw, profile, tag)
                        if parsed is not None:
                            break
                    if parsed is not None and parsed[0]:
                        break
                except OSError:
                    continue
                finally:
                    try:
                        dev.close()
                    except Exception:
                        pass

            online, pct, chg = parsed if parsed else (False, None, False)
            if online:
                self._proven_shared.add(dev_id)
            elif shared and dev_id not in self._proven_shared:
                continue

            prev = self._cache.get(dev_id)
            if online:
                now_ts = time.time()
                item = DeviceBattery(
                    device_id=dev_id,
                    name=name,
                    brand=brand,
                    kind=KIND_KEYBOARD,
                    connection_mode="有线" if (is_wired or chg) else "2.4G",
                    vid=vid,
                    pid=pid,
                    connected=True,
                    online=True,
                    asleep=False,
                    percent=pct,
                    charging=chg and (pct is None or pct < 100),
                    full=chg and pct == 100,
                    support_status=STATUS_PROTOCOL,
                    status_detail="",
                    provider_name=self.name,
                    timestamp=now_ts,
                    last_success_ts=now_ts,
                    from_cache=False,
                    stale=False,
                )
                out.append(self._remember(item, now_mono))
            else:
                out.append(
                    self._fallback_asleep(
                        dev_id,
                        prev,
                        name=name,
                        brand=brand,
                        vid=vid,
                        pid=pid,
                        connection_mode="有线" if is_wired else "休眠",
                    )
                )
        return out

    def _poll_other_keyboards(self, hid_snapshot: list[dict], now_mono: float, force: bool) -> list[DeviceBattery]:
        out: list[DeviceBattery] = []
        semico_groups: dict[int, list[dict]] = {}
        k87v3_colls: list[dict] = []
        aw_kb_colls: list[dict] = []
        apple_groups: dict[int, list[dict]] = {}
        urx_colls: list[dict] = []
        rongyuan_groups: dict[tuple[int, int], list[dict]] = {}

        for d in hid_snapshot:
            vid = int(d.get("vendor_id", 0))
            pid = int(d.get("product_id", 0))
            path = d.get("path")
            if not path:
                continue
            if vid == 0x1A2C and pid in (0x8FFF, 0xA034, 0xA036):
                if int(d.get("usage_page", 0)) == 0xFF02 and int(d.get("usage", 0)) == 0x0002:
                    in_len, out_len, _ = get_hid_report_lengths(path)
                    if in_len == 65 and out_len == 65:
                        semico_groups.setdefault(pid, []).append(d)
            elif vid == 0x3837 and pid == 0x1015:
                if int(d.get("usage_page", 0)) == 0xFF80 and int(d.get("usage", 0)) == 0x0001:
                    in_len, out_len, _ = get_hid_report_lengths(path)
                    if in_len == 64 and out_len == 64:
                        k87v3_colls.append(d)
            elif vid == 0x413C and pid == 0x211D:
                if int(d.get("usage_page", 0)) == 0xFF00 and int(d.get("usage", 0)) == 0x0001:
                    aw_kb_colls.append(d)
            elif vid in (0x004C, 0x05AC) and pid in APPLE_MAGIC_KB_PIDS:
                if b"{00001124-" in bytes(path).lower():
                    in_len, _, _ = get_hid_report_lengths(path)
                    if in_len >= 3:
                        apple_groups.setdefault(pid, []).append(d)
            elif vid == 0x36B0 and pid == 0x3002:
                prod_str = str(d.get("product_string") or "").strip()
                if (
                    int(d.get("interface_number", -1)) == 1
                    and int(d.get("usage_page", 0)) == 0xFF60
                    and int(d.get("usage", 0)) == 0x0061
                    and prod_str.lower().startswith("urx core75")
                ):
                    in_len, out_len, _ = get_hid_report_lengths(path)
                    if in_len == 33 and out_len == 33:
                        urx_colls.append(d)
            elif (vid, pid) in RONGYUAN_RECEIVERS:
                if (
                    int(d.get("interface_number", -1)) == 2
                    and int(d.get("usage_page", 0)) == 0xFFFF
                    and int(d.get("usage", 0)) == 0x0002
                ):
                    _, _, feat_len = get_hid_report_lengths(path)
                    if feat_len >= 7:
                        rongyuan_groups.setdefault((vid, pid), []).append(d)

        # 1. Semico 三模键盘 (1A2C:8FFF / A034 / A036)
        for pid, colls in semico_groups.items():
            dev_id = f"kb-semico:{pid:04x}"
            cached = self._get_throttled(dev_id, now_mono, force)
            if cached is not None:
                out.append(cached)
                continue
            parsed = None
            hit_entry = colls[0]
            for d in colls:
                dev = hid.device()
                try:
                    dev.open_path(d["path"])
                    hid_drain(dev, 65, 4, 5)
                    dev.write(pad_report(65, [0x00, 0xAA, 0x55, 0xCC, 0x33, 0x0E]))
                    for _ in range(6):
                        raw = dev.read(65, 220)
                        if not raw:
                            break
                        if not any(raw):
                            continue
                        parsed = parse_semico_reply(raw)
                        if parsed is not None:
                            hit_entry = d
                            break
                    if parsed is not None and parsed[0]:
                        break
                except OSError:
                    continue
                finally:
                    try:
                        dev.close()
                    except Exception:
                        pass
            online, pct = parsed if parsed else (False, None)
            if online:
                self._proven_shared.add(dev_id)
            elif dev_id not in self._proven_shared:
                continue
            prev = self._cache.get(dev_id)
            name = {0xA034: "Attack Shark X98", 0xA036: "AJAZZ AK820 Max Plus"}.get(
                pid, str(hit_entry.get("product_string") or "").strip() or "Semico 2.4G 无线键盘"
            )
            brand = _infer_kb_brand(name, "Attack Shark")
            if online:
                now_ts = time.time()
                out.append(
                    self._remember(
                        DeviceBattery(
                            device_id=dev_id,
                            name=name,
                            brand=brand,
                            kind=KIND_KEYBOARD,
                            connection_mode="有线" if pid in (0xA034, 0xA036) else "2.4G",
                            vid=0x1A2C,
                            pid=pid,
                            connected=True,
                            online=True,
                            asleep=False,
                            percent=pct,
                            support_status=STATUS_PROTOCOL,
                            status_detail="",
                            provider_name=self.name,
                            timestamp=now_ts,
                            last_success_ts=now_ts,
                            from_cache=False,
                            stale=False,
                        ),
                        now_mono,
                    )
                )
            else:
                out.append(
                    self._fallback_asleep(
                        dev_id,
                        prev,
                        name=name,
                        brand=brand,
                        vid=0x1A2C,
                        pid=pid,
                        connection_mode="有线" if pid in (0xA034, 0xA036) else "休眠",
                    )
                )

        # 2. MCHOSE K87 V3 (3837:1015, FF80:0001, 64B, Report 0x4D)
        if k87v3_colls:
            dev_id = "kb-mchose:k87v3"
            cached = self._get_throttled(dev_id, now_mono, force)
            if cached is not None:
                out.append(cached)
            else:
                parsed = None
                for d in k87v3_colls:
                    dev = hid.device()
                    try:
                        dev.open_path(d["path"])
                        hid_drain(dev, 64, 4, 5)
                        dev.write(build_mchose_k87_v3_request())
                        for _ in range(8):
                            raw = dev.read(64, 220)
                            if not raw:
                                break
                            if not any(raw):
                                continue
                            parsed = parse_mchose_k87_v3_reply(raw)
                            if parsed is not None:
                                break
                        if parsed is not None and parsed[0]:
                            break
                    except OSError:
                        continue
                    finally:
                        try:
                            dev.close()
                        except Exception:
                            pass
                online, pct, chg = parsed if parsed else (False, None, False)
                if online:
                    self._proven_shared.add(dev_id)
                if dev_id in self._proven_shared:
                    prev = self._cache.get(dev_id)
                    if online:
                        now_ts = time.time()
                        out.append(
                            self._remember(
                                DeviceBattery(
                                    device_id=dev_id,
                                    name="MCHOSE K87 V3",
                                    brand="MCHOSE",
                                    kind=KIND_KEYBOARD,
                                    connection_mode="有线" if chg else "2.4G",
                                    vid=0x3837,
                                    pid=0x1015,
                                    connected=True,
                                    online=True,
                                    asleep=False,
                                    percent=pct,
                                    charging=chg and (pct is None or pct < 100),
                                    full=chg and pct == 100,
                                    support_status=STATUS_PROTOCOL,
                                    status_detail="",
                                    provider_name=self.name,
                                    timestamp=now_ts,
                                    last_success_ts=now_ts,
                                    from_cache=False,
                                    stale=False,
                                ),
                                now_mono,
                            )
                        )
                    else:
                        out.append(
                            self._fallback_asleep(
                                dev_id, prev, name="MCHOSE K87 V3", brand="MCHOSE", vid=0x3837, pid=0x1015
                            )
                        )

        # 3. Alienware Pro Wireless Gaming Keyboard (413C:211D)
        if aw_kb_colls:
            dev_id = "kb-alienware:pro-wireless"
            cached = self._get_throttled(dev_id, now_mono, force)
            if cached is not None:
                out.append(cached)
            else:
                parsed = None
                for d in aw_kb_colls:
                    path = d["path"]
                    in_len, _, feat_len = get_hid_report_lengths(path)
                    flen = max(65, feat_len)
                    rlen = max(65, in_len)
                    dev = hid.device()
                    try:
                        dev.open_path(path)
                        hid_drain(dev, rlen, 4, 5)
                        req = [0x00] * flen
                        req[1], req[2] = 0x0E, 0xA1
                        if dev.send_feature_report(req) > 0:
                            for _ in range(8):
                                raw = dev.read(rlen, 220)
                                if not raw:
                                    break
                                if not any(raw):
                                    continue
                                parsed = parse_alienware_kb_reply(raw)
                                if parsed is not None:
                                    break
                        if parsed is not None:
                            break
                    except OSError:
                        continue
                    finally:
                        try:
                            dev.close()
                        except Exception:
                            pass
                pct, chg = parsed if parsed else (None, False)
                prev = self._cache.get(dev_id)
                if parsed is not None:
                    now_ts = time.time()
                    out.append(
                        self._remember(
                            DeviceBattery(
                                device_id=dev_id,
                                name="Alienware Pro Wireless Gaming Keyboard",
                                brand="Alienware",
                                kind=KIND_KEYBOARD,
                                connection_mode="有线" if chg else "2.4G",
                                vid=0x413C,
                                pid=0x211D,
                                connected=True,
                                online=True,
                                asleep=False,
                                percent=pct,
                                charging=chg and (pct is None or pct < 100),
                                full=chg and pct == 100,
                                support_status=STATUS_PROTOCOL,
                                status_detail="",
                                provider_name=self.name,
                                timestamp=now_ts,
                                last_success_ts=now_ts,
                                from_cache=False,
                                stale=False,
                            ),
                            now_mono,
                        )
                    )
                else:
                    out.append(
                        self._fallback_asleep(
                            dev_id,
                            prev,
                            name="Alienware Pro Wireless Gaming Keyboard",
                            brand="Alienware",
                            vid=0x413C,
                            pid=0x211D,
                        )
                    )

        # 4. Apple Magic Keyboard (Classic Bluetooth HID {00001124-...}, 只读 HidD_GetInputReport 0x90)
        for pid, colls in apple_groups.items():
            dev_id = f"kb-apple:{pid:04x}"
            cached = self._get_throttled(dev_id, now_mono, force)
            if cached is not None:
                out.append(cached)
                continue
            parsed = None
            hit_vid = int(colls[0].get("vendor_id", 0x05AC))
            for d in colls:
                in_len, _, _ = get_hid_report_lengths(d["path"])
                raw = _get_win32_input_report(d["path"], 0x90, max(8, in_len))
                parsed = parse_apple_magic_keyboard_report(raw) if raw else None
                if parsed is not None:
                    hit_vid = int(d.get("vendor_id", hit_vid))
                    break
            if parsed is not None:
                pct, chg, full = parsed
                out.append(
                    self._remember(
                        DeviceBattery(
                            device_id=dev_id,
                            name=APPLE_MAGIC_KB_PIDS[pid],
                            brand="Apple",
                            kind=KIND_KEYBOARD,
                            connection_mode="蓝牙",
                            vid=hit_vid,
                            pid=pid,
                            connected=True,
                            online=True,
                            asleep=False,
                            percent=pct,
                            charging=chg,
                            full=full,
                            support_status=STATUS_PROTOCOL,
                            provider_name=self.name,
                        ),
                        now_mono,
                    )
                )

        # 5. URX Core75 VIA 2.4G 键盘 (36B0:3002)
        if urx_colls:
            dev_id = "kb-urx:core75"
            cached = self._get_throttled(dev_id, now_mono, force)
            if cached is not None:
                out.append(cached)
            else:
                pct = None
                for d in urx_colls:
                    dev = hid.device()
                    try:
                        dev.open_path(d["path"])
                        hid_drain(dev, 33, 4, 5)
                        dev.write(pad_report(33, [0x00, 0x08, 0x00, 0x07]))
                        for _ in range(6):
                            raw = dev.read(33, 220)
                            if not raw:
                                break
                            if not any(raw):
                                continue
                            pct = parse_urx_via_battery(raw)
                            if pct is not None:
                                break
                        if pct is not None:
                            break
                    except OSError:
                        continue
                    finally:
                        try:
                            dev.close()
                        except Exception:
                            pass
                if pct is not None:
                    self._proven_shared.add(dev_id)
                if dev_id in self._proven_shared:
                    prev = self._cache.get(dev_id)
                    if pct is not None:
                        now_ts = time.time()
                        out.append(
                            self._remember(
                                DeviceBattery(
                                    device_id=dev_id,
                                    name="URX Core75",
                                    brand="URX",
                                    kind=KIND_KEYBOARD,
                                    connection_mode="2.4G",
                                    vid=0x36B0,
                                    pid=0x3002,
                                    connected=True,
                                    online=True,
                                    asleep=False,
                                    percent=pct,
                                    support_status=STATUS_PROTOCOL,
                                    status_detail="",
                                    provider_name=self.name,
                                    timestamp=now_ts,
                                    last_success_ts=now_ts,
                                    from_cache=False,
                                    stale=False,
                                ),
                                now_mono,
                            )
                        )
                    else:
                        out.append(
                            self._fallback_asleep(
                                dev_id, prev, name="URX Core75", brand="URX", vid=0x36B0, pid=0x3002
                            )
                        )

        # 6. Rongyuan (荣元) 2.4G 无线键盘/双槽接收器平台 (Interface 2, FFFF:0002, Feature 0xF7)
        for (vid, pid), colls in rongyuan_groups.items():
            kb_id = f"kb-rongyuan:{vid:04x}:{pid:04x}"
            cached = self._get_throttled(kb_id, now_mono, force)
            if cached is not None:
                out.append(cached)
                continue
            status = None
            hit_entry = colls[0]
            for d in colls:
                path = d["path"]
                _, _, feat_len = get_hid_report_lengths(path)
                dev = hid.device()
                try:
                    dev.open_path(path)
                    req = [0x00] * feat_len
                    req[1] = 0xF7
                    for _ in range(2):
                        if dev.send_feature_report(req) > 0:
                            time.sleep(0.025)
                            rep = dev.get_feature_report(0, feat_len)
                            status = parse_rongyuan_status(rep) if rep else None
                            if status is not None:
                                hit_entry = d
                                break
                    if status is not None and status["kb_online"]:
                        break
                except OSError:
                    continue
                finally:
                    try:
                        dev.close()
                    except Exception:
                        pass
            if status and status["kb_online"]:
                self._proven_shared.add(kb_id)
            if kb_id in self._proven_shared:
                kb_on = bool(status and status["kb_online"])
                kb_pct = status["kb_percent"] if (status and kb_on) else None
                prev = self._cache.get(kb_id)
                prod = str(hit_entry.get("product_string") or "").strip()
                name = prod if (prod and prod.lower() not in ("2.4g wireless receiver", "2.4g dongle", "usb receiver")) else "Rongyuan 2.4G 无线键盘"
                brand = _infer_kb_brand(name, "Akko" if vid == 0x38EE else "Attack Shark")
                if kb_on and isinstance(kb_pct, int):
                    now_ts = time.time()
                    out.append(
                        self._remember(
                            DeviceBattery(
                                device_id=kb_id,
                                name=name,
                                brand=brand,
                                kind=KIND_KEYBOARD,
                                connection_mode="2.4G",
                                vid=vid,
                                pid=pid,
                                connected=True,
                                online=True,
                                asleep=False,
                                percent=kb_pct,
                                support_status=STATUS_PROTOCOL,
                                status_detail="",
                                provider_name=self.name,
                                timestamp=now_ts,
                                last_success_ts=now_ts,
                                from_cache=False,
                                stale=False,
                            ),
                            now_mono,
                        )
                    )
                else:
                    out.append(self._fallback_asleep(kb_id, prev, name=name, brand=brand, vid=vid, pid=pid))
        return out

    def poll(self, hid_snapshot: list[dict], force: bool = False) -> list[DeviceBattery]:
        now_mono = time.monotonic()
        out: list[DeviceBattery] = []
        out.extend(self._poll_compx_keyboards(hid_snapshot, now_mono, force))
        out.extend(self._poll_sonix_keyboards(hid_snapshot, now_mono, force))
        out.extend(self._poll_evision_keyboards(hid_snapshot, now_mono, force))
        out.extend(self._poll_other_keyboards(hid_snapshot, now_mono, force))
        present_ids = {d.device_id for d in out}
        for old_id in list(self._cache.keys()):
            if old_id not in present_ids:
                del self._cache[old_id]
        self._proven_shared &= present_ids
        return out
