"""HyperX 无线耳机与 Pulsefire 无线鼠标 HID 适配器。

协议参考（公开协议与 MIT 参考项目 qu1ncky/BatteryTray）：
- Cloud Alpha Wireless (`21 BB 03/0B/0C`)
- Cloud II Wireless HP (`06 FF BB 02/03`, 52 字节) / Kingston (`06 ... BB`)
- Cloud III / II Core Wireless (`66 82/89/8A`, 62 字节)
- Cloud III S Wireless (`0C 02 03 01 00 02/06/48`)
- Pulsefire Haste 2 Wireless / Mini / Core (`52 01` / `50 02`, 64 字节)
- Pulsefire Haste Wireless / Dart (`46` / `51`, 64 字节)
"""

from __future__ import annotations

from typing import Optional

import hid

from .base import (
    BatteryProvider,
    DeviceBattery,
    KIND_HEADSET,
    KIND_MOUSE,
    STATUS_PROTOCOL,
    get_hid_report_lengths,
    hid_drain,
    interpolate_voltage,
    pad_report,
    round_half_up,
)

HP_VID = 0x03F0
KINGSTON_VID = 0x0951

# (vid, pid) -> (key, name, kind, proto, usage_page, usage)
HYPERX_DEVICES: dict[tuple[int, int], tuple[str, str, str, str, int, int]] = {
    (HP_VID, 0x098D): ("cloud-alpha", "HyperX Cloud Alpha Wireless", KIND_HEADSET, "alpha", 0, 0),
    (HP_VID, 0x1743): ("cloud-alpha", "HyperX Cloud Alpha Wireless", KIND_HEADSET, "alpha", 0, 0),
    (HP_VID, 0x1765): ("cloud-alpha", "HyperX Cloud Alpha Wireless", KIND_HEADSET, "alpha", 0, 0),
    (HP_VID, 0x08BE): ("cloud-alpha-2", "HyperX Cloud Alpha 2 Wireless", KIND_HEADSET, "universal", 0xFF13, 0xFF00),
    (HP_VID, 0x0696): ("cloud-ii", "HyperX Cloud II Wireless", KIND_HEADSET, "cloud2_hp", 0xFF90, 0x0303),
    (HP_VID, 0x018B): ("cloud-ii", "HyperX Cloud II Wireless", KIND_HEADSET, "cloud2_hp", 0xFF90, 0x0303),
    (KINGSTON_VID, 0x1718): ("cloud-ii", "HyperX Cloud II Wireless", KIND_HEADSET, "cloud2_kingston", 0, 0),
    (KINGSTON_VID, 0x16EA): ("cloud-flight-s", "HyperX Cloud Flight S", KIND_HEADSET, "cloud2_kingston", 0, 0),
    (KINGSTON_VID, 0x16EB): ("cloud-flight-s", "HyperX Cloud Flight S", KIND_HEADSET, "cloud2_kingston", 0, 0),
    (KINGSTON_VID, 0x16C4): ("cloud-flight", "HyperX Cloud Flight", KIND_HEADSET, "cloud_flight", 0, 0),
    (KINGSTON_VID, 0x1723): ("cloud-flight", "HyperX Cloud Flight", KIND_HEADSET, "cloud_flight", 0, 0),
    (KINGSTON_VID, 0x1749): ("cloud-flight", "HyperX Cloud Flight", KIND_HEADSET, "cloud_flight", 0, 0),
    (HP_VID, 0x0E90): ("cloud-flight", "HyperX Cloud Flight", KIND_HEADSET, "cloud_flight", 0, 0),
    (HP_VID, 0x0D93): ("cloud-stinger-2", "HyperX Cloud Stinger 2 Wireless", KIND_HEADSET, "cloud2_hp", 0xFF90, 0x0303),
    (HP_VID, 0x0A93): ("cloud-stinger-core", "HyperX Cloud Stinger Core Wireless", KIND_HEADSET, "stinger_core", 0xFF00, 0x0001),
    (KINGSTON_VID, 0x1713): ("cloud-stinger-core", "HyperX Cloud Stinger Core Wireless", KIND_HEADSET, "stinger_core", 0xFF00, 0x0001),
    (HP_VID, 0x0A8E): ("cloud-stinger-core-dts", "HyperX Cloud Stinger Core Wireless DTS", KIND_HEADSET, "stinger_core", 0xFF00, 0x0001),
    (HP_VID, 0x05B7): ("cloud-iii", "HyperX Cloud III Wireless", KIND_HEADSET, "cloud3", 0, 0),
    (HP_VID, 0x0C9D): ("cloud-iii", "HyperX Cloud III Wireless", KIND_HEADSET, "cloud3", 0, 0),
    (HP_VID, 0x06BE): ("cloud-iii-s", "HyperX Cloud III S Wireless", KIND_HEADSET, "cloud3s", 0, 0),
    (HP_VID, 0x02CC): ("cloud-iii-s", "HyperX Cloud III S Wireless", KIND_HEADSET, "cloud3s", 0, 0),
    (HP_VID, 0x069F): ("cloud-ii-core", "HyperX Cloud II Core Wireless", KIND_HEADSET, "cloud3", 0, 0),
    (HP_VID, 0x0995): ("cloud-ii-core", "HyperX Cloud II Core Wireless", KIND_HEADSET, "cloud3", 0, 0),
    (HP_VID, 0x0F98): ("pulsefire-haste-2", "HyperX Pulsefire Haste 2 Wireless", KIND_MOUSE, "universal", 0, 0),
    (HP_VID, 0x0D97): ("pulsefire-haste-2", "HyperX Pulsefire Haste 2 Wireless", KIND_MOUSE, "universal", 0, 0),
    (HP_VID, 0x0AB5): ("pulsefire-haste-2-core", "HyperX Pulsefire Haste 2 Core", KIND_MOUSE, "universal", 0, 0),
    (HP_VID, 0x0DA0): ("pulsefire-haste-2-mini", "HyperX Pulsefire Haste 2 Mini", KIND_MOUSE, "universal", 0, 0),
    (HP_VID, 0x028E): ("pulsefire-haste", "HyperX Pulsefire Haste Wireless", KIND_MOUSE, "ngenuity2", 0xFF00, 0x0001),
    (KINGSTON_VID, 0x16E1): ("pulsefire-dart", "HyperX Pulsefire Dart", KIND_MOUSE, "ngenuity2", 0xFF00, 0x0001),
}


def parse_hyperx_alpha_battery(reply: list[int] | bytes) -> Optional[int]:
    if len(reply) > 3 and reply[0] == 0x21 and reply[1] == 0xBB and reply[2] == 0x0B and reply[3] <= 100:
        return int(reply[3])
    return None


def parse_hyperx_cloud2_hp(reply: list[int] | bytes) -> Optional[int]:
    if len(reply) >= 8 and reply[0] == 0x06 and reply[1] == 0xFF and reply[2] == 0xBB and reply[3] == 0x02 and reply[7] <= 100:
        return int(reply[7])
    return None


def parse_hyperx_universal_battery(reply: list[int] | bytes) -> Optional[tuple[int, bool, bool]]:
    """解析 HyperX Universal 协议 0x51 0x02 电池回包 -> (percent, charging, full)。"""
    if len(reply) >= 4 and reply[0] == 0x51 and reply[1] == 0x02 and reply[2] <= 100:
        return (int(reply[2]), reply[3] == 1, reply[3] == 2)
    return None


def parse_hyperx_ngenuity2_heartbeat(reply: list[int] | bytes) -> Optional[tuple[int, bool, bool]]:
    """解析 Pulsefire Haste / Dart 0x51 回包 -> (percent, charging, full)。"""
    r = list(reply)
    if len(r) >= 7 and r[0] == 0x00 and r[1] == 0x51:
        r = r[1:]
    if len(r) >= 6 and r[0] == 0x51 and r[4] <= 100:
        return (int(r[4]), r[5] == 1, r[5] == 2)
    return None


def parse_hyperx_cloud3s_reply(reply: list[int] | bytes, field_id: int) -> Optional[int]:
    """解析 Cloud III S Wireless Report 0x0C 回包，返回字段值。"""
    r = list(reply)
    if len(r) >= 7 and r[0] == 0x0C and r[5] == field_id:
        return int(r[6])
    return None


def parse_hyperx_cloud_flight_voltage(reply: list[int] | bytes) -> Optional[tuple[bool, Optional[int], bool]]:
    """解析 Cloud Flight 电压回包 -> (online, percent, charging)。"""
    r = list(reply)
    if len(r) < 5 or r[0] in (0x64, 0x65):
        return None
    mv = (r[3] << 8) | r[4]
    if mv > 4107:
        return (True, None, True)
    if mv < 3000:
        return (False, None, False)
    if mv <= 3648:
        pct = round_half_up(0.00125 * mv)
    elif mv > 3975:
        pct = 100
    else:
        v = float(mv)
        pct = round_half_up(2.547505e-8 * v**4 - 3.900299e-4 * v**3 + 2.238321 * v**2 - 5706.256 * v + 5452299.0)
    return (True, max(0, min(100, pct)), False)


_STINGER_MV = (3517, 3651, 3700, 3738, 3763, 3785, 3838, 3905, 3954, 4042, 4121)
_STINGER_CURVE: list[tuple[int, int]] = [(mv, idx * 10) for idx, mv in reversed(list(enumerate(_STINGER_MV)))]


def parse_hyperx_stinger_core_battery(reply: list[int] | bytes) -> Optional[tuple[Optional[int], bool, bool]]:
    """解析 Cloud Stinger Core Wireless Feature 0xFF 电池回包 -> (percent, charging, full)（标准四舍五入插值）。"""
    r = list(reply)
    if len(r) < 13 or r[0] != 0xFF or r[1] != 0x12 or r[2] != 0x05:
        return None
    code = r[9]
    mv = r[11] | (r[12] << 8)
    if code == 0x03 and 3000 <= mv <= 4400:
        return (interpolate_voltage(mv, _STINGER_CURVE), False, False)
    if code == 0x05:
        return (None, True, False)
    if code == 0x06:
        return (100, False, True)
    return None


class HyperXHidProvider(BatteryProvider):
    name = "hyperx_hid"
    brand = "HyperX"

    def __init__(self) -> None:
        self._cache: dict[str, DeviceBattery] = {}

    def _ask(self, dev: hid.device, pkt: list[int], match_fn, read_len: int = 64) -> Optional[list[int]]:
        try:
            dev.write(pkt)
            for _ in range(8):
                raw = dev.read(read_len, 180)
                if not raw:
                    break
                if not any(raw):
                    continue
                if match_fn(raw):
                    return list(raw)
        except OSError:
            return None
        return None

    def _query_device(self, path: bytes, proto: str) -> Optional[tuple[bool, Optional[int], bool, bool]]:
        dev = hid.device()
        try:
            dev.open_path(path)
            hid_drain(dev, 64, 4, 10)

            if proto == "alpha":
                link = self._ask(dev, [0x21, 0xBB, 0x03], lambda d: len(d) > 3 and d[0] == 0x21 and d[1] == 0xBB and d[2] == 0x03)
                if not link or link[3] == 0x01:
                    return (False, None, False, False)
                chg = self._ask(dev, [0x21, 0xBB, 0x0C], lambda d: len(d) > 3 and d[0] == 0x21 and d[1] == 0xBB and d[2] == 0x0C)
                bat = self._ask(dev, [0x21, 0xBB, 0x0B], lambda d: parse_hyperx_alpha_battery(d) is not None)
                pct = parse_hyperx_alpha_battery(bat) if bat else None
                return (pct is not None, pct, bool(chg and chg[3] == 0x01), False)

            if proto == "cloud2_hp":
                bat = self._ask(dev, pad_report(52, [0x06, 0xFF, 0xBB, 0x02]), lambda d: parse_hyperx_cloud2_hp(d) is not None)
                if not bat:
                    return (False, None, False, False)
                chg = self._ask(dev, pad_report(52, [0x06, 0xFF, 0xBB, 0x03]), lambda d: len(d) >= 5 and d[0] == 0x06 and d[3] == 0x03)
                return (True, parse_hyperx_cloud2_hp(bat), bool(chg and chg[4] == 0x01), False)

            if proto == "cloud3":
                link = self._ask(dev, pad_report(62, [0x66, 0x82]), lambda d: len(d) > 2 and d[0] == 0x66 and d[1] in (0x82, 0x0B))
                if not link or link[2] != 0x01:
                    return (False, None, False, False)
                pwr = self._ask(dev, pad_report(62, [0x66, 0x8A]), lambda d: len(d) > 2 and d[0] == 0x66 and d[1] in (0x8A, 0x0C))
                bat = self._ask(dev, pad_report(62, [0x66, 0x89]), lambda d: len(d) > 4 and d[0] == 0x66 and d[1] in (0x89, 0x0D))
                pct = min(100, bat[4]) if (bat and (bat[2] | bat[3]) != 0) else None
                pcode = pwr[2] if pwr else 0
                return (True, pct, pcode == 1, pcode == 2)

            if proto == "cloud2_kingston":
                pkt_bat = pad_report(62, [0x06, 0x00, 0x02, 0x00, 0x9A, 0x00, 0x00, 0x68, 0x4A, 0x8E, 0x0A, 0, 0, 0, 0xBB, 0x02])
                bat = self._ask(dev, pkt_bat, lambda d: len(d) >= 8 and d[0] == 0x0B and d[2] == 0xBB and d[3] == 0x02)
                if not bat or bat[7] > 100:
                    return (False, None, False, False)
                pkt_chg = pad_report(62, [0x06, 0x00, 0x02, 0x00, 0x9A, 0x00, 0x00, 0x68, 0x4A, 0x8E, 0x0A, 0, 0, 0, 0xBB, 0x03])
                chg = self._ask(dev, pkt_chg, lambda d: len(d) >= 5 and d[0] == 0x0B and d[2] == 0xBB and d[3] == 0x03)
                return (True, int(bat[7]), bool(chg and chg[4] == 0x01), False)

            if proto == "cloud_flight":
                raw = self._ask(dev, pad_report(20, [0x21, 0xFF, 0x05]), lambda d: len(d) >= 5 and d[0] not in (0x64, 0x65))
                res = parse_hyperx_cloud_flight_voltage(raw) if raw else None
                return (res[0], res[1], res[2], False) if res else (False, None, False, False)

            if proto == "cloud3s":
                def _ask_c3s(field_id: int) -> Optional[int]:
                    raw = self._ask(
                        dev,
                        pad_report(64, [0x0C, 0x02, 0x03, 0x01, 0x00, field_id]),
                        lambda d: parse_hyperx_cloud3s_reply(d, field_id) is not None,
                    )
                    return parse_hyperx_cloud3s_reply(raw, field_id) if raw else None

                if _ask_c3s(0x02) != 0x02:
                    return (False, None, False, False)
                lvl = _ask_c3s(0x06)
                chg = _ask_c3s(0x48)
                pct = lvl if (lvl is not None and lvl <= 100) else None
                return (True, pct, chg == 1, chg == 2)

            if proto == "stinger_core":
                import time as _time
                link_req = [0xFF, 0x07, 0x00, 0xFD, 0x04, 0x00, 0x00, 0x02, 0x82, 0x03, 0x05, 0x29, 0x0F, 0x00, 0x00, 0x03, 0x68, 0x10, 0x00, 0x00]
                if dev.send_feature_report(pad_report(64, link_req)) <= 0:
                    return (False, None, False, False)
                linked = False
                for _ in range(8):
                    _time.sleep(0.02)
                    rep = dev.get_feature_report(0xFF, 64)
                    if rep and len(rep) >= 13 and rep[0] == 0xFF and not (rep[1] == 0x01 and rep[2] == 0x00):
                        linked = rep[11] == 0x01
                        break
                if not linked:
                    return (False, None, False, False)
                bat_req = [0xFF, 0x07, 0x00, 0xFD, 0x04, 0x0C, 0xF1, 0x02, 0x01, 0x04, 0xF0, 0x0C]
                if dev.send_feature_report(pad_report(64, bat_req)) <= 0:
                    return (True, None, False, False)
                for _ in range(8):
                    _time.sleep(0.02)
                    rep = dev.get_feature_report(0xFF, 64)
                    res = parse_hyperx_stinger_core_battery(rep) if rep else None
                    if res is not None:
                        return (True, res[0], res[1], res[2])
                return (True, None, False, False)

            if proto == "universal":
                link = self._ask(dev, pad_report(64, [0x52, 0x01]), lambda d: len(d) > 2 and d[0] == 0x53 and d[1] == 0x01)
                if not link or link[2] == 0:
                    return (False, None, False, False)
                bat = self._ask(dev, pad_report(64, [0x50, 0x02]), lambda d: parse_hyperx_universal_battery(d) is not None)
                res = parse_hyperx_universal_battery(bat) if bat else None
                return (True, res[0], res[1], res[2]) if res else (False, None, False, False)

            if proto == "ngenuity2":
                bat = self._ask(dev, pad_report(65, [0x00, 0x51]), lambda d: parse_hyperx_ngenuity2_heartbeat(d) is not None, 65)
                res = parse_hyperx_ngenuity2_heartbeat(bat) if bat else None
                return (True, res[0], res[1], res[2]) if res else (False, None, False, False)
        except OSError:
            return None
        finally:
            try:
                dev.close()
            except Exception:
                pass
        return None

    def poll(self, hid_snapshot: list[dict]) -> list[DeviceBattery]:
        out: list[DeviceBattery] = []
        grouped: dict[tuple[int, int], list[dict]] = {}
        for d in hid_snapshot:
            vid = int(d.get("vendor_id", 0))
            pid = int(d.get("product_id", 0))
            if (vid, pid) not in HYPERX_DEVICES:
                continue
            key, name, kind, proto, up, u = HYPERX_DEVICES[(vid, pid)]
            path = d.get("path")
            if not path:
                continue
            if proto == "cloud3s":
                in_len, out_len, _ = get_hid_report_lengths(path)
                if in_len != 64 or out_len != 64:
                    continue
            elif proto == "stinger_core":
                if d.get("usage_page") != 0xFF00 or d.get("usage") != 0x0001:
                    continue
                _, _, feat_len = get_hid_report_lengths(path)
                if feat_len < 32:
                    continue
            else:
                if up and d.get("usage_page") != up:
                    continue
                if u and d.get("usage") != u:
                    continue
                if not up and d.get("usage_page", 0) < 0xFF00:
                    continue
            grouped.setdefault((vid, pid), []).append(d)

        for (vid, pid), colls in grouped.items():
            key, name, kind, proto, _up, _u = HYPERX_DEVICES[(vid, pid)]
            res = None
            for c in colls:
                cand = self._query_device(c["path"], proto)
                if cand is not None:
                    res = cand
                    if cand[0]:
                        break
            online, pct, charging, full = res if res else (False, None, False, False)
            dev_id = f"hyperx:{key}"
            prev = self._cache.get(dev_id)
            item = DeviceBattery(
                device_id=dev_id,
                name=name,
                brand="HyperX",
                kind=kind,
                connection_mode="2.4G",
                vid=vid,
                pid=pid,
                connected=True,
                online=online,
                asleep=not online,
                percent=pct if online else (prev.percent if prev else None),
                charging=charging and not full,
                full=full,
                support_status=STATUS_PROTOCOL,
                status_detail="" if online else "离线或休眠",
                provider_name=self.name,
            )
            if online:
                self._cache[dev_id] = item
            out.append(item)
        return out
