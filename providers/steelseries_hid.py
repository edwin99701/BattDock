"""SteelSeries 赛睿无线鼠标与 Arctis / Nova 无线耳机 HID 适配器。

协议参考（公开协议与 MIT 参考项目 qu1ncky/BatteryTray）：
- 无线鼠标（Aerox 3/5/9、Aerox 3 Gen 2、Prime、Rival 3/650）：
  Aerox/Prime 有线 0x92 / 无线 0xD2；Rival 0xAA 0x01。
- 无线耳机（Arctis 1 / 7 / 7+ / 9 / Pro / Nova 5 / Nova 7 / Nova Pro / Nova Elite / GameBuds）。
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
    KIND_MOUSE,
    STATUS_PROTOCOL,
    get_hid_report_lengths,
    hid_drain,
    map_range,
    pad_report,
)

STEELSERIES_VID = 0x1038


@dataclass(frozen=True)
class SteelSeriesMouseModel:
    key: str
    name: str
    interface: int
    protocol: str  # "aerox" | "aerox_gen2" | "rival"
    wireless: bool


MOUSE_MODELS: dict[int, SteelSeriesMouseModel] = {
    0x1838: SteelSeriesMouseModel("aerox3", "SteelSeries Aerox 3 Wireless", 3, "aerox", True),
    0x1878: SteelSeriesMouseModel("aerox3", "SteelSeries Aerox 3 Wireless", 3, "aerox", True),
    0x183A: SteelSeriesMouseModel("aerox3", "SteelSeries Aerox 3 Wireless", 3, "aerox", False),
    0x187A: SteelSeriesMouseModel("aerox3", "SteelSeries Aerox 3 Wireless", 3, "aerox", False),
    0x1890: SteelSeriesMouseModel("aerox3gen2", "SteelSeries Aerox 3 Wireless Gen 2", 3, "aerox_gen2", True),
    0x1892: SteelSeriesMouseModel("aerox3gen2", "SteelSeries Aerox 3 Wireless Gen 2", 3, "aerox_gen2", False),
    0x1852: SteelSeriesMouseModel("aerox5", "SteelSeries Aerox 5 Wireless", 3, "aerox", True),
    0x1854: SteelSeriesMouseModel("aerox5", "SteelSeries Aerox 5 Wireless", 3, "aerox", False),
    0x1858: SteelSeriesMouseModel("aerox9", "SteelSeries Aerox 9 Wireless", 3, "aerox", True),
    0x185A: SteelSeriesMouseModel("aerox9", "SteelSeries Aerox 9 Wireless", 3, "aerox", False),
    0x1840: SteelSeriesMouseModel("prime", "SteelSeries Prime Wireless", 3, "aerox", True),
    0x1842: SteelSeriesMouseModel("prime", "SteelSeries Prime Wireless", 3, "aerox", False),
    0x1848: SteelSeriesMouseModel("primemini", "SteelSeries Prime Mini Wireless", 3, "aerox", True),
    0x184A: SteelSeriesMouseModel("primemini", "SteelSeries Prime Mini Wireless", 3, "aerox", False),
    0x1830: SteelSeriesMouseModel("rival3", "SteelSeries Rival 3 Wireless", 3, "rival", True),
    0x1872: SteelSeriesMouseModel("rival3gen2", "SteelSeries Rival 3 Wireless Gen 2", 3, "rival", True),
    0x1726: SteelSeriesMouseModel("rival650", "SteelSeries Rival 650 Wireless", 0, "rival", True),
    0x172B: SteelSeriesMouseModel("rival650", "SteelSeries Rival 650 Wireless", 0, "rival", False),
}

# 耳机表: pid -> (key, name, proto, interface, usage_page, kind)
HEADSET_MODELS: dict[int, tuple[str, str, str, int, int, str]] = {
    0x12B3: ("arctis-1", "SteelSeries Arctis 1 Wireless", "arctis1", 3, 0xFF43, KIND_HEADSET),
    0x12B6: ("arctis-1", "SteelSeries Arctis 1 Wireless", "arctis1", 3, 0xFF43, KIND_HEADSET),
    0x12D7: ("arctis-1", "SteelSeries Arctis 1 Wireless", "arctis1", 3, 0xFF43, KIND_HEADSET),
    0x12D5: ("arctis-1", "SteelSeries Arctis 1 Wireless", "arctis1", 3, 0xFF43, KIND_HEADSET),
    0x1260: ("arctis-7", "SteelSeries Arctis 7", "arctis7", 5, 0, KIND_HEADSET),
    0x12AD: ("arctis-7", "SteelSeries Arctis 7 (2019)", "arctis7", 5, 0, KIND_HEADSET),
    0x1252: ("arctis-7", "SteelSeries Arctis Pro", "arctis7", 5, 0, KIND_HEADSET),
    0x1280: ("arctis-7", "SteelSeries Arctis 7", "arctis7", 5, 0, KIND_HEADSET),
    0x12C2: ("arctis-9", "SteelSeries Arctis 9", "arctis9", -1, 0, KIND_HEADSET),
    0x12C4: ("arctis-9", "SteelSeries Arctis 9", "arctis9", -1, 0, KIND_HEADSET),
    0x1290: ("arctis-pro-wireless", "SteelSeries Arctis Pro Wireless", "arctis_pro", -1, 0, KIND_HEADSET),
    0x12E0: ("arctis-nova-pro", "SteelSeries Arctis Nova Pro Wireless", "nova_pro", 4, 0, KIND_HEADSET),
    0x12E5: ("arctis-nova-pro", "SteelSeries Arctis Nova Pro Wireless", "nova_pro", 4, 0, KIND_HEADSET),
    0x225D: ("arctis-nova-pro", "SteelSeries Arctis Nova Pro Wireless", "nova_pro", 4, 0, KIND_HEADSET),
    0x2244: ("arctis-nova-elite", "SteelSeries Arctis Nova Elite", "nova_elite", 3, 0, KIND_HEADSET),
    0x2246: ("arctis-nova-elite", "SteelSeries Arctis Nova Elite", "nova_elite", 3, 0, KIND_HEADSET),
    0x2249: ("arctis-nova-elite", "SteelSeries Arctis Nova Elite", "nova_elite", 3, 0, KIND_HEADSET),
    0x2270: ("arctis-nova-elite", "SteelSeries Arctis Nova Elite", "nova_elite", 3, 0, KIND_HEADSET),
    0x2290: ("arctis-nova-pro-omni", "SteelSeries Arctis Nova Pro Omni", "nova_omni", 3, 0, KIND_HEADSET),
    0x220E: ("arctis-7-plus", "SteelSeries Arctis 7+", "arctis7p", 3, 0xFFC0, KIND_HEADSET),
    0x2212: ("arctis-7-plus", "SteelSeries Arctis 7+", "arctis7p", 3, 0xFFC0, KIND_HEADSET),
    0x2216: ("arctis-7-plus", "SteelSeries Arctis 7+", "arctis7p", 3, 0xFFC0, KIND_HEADSET),
    0x2236: ("arctis-7-plus", "SteelSeries Arctis 7+", "arctis7p", 3, 0xFFC0, KIND_HEADSET),
    0x2202: ("arctis-nova-7", "SteelSeries Arctis Nova 7", "nova7_steps", 3, 0xFFC0, KIND_HEADSET),
    0x2206: ("arctis-nova-7", "SteelSeries Arctis Nova 7", "nova7_steps", 3, 0xFFC0, KIND_HEADSET),
    0x220A: ("arctis-nova-7", "SteelSeries Arctis Nova 7", "nova7_steps", 3, 0xFFC0, KIND_HEADSET),
    0x223A: ("arctis-nova-7", "SteelSeries Arctis Nova 7", "nova7_steps", 3, 0xFFC0, KIND_HEADSET),
    0x227A: ("arctis-nova-7", "SteelSeries Arctis Nova 7", "nova7_steps", 3, 0xFFC0, KIND_HEADSET),
    0x22A4: ("arctis-nova-7", "SteelSeries Arctis Nova 7", "nova7_steps", 3, 0xFFC0, KIND_HEADSET),
    0x2258: ("arctis-nova-7", "SteelSeries Arctis Nova 7", "nova7_pct", 3, 0xFFC0, KIND_HEADSET),
    0x22A1: ("arctis-nova-7", "SteelSeries Arctis Nova 7", "nova7_pct", 3, 0xFFC0, KIND_HEADSET),
    0x227E: ("arctis-nova-7", "SteelSeries Arctis Nova 7", "nova7_pct", 3, 0xFFC0, KIND_HEADSET),
    0x229E: ("arctis-nova-7", "SteelSeries Arctis Nova 7", "nova7_pct", 3, 0xFFC0, KIND_HEADSET),
    0x22AD: ("arctis-nova-7", "SteelSeries Arctis Nova 7", "nova7_pct", 3, 0xFFC0, KIND_HEADSET),
    0x22A9: ("arctis-nova-7", "SteelSeries Arctis Nova 7", "nova7_pct", 3, 0xFFC0, KIND_HEADSET),
    0x22A5: ("arctis-nova-7", "SteelSeries Arctis Nova 7", "nova7_pct", 3, 0xFFC0, KIND_HEADSET),
    0x22A7: ("arctis-nova-7", "SteelSeries Arctis Nova 7", "nova7_pct", 3, 0xFFC0, KIND_HEADSET),
    0x2298: ("arctis-nova-7", "SteelSeries Arctis Nova 7", "nova7_pct", 3, 0xFFC0, KIND_HEADSET),
    0x2232: ("arctis-nova-5", "SteelSeries Arctis Nova 5", "nova5", 3, 0xFFC0, KIND_HEADSET),
    0x2253: ("arctis-nova-5", "SteelSeries Arctis Nova 5", "nova5", 3, 0xFFC0, KIND_HEADSET),
    0x2269: ("arctis-nova-5", "SteelSeries Arctis Nova 5 / Nova 3P", "nova5", 3, 0xFFC0, KIND_HEADSET),
    0x226D: ("arctis-nova-5", "SteelSeries Arctis Nova 5 / Nova 3P", "nova5", 3, 0xFFC0, KIND_HEADSET),
    0x230A: ("arctis-gamebuds", "SteelSeries Arctis GameBuds", "gamebuds", 3, 0xFFC0, KIND_EARBUDS),
}


def parse_steelseries_mouse(reply: list[int] | bytes, protocol: str, command: int) -> Optional[tuple[Optional[int], bool, bool]]:
    """解析 SteelSeries 鼠标回包（兼容 hidapi 含/不含前导 Report ID），返回 (percent, charging, full)。"""
    if not reply:
        return None
    # hidapi 在 Windows 无 Report ID 设备上可能直接返回负载字节，统一对齐
    r = list(reply)
    if protocol == "aerox":
        if len(r) < 2:
            return None
        b = r[2] if (len(r) >= 3 and r[0] == 0x00) else r[1]
        pct = ((b & 0x7F) - 1) * 5
        if not (0 <= pct <= 100):
            return None
        return (pct, bool(b & 0x80), False)

    if protocol == "aerox_gen2":
        off = 1 if (len(r) >= 4 and r[0] == 0x00 and r[1] == command) else 0
        if len(r) < off + 3 or r[off] != command:
            return None
        status, level = r[off + 1], r[off + 2]
        pct = level if level <= 100 else None
        return (pct, status == 1, status == 2)

    if protocol == "rival":
        off = 1 if (len(r) >= 4 and r[0] == 0x00) else 0
        if len(r) < off + 3:
            return None
        level = r[off]
        charging = r[off + 2] != 0
        if not (0 <= level <= 100):
            return None
        return (level, charging, False)

    return None


def parse_steelseries_headset(proto: str, reply: list[int] | bytes) -> Optional[tuple[bool, Optional[int], bool]]:
    """解析 SteelSeries 无线耳机状态回包，返回 (online, percent, charging)。"""
    r = list(reply)
    if not r:
        return None
    if proto == "arctis1" and len(r) > 3:
        if r[2] == 0x01:
            return (False, None, False)
        return (True, min(100, r[3]), False)
    if proto == "arctis7" and len(r) > 2:
        return (True, min(100, r[2]), False)
    if proto == "arctis9" and len(r) > 4:
        if r[4] == 0xFF:
            return (False, None, False)
        return (True, map_range(r[3], 0x64, 0x9A), r[4] == 0x01)
    if proto == "nova_pro" and len(r) >= 16 and r[1] == 0xB0:
        if r[15] == 0x01:
            return (False, None, False)
        return (True, map_range(r[6], 0, 8), r[15] == 0x02)
    if proto in ("nova_elite", "nova_omni") and len(r) >= 16 and r[0] == 0x01 and r[1] == 0xB0:
        omni = proto == "nova_omni"
        level, power, charge = r[6], r[14], r[15]
        there = power != 0x01 and (not omni or charge in (0x02, 0x08))
        charging = charge == 0x02 or (not omni and power == 0x02)
        if not there or level > 100 or (level == 0 and not charging):
            return (False, None, False)
        return (True, int(level), charging)
    if proto == "arctis7p" and len(r) >= 4:
        if r[1] == 0x01:
            return (False, None, False)
        return (True, map_range(r[2], 0, 4), r[3] == 0x01)
    if proto in ("nova7_steps", "nova7_pct") and len(r) >= 4:
        if r[3] == 0x00:
            return (False, None, False)
        pct = map_range(r[2], 0, 4) if proto == "nova7_steps" else min(100, r[2])
        return (True, pct, r[3] in (0x01, 0x02))
    if proto == "nova5" and len(r) >= 5:
        if r[1] == 0x02:
            return (False, None, False)
        return (True, min(100, r[3]), r[4] == 0x01)
    if proto == "gamebuds" and len(r) >= 7:
        vals = [pct for st, pct in ((r[3], r[5]), (r[4], r[6])) if st == 0x03 and pct <= 100]
        return (True, min(vals), False) if vals else (False, None, False)
    return None


class SteelSeriesHidProvider(BatteryProvider):
    name = "steelseries_hid"
    brand = "SteelSeries"

    def _poll_mice(self, hid_snapshot: list[dict]) -> list[DeviceBattery]:
        by_pid: dict[int, list[dict]] = {}
        for d in hid_snapshot:
            if d.get("vendor_id") == STEELSERIES_VID and d.get("product_id") in MOUSE_MODELS:
                by_pid.setdefault(d["product_id"], []).append(d)

        out: list[DeviceBattery] = []
        for pid, colls in by_pid.items():
            model = MOUSE_MODELS[pid]
            cmd = 0xAA if model.protocol == "rival" else (0xD2 if model.wireless else 0x92)
            req = [0x00, 0xAA, 0x01] if model.protocol == "rival" else [0x00, cmd]
            parsed = None
            for c in colls:
                if max(0, int(c.get("interface_number", 0))) != model.interface:
                    continue
                if c.get("usage_page", 0) < 0xFF00:
                    continue
                path = c.get("path")
                if not path:
                    continue
                in_len, out_len, _ = get_hid_report_lengths(path)
                if in_len == 0 or out_len == 0:
                    continue
                dev = hid.device()
                try:
                    dev.open_path(path)
                    hid_drain(dev, in_len, 4, 10)
                    dev.write(pad_report(out_len, req))
                    raw = dev.read(in_len, 300)
                    if raw:
                        parsed = parse_steelseries_mouse(raw, model.protocol, cmd)
                        if parsed is not None:
                            break
                except OSError:
                    continue
                finally:
                    try:
                        dev.close()
                    except Exception:
                        pass

            pct, charging, full = parsed if parsed else (None, False, False)
            out.append(
                DeviceBattery(
                    device_id=f"steelseries:{model.key}",
                    name=model.name,
                    brand="SteelSeries",
                    kind=KIND_MOUSE,
                    connection_mode="有线" if (not model.wireless or charging) else "2.4G",
                    vid=STEELSERIES_VID,
                    pid=pid,
                    connected=True,
                    online=parsed is not None,
                    asleep=parsed is None,
                    percent=pct,
                    charging=charging and not full,
                    full=full,
                    support_status=STATUS_PROTOCOL,
                    status_detail="" if parsed is not None else "休眠中",
                    provider_name=self.name,
                )
            )
        return out

    def _poll_headsets(self, hid_snapshot: list[dict]) -> list[DeviceBattery]:
        seen: set[int] = set()
        out: list[DeviceBattery] = []
        for d in hid_snapshot:
            if d.get("vendor_id") != STEELSERIES_VID:
                continue
            pid = d.get("product_id", 0)
            if pid not in HEADSET_MODELS or pid in seen:
                continue
            key, name, proto, iface, up, kind = HEADSET_MODELS[pid]
            if iface >= 0 and d.get("interface_number") != iface:
                continue
            if up and d.get("usage_page") != up:
                continue
            if proto in ("nova_elite", "nova_omni"):
                if int(d.get("usage_page", 0)) < 0xFF00:
                    continue
                _, out_len, _ = get_hid_report_lengths(d.get("path"))
                if out_len == 0:
                    continue
            path = d.get("path")
            if not path:
                continue
            seen.add(pid)

            req_map = {
                "arctis1": [0x06, 0x12],
                "arctis7": [0x06, 0x18],
                "arctis9": [0x00, 0x20],
                "nova_pro": pad_report(31, [0x06, 0xB0]),
                "nova_elite": pad_report(64, [0x01, 0xB0]),
                "nova_omni": pad_report(64, [0x01, 0xB0]),
                "arctis7p": pad_report(64, [0x00, 0xB0]),
                "nova7_steps": pad_report(64, [0x00, 0xB0]),
                "nova7_pct": pad_report(64, [0x00, 0xB0]),
                "nova5": pad_report(64, [0x00, 0xB0]),
                "gamebuds": pad_report(64, [0x00, 0xB0]),
            }
            dev = hid.device()
            parsed = None
            try:
                dev.open_path(path)
                hid_drain(dev, 64, 4, 10)
                if proto == "arctis_pro":
                    dev.write(pad_report(31, [0x41, 0xAA]))
                    link = dev.read(64, 250)
                    if link and link[0] != 0x02:
                        dev.write(pad_report(31, [0x40, 0xAA]))
                        bat = dev.read(64, 250)
                        if bat:
                            parsed = (True, map_range(bat[0], 0, 4), False)
                    else:
                        parsed = (False, None, False)
                else:
                    dev.write(req_map[proto])
                    for _ in range(8 if proto in ("nova_elite", "nova_omni") else 4):
                        raw = dev.read(64, 250)
                        if not raw:
                            break
                        parsed = parse_steelseries_headset(proto, raw)
                        if parsed is not None:
                            break
            except OSError:
                parsed = None
            finally:
                try:
                    dev.close()
                except Exception:
                    pass

            online, pct, charging = parsed if parsed else (False, None, False)
            out.append(
                DeviceBattery(
                    device_id=f"steelseries:{key}",
                    name=name,
                    brand="SteelSeries",
                    kind=kind,
                    connection_mode="2.4G",
                    vid=STEELSERIES_VID,
                    pid=pid,
                    connected=True,
                    online=online,
                    asleep=not online,
                    percent=pct,
                    charging=charging,
                    support_status=STATUS_PROTOCOL,
                    status_detail="" if online else "耳机离线或休眠",
                    provider_name=self.name,
                )
            )
        return out

    def poll(self, hid_snapshot: list[dict]) -> list[DeviceBattery]:
        return self._poll_mice(hid_snapshot) + self._poll_headsets(hid_snapshot)
