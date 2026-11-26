"""Corsair 海盗船 SLIPSTREAM 无线鼠标/键盘与 Void / Virtuoso / HS80 无线耳机适配器。

协议参考（公开 Bragi 协议与 MIT 参考项目 qu1ncky/BatteryTray）：
- 鼠标/键盘（Bragi 属性只读协议，Interface 1, FF42:0001, 65 字节无 Report ID）：
  读属性请求 `00 TT 02 PP`（TT=0x08 接收器/有线本体，0x08+slot 为配对槽位 1..7）。
  属性：0x36 在线槽位掩码，0x0F 千分比电量 (0..1000)，0x10 充电状态 (1 充电/2 电池/3 充满)，0x12 产品 PID。
- 耳机：Void/HS70 (`C9 64`) 与 Virtuoso/HS80 MAX/Void v2（Bragi 端点 0x09）。
"""

from __future__ import annotations

from typing import Optional

import hid

from .base import (
    BatteryProvider,
    DeviceBattery,
    KIND_HEADSET,
    KIND_KEYBOARD,
    KIND_MOUSE,
    STATUS_PROTOCOL,
    get_hid_report_lengths,
    hid_drain,
    pad_report,
)

CORSAIR_VID = 0x1B1C
BRAGI_PAGE = 0xFF42
BRAGI_USAGE = 0x0001

CORSAIR_PERIPHERALS: dict[int, tuple[str, str]] = {
    0x1B7E: ("Corsair Dark Core RGB Pro SE", KIND_MOUSE),
    0x1B80: ("Corsair Dark Core RGB Pro", KIND_MOUSE),
    0x1B4C: ("Corsair Ironclaw RGB Wireless", KIND_MOUSE),
    0x1B5E: ("Corsair Harpoon RGB Wireless", KIND_MOUSE),
    0x1B98: ("Corsair Sabre RGB Pro Wireless", KIND_MOUSE),
    0x1BB5: ("Corsair M65 RGB Ultra Wireless", KIND_MOUSE),
    0x1BD6: ("Corsair M65 RGB Ultra Wireless", KIND_MOUSE),
    0x1BF1: ("Corsair M75 Wireless", KIND_MOUSE),
    0x1BF2: ("Corsair M75 Air", KIND_MOUSE),
    0x1BDB: ("Corsair Scimitar RGB Elite Wireless", KIND_MOUSE),
    0x1BB8: ("Corsair Nightsabre Wireless", KIND_MOUSE),
    0x1BB2: ("Corsair Darkstar Wireless", KIND_MOUSE),
    0x1BFB: ("Corsair M55 Wireless", KIND_MOUSE),
    0x1B6E: ("Corsair K57 RGB Wireless", KIND_KEYBOARD),
    0x1BAB: ("Corsair K100 Air Wireless", KIND_KEYBOARD),
    0x1BB6: ("Corsair K70 Pro Mini Wireless", KIND_KEYBOARD),
    0x2B10: ("Corsair K65 Plus Wireless", KIND_KEYBOARD),
}

SLIPSTREAM_RECEIVERS: dict[int, Optional[str]] = {
    0x1BA6: None,
    0x1BDC: None,
    0x2B00: None,
    0x1B7F: "Corsair Dark Core RGB Pro SE",
    0x1B81: "Corsair Dark Core RGB Pro",
    0x1B65: "Corsair Harpoon RGB Wireless",
    0x1B66: "Corsair Ironclaw RGB Wireless",
    0x1B62: "Corsair K57 RGB Wireless",
    0x1B94: "Corsair Katar Pro Wireless",
    0x2B07: "Corsair K65 Plus Wireless",
}

VOID_HEADSET_PIDS = {0x0A14, 0x0A16, 0x0A17, 0x0A1D, 0x0A1A, 0x0A55, 0x0A51, 0x0A52, 0x0A38, 0x0A4F, 0x0A2B, 0x0A75, 0x0A56}
BRAGI_HEADSET_PIDS = {0x2A08, 0x2A02, 0x0A97, 0x2A0F, 0x2A03, 0x2A0C, 0x2A12, 0x2A05}


def parse_bragi_property(reply: list[int] | bytes, expected_slot: int) -> Optional[int]:
    """解析 Bragi 属性读取回包 `[slot, 0x02, status, v0, v1, v2, v3]`，返回 little-endian 32 位值。"""
    r = list(reply)
    if len(r) >= 8 and r[0] == 0x00:
        r = r[1:]
    if len(r) < 7:
        return None
    if (r[0] & 0x07) != (expected_slot & 0x07):
        return None
    if r[1] != 0x02 or r[2] != 0x00:
        return None
    return r[3] | (r[4] << 8) | (r[5] << 16) | (r[6] << 24)


def parse_corsair_void_reply(reply: list[int] | bytes) -> Optional[tuple[bool, Optional[int], bool]]:
    """解析 Corsair Void / HS70 耳机 `C9 64` 回包。"""
    r = list(reply)
    if len(r) > 4 and r[0] == 0x64:
        if r[4] == 0:
            return (False, None, False)
        return (True, min(100, r[2] & 0x7F), r[4] in (4, 5))
    return None


class CorsairHidProvider(BatteryProvider):
    name = "corsair_hid"
    brand = "Corsair"

    def _read_bragi_prop(self, dev: hid.device, target: int, prop_id: int, report_len: int = 65) -> Optional[int]:
        req = pad_report(report_len, [0x00, target, 0x02, prop_id])
        try:
            dev.write(req)
            for _ in range(4):
                raw = dev.read(report_len, 220)
                if not raw:
                    break
                val = parse_bragi_property(raw, target & 0x07)
                if val is not None:
                    return val
        except OSError:
            return None
        return None

    def _poll_bragi_peripherals(self, hid_snapshot: list[dict]) -> list[DeviceBattery]:
        out: list[DeviceBattery] = []
        seen_paths: set[bytes] = set()
        for d in hid_snapshot:
            if d.get("vendor_id") != CORSAIR_VID:
                continue
            pid = d.get("product_id", 0)
            if pid not in SLIPSTREAM_RECEIVERS and pid not in CORSAIR_PERIPHERALS:
                continue
            if d.get("usage_page") != BRAGI_PAGE or d.get("usage") != BRAGI_USAGE:
                continue
            path = d.get("path")
            if not path or path in seen_paths:
                continue
            in_len, out_len, _ = get_hid_report_lengths(path)
            if out_len < 64 or in_len < 64:
                continue
            seen_paths.add(path)

            dev = hid.device()
            try:
                dev.open_path(path)
                hid_drain(dev, in_len, 4, 10)
                if pid in SLIPSTREAM_RECEIVERS:
                    linked = self._read_bragi_prop(dev, 0x08, 0x36, out_len) or 0
                    for slot in range(1, 8):
                        if not (linked & (1 << slot)):
                            continue
                        target = 0x08 + slot
                        tenths = self._read_bragi_prop(dev, target, 0x0F, out_len)
                        if tenths is None or not (0 <= tenths <= 1000):
                            continue
                        pwr = self._read_bragi_prop(dev, target, 0x10, out_len) or 2
                        child_pid = self._read_bragi_prop(dev, target, 0x12, out_len) or 0
                        name, kind = CORSAIR_PERIPHERALS.get(
                            child_pid,
                            (SLIPSTREAM_RECEIVERS[pid] or f"Corsair Wireless ({child_pid:04X})", KIND_MOUSE),
                        )
                        out.append(
                            DeviceBattery(
                                device_id=f"corsair:{child_pid or pid:04x}:{slot}",
                                name=name,
                                brand="Corsair",
                                kind=kind,
                                connection_mode="2.4G",
                                vid=CORSAIR_VID,
                                pid=child_pid or pid,
                                connected=True,
                                online=True,
                                percent=min(100, tenths // 10),
                                charging=pwr == 1,
                                full=pwr == 3,
                                support_status=STATUS_PROTOCOL,
                                provider_name=self.name,
                            )
                        )
                else:
                    name, kind = CORSAIR_PERIPHERALS[pid]
                    tenths = self._read_bragi_prop(dev, 0x08, 0x0F, out_len)
                    if tenths is not None and 0 <= tenths <= 1000:
                        pwr = self._read_bragi_prop(dev, 0x08, 0x10, out_len) or 1
                        out.append(
                            DeviceBattery(
                                device_id=f"corsair:{pid:04x}",
                                name=name,
                                brand="Corsair",
                                kind=kind,
                                connection_mode="有线",
                                vid=CORSAIR_VID,
                                pid=pid,
                                connected=True,
                                online=True,
                                percent=min(100, tenths // 10),
                                charging=pwr == 1,
                                full=pwr == 3,
                                support_status=STATUS_PROTOCOL,
                                provider_name=self.name,
                            )
                        )
            except OSError:
                pass
            finally:
                try:
                    dev.close()
                except Exception:
                    pass
        return out

    def _poll_headsets(self, hid_snapshot: list[dict]) -> list[DeviceBattery]:
        out: list[DeviceBattery] = []
        seen: set[int] = set()
        for d in hid_snapshot:
            if d.get("vendor_id") != CORSAIR_VID:
                continue
            pid = d.get("product_id", 0)
            if pid in seen:
                continue
            path = d.get("path")
            if not path:
                continue

            if pid in VOID_HEADSET_PIDS and d.get("usage_page") == 0xFFC5 and d.get("usage") == 0x0001:
                seen.add(pid)
                dev = hid.device()
                parsed = None
                try:
                    dev.open_path(path)
                    hid_drain(dev, 64, 4, 10)
                    dev.write([0xC9, 0x64])
                    for _ in range(4):
                        raw = dev.read(64, 250)
                        if not raw:
                            break
                        parsed = parse_corsair_void_reply(raw)
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
                        device_id=f"corsair:void:{pid:04x}",
                        name="Corsair Void / HS70 Wireless",
                        brand="Corsair",
                        kind=KIND_HEADSET,
                        connection_mode="2.4G",
                        vid=CORSAIR_VID,
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
        return self._poll_bragi_peripherals(hid_snapshot) + self._poll_headsets(hid_snapshot)
