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
    hid_drain,
    pad_report,
)

HP_VID = 0x03F0
KINGSTON_VID = 0x0951

# (vid, pid) -> (key, name, kind, proto, usage_page, usage)
HYPERX_DEVICES: dict[tuple[int, int], tuple[str, str, str, str, int, int]] = {
    (HP_VID, 0x098D): ("cloud-alpha", "HyperX Cloud Alpha Wireless", KIND_HEADSET, "alpha", 0, 0),
    (HP_VID, 0x1743): ("cloud-alpha", "HyperX Cloud Alpha Wireless", KIND_HEADSET, "alpha", 0, 0),
    (HP_VID, 0x1765): ("cloud-alpha", "HyperX Cloud Alpha Wireless", KIND_HEADSET, "alpha", 0, 0),
    (HP_VID, 0x0696): ("cloud-ii", "HyperX Cloud II Wireless", KIND_HEADSET, "cloud2_hp", 0xFF90, 0x0303),
    (HP_VID, 0x018B): ("cloud-ii", "HyperX Cloud II Wireless", KIND_HEADSET, "cloud2_hp", 0xFF90, 0x0303),
    (HP_VID, 0x0D93): ("cloud-stinger-2", "HyperX Cloud Stinger 2 Wireless", KIND_HEADSET, "cloud2_hp", 0xFF90, 0x0303),
    (HP_VID, 0x05B7): ("cloud-iii", "HyperX Cloud III Wireless", KIND_HEADSET, "cloud3", 0, 0),
    (HP_VID, 0x0C9D): ("cloud-iii", "HyperX Cloud III Wireless", KIND_HEADSET, "cloud3", 0, 0),
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


class HyperXHidProvider(BatteryProvider):
    name = "hyperx_hid"
    brand = "HyperX"

    def _ask(self, dev: hid.device, pkt: list[int], match_fn, read_len: int = 64) -> Optional[list[int]]:
        try:
            dev.write(pkt)
            for _ in range(4):
                raw = dev.read(read_len, 220)
                if not raw:
                    break
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
        seen: set[tuple[int, int]] = set()
        for d in hid_snapshot:
            vid = d.get("vendor_id", 0)
            pid = d.get("product_id", 0)
            if (vid, pid) not in HYPERX_DEVICES or (vid, pid) in seen:
                continue
            key, name, kind, proto, up, u = HYPERX_DEVICES[(vid, pid)]
            if up and d.get("usage_page") != up:
                continue
            if u and d.get("usage") != u:
                continue
            if not up and d.get("usage_page", 0) < 0xFF00:
                continue
            path = d.get("path")
            if not path:
                continue
            seen.add((vid, pid))
            res = self._query_device(path, proto)
            online, pct, charging, full = res if res else (False, None, False, False)
            out.append(
                DeviceBattery(
                    device_id=f"hyperx:{key}",
                    name=name,
                    brand="HyperX",
                    kind=kind,
                    connection_mode="2.4G",
                    vid=vid,
                    pid=pid,
                    connected=True,
                    online=online,
                    asleep=not online,
                    percent=pct,
                    charging=charging and not full,
                    full=full,
                    support_status=STATUS_PROTOCOL,
                    status_detail="" if online else "离线或休眠",
                    provider_name=self.name,
                )
            )
        return out
