"""ASUS ROG / TUF 无线外设（鼠标/键盘/Omni接收器/耳机）与 Sony INZONE 系列适配器。

协议参考来源：
- ASUS ROG/TUF 鼠标/键盘/Omni 接收器/耳机协议字段规范参考自 MIT 许可项目
  BatteryMonitor (JKWTCN/BatteryMonitor) 与 BatteryTray (qu1ncky/BatteryTray)。
- Sony INZONE H5 / H9 II / Buds 2.4G 接收器查询协议参考自 MIT 许可项目 BatteryTray。
本模块为独立 Python 只读实现，绝不发送任何设置/写入指令（如 ASUS 0x50/0x51）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import hid

from .base import (
    BatteryProvider,
    DeviceBattery,
    KIND_EARBUDS,
    KIND_HEADSET,
    KIND_KEYBOARD,
    KIND_MOUSE,
    STATUS_PROTOCOL,
    SubBattery,
    get_hid_report_lengths,
    hid_drain,
    interpolate_voltage,
    pad_report,
)

ASUS_VID = 0x0B05
SONY_VID = 0x054C

ASUS_CMD_GET = 0x12
ASUS_SUB_MOUSE = 0x07
ASUS_SUB_KEYBOARD = 0x01
ASUS_OMNI_PID = 0x1ACE
ASUS_SPEEDNOVA_PID = 0x1AD0


@dataclass(frozen=True)
class AsusMouseSpec:
    pid: int
    name: str
    interface: int = 0
    is_wired: bool = False
    level_offset: int = 4
    multiplier: int = 1  # 1 = 直接百分比，25 = 0..4 档位
    charging_offset: int = 9
    cell_battery: bool = False  # 干电池鼠标无充电位


# ASUS ROG / TUF 无线与有线鼠标兼容表（仅匹配已知安全 PID）
ASUS_MICE: dict[int, AsusMouseSpec] = {
    0x1A1A: AsusMouseSpec(0x1A1A, "ROG Chakram X", 0, False),
    0x1A18: AsusMouseSpec(0x1A18, "ROG Chakram X", 0, True),
    0x197F: AsusMouseSpec(0x197F, "ROG Gladius III Wireless", 0, False),
    0x197D: AsusMouseSpec(0x197D, "ROG Gladius III Wireless", 0, True),
    0x1A72: AsusMouseSpec(0x1A72, "ROG Gladius III AimPoint", 0, False),
    0x1A70: AsusMouseSpec(0x1A70, "ROG Gladius III AimPoint", 0, True),
    0x1B0C: AsusMouseSpec(0x1B0C, "ROG Gladius III EVA-02", 0, False),
    0x1B0A: AsusMouseSpec(0x1B0A, "ROG Gladius III EVA-02", 0, True),
    0x1A94: AsusMouseSpec(0x1A94, "ROG Harpe Ace Aim Lab", 0, False),
    0x1A92: AsusMouseSpec(0x1A92, "ROG Harpe Ace Aim Lab", 0, True),
    0x1B67: AsusMouseSpec(0x1B67, "ROG Harpe Ace Extreme", 0, True),
    0x1B63: AsusMouseSpec(0x1B63, "ROG Harpe Ace Mini", 0, True),
    0x1C69: AsusMouseSpec(0x1C69, "ROG Harpe II Ace", 0, True),
    0x1A68: AsusMouseSpec(0x1A68, "ROG Keris Wireless AimPoint", 0, False),
    0x1A66: AsusMouseSpec(0x1A66, "ROG Keris Wireless AimPoint", 0, True),
    0x1B16: AsusMouseSpec(0x1B16, "ROG Keris II Ace", 0, True),
    0x1C0C: AsusMouseSpec(0x1C0C, "ROG Keris II Origin", 0, True),
    0x1D4C: AsusMouseSpec(0x1D4C, "ROG Keris II Origin KJP", 0, True),
    0x1979: AsusMouseSpec(0x1979, "ROG Spatha X", 0, False),
    0x1977: AsusMouseSpec(0x1977, "ROG Spatha X", 0, True),
    0x19F4: AsusMouseSpec(0x19F4, "TUF Gaming M4 Wireless", 0, False),
    0x1A8D: AsusMouseSpec(0x1A8D, "ASUS TX Gaming Mouse", 0, False),
    0x1AF5: AsusMouseSpec(0x1AF5, "ASUS TX Gaming Mini", 0, False),
    0x1AF3: AsusMouseSpec(0x1AF3, "ASUS TX Gaming Mini", 0, True),
    0x1C57: AsusMouseSpec(0x1C57, "TUF Gaming Mini Miku", 0, False),
    0x1C56: AsusMouseSpec(0x1C56, "TUF Gaming Mini Miku", 0, True),
    0x1C5A: AsusMouseSpec(0x1C5A, "ASUS TX Gaming Mini Miku", 0, False),
    0x1A24: AsusMouseSpec(0x1A24, "ASUS SmartO Mouse MD200", 2, False),
    0x1CD3: AsusMouseSpec(0x1CD3, "ASUS ProArt Mouse MD301", 3, False),
    0x1CD5: AsusMouseSpec(0x1CD5, "ASUS ProArt Mouse MD301", 3, True),
    # 老款四档电量鼠标（0..4 -> 0/25/50/75/100%）
    0x18E5: AsusMouseSpec(0x18E5, "ROG Chakram", 0, False, 4, 25),
    0x18E3: AsusMouseSpec(0x18E3, "ROG Chakram", 0, True, 4, 25),
    0x1960: AsusMouseSpec(0x1960, "ROG Keris Wireless", 0, False, 4, 25),
    0x195E: AsusMouseSpec(0x195E, "ROG Keris Wireless", 0, True, 4, 25),
    0x1A59: AsusMouseSpec(0x1A59, "ROG Keris Wireless EVA", 0, False, 4, 25),
    0x1A57: AsusMouseSpec(0x1A57, "ROG Keris Wireless EVA", 0, True, 4, 25),
    0x1908: AsusMouseSpec(0x1908, "ROG Pugio II", 0, False, 4, 25),
    0x1906: AsusMouseSpec(0x1906, "ROG Pugio II", 0, True, 4, 25),
    0x1949: AsusMouseSpec(0x1949, "ROG Strix Impact II Wireless", 0, False, 4, 25),
    0x1947: AsusMouseSpec(0x1947, "ROG Strix Impact II Wireless", 0, True, 4, 25),
    0x18A0: AsusMouseSpec(0x18A0, "ROG Gladius II Wireless", 2, False, 4, 25),
    0x18B4: AsusMouseSpec(0x18B4, "ROG Strix Carry", 1, False, 6, 25, 9, True),
}

# ASUS ROG 无线键盘兼容表（interface 1, usage_page 0xFF00）
ASUS_KEYBOARDS: dict[int, tuple[str, bool, int]] = {
    0x1A85: ("ROG Azoth", False, 5),
    0x1A83: ("ROG Azoth", True, 5),
    0x1B3F: ("ROG Azoth Extreme", True, 5),
    0x1CEF: ("ROG Azoth Extreme SE", True, 5),
    0x1C25: ("ROG Azoth X", False, 5),
    0x1C24: ("ROG Azoth X", True, 5),
    0x193E: ("ROG Falchion", False, 10),
    0x193C: ("ROG Falchion", True, 10),
    0x1B04: ("ROG Falchion RX Low Profile", True, 10),
    0x1AAE: ("ROG Strix Scope II 96 Wireless", True, 5),
    0x1B78: ("ROG Strix Scope II 96 RX Wireless", True, 5),
}

# ROG Omni Receiver 配对表已知 PID -> 名称
OMNI_MICE_NAMES: dict[int, str] = {
    0x1B65: "ROG Harpe Ace Mini",
    0x1C0E: "ROG Keris II Origin",
    0x1D4E: "ROG Keris II Origin KJP",
    0x1A94: "ROG Harpe Ace Aim Lab",
    0x1AD7: "ROG Strix Impact III Wireless",
    0x1A72: "ROG Gladius III AimPoint",
    0x1A68: "ROG Keris Wireless AimPoint",
    0x1A6A: "ROG Keris Wireless AimPoint",
    0x1B1A: "ROG Keris II Ace",
    0x1B18: "ROG Keris II Ace",
    0x1B68: "ROG Harpe Ace Extreme",
    0x1B69: "ROG Harpe Ace Extreme",
}

OMNI_KEYBOARDS_INFO: dict[int, tuple[str, int]] = {
    0x1A85: ("ROG Azoth", 5),
    0x1B42: ("ROG Azoth Extreme", 5),
    0x1CF1: ("ROG Azoth Extreme SE", 5),
    0x1AB0: ("ROG Strix Scope II 96 Wireless", 5),
    0x1B7A: ("ROG Strix Scope II 96 RX Wireless", 5),
    0x1B06: ("ROG Falchion RX Low Profile", 10),
    0x1CEA: ("ROG Strix Morph 96 Wireless", 5),
}

# ASUS ROG 耳机
ASUS_HEADSETS: dict[int, tuple[str, str]] = {
    0x1B84: ("ASUS ROG Pelta", "rog_cc"),
    0x1AFA: ("ASUS ROG Delta II", "rog_cc"),
    0x1D41: ("ASUS ROG Delta II", "rog_cc"),
    0x1AD3: ("ASUS ROG Cetra SpeedNova", "cetra_speednova"),
    0x1CAC: ("ASUS ROG Cetra Open", "cetra_open"),
    0x18D6: ("ASUS ROG Strix Go 2.4", "strix_go"),
}

# Sony INZONE 系列（VID 0x054C）
SONY_INZONE_MODELS: dict[int, tuple[str, str]] = {
    0x0EBF: ("Sony INZONE H5", "h5"),
    0x0FA8: ("Sony INZONE H9 II", "h5"),
    0x0EC2: ("Sony INZONE Buds", "buds"),
}


# ================= 纯函数解析器（便于单元测试） =================

def _strip_report_id(raw: list[int] | bytes, report_id: int) -> list[int]:
    data = list(raw)
    if report_id != 0 and data and data[0] == report_id:
        return data[1:]
    if report_id == 0 and len(data) >= 3 and data[0] == 0x00 and data[1] == ASUS_CMD_GET:
        return data[1:]
    return data


def parse_asus_mouse_reply(
    raw: list[int] | bytes,
    report_id: int = 0x00,
    level_offset: int = 4,
    multiplier: int = 1,
    charging_offset: int = 9,
    cell_battery: bool = False,
) -> tuple[bool, bool, Optional[int], bool, str]:
    """解析 ASUS ROG 鼠标回包 -> (online, asleep, percent, charging, detail)。"""
    body = _strip_report_id(raw, report_id)
    if len(body) >= 2 and (body[:2] == [0xFF, 0xAA] or body[:3] == [0x00, 0x00, 0x00]):
        return (False, True, None, False, "设备休眠中")
    req_len = max(level_offset, charging_offset) + 1
    if len(body) < req_len or body[0] != ASUS_CMD_GET or body[1] != ASUS_SUB_MOUSE:
        return (False, False, None, False, "未响应")

    raw_val = body[level_offset]
    charging = (not cell_battery) and (body[charging_offset] != 0)
    if multiplier == 25:
        if raw_val > 4:
            return (True, False, None, charging, "电量未知")
        pct = raw_val * 25
    else:
        if raw_val > 100:
            return (True, False, None, charging, "电量未知")
        pct = raw_val

    # ASUS 接收器在鼠标休眠/待机时会返回 0，绝不冒充 0% 电量
    if pct == 0 and not charging:
        return (False, True, None, False, "设备休眠中")
    if pct == 0 and charging:
        return (True, False, None, True, "充电中（电量读取中）")
    return (True, False, pct, charging, "")


def parse_asus_keyboard_reply(
    raw: list[int] | bytes,
    report_id: int = 0x00,
    level_offset: int = 5,
) -> tuple[bool, bool, Optional[int], bool, str]:
    """解析 ASUS ROG 键盘回包 -> (online, asleep, percent, charging, detail)。"""
    body = _strip_report_id(raw, report_id)
    if len(body) >= 2 and (body[:2] == [0xFF, 0xAA] or body[:3] == [0x00, 0x00, 0x00]):
        return (False, True, None, False, "设备休眠中")
    if len(body) <= max(level_offset, 8) or body[0] != ASUS_CMD_GET or body[1] != ASUS_SUB_KEYBOARD:
        return (False, False, None, False, "未响应")
    raw_val = body[level_offset]
    charging = body[8] == 0x01
    if raw_val > 100:
        return (True, False, None, charging, "电量未知")
    if raw_val == 0 and not charging:
        return (False, True, None, False, "设备休眠中")
    if raw_val == 0 and charging:
        return (True, False, None, True, "充电中")
    return (True, False, raw_val, charging, "")


def parse_asus_omni_pairs(raw: list[int] | bytes) -> list[tuple[int, int]]:
    """解析 ROG Omni Receiver 配对表 `01 A0 00 NN 00 [pid_lo pid_hi ch xx]...` -> [(pid, channel), ...]。"""
    data = list(raw)
    if len(data) < 5 or data[:3] != [0x01, 0xA0, 0x00]:
        return []
    slots: list[tuple[int, int]] = []
    idx = 5
    while idx + 4 <= len(data):
        pid = data[idx] | (data[idx + 1] << 8)
        ch = data[idx + 2]
        if pid == 0:
            break
        slots.append((pid, ch))
        idx += 4
    return slots


def parse_asus_rog_headset_cc(
    bat_raw: list[int] | bytes,
    chg_raw: Optional[list[int] | bytes] = None,
) -> tuple[bool, Optional[int], bool]:
    """解析 ROG Pelta / Delta II `CC 12 07` 与 `CC 12 08` 回包 -> (online, percent, charging)。"""
    b = list(bat_raw)
    if len(b) < 7 or b[0] != 0xCC or b[1] != 0x12 or b[5:7] == [0xFF, 0xAA]:
        return (False, None, False)
    charging = False
    if chg_raw:
        c = list(chg_raw)
        if len(c) >= 6 and c[0] == 0xCC and c[1] == 0x12 and c[5:7] != [0xFF, 0xAA]:
            charging = c[5] == 1
    pct = b[6] if b[6] <= 100 else None
    return (True, pct, charging)


def parse_asus_cetra_speednova(
    bat_raw: list[int] | bytes,
    chg_raw: Optional[list[int] | bytes] = None,
) -> tuple[bool, Optional[int], bool, Optional[SubBattery]]:
    """解析 ROG Cetra SpeedNova（字节 6/7/8 = 左/右/盒）。"""
    b = list(bat_raw)
    if len(b) < 9 or b[0] != 0xCC or b[1] != 0x12 or b[5:7] == [0xFF, 0xAA]:
        return (False, None, False, None)
    left = b[6] if 1 <= b[6] <= 100 else None
    right = b[7] if 1 <= b[7] <= 100 else None
    case = b[8] if 1 <= b[8] <= 100 else None
    l_chg = r_chg = False
    if chg_raw:
        c = list(chg_raw)
        if len(c) >= 6 and c[0] == 0xCC and c[1] == 0x12:
            l_chg = bool(c[5] & 0x01)
            r_chg = bool(c[5] & 0x02)
    valid = [x for x in (left, right) if x is not None]
    if not valid and case is None:
        return (False, None, False, None)
    main_pct = min(valid) if valid else case
    sub = SubBattery(
        left_percent=left,
        left_charging=l_chg,
        right_percent=right,
        right_charging=r_chg,
        case_percent=case,
        case_charging=False,
    )
    return (True, main_pct, l_chg or r_chg, sub)


_STRIX_GO_CURVE: list[tuple[int, int]] = [
    (4100, 100),
    (3800, 75),
    (3700, 50),
    (3500, 25),
    (3300, 10),
    (3150, 0),
]


def parse_asus_strix_go(raw: list[int] | bytes) -> tuple[bool, Optional[int], bool, Optional[int]]:
    """解析 ROG Strix Go 2.4 Feature Report 0xFF -> (online, percent, charging, mv)（电压分段线性插值）。"""
    d = list(raw)
    if len(d) < 13 or d[0] != 0xFF or d[1] != 0x1B:
        return (False, None, False, None)
    mv = d[11] | (d[12] << 8)
    if d[9] == 0x0A:
        return (True, None, True, mv if 3000 <= mv <= 4400 else None)
    if not (3000 <= mv <= 4400):
        return (True, None, False, None)
    pct = interpolate_voltage(mv, _STRIX_GO_CURVE)
    return (True, pct, False, mv)


def build_sony_inzone_request() -> list[int]:
    """构建 Sony INZONE 64 字节只读电量查询报文（含校验和）。"""
    req = pad_report(64, [0x02, 0x0C, 0x01, 0x00, 0xFC, 0x08, 0x96, 0xC3, 0x41, 0x04, 0x01, 0x02, 0x00])
    req[13] = sum(req[6:13]) & 0xFF
    return req


def _is_sony_inzone_reply(d: list[int], min_payload: int) -> bool:
    return (
        len(d) > 12 + min_payload
        and d[0] == 0x02
        and d[1] >= 12 + min_payload
        and d[2] == 0x04
        and d[3] == 0xFF
        and d[6] == 0x96
        and d[7] == 0xC3
        and (d[8] >> 4) == 1
        and d[9] == 0x04
        and d[10] in (0x10, 0xA0)
        and d[11] == 0x02
        and d[12] == 0x00
    )


def parse_sony_inzone_h5(raw: list[int] | bytes) -> tuple[bool, Optional[int], bool]:
    """解析 Sony INZONE H5 / H9 II 回包 -> (online, percent, charging)。"""
    d = list(raw)
    if not _is_sony_inzone_reply(d, 2):
        return (False, None, False)
    if d[14] > 100:
        return (False, None, False)
    return (True, d[14], d[13] != 0)


def parse_sony_inzone_buds(raw: list[int] | bytes) -> tuple[bool, Optional[int], bool, Optional[SubBattery]]:
    """解析 Sony INZONE Buds 6 字节 payload -> (online, min_bud_pct, charging, SubBattery)。"""
    d = list(raw)
    if not _is_sony_inzone_reply(d, 6):
        return (False, None, False, None)
    p = d[13:19]  # [left_state, left_lvl, right_state, right_lvl, case_state, case_lvl]
    left = p[1] if p[1] <= 100 else None
    right = p[3] if p[3] <= 100 else None
    case = p[5] if p[5] <= 100 else None
    valid_buds = [x for x in (left, right) if x is not None]
    if not valid_buds and case is None:
        return (False, None, False, None)
    main_pct = min(valid_buds) if valid_buds else case
    sub = SubBattery(
        left_percent=left,
        left_charging=False,
        right_percent=right,
        right_charging=False,
        case_percent=case,
        case_charging=False,
    )
    return (True, main_pct, False, sub)


# ================= 统一适配器 =================

class ExtraBrandsProvider(BatteryProvider):
    """ASUS ROG / TUF 与 Sony INZONE 系列统一只读 HID 适配器。"""

    name = "asus_sony_hid"
    brand = "ASUS / Sony"

    def __init__(self) -> None:
        self._cache: dict[str, DeviceBattery] = {}

    def _ask_asus_report(
        self,
        path: bytes,
        report_id: int,
        sub: int,
        report_len: int = 65,
    ) -> Optional[list[int]]:
        dev = hid.device()
        try:
            dev.open_path(path)
            hid_drain(dev, 65, 4, 5)
            req = pad_report(report_len, [report_id, ASUS_CMD_GET, sub])
            if dev.write(req) <= 0:
                return None
            for _ in range(10):
                raw = dev.read(66, 120)
                if not raw:
                    break
                if not any(raw):
                    continue
                body = _strip_report_id(raw, report_id)
                if len(body) >= 3 and (
                    (body[0] == ASUS_CMD_GET and body[1] == sub)
                    or body[:2] == [0xFF, 0xAA]
                    or body[:3] == [0x00, 0x00, 0x00]
                ):
                    return list(raw)
        except OSError:
            return None
        finally:
            try:
                dev.close()
            except Exception:
                pass
        return None

    def _poll_asus_direct(self, entries: list[dict], results: list[DeviceBattery]) -> None:
        mouse_groups: dict[int, list[dict]] = {}
        kb_groups: dict[int, list[dict]] = {}
        for item in entries:
            pid = int(item.get("product_id", 0))
            path = item.get("path")
            if not path:
                continue
            iface = int(item.get("interface_number", -1))
            up = int(item.get("usage_page", 0))
            if pid in ASUS_MICE:
                spec = ASUS_MICE[pid]
                if iface == spec.interface and up >= 0xFF00:
                    in_len, out_len, _ = get_hid_report_lengths(path)
                    if in_len >= 64 and out_len >= 64:
                        mouse_groups.setdefault(pid, []).append(item)
            elif pid in ASUS_KEYBOARDS:
                if iface == 1 and up == 0xFF00:
                    in_len, out_len, _ = get_hid_report_lengths(path)
                    if in_len >= 64 and out_len >= 64:
                        kb_groups.setdefault(pid, []).append(item)

        for pid, colls in mouse_groups.items():
            spec = ASUS_MICE[pid]
            online, asleep, pct, chg, detail = (False, True, None, False, "未响应")
            for c in colls:
                _, out_len, _ = get_hid_report_lengths(c["path"])
                raw = self._ask_asus_report(c["path"], 0x00, ASUS_SUB_MOUSE, max(65, out_len))
                if raw:
                    online, asleep, pct, chg, detail = parse_asus_mouse_reply(
                        raw, 0x00, spec.level_offset, spec.multiplier, spec.charging_offset, spec.cell_battery
                    )
                    if online:
                        break
            dev_id = f"asus:{pid:04x}"
            prev = self._cache.get(dev_id)
            item = DeviceBattery(
                device_id=dev_id,
                name=spec.name,
                brand="ASUS ROG",
                kind=KIND_MOUSE,
                connection_mode="有线" if spec.is_wired else "2.4G",
                vid=ASUS_VID,
                pid=pid,
                connected=True,
                online=online,
                asleep=asleep or not online,
                percent=pct if online else (prev.percent if prev else None),
                charging=chg,
                full=chg and pct == 100,
                support_status=STATUS_PROTOCOL,
                status_detail=detail,
                provider_name=self.name,
            )
            if online:
                self._cache[dev_id] = item
            results.append(item)

        for pid, colls in kb_groups.items():
            name, is_wired, lvl_off = ASUS_KEYBOARDS[pid]
            online, asleep, pct, chg, detail = (False, True, None, False, "未响应")
            for c in colls:
                _, out_len, _ = get_hid_report_lengths(c["path"])
                raw = self._ask_asus_report(c["path"], 0x00, ASUS_SUB_KEYBOARD, max(65, out_len))
                if raw:
                    online, asleep, pct, chg, detail = parse_asus_keyboard_reply(raw, 0x00, lvl_off)
                    if online:
                        break
            dev_id = f"asus:{pid:04x}"
            prev = self._cache.get(dev_id)
            item = DeviceBattery(
                device_id=dev_id,
                name=name,
                brand="ASUS ROG",
                kind=KIND_KEYBOARD,
                connection_mode="有线" if is_wired else "2.4G",
                vid=ASUS_VID,
                pid=pid,
                connected=True,
                online=online,
                asleep=asleep or not online,
                percent=pct if online else (prev.percent if prev else None),
                charging=chg,
                full=chg and pct == 100,
                support_status=STATUS_PROTOCOL,
                status_detail=detail,
                provider_name=self.name,
            )
            if online:
                self._cache[dev_id] = item
            results.append(item)

    def _poll_asus_receivers(self, entries: list[dict], results: list[DeviceBattery]) -> None:
        recv_entries = [
            e for e in entries
            if int(e.get("product_id", 0)) in (ASUS_OMNI_PID, ASUS_SPEEDNOVA_PID)
            and int(e.get("interface_number", -1)) == 2
        ]
        if not recv_entries:
            return
        by_pid: dict[int, list[dict]] = {}
        for e in recv_entries:
            by_pid.setdefault(int(e["product_id"]), []).append(e)

        for pid, cols in by_pid.items():
            pair_col = next((c for c in cols if int(c.get("usage_page", 0)) == 0xFF02), None)
            mouse_col = next((c for c in cols if int(c.get("usage_page", 0)) == 0xFF01), None)
            kb_col = next((c for c in cols if int(c.get("usage_page", 0)) == 0xFF00), None)

            slots: list[tuple[int, int]] = []
            if pid == ASUS_OMNI_PID and pair_col and pair_col.get("path"):
                dev = hid.device()
                try:
                    dev.open_path(pair_col["path"])
                    dev.write(pad_report(64, [0x01, 0xA0, 0x00]))
                    raw = dev.read(64, 200)
                    if raw:
                        slots = parse_asus_omni_pairs(raw)
                except OSError:
                    pass
                finally:
                    try:
                        dev.close()
                    except Exception:
                        pass

            # 鼠标通道 (Report ID 0x03)
            if mouse_col and mouse_col.get("path"):
                mouse_name = "ROG Harpe II Ace" if pid == ASUS_SPEEDNOVA_PID else "ROG Omni Mouse"
                for spid, _ch in slots:
                    if spid in OMNI_MICE_NAMES:
                        mouse_name = OMNI_MICE_NAMES[spid]
                        break
                raw = self._ask_asus_report(mouse_col["path"], 0x03, ASUS_SUB_MOUSE, 64)
                if raw:
                    online, asleep, pct, chg, detail = parse_asus_mouse_reply(raw, 0x03)
                    if online or slots:
                        results.append(
                            DeviceBattery(
                                device_id=f"asus-recv:{pid:04x}:mouse",
                                name=mouse_name,
                                brand="ASUS ROG",
                                kind=KIND_MOUSE,
                                connection_mode="2.4G",
                                vid=ASUS_VID,
                                pid=pid,
                                connected=True,
                                online=online,
                                asleep=asleep,
                                percent=pct,
                                charging=chg,
                                full=chg and pct == 100,
                                support_status=STATUS_PROTOCOL,
                                status_detail=detail,
                                provider_name=self.name,
                            )
                        )

            # 键盘通道 (Report ID 0x02)
            if pid == ASUS_OMNI_PID and kb_col and kb_col.get("path"):
                kb_match = next(((OMNI_KEYBOARDS_INFO[spid]) for spid, _ in slots if spid in OMNI_KEYBOARDS_INFO), None)
                if kb_match:
                    kb_name, lvl_off = kb_match
                    raw = self._ask_asus_report(kb_col["path"], 0x02, ASUS_SUB_KEYBOARD, 64)
                    if raw:
                        online, asleep, pct, chg, detail = parse_asus_keyboard_reply(raw, 0x02, lvl_off)
                    else:
                        online, asleep, pct, chg, detail = (False, False, None, False, "未响应")
                    results.append(
                        DeviceBattery(
                            device_id=f"asus-recv:{pid:04x}:kb",
                            name=kb_name,
                            brand="ASUS ROG",
                            kind=KIND_KEYBOARD,
                            connection_mode="2.4G",
                            vid=ASUS_VID,
                            pid=pid,
                            connected=True,
                            online=online,
                            asleep=asleep,
                            percent=pct,
                            charging=chg,
                            full=chg and pct == 100,
                            support_status=STATUS_PROTOCOL,
                            status_detail=detail,
                            provider_name=self.name,
                        )
                    )

    def _poll_asus_headsets(self, entries: list[dict], results: list[DeviceBattery]) -> None:
        grouped: dict[int, list[dict]] = {}
        for item in entries:
            pid = int(item.get("product_id", 0))
            if pid not in ASUS_HEADSETS or not item.get("path"):
                continue
            _name, proto = ASUS_HEADSETS[pid]
            up = int(item.get("usage_page", 0))
            in_len, out_len, feat_len = get_hid_report_lengths(item["path"])
            if proto == "strix_go":
                if feat_len >= 64:
                    grouped.setdefault(pid, []).append(item)
            elif up == 0xFF00 and out_len >= 64:
                grouped.setdefault(pid, []).append(item)

        for pid, colls in grouped.items():
            name, proto = ASUS_HEADSETS[pid]
            dev_id = f"asus-hs:{pid:04x}"
            prev = self._cache.get(dev_id)
            if proto == "strix_go":
                online, pct, chg, mv = (False, None, False, None)
                for c in colls:
                    dev = hid.device()
                    try:
                        dev.open_path(c["path"])
                        dev.send_feature_report(pad_report(64, [0xFF, 0x08, 0x00, 0xFD, 0x04, 0x12, 0xF1, 0x03, 0x52, 0x01]))
                        time.sleep(0.035)
                        reply = dev.get_feature_report(0xFF, 64)
                        online, pct, chg, mv = parse_asus_strix_go(reply) if reply else (False, None, False, None)
                        if online:
                            break
                    except OSError:
                        continue
                    finally:
                        try:
                            dev.close()
                        except Exception:
                            pass
                item = DeviceBattery(
                    device_id=dev_id,
                    name=name,
                    brand="ASUS ROG",
                    kind=KIND_HEADSET,
                    connection_mode="2.4G",
                    vid=ASUS_VID,
                    pid=pid,
                    connected=True,
                    online=online,
                    asleep=not online,
                    percent=pct if online else (prev.percent if prev else None),
                    charging=chg,
                    voltage_mv=mv if online else (prev.voltage_mv if prev else None),
                    support_status=STATUS_PROTOCOL,
                    status_detail="" if online else "未响应 / 休眠",
                    provider_name=self.name,
                )
                if online:
                    self._cache[dev_id] = item
                results.append(item)
            else:
                online = False
                pct = None
                chg = False
                sub: Optional[SubBattery] = None
                for c in colls:
                    dev = hid.device()
                    try:
                        dev.open_path(c["path"])
                        hid_drain(dev, 64, 4, 5)
                        sub_cmd = 0x12 if proto == "cetra_open" else 0x07
                        dev.write(pad_report(64, [0xCC, 0x12, sub_cmd]))
                        bat_raw = None
                        for _ in range(6):
                            r0 = dev.read(64, 140)
                            if not r0:
                                break
                            if any(r0) and r0[0] == 0xCC and r0[1] == 0x12:
                                bat_raw = r0
                                break
                        chg_raw = None
                        if proto in ("rog_cc", "cetra_speednova") and bat_raw:
                            dev.write(pad_report(64, [0xCC, 0x12, 0x08]))
                            for _ in range(4):
                                r1 = dev.read(64, 120)
                                if not r1:
                                    break
                                if any(r1) and r1[0] == 0xCC and r1[1] == 0x12:
                                    chg_raw = r1
                                    break
                        if bat_raw:
                            if proto == "rog_cc":
                                online, pct, chg = parse_asus_rog_headset_cc(bat_raw, chg_raw)
                            elif proto == "cetra_speednova":
                                online, pct, chg, sub = parse_asus_cetra_speednova(bat_raw, chg_raw)
                            elif proto == "cetra_open":
                                b = list(bat_raw)
                                if len(b) >= 8 and b[0] == 0xCC and b[1] == 0x12 and b[5:7] != [0xFF, 0xAA]:
                                    left = b[5] if 1 <= b[5] <= 100 else None
                                    right = b[6] if 1 <= b[6] <= 100 else None
                                    case = b[7] if 1 <= b[7] <= 100 else None
                                    valid = [x for x in (left, right) if x is not None]
                                    if valid or case is not None:
                                        online = True
                                        pct = min(valid) if valid else case
                                        sub = SubBattery(left_percent=left, right_percent=right, case_percent=case)
                        if online:
                            break
                    except OSError:
                        continue
                    finally:
                        try:
                            dev.close()
                        except Exception:
                            pass
                item = DeviceBattery(
                    device_id=dev_id,
                    name=name,
                    brand="ASUS ROG",
                    kind=KIND_EARBUDS if "cetra" in proto else KIND_HEADSET,
                    connection_mode="2.4G",
                    vid=ASUS_VID,
                    pid=pid,
                    connected=True,
                    online=online,
                    asleep=not online,
                    percent=pct if online else (prev.percent if prev else None),
                    charging=chg,
                    full=chg and pct == 100,
                    sub_batteries=sub if online else (prev.sub_batteries if prev else None),
                    support_status=STATUS_PROTOCOL,
                    status_detail="" if online else "未响应 / 休眠",
                    provider_name=self.name,
                )
                if online:
                    self._cache[dev_id] = item
                results.append(item)

    def _poll_sony_inzone(self, entries: list[dict], results: list[DeviceBattery]) -> None:
        grouped: dict[int, list[dict]] = {}
        for item in entries:
            pid = int(item.get("product_id", 0))
            if pid not in SONY_INZONE_MODELS or not item.get("path"):
                continue
            if int(item.get("usage_page", 0)) != 0xFF04:
                continue
            _, out_len, _ = get_hid_report_lengths(item["path"])
            if out_len >= 64:
                grouped.setdefault(pid, []).append(item)

        for pid, colls in grouped.items():
            name, mode = SONY_INZONE_MODELS[pid]
            req = build_sony_inzone_request()
            online = False
            pct: Optional[int] = None
            chg = False
            sub: Optional[SubBattery] = None
            for c in colls:
                dev = hid.device()
                try:
                    dev.open_path(c["path"])
                    hid_drain(dev, 64, 4, 5)
                    dev.write(req)
                    for _ in range(12):
                        raw = dev.read(64, 150)
                        if not raw:
                            break
                        if not any(raw):
                            continue
                        if mode == "h5":
                            ok, p, ch = parse_sony_inzone_h5(raw)
                            if ok:
                                online, pct, chg = ok, p, ch
                                break
                        else:
                            ok, p, ch, sb = parse_sony_inzone_buds(raw)
                            if ok:
                                online, pct, chg, sub = ok, p, ch, sb
                                break
                    if online:
                        break
                except OSError:
                    continue
                finally:
                    try:
                        dev.close()
                    except Exception:
                        pass
            dev_id = f"sony:{pid:04x}"
            prev = self._cache.get(dev_id)
            item = DeviceBattery(
                device_id=dev_id,
                name=name,
                brand="Sony",
                kind=KIND_EARBUDS if mode == "buds" else KIND_HEADSET,
                connection_mode="2.4G",
                vid=SONY_VID,
                pid=pid,
                connected=True,
                online=online,
                asleep=not online,
                percent=pct if online else (prev.percent if prev else None),
                charging=chg,
                full=chg and pct == 100,
                sub_batteries=sub if online else (prev.sub_batteries if prev else None),
                support_status=STATUS_PROTOCOL,
                status_detail="" if online else "未连接耳机 / 充电盒内",
                provider_name=self.name,
            )
            if online:
                self._cache[dev_id] = item
            results.append(item)

    def poll(self, hid_snapshot: list[dict]) -> list[DeviceBattery]:
        results: list[DeviceBattery] = []
        asus_entries = [d for d in hid_snapshot if int(d.get("vendor_id", 0)) == ASUS_VID]
        sony_entries = [d for d in hid_snapshot if int(d.get("vendor_id", 0)) == SONY_VID]

        if asus_entries:
            self._poll_asus_direct(asus_entries, results)
            self._poll_asus_receivers(asus_entries, results)
            self._poll_asus_headsets(asus_entries, results)
        if sony_entries:
            self._poll_sony_inzone(sony_entries, results)

        return results
