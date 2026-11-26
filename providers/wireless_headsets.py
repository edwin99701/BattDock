"""多品牌无线耳机只读 HID 电量适配器（Razer Audio / Logitech Centurion / ASTRO / JBL Quantum / Audeze / EPOS / MCHOSE / FIFINE）。

协议参考说明（独立只读 Python 实现，绝不修改设备 EQ/灯光/固件）：
- 协议字段与报文规范参考自 MIT 许可开源项目 `qu1ncky/BatteryTray`，
  所有涉及的开源参考及许可证均记录于 `THIRD_PARTY_LICENSES.md`。
- 对于高频轮询易掉线的型号（如 Razer BlackShark V3）内置 300 秒防断连节流保护。
"""

from __future__ import annotations

import time
from typing import Optional

import hid

from .base import (
    BatteryProvider,
    DeviceBattery,
    KIND_HEADSET,
    STATUS_PROTOCOL,
    get_hid_report_lengths,
    hid_drain,
    pad_report,
)


def _xor_bytes(data: list[int] | bytes) -> int:
    res = 0
    for b in data:
        res ^= b & 0xFF
    return res


# ================= 1. Razer 无线耳机 (Report 02 / Feature 07 / Feature FF / Airoha Bridge) =================

RAZER_VID = 0x1532

# (pid): (key, name, proto, is_wired)
RAZER_HEADSETS: dict[int, tuple[str, str, str, bool]] = {
    0x0565: ("razer-blackshark-v2-hs", "Razer BlackShark V2 HyperSpeed", "report02_cnt", False),
    0x056E: ("razer-blackshark-v2-hs", "Razer BlackShark V2 HyperSpeed", "report02_cnt", True),
    0x0568: ("razer-kraken-v4-pro", "Razer Kraken V4 Pro", "report02", False),
    0x0567: ("razer-kraken-v4-pro", "Razer Kraken V4 Pro", "report02", True),
    0x056C: ("razer-kraken-v4", "Razer Kraken V4", "report02", False),
    0x0588: ("razer-kraken-kitty-v3-pro", "Razer Kraken Kitty V3 Pro", "report02", False),
    0x0587: ("razer-kraken-kitty-v3-pro", "Razer Kraken Kitty V3 Pro", "report02", True),
    0x057A: ("razer-blackshark-v3", "Razer BlackShark V3", "report02_v3", False),
    0x057D: ("razer-blackshark-v3-x", "Razer BlackShark V3 X HyperSpeed", "feat07", False),
    0x057C: ("razer-blackshark-v3-x", "Razer BlackShark V3 X HyperSpeed", "feat07", True),
    0x0528: ("razer-blackshark-v2-pro-2020", "Razer BlackShark V2 Pro (2020)", "featff", False),
    0x0555: ("razer-blackshark-v2-pro-2023", "Razer BlackShark V2 Pro (2023)", "bridge_02", False),
    0x053A: ("razer-barracuda-pro", "Razer Barracuda Pro", "bridge_01", False),
}


def build_razer_report02_frame(route: int, cmd: int, seq: int = 0) -> list[int]:
    frame = [0] * 64
    frame[0] = 0x02
    frame[2] = 0x60 | (seq & 0x1F)
    frame[6] = 0x04
    frame[9] = route & 0xFF
    frame[10] = cmd & 0xFF
    frame[62] = _xor_bytes(frame[:62])
    return frame


def parse_razer_report02_answer(reply: list[int] | bytes, request: list[int]) -> Optional[int]:
    d = list(reply)
    if len(d) < 64 or d[0] != 0x02 or d[2] != request[2] or d[10] != request[10] or d[11] != 0x01:
        return None
    if d[9] != request[9] and not (request[9] == 0x00 and d[9] == 0x80):
        return None
    x = _xor_bytes(d[1:62])
    if d[62] != x and d[62] != (x ^ d[0]):
        return None
    if d[1] == 0x02 and d[12] >= 1 and d[6] == 4 + d[12]:
        return int(d[13])
    return None


def build_razer_v3x_request(tx: int, cmd: int) -> list[int]:
    req = [0] * 64
    req[0] = 0x07
    req[2] = tx & 0xFF
    req[6] = 0x02
    req[7] = 0x07
    req[8] = cmd & 0xFF
    req[62] = _xor_bytes(req[3:61])
    return req


def parse_razer_v3x_reply(reply: list[int] | bytes, req: list[int]) -> Optional[int]:
    r = list(reply)
    if len(r) < 64 or r[0] != 0x07 or r[2] != req[2] or r[7] != req[7] or r[8] != req[8] or r[6] < 2:
        return None
    if r[62] != _xor_bytes(r[3:61]):
        return None
    return int(r[10]) if r[1] == 0x02 else None


def parse_razer_v2_pro_2020_reply(reply: list[int] | bytes) -> Optional[tuple[bool, Optional[int], bool, bool]]:
    """解析 BlackShark V2 Pro (2020) Feature 0xFF 回包 -> (online, percent, charging, full)。"""
    r = list(reply)
    if len(r) < 15 or r[:9] != [0xFF, 0x0F, 0x05, 0xFE, 0x12, 0x04, 0x1F, 0x08, 0x05]:
        return None
    if r[12] == 0 and r[13] == 0:
        return (False, None, False, False)
    power = r[11]
    charging = power == 0x09
    full = power == 0x06
    pct = int(r[14]) if (r[14] <= 100 and not charging) else None
    return (True, pct, charging, full)


def build_razer_bridge_frame(report_id: int, kind: int, body: list[int]) -> list[int]:
    at, seq = (5, 0x00) if report_id == 0x02 else (3, 0x08)
    frame = [0] * 64
    frame[0] = report_id
    frame[1] = 0x80
    frame[2] = 4 + len(body)
    frame[at : at + 4] = [0x50, 0x41, kind, seq]
    frame[at + 4 : at + 4 + len(body)] = body
    return frame


def parse_razer_bridge_value(reply: list[int] | bytes, report_id: int, val_id: int) -> Optional[int]:
    d = list(reply)
    at = 2 if report_id == 0x02 else 3
    if len(d) <= at + 13 or d[0] != report_id:
        return None
    if report_id != 0x02 and d[1] != 0x80:
        return None
    if d[at : at + 2] == [0x50, 0x49] and d[at + 10] == val_id and d[at + 11] == 0x01 and d[at + 12] >= 1:
        return int(d[at + 13])
    return None


# ================= 2. Logitech Centurion & ASTRO A50 无线耳机 =================

CENTURION_SW_ID = 0x06
CENTURION_HEADSETS: dict[int, tuple[str, str, tuple[int, ...], bool]] = {
    # pid: (key, name, prefix, is_wired)
    0x0AF7: ("logitech-g-pro-x-2", "Logitech G Pro X 2 Lightspeed", (0x51,), False),
    0x0B18: ("logitech-g522", "Logitech G522 Lightspeed", (0x50, 0x23), False),
    0x0B45: ("logitech-g-pro-x-3", "Logitech G Pro X 3 Lightspeed", (0x50, 0x23), False),
    0x0B35: ("astro-a20-x", "ASTRO A20 X", (0x50, 0x23), False),
    0x0B2E: ("astro-a20-x", "ASTRO A20 X", (0x50, 0x23), True),
}


def build_centurion_frame(prefix: tuple[int, ...], payload: list[int]) -> list[int]:
    return pad_report(64, list(prefix) + [len(payload) + 1, 0x00] + payload)


def parse_centurion_payload(prefix: tuple[int, ...], report: list[int] | bytes) -> Optional[list[int]]:
    r = list(report)
    plen = len(prefix)
    if len(r) < plen + 2 or tuple(r[:plen]) != prefix:
        return None
    length, flags = r[plen], r[plen + 1]
    if flags != 0x00 or length < 2 or len(r) < plen + 2 + (length - 1):
        return None
    return r[plen + 2 : plen + 2 + (length - 1)]


def parse_centurion_battery(params: list[int]) -> Optional[tuple[int, bool, bool]]:
    if len(params) < 3 or params[0] > 100:
        return None
    pct, power = int(params[0]), int(params[2])
    return (pct, power in (1, 2), power == 3)


def parse_astro_a50_gen5_reply(raw: list[int] | bytes) -> Optional[tuple[int, bool]]:
    r = list(raw)
    if len(r) > 8 and r[0] == 0x02 and r[1] == 0x0C and r[4] == 0x06 and r[6] <= 100:
        return (int(r[6]), r[8] != 0)
    return None


def parse_astro_a50_gen4_battery(raw: list[int] | bytes) -> Optional[tuple[int, bool]]:
    r = list(raw)
    if len(r) >= 4 and r[0] == 0x02 and r[1] == 0x02 and r[2] >= 1:
        b = int(r[3])
        pct = b & 0x7F
        if pct <= 100:
            return (pct, bool(b & 0x80))
    return None


# ================= 3. JBL Quantum / EPOS / Airoha RACE / MCHOSE / FIFINE 无线耳机 =================

JBL_INFO_MODELS: dict[int, tuple[str, str, bool]] = {
    0x2125: ("jbl-quantum-650", "JBL Quantum 650 Wireless", False),
    0x2126: ("jbl-quantum-650", "JBL Quantum 650 Wireless", True),
    0x213B: ("jbl-quantum-650x", "JBL Quantum 650X Wireless", False),
    0x213D: ("jbl-quantum-650x", "JBL Quantum 650X Wireless", True),
    0x2127: ("jbl-quantum-950", "JBL Quantum 950 Wireless", False),
    0x2128: ("jbl-quantum-950", "JBL Quantum 950 Wireless", True),
    0x213E: ("jbl-quantum-950x", "JBL Quantum 950X Wireless", False),
    0x2140: ("jbl-quantum-950x", "JBL Quantum 950X Wireless", True),
    0x218D: ("jbl-quantum-520", "JBL Quantum 520 Wireless", False),
    0x218E: ("jbl-quantum-520", "JBL Quantum 520 Wireless", True),
    0x219A: ("jbl-quantum-850", "JBL Quantum 850 Wireless", False),
    0x219B: ("jbl-quantum-850", "JBL Quantum 850 Wireless", True),
}

JBL_LEGACY_MODELS: dict[int, tuple[str, str, int]] = {
    0x206B: ("jbl-quantum-350", "JBL Quantum 350 Wireless", 3),
    0x2115: ("jbl-quantum-360", "JBL Quantum 360 Wireless", 5),
    0x205C: ("jbl-quantum-610", "JBL Quantum 610 Wireless", 5),
    0x2069: ("jbl-quantum-810", "JBL Quantum 810 Wireless", -1),
    0x2088: ("jbl-quantum-910", "JBL Quantum 910 Wireless", -1),
}

JBL_INFO_REQUEST = [0x88, 0x00, 0xDD, 0x01, 0x00, 0x01, 0x00, 0x02, 0x00, 0x0D, 0x00]


def parse_jbl_info_reply(raw: list[int] | bytes) -> Optional[tuple[int, bool]]:
    d = list(raw)
    if len(d) < 16 or d[:6] != [0x86, 0x00, 0xDD, 0x01, 0x00, 0x01]:
        return None
    if (d[10] & 0x80) != 0 or d[11:13] != [0x0D, 0x00] or d[13:15] == [0x00, 0x00]:
        return None
    level = d[15] & 0x7F
    if level <= 100:
        return (int(level), bool(d[15] & 0x80))
    return None


def epos_crc8(payload: bytes | list[int]) -> int:
    crc = 0xFF
    for byte in payload:
        crc ^= byte & 0xFF
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if (crc & 0x80) else (crc << 1) & 0xFF
    return crc


def build_epos_request(target: int, group: int, cmd: int) -> list[int]:
    payload = [group & 0xFF, (group >> 8) & 0xFF, cmd & 0xFF, (cmd >> 8) & 0xFF]
    header_words = [0x0001, 0x0004, target & 0xFFFF, len(payload), epos_crc8(payload)]
    pkt = [0x01, 0xEB, 0xFE]
    for w in header_words:
        pkt.extend([w & 0xFF, (w >> 8) & 0xFF])
    pkt.extend(payload)
    return pad_report(107, pkt)


def parse_epos_reply(raw: list[int] | bytes, expected_target: int, group: int, cmd: int) -> Optional[list[int]]:
    d = list(raw)
    if len(d) < 17 or d[:3] != [0x01, 0xEB, 0xFE]:
        return None
    w = lambda idx: d[idx] | (d[idx + 1] << 8)
    kind, target, length, crc = w(5), w(7), w(9), w(11)
    if kind != 0x0004 or length < 4 or (length % 2) != 0 or len(d) < 13 + length:
        return None
    payload = d[13 : 13 + length]
    if crc != epos_crc8(payload):
        return None
    words = [payload[i] | (payload[i + 1] << 8) for i in range(0, length, 2)]
    if words[0] != group or words[1] != cmd:
        return None
    if target == expected_target - 1:
        return words[2:]
    if expected_target == 0x0005 and target == 0x0001:
        return []  # 耳机离线
    return None


def parse_race_battery_reply(raw: list[int] | bytes) -> Optional[int]:
    """解析 Airoha RACE (Audeze Maxwell / AKG N9 / Skullcandy PLYR) Input Report 0x07 电量 -> percent。"""
    d = list(raw)
    if len(d) < 12 or d[0] != 0x07:
        return None
    n = int(d[1])
    if n < 9 or len(d) < 3 + n:
        return None
    stream = d[3 : 3 + n]
    for i in range(len(stream) - 8):
        if stream[i] == 0x05 and stream[i + 1] == 0x5D and stream[i + 4] == 0xD6 and stream[i + 5] == 0x0C:
            status, _role, pct = stream[i + 6], stream[i + 7], stream[i + 8]
            if status == 0x00 and 0 <= pct <= 100:
                return int(pct)
    return None


def parse_cmedia_5565_reply(raw: list[int] | bytes, allow_zero_charge: bool = False) -> Optional[tuple[bool, Optional[int], bool, bool]]:
    """解析 MCHOSE X9 / V9 Pro / FIFINE HT6 `55 65 <level> <status>` 回包 -> (online, percent, charging, full)。"""
    r = list(raw)
    off = 1 if (len(r) >= 5 and r[0] == 0x00 and r[1] == 0x55) else 0
    if len(r) < off + 4 or r[off] != 0x55 or r[off + 1] != 0x65:
        return None
    lvl, status = int(r[off + 2]), int(r[off + 3])
    if status == 0x1A:
        return (False, None, False, False)
    if status == 0x02:
        chg, full = False, False
    elif status == 0x03 or (allow_zero_charge and status == 0x00):
        chg, full = True, False
    elif status == 0x04:
        chg, full = False, True
    else:
        return None
    return (True, lvl if lvl <= 100 else None, chg, full)


def parse_mchose_v9_pro_2_reply(raw: list[int] | bytes) -> Optional[tuple[bool, Optional[int], bool]]:
    """解析 MCHOSE V9 Pro 2 (MC 协议 55 AA 01) 电量回包/通知 -> (online, percent, charging)。"""
    d = list(raw)
    if len(d) < 10 or d[0] != 0x55 or d[1] != 0xAA or d[2] != 0x01 or d[5] != 0x00:
        return None
    if (d[6], d[7]) not in ((0x01, 0x0B), (0x04, 0x22)):
        return None
    length = int(d[4])
    if length < 3 or 7 + length >= len(d):
        return None
    check = _xor_bytes(d[3 : 7 + length]) if d[3] == 0x01 else 0
    if d[7 + length] != check:
        return None
    if d[8] == 0:
        return (False, None, False)
    level = d[9] & 0x7F
    if level <= 100:
        return (True, int(level), bool(d[9] & 0x80))
    return None


CMEDIA_5565_HEADSETS: dict[tuple[int, int], tuple[str, str, str, int, bool]] = {
    # (vid, pid): (key, name, brand, req_usage_page or 0, allow_zero_charge)
    (0x3837, 0x6045): ("mchose-x9", "MCHOSE X9", "MCHOSE", 0xFF90, False),
    (0x3142, 0x00C3): ("fifine-ht6", "FIFINE HT6", "FIFINE", 0xFF90, False),
    (0x291D, 0x385D): ("mchose-v9-pro", "MCHOSE V9 Pro", "MCHOSE", 0, True),
}

AIROHA_RACE_HEADSETS: dict[tuple[int, int], tuple[str, str, str]] = {
    (0x3329, 0x4B19): ("audeze-maxwell", "Audeze Maxwell", "Audeze"),
    (0x3329, 0x4B18): ("audeze-maxwell", "Audeze Maxwell", "Audeze"),
    (0x3329, 0x4B29): ("audeze-maxwell-2", "Audeze Maxwell 2", "Audeze"),
    (0x3329, 0x4B28): ("audeze-maxwell-2", "Audeze Maxwell 2", "Audeze"),
    (0x0ECB, 0x20D9): ("akg-n9-hybrid", "AKG N9 Hybrid", "AKG"),
    (0x34F0, 0x3210): ("skullcandy-plyr", "Skullcandy PLYR", "Skullcandy"),
    (0x34F0, 0x5310): ("skullcandy-crusher-plyr-720", "Skullcandy Crusher PLYR 720", "Skullcandy"),
}


class WirelessHeadsetsProvider(BatteryProvider):
    """多品牌无线耳机统一只读适配器（Razer / Logitech Centurion / ASTRO / JBL / Audeze / AKG / EPOS / MCHOSE / FIFINE）。"""

    name = "wireless_headsets"
    brand = "Wireless Headsets"

    def __init__(self) -> None:
        self._seq: int = 1
        self._v3_cache: Optional[tuple[float, DeviceBattery]] = None

    def _next_seq(self) -> int:
        self._seq = (self._seq + 1) & 0xFF
        return self._seq

    def _poll_razer_headsets(self, hid_snapshot: list[dict], now_mono: float) -> list[DeviceBattery]:
        out: list[DeviceBattery] = []
        seen_pids: set[int] = set()
        for d in hid_snapshot:
            if int(d.get("vendor_id", 0)) != RAZER_VID:
                continue
            pid = int(d.get("product_id", 0))
            if pid not in RAZER_HEADSETS or pid in seen_pids:
                continue
            key, name, proto, is_wired = RAZER_HEADSETS[pid]
            path = d.get("path")
            if not path:
                continue
            up = int(d.get("usage_page", 0))
            u = int(d.get("usage", 0))
            in_len, out_len, feat_len = get_hid_report_lengths(path)

            if proto.startswith("report02"):
                if up not in (0xFF14, 0xFF00) or u != 0x0001 or in_len != 64 or out_len != 64:
                    continue
            elif proto == "feat07":
                if up < 0xFF00 or feat_len != 64:
                    continue
            elif proto == "featff":
                if up != 0xFF00 or u != 0x0001 or feat_len != 64:
                    continue
            elif proto.startswith("bridge_"):
                if up != 0xFF00 or in_len != 64 or out_len != 64:
                    continue

            seen_pids.add(pid)
            # BlackShark V3 高频轮询会断连，强制 5 分钟节流（在线）或 60 秒（离线）
            if proto == "report02_v3" and self._v3_cache is not None:
                ts_c, dev_c = self._v3_cache
                wait_s = 300.0 if dev_c.online else 60.0
                if (now_mono - ts_c) < wait_s:
                    out.append(dev_c)
                    continue

            online, pct, chg, full = False, None, False, False
            dev = hid.device()
            try:
                dev.open_path(path)
                if proto.startswith("report02"):
                    hid_drain(dev, 64, 4, 5)
                    route = 0x00 if is_wired else 0x80
                    counting = proto == "report02_cnt"
                    if proto == "report02_v3":
                        for wake_cmd in (0x02, 0x2A):
                            dev.write(build_razer_report02_frame(0x00, wake_cmd, 0))
                            time.sleep(0.005)
                    req_bat = build_razer_report02_frame(route, 0x21, self._next_seq() if counting else 0)
                    dev.write(req_bat)
                    lvl = None
                    for _ in range(10):
                        raw = dev.read(64, 180)
                        if not raw:
                            break
                        lvl = parse_razer_report02_answer(raw, req_bat)
                        if lvl is not None:
                            break
                    if lvl is not None and lvl <= 100:
                        online, pct = True, lvl
                        req_chg = build_razer_report02_frame(route, 0x2A, self._next_seq() if counting else 0)
                        dev.write(req_chg)
                        for _ in range(8):
                            raw_c = dev.read(64, 150)
                            if not raw_c:
                                break
                            cval = parse_razer_report02_answer(raw_c, req_chg)
                            if cval is not None:
                                chg = cval not in (0, 0xFF)
                                break
                elif proto == "feat07":
                    for cmd, target_slot in ((0x80, "bat"), (0x84, "chg")):
                        if target_slot == "chg" and not online:
                            break
                        req = build_razer_v3x_request(self._next_seq(), cmd)
                        if dev.send_feature_report(req) >= 64:
                            time.sleep(0.06)
                            rep = dev.get_feature_report(0x07, 64)
                            val = parse_razer_v3x_reply(rep, req) if rep else None
                            if target_slot == "bat" and val is not None and 1 <= val <= 100:
                                online, pct = True, val
                            elif target_slot == "chg" and val is not None:
                                chg = val == 1
                elif proto == "featff":
                    req = pad_report(64, [0xFF, 0x0A, 0x00, 0xFD, 0x04, 0x12, 0xF1, 0x02, 0x05])
                    if dev.send_feature_report(req) >= 9:
                        for _ in range(3):
                            time.sleep(0.1)
                            rep = dev.get_feature_report(0xFF, 64)
                            parsed = parse_razer_v2_pro_2020_reply(rep) if rep else None
                            if parsed is not None:
                                online, pct, chg, full = parsed
                                break
                elif proto.startswith("bridge_"):
                    rid = 0x02 if proto == "bridge_02" else 0x01
                    hid_drain(dev, 64, 4, 5)
                    try:
                        dev.write(build_razer_bridge_frame(rid, 0x0E, [0x02, 0xE1, 0x01]))
                        time.sleep(0.04)
                        dev.write(build_razer_bridge_frame(rid, 0x08, [0x03, 0x21, 0x00, 0x00]))
                        for _ in range(8):
                            raw = dev.read(64, 150)
                            if not raw:
                                break
                            val = parse_razer_bridge_value(raw, rid, 0x21)
                            if val is not None and val <= 100:
                                online, pct = True, val
                                break
                        if online:
                            dev.write(build_razer_bridge_frame(rid, 0x08, [0x03, 0x2A, 0x00, 0x00]))
                            for _ in range(6):
                                raw_c = dev.read(64, 120)
                                if not raw_c:
                                    break
                                cval = parse_razer_bridge_value(raw_c, rid, 0x2A)
                                if cval is not None:
                                    chg = cval != 0
                                    break
                    finally:
                        try:
                            dev.write(build_razer_bridge_frame(rid, 0x0E, [0x02, 0xE1, 0x00]))
                        except OSError:
                            pass
            except OSError:
                pass
            finally:
                try:
                    dev.close()
                except Exception:
                    pass

            item = DeviceBattery(
                device_id=f"headset:{key}",
                name=name,
                brand="Razer",
                kind=KIND_HEADSET,
                connection_mode="有线" if (is_wired or chg) else "2.4G",
                vid=RAZER_VID,
                pid=pid,
                connected=True,
                online=online,
                asleep=not online,
                percent=pct,
                charging=chg and not full,
                full=full or (chg and pct == 100),
                support_status=STATUS_PROTOCOL,
                status_detail="" if online else "耳机离线或休眠",
                provider_name=self.name,
            )
            if proto == "report02_v3":
                self._v3_cache = (now_mono, item)
            out.append(item)
        return out

    def _poll_centurion_and_astro(self, hid_snapshot: list[dict]) -> list[DeviceBattery]:
        out: list[DeviceBattery] = []
        seen: set[tuple[int, int]] = set()
        for d in hid_snapshot:
            vid = int(d.get("vendor_id", 0))
            pid = int(d.get("product_id", 0))
            path = d.get("path")
            if not path or (vid, pid) in seen:
                continue
            up = int(d.get("usage_page", 0))
            u = int(d.get("usage", 0))

            # 1. Logitech Centurion (G PRO X 2 / G522 / G PRO X 3 / ASTRO A20 X)
            if vid == 0x046D and pid in CENTURION_HEADSETS and up == 0xFFA0 and u == 0x0001:
                seen.add((vid, pid))
                key, name, prefix, is_wired = CENTURION_HEADSETS[pid]
                brand = "ASTRO" if key.startswith("astro-") else "Logitech"
                online, pct, chg, full = False, None, False, False
                dev = hid.device()
                try:
                    dev.open_path(path)
                    hid_drain(dev, 64, 4, 5)

                    def _ask_direct(feat: int, func: int, params: list[int]) -> Optional[list[int]]:
                        dev.write(build_centurion_frame(prefix, [feat, func | CENTURION_SW_ID] + params))
                        for _ in range(12):
                            raw = dev.read(64, 180)
                            if not raw:
                                break
                            pl = parse_centurion_payload(prefix, raw)
                            if pl and len(pl) >= 2 and pl[0] == feat and pl[1] == (func | CENTURION_SW_ID):
                                return pl[2:]
                            if pl and len(pl) >= 3 and pl[0] == 0xFF and pl[1] == feat:
                                return None
                        return None

                    if is_wired:
                        bfeat = _ask_direct(0x00, 0x00, [0x01, 0x04])
                        if bfeat and bfeat[0] != 0:
                            bres = _ask_direct(bfeat[0], 0x00, [])
                            parsed = parse_centurion_battery(bres) if bres else None
                            if parsed:
                                pct, chg, full = parsed
                                online = True
                    else:
                        br = _ask_direct(0x00, 0x00, [0x00, 0x03])
                        if br and br[0] != 0:
                            bridge = br[0]

                            def _ask_bridged(feat: int, func: int, params: list[int]) -> Optional[list[int]]:
                                size = len(params) + 3
                                msg = [bridge, 0x10 | CENTURION_SW_ID, 0x00, size, 0x00, feat, func | CENTURION_SW_ID] + params
                                dev.write(build_centurion_frame(prefix, msg))
                                for _ in range(14):
                                    raw = dev.read(64, 200)
                                    if not raw:
                                        break
                                    pl = parse_centurion_payload(prefix, raw)
                                    if not pl or len(pl) < 4:
                                        continue
                                    if pl[0] == 0xFF and pl[1] == bridge:
                                        return None
                                    if pl[0] == bridge and pl[1] == 0x10 and pl[2] == 0x00:
                                        sz = pl[3]
                                        inner = pl[4 : 4 + sz]
                                        if len(inner) >= 3 and inner[0] == 0x00 and inner[1] == feat and inner[2] == (func | CENTURION_SW_ID):
                                            return inner[3:]
                                        if len(inner) >= 4 and inner[0] == 0x00 and inner[1] == 0xFF:
                                            return None
                                return None

                            bf = _ask_bridged(0x00, 0x00, [0x01, 0x04])
                            if bf and bf[0] != 0:
                                bres = _ask_bridged(bf[0], 0x00, [])
                                parsed = parse_centurion_battery(bres) if bres else None
                                if parsed:
                                    pct, chg, full = parsed
                                    online = True
                except OSError:
                    pass
                finally:
                    try:
                        dev.close()
                    except Exception:
                        pass

                out.append(
                    DeviceBattery(
                        device_id=f"headset:{key}",
                        name=name,
                        brand=brand,
                        kind=KIND_HEADSET,
                        connection_mode="有线" if (is_wired or chg) else "2.4G",
                        vid=vid,
                        pid=pid,
                        connected=True,
                        online=online,
                        asleep=not online,
                        percent=pct,
                        charging=chg and not full,
                        full=full,
                        support_status=STATUS_PROTOCOL,
                        status_detail="" if online else "耳机离线或休眠",
                        provider_name=self.name,
                    )
                )

            # 2. ASTRO A50 Gen 5 / A50 X (046D:0B1C / 0B0B) & A50 Gen 4 (9886:002C)
            elif ((vid == 0x046D and pid in (0x0B1C, 0x0B0B)) or (vid == 0x9886 and pid == 0x002C)) and up == 0xFF32 and u == 0x0074:
                seen.add((vid, pid))
                is_gen4 = vid == 0x9886
                online, pct, chg = False, None, False
                dev = hid.device()
                try:
                    dev.open_path(path)
                    hid_drain(dev, 64, 4, 5)
                    if is_gen4:
                        dev.write(pad_report(64, [0x02, 0x54]))
                        st_raw = dev.read(64, 250)
                        if st_raw and len(st_raw) >= 4 and st_raw[0] == 0x02 and st_raw[1] == 0x02 and (st_raw[3] & 0x03):
                            dev.write(pad_report(64, [0x02, 0x7C]))
                            b_raw = dev.read(64, 250)
                            parsed = parse_astro_a50_gen4_battery(b_raw) if b_raw else None
                            if parsed:
                                online, (pct, chg) = True, parsed
                    else:
                        dev.write(pad_report(64, [0x02, 0x0C, 0x03, 0x00, 0x06, 0x0C]))
                        for _ in range(8):
                            raw = dev.read(64, 200)
                            if not raw:
                                break
                            parsed = parse_astro_a50_gen5_reply(raw)
                            if parsed:
                                online, (pct, chg) = True, parsed
                                break
                except OSError:
                    pass
                finally:
                    try:
                        dev.close()
                    except Exception:
                        pass

                out.append(
                    DeviceBattery(
                        device_id="headset:astro-a50-gen4" if is_gen4 else "headset:astro-a50",
                        name="ASTRO A50 Gen 4" if is_gen4 else "ASTRO A50 / A50 X",
                        brand="ASTRO",
                        kind=KIND_HEADSET,
                        connection_mode="2.4G",
                        vid=vid,
                        pid=pid,
                        connected=True,
                        online=online,
                        asleep=not online,
                        percent=pct,
                        charging=chg,
                        support_status=STATUS_PROTOCOL,
                        status_detail="" if online else "耳机离线或休眠",
                        provider_name=self.name,
                    )
                )
        return out

    def _poll_jbl_epos_airoha_cmedia(self, hid_snapshot: list[dict]) -> list[DeviceBattery]:
        out: list[DeviceBattery] = []
        seen: set[tuple[int, int]] = set()
        for d in hid_snapshot:
            vid = int(d.get("vendor_id", 0))
            pid = int(d.get("product_id", 0))
            path = d.get("path")
            if not path or (vid, pid) in seen:
                continue
            up = int(d.get("usage_page", 0))
            u = int(d.get("usage", 0))
            iface = int(d.get("interface_number", -1))
            in_len, out_len, feat_len = get_hid_report_lengths(path)

            # 1. JBL Quantum 新一代 (FF12 Feature 0x88 -> Input 0x86)
            if vid == 0x0ECB and pid in JBL_INFO_MODELS and up == 0xFF12 and feat_len >= 11 and in_len >= 16:
                seen.add((vid, pid))
                key, name, is_wired = JBL_INFO_MODELS[pid]
                parsed = None
                dev = hid.device()
                try:
                    dev.open_path(path)
                    hid_drain(dev, in_len, 4, 5)
                    if dev.send_feature_report(pad_report(max(64, feat_len), JBL_INFO_REQUEST)) > 0:
                        for _ in range(8):
                            raw = dev.read(in_len, 180)
                            if not raw:
                                break
                            parsed = parse_jbl_info_reply(raw)
                            if parsed is not None:
                                break
                except OSError:
                    parsed = None
                finally:
                    try:
                        dev.close()
                    except Exception:
                        pass
                pct, chg = parsed if parsed else (None, False)
                out.append(
                    DeviceBattery(
                        device_id=f"headset:{key}",
                        name=name,
                        brand="JBL",
                        kind=KIND_HEADSET,
                        connection_mode="有线" if (is_wired or chg) else "2.4G",
                        vid=vid,
                        pid=pid,
                        connected=True,
                        online=parsed is not None,
                        asleep=parsed is None,
                        percent=pct,
                        charging=chg,
                        support_status=STATUS_PROTOCOL,
                        status_detail="" if parsed else "耳机离线或休眠",
                        provider_name=self.name,
                    )
                )

            # 2. JBL Quantum 经典款 (Feature 0x68 link + 0x49 level)
            elif vid == 0x0ECB and pid in JBL_LEGACY_MODELS and feat_len >= 2:
                key, name, req_if = JBL_LEGACY_MODELS[pid]
                if req_if >= 0 and iface != req_if:
                    continue
                seen.add((vid, pid))
                online, pct = False, None
                dev = hid.device()
                try:
                    dev.open_path(path)
                    link = dev.get_feature_report(0x68, max(4, feat_len))
                    if link and len(link) >= 2 and link[0] == 0x68 and link[1] == 1:
                        online = True
                        lvl = dev.get_feature_report(0x49, max(4, feat_len))
                        if lvl and len(lvl) >= 2 and lvl[0] == 0x49 and 1 <= lvl[1] <= 100:
                            pct = int(lvl[1])
                except OSError:
                    pass
                finally:
                    try:
                        dev.close()
                    except Exception:
                        pass
                out.append(
                    DeviceBattery(
                        device_id=f"headset:{key}",
                        name=name,
                        brand="JBL",
                        kind=KIND_HEADSET,
                        connection_mode="2.4G",
                        vid=vid,
                        pid=pid,
                        connected=True,
                        online=online,
                        asleep=not online,
                        percent=pct,
                        support_status=STATUS_PROTOCOL,
                        status_detail="" if online else "耳机离线或休眠",
                        provider_name=self.name,
                    )
                )

            # 3. EPOS H3PRO Hybrid (1395:0303 / 0101, FFFF:0001)
            elif vid == 0x1395 and pid in (0x0303, 0x0101) and up == 0xFFFF and u == 0x0001:
                seen.add((vid, pid))
                is_dongle = pid == 0x0303
                online, pct = False, None
                dev = hid.device()
                try:
                    dev.open_path(path)
                    hid_drain(dev, 107, 4, 5)
                    linked = True
                    if is_dongle:
                        dev.write(build_epos_request(0x0001, 0x01, 0x09))
                        linked = False
                        for _ in range(6):
                            raw = dev.read(107, 200)
                            if not raw:
                                break
                            vals = parse_epos_reply(raw, 0x0001, 0x01, 0x09)
                            if vals is not None:
                                linked = vals == [1]
                                break
                    if linked:
                        tgt = 0x0005 if is_dongle else 0x0001
                        dev.write(build_epos_request(tgt, 0x12, 0x03))
                        for _ in range(6):
                            raw = dev.read(107, 220)
                            if not raw:
                                break
                            vals = parse_epos_reply(raw, tgt, 0x12, 0x03)
                            if vals is not None and len(vals) == 1 and vals[0] <= 100:
                                online, pct = True, int(vals[0])
                                break
                except OSError:
                    pass
                finally:
                    try:
                        dev.close()
                    except Exception:
                        pass
                out.append(
                    DeviceBattery(
                        device_id="headset:epos-h3pro-hybrid",
                        name="EPOS H3PRO Hybrid",
                        brand="EPOS",
                        kind=KIND_HEADSET,
                        connection_mode="2.4G" if is_dongle else "有线",
                        vid=vid,
                        pid=pid,
                        connected=True,
                        online=online,
                        asleep=not online,
                        percent=pct,
                        support_status=STATUS_PROTOCOL,
                        status_detail="" if online else "耳机离线或休眠",
                        provider_name=self.name,
                    )
                )

            # 4. Airoha RACE 耳机 (Audeze Maxwell / AKG N9 / Skullcandy PLYR)
            elif (vid, pid) in AIROHA_RACE_HEADSETS and up == 0xFF13 and u == 0x0001:
                seen.add((vid, pid))
                key, name, brand = AIROHA_RACE_HEADSETS[(vid, pid)]
                online, pct = False, None
                dev = hid.device()
                try:
                    dev.open_path(path)
                    # Out 06 <n=7> 80 [05 5A 03 00 D6 0C 00]
                    req = pad_report(62, [0x06, 0x07, 0x80, 0x05, 0x5A, 0x03, 0x00, 0xD6, 0x0C, 0x00])
                    dev.write(req)
                    for _ in range(5):
                        time.sleep(0.06)
                        raw = dev.read(62, 120)
                        if raw:
                            val = parse_race_battery_reply(raw)
                            if val is not None:
                                online, pct = True, val
                                break
                except OSError:
                    pass
                finally:
                    try:
                        dev.close()
                    except Exception:
                        pass
                out.append(
                    DeviceBattery(
                        device_id=f"headset:{key}",
                        name=name,
                        brand=brand,
                        kind=KIND_HEADSET,
                        connection_mode="2.4G",
                        vid=vid,
                        pid=pid,
                        connected=True,
                        online=online,
                        asleep=not online,
                        percent=pct,
                        support_status=STATUS_PROTOCOL,
                        status_detail="" if online else "耳机离线或休眠",
                        provider_name=self.name,
                    )
                )

            # 5. MCHOSE X9 / V9 Pro / FIFINE HT6 (55 65 01)
            elif (vid, pid) in CMEDIA_5565_HEADSETS:
                key, name, brand, req_up, allow_zero_chg = CMEDIA_5565_HEADSETS[(vid, pid)]
                if req_up and up != req_up:
                    continue
                if not req_up and up < 0xFF00:
                    continue
                if out_len == 0 or in_len == 0:
                    continue
                seen.add((vid, pid))
                parsed = None
                dev = hid.device()
                try:
                    dev.open_path(path)
                    hid_drain(dev, in_len, 4, 5)
                    dev.write(pad_report(out_len, [0x55, 0x65, 0x01]))
                    for _ in range(8):
                        raw = dev.read(in_len, 180)
                        if not raw:
                            break
                        parsed = parse_cmedia_5565_reply(raw, allow_zero_charge=allow_zero_chg)
                        if parsed is not None:
                            break
                except OSError:
                    parsed = None
                finally:
                    try:
                        dev.close()
                    except Exception:
                        pass
                online, pct, chg, full = parsed if parsed else (False, None, False, False)
                out.append(
                    DeviceBattery(
                        device_id=f"headset:{key}",
                        name=name,
                        brand=brand,
                        kind=KIND_HEADSET,
                        connection_mode="有线" if chg else "2.4G",
                        vid=vid,
                        pid=pid,
                        connected=True,
                        online=online,
                        asleep=not online,
                        percent=pct,
                        charging=chg and not full,
                        full=full,
                        support_status=STATUS_PROTOCOL,
                        status_detail="" if online else "耳机离线或休眠",
                        provider_name=self.name,
                    )
                )
            # 6. MCHOSE V9 Pro 2 (3837:6011, FF07:0222, MC 协议)
            elif vid == 0x3837 and pid == 0x6011 and up == 0xFF07 and u == 0x0222:
                seen.add((vid, pid))
                parsed = None
                dev = hid.device()
                try:
                    dev.open_path(path)
                    hid_drain(dev, 64, 4, 5)
                    dev.write(pad_report(64, [0x55, 0xAA, 0x01, 0x00, 0x01, 0x00, 0x01, 0x0B]))
                    for _ in range(10):
                        raw = dev.read(64, 180)
                        if not raw:
                            break
                        parsed = parse_mchose_v9_pro_2_reply(raw)
                        if parsed is not None:
                            break
                except OSError:
                    parsed = None
                finally:
                    try:
                        dev.close()
                    except Exception:
                        pass
                online, pct, chg = parsed if parsed else (False, None, False)
                out.append(
                    DeviceBattery(
                        device_id="headset:mchose-v9-pro-2",
                        name="MCHOSE V9 Pro 2",
                        brand="MCHOSE",
                        kind=KIND_HEADSET,
                        connection_mode="有线" if chg else "2.4G",
                        vid=vid,
                        pid=pid,
                        connected=True,
                        online=online,
                        asleep=not online,
                        percent=pct,
                        charging=chg,
                        support_status=STATUS_PROTOCOL,
                        status_detail="" if online else "耳机离线或休眠",
                        provider_name=self.name,
                    )
                )

            # 7. VGN OMNISOUND 无线耳机 (372E:10BB, 000C:0001, 64B, 55 65 01)
            elif vid == 0x372E and pid == 0x10BB and up == 0x000C and u == 0x0001 and out_len >= 64:
                seen.add((vid, pid))
                online, pct = False, None
                dev = hid.device()
                try:
                    dev.open_path(path)
                    hid_drain(dev, max(64, in_len), 4, 5)
                    dev.write(pad_report(out_len, [0x55, 0x65, 0x01]))
                    for _ in range(10):
                        raw = dev.read(max(64, in_len), 180)
                        if not raw:
                            break
                        r = list(raw)
                        if len(r) > 2 and r[0] == 0x55 and r[1] == 0x65 and 1 <= r[2] <= 100:
                            online, pct = True, int(r[2])
                            break
                except OSError:
                    pass
                finally:
                    try:
                        dev.close()
                    except Exception:
                        pass
                out.append(
                    DeviceBattery(
                        device_id="headset:vgn-omnisound",
                        name="VGN OMNISOUND",
                        brand="VGN",
                        kind=KIND_HEADSET,
                        connection_mode="2.4G",
                        vid=vid,
                        pid=pid,
                        connected=True,
                        online=online,
                        asleep=not online,
                        percent=pct,
                        support_status=STATUS_PROTOCOL,
                        status_detail="" if online else "耳机离线或休眠",
                        provider_name=self.name,
                    )
                )

            # 8. Lenovo Wireless VoIP Headset (17EF:A07D, FF07:0222, Feature 24 01 -> Input 27 01)
            elif vid == 0x17EF and pid == 0xA07D and up == 0xFF07 and u == 0x0222 and iface in (-1, 3):
                seen.add((vid, pid))
                online, pct = False, None
                dev = hid.device()
                try:
                    dev.open_path(path)
                    if dev.send_feature_report(pad_report(61, [0x24, 0x01])) > 0:
                        for _ in range(4):
                            raw = dev.read(64, 200)
                            if not raw:
                                break
                            r = list(raw)
                            if len(r) > 7 and r[0] == 0x27 and r[1] == 0x01 and r[2] == 0 and r[7] <= 100:
                                online, pct = True, int(r[7])
                                break
                except OSError:
                    pass
                finally:
                    try:
                        dev.close()
                    except Exception:
                        pass
                out.append(
                    DeviceBattery(
                        device_id="headset:lenovo-wireless-voip",
                        name="Lenovo Wireless VoIP Headset",
                        brand="Lenovo",
                        kind=KIND_HEADSET,
                        connection_mode="2.4G",
                        vid=vid,
                        pid=pid,
                        connected=True,
                        online=online,
                        asleep=not online,
                        percent=pct,
                        support_status=STATUS_PROTOCOL,
                        status_detail="" if online else "耳机离线或休眠",
                        provider_name=self.name,
                    )
                )
        return out

    def poll(self, hid_snapshot: list[dict], force: bool = False) -> list[DeviceBattery]:
        now_mono = time.monotonic()
        out: list[DeviceBattery] = []
        out.extend(self._poll_razer_headsets(hid_snapshot, now_mono))
        out.extend(self._poll_centurion_and_astro(hid_snapshot))
        out.extend(self._poll_jbl_epos_airoha_cmedia(hid_snapshot))
        return out
