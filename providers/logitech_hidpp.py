"""Logitech 罗技 HID++ 2.0 / 1.0 无线鼠标、键盘与 Logitech G 无线耳机适配器。

协议参考（公开规范与 MIT 参考项目 qu1ncky/BatteryTray、JKWTCN/BatteryMonitor）：
- 仅执行只读查询，绝不修改设备寄存器或配置；自动跳过摄像头 PID (0x0800..0x09FF)。
- 支持 Unifying / Bolt / Lightspeed 接收器（槽位 1..6）与有线直连（设备索引 0xFF / 0x00）。
- 支持 HID++ 2.0 特性：0x1004 UnifiedBattery、0x1000 BatteryStatus、0x1001 BatteryVoltage、0x1F20 ADC，
  以及 0x0005 DeviceName 读取真实设备型号与类型；支持 HID++ 1.0 寄存器 0x0D / 0x07。
- 支持 Logitech G 无线耳机（G533 / G535 / G733 / G935 / G PRO X Wireless）。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Optional

import hid

from .base import (
    BatteryProvider,
    DeviceBattery,
    KIND_HEADSET,
    KIND_KEYBOARD,
    KIND_MOUSE,
    KIND_OTHER,
    STATUS_PROTOCOL,
    get_hid_report_lengths,
    hid_drain,
    interpolate_voltage,
    pad_report,
)

LOGITECH_VID = 0x046D
SW_ID = 0x0C  # 与 Solaar(0x0B)/G HUB(0x0D) 区分
FEATURE_DEVICE_NAME = 0x0005
BATTERY_FEATURES = (0x1004, 0x1000, 0x1001, 0x1F20)

# 锂电池电压 -> 百分比标准映射曲线（降序）
LI_ION_CURVE: list[tuple[int, int]] = [
    (4186, 100), (4067, 90), (3989, 80), (3922, 70), (3859, 60),
    (3811, 50), (3778, 40), (3751, 30), (3717, 20), (3671, 10),
    (3646, 5), (3500, 0),
]

G533_CURVE: list[tuple[int, int]] = [(4200, 100), (3850, 50), (3790, 30), (3750, 20), (3680, 5), (3330, 0)]
G535_CURVE: list[tuple[int, int]] = [(4175, 100), (3817, 50), (3766, 30), (3730, 20), (3664, 5), (3310, 0)]
G633_CURVE: list[tuple[int, int]] = [(4100, 100), (3950, 80), (3850, 60), (3750, 40), (3650, 20), (3500, 10), (3300, 5), (3150, 0)]
GPRO_CURVE: list[tuple[int, int]] = [(4150, 100), (3830, 50), (3780, 30), (3740, 20), (3670, 5), (3320, 0)]

# Logitech G 耳机固定特征索引表: pid -> (name, usage_page, usage, feat_idx, cmd_byte, curve)
LOGITECH_HEADSETS: dict[int, tuple[str, int, int, int, int, list[tuple[int, int]]]] = {
    0x0A66: ("Logitech G533", 0xFF43, 0x0202, 0x07, 0x01, G533_CURVE),
    0x0AC4: ("Logitech G535", 0x000C, 0x0001, 0x05, 0x0D, G535_CURVE),
    0x0A5C: ("Logitech G633", 0xFF43, 0x0202, 0x08, 0x0A, G633_CURVE),
    0x0A89: ("Logitech G635", 0xFF43, 0x0202, 0x08, 0x0A, G633_CURVE),
    0x0A5B: ("Logitech G933", 0xFF43, 0x0202, 0x08, 0x0A, G633_CURVE),
    0x0A87: ("Logitech G935", 0xFF43, 0x0202, 0x08, 0x0A, G633_CURVE),
    0x0AB5: ("Logitech G733", 0xFF43, 0x0202, 0x08, 0x0A, G633_CURVE),
    0x0AFE: ("Logitech G733", 0xFF43, 0x0202, 0x08, 0x0A, G633_CURVE),
    0x0B1F: ("Logitech G733", 0xFF43, 0x0202, 0x08, 0x0A, G633_CURVE),
    0x0AA7: ("Logitech G Pro Wireless Headset", 0xFF43, 0x0202, 0x06, 0x0D, GPRO_CURVE),
    0x0AAA: ("Logitech G Pro X Wireless", 0xFF43, 0x0202, 0x06, 0x0D, GPRO_CURVE),
    0x0ABA: ("Logitech G Pro X Wireless", 0xFF43, 0x0202, 0x06, 0x0D, GPRO_CURVE),
    0x0AFB: ("Logitech G Pro X 2 Lightspeed", 0xFF43, 0x0202, 0x06, 0x0D, GPRO_CURVE),
    0x0AFC: ("Logitech G Pro X 2 Lightspeed", 0xFF43, 0x0202, 0x06, 0x0D, GPRO_CURVE),
}


def parse_hidpp_battery(feature_id: int, params: list[int] | bytes) -> Optional[tuple[bool, Optional[int], bool, bool, Optional[int]]]:
    """解析 HID++ 2.0 电池特性回包参数，返回 (online, percent, charging, full, voltage_mv)。"""
    if len(params) < 3:
        return None
    if feature_id == 0x1004:  # UnifiedBattery GetStatus
        soc, level_bits, status = params[0], params[1], params[2]
        if soc != 0:
            pct: Optional[int] = min(100, soc)
        else:
            pct = {8: 90, 4: 50, 2: 20, 1: 5}.get(level_bits)
        full = status == 3
        charging = status in (1, 2, 4)
        if full and pct is None:
            pct = 100
        return (True, pct, charging, full, None)

    if feature_id == 0x1000:  # BatteryStatus GetBatteryLevelStatus
        level, _next, status = params[0], params[1], params[2]
        full = status == 3
        charging = status in (1, 2, 4)
        pct = min(100, level) if level != 0 else (100 if full else None)
        return (True, pct, charging, full, None)

    if feature_id == 0x1001:  # BatteryVoltage GetBatteryInfo
        mv = (params[0] << 8) | params[1]
        flags = params[2]
        powered = bool(flags & 0x80)
        full = powered and bool(flags & 0x01)
        pct = interpolate_voltage(mv, LI_ION_CURVE) if mv > 2000 else None
        return (True, pct, powered and not full, full, mv if mv > 2000 else None)

    if feature_id == 0x1F20:  # ADC measurement (headsets)
        mv = (params[0] << 8) | params[1]
        flags = params[2]
        active = bool(flags & 0x01)
        if not active:
            return (False, None, False, False, None)
        charging = bool(flags & 0x02)
        pct = interpolate_voltage(mv, LI_ION_CURVE) if mv > 2000 else None
        return (True, pct, charging, False, mv if mv > 2000 else None)

    return None


def parse_logitech_headset_voltage(reply: list[int] | bytes, curve: list[tuple[int, int]]) -> Optional[tuple[bool, Optional[int], bool, Optional[int]]]:
    """解析 Logitech G 无线耳机 20 字节 HID++ 电压回包: [11, FF, idx, cmd, mv_hi, mv_lo, state, ...]。"""
    if len(reply) < 7 or reply[0] != 0x11:
        return None
    mv = (reply[4] << 8) | reply[5]
    state = reply[6]
    if state == 0x00 or mv < 2500:
        return (False, None, False, None)
    charging = state == 0x03
    pct = interpolate_voltage(mv, curve)
    return (True, pct, charging, mv)


def _channel_key(path: bytes) -> str:
    s = path.decode("utf-8", "ignore").lower()
    s = re.sub(r"&col[0-9a-f]{2}", "", s)
    s = re.sub(r"&[0-9a-f]{4}(?=#\{)", "", s)
    return s


@dataclass
class _SlotCache:
    name: str
    kind: str
    hidpp20: bool
    feature_index: int = 0
    feature_id: int = 0
    last_percent: Optional[int] = None
    last_voltage: Optional[int] = None


class _HidppLink:
    def __init__(self, short_path: Optional[bytes], long_path: Optional[bytes]) -> None:
        self.short_dev: Optional[hid.device] = None
        self.long_dev: Optional[hid.device] = None
        if short_path:
            d = hid.device()
            d.open_path(short_path)
            hid_drain(d, 7, 4, 5)
            self.short_dev = d
        if long_path:
            d = hid.device()
            d.open_path(long_path)
            hid_drain(d, 20, 4, 5)
            self.long_dev = d

    def close(self) -> None:
        for d in (self.short_dev, self.long_dev):
            if d is not None:
                try:
                    d.close()
                except Exception:
                    pass

    def _read_reply(self, dev_idx: int, timeout_ms: int = 400) -> Optional[list[int]]:
        deadline = time.monotonic() + timeout_ms / 1000.0
        readers = [x for x in ((self.long_dev, 20), (self.short_dev, 7)) if x[0] is not None]
        while time.monotonic() < deadline:
            for d, rlen in readers:
                try:
                    r = d.read(rlen, 25)
                except OSError:
                    continue
                if not r or len(r) < 5:
                    continue
                if r[0] not in (0x10, 0x11) or r[1] != dev_idx:
                    continue
                return list(r)
        return None

    def ping(self, dev_idx: int) -> str:
        """返回 'hidpp20' / 'hidpp10' / 'offline' / 'empty'。"""
        mark = 0xAA
        if self.short_dev is not None:
            pkt = [0x10, dev_idx, 0x00, 0x10 | SW_ID, 0x00, 0x00, mark]
            try:
                self.short_dev.write(pkt)
            except OSError:
                return "empty"
        elif self.long_dev is not None:
            pkt = pad_report(20, [0x11, dev_idx, 0x00, 0x10 | SW_ID, 0x00, 0x00, mark])
            try:
                self.long_dev.write(pkt)
            except OSError:
                return "empty"
        else:
            return "empty"

        r = self._read_reply(dev_idx, 350)
        if not r:
            return "empty"
        if r[2] == 0x8F:  # HID++ 1.0 error
            err = r[5] if len(r) > 5 else 0
            if err == 0x01:
                return "hidpp10"
            if err in (0x04, 0x09):
                return "offline"
            return "empty"
        if r[2] == 0x00 and (r[3] & 0x0F) == SW_ID and len(r) >= 7 and r[6] == mark:
            return "hidpp20"
        return "empty"

    def call_20(self, dev_idx: int, feat_idx: int, func_id: int, params: list[int] | None = None) -> Optional[list[int]]:
        if self.long_dev is None:
            return None
        pkt = pad_report(20, [0x11, dev_idx, feat_idx, ((func_id & 0x0F) << 4) | SW_ID] + (params or []))
        try:
            self.long_dev.write(pkt)
        except OSError:
            return None
        deadline = time.monotonic() + 0.45
        while time.monotonic() < deadline:
            r = self._read_reply(dev_idx, 200)
            if not r:
                break
            if r[0] == 0x11 and r[2] == feat_idx and (r[3] & 0x0F) == SW_ID:
                return r[4:]
            if r[2] == 0xFF and len(r) >= 6:  # HID++ 2.0 error
                return None
        return None

    def get_feature(self, dev_idx: int, feature_id: int) -> Optional[int]:
        res = self.call_20(dev_idx, 0x00, 0x00, [(feature_id >> 8) & 0xFF, feature_id & 0xFF])
        return res[0] if res else None


class LogitechHidppProvider(BatteryProvider):
    name = "logitech_hidpp"
    brand = "Logitech"

    def __init__(self) -> None:
        self._slots: dict[str, _SlotCache] = {}

    def _describe_slot(self, link: _HidppLink, dev_idx: int, pid: int) -> Optional[_SlotCache]:
        slot = _SlotCache(
            name=f"Logitech {pid:04X}" + (f" #{dev_idx}" if 1 <= dev_idx <= 6 else ""),
            kind=KIND_MOUSE,
            hidpp20=True,
        )
        name_idx = link.get_feature(dev_idx, FEATURE_DEVICE_NAME)
        if name_idx:
            len_res = link.call_20(dev_idx, name_idx, 0)
            if len_res and len_res[0] > 0:
                total = min(64, len_res[0])
                raw_name = bytearray()
                while len(raw_name) < total:
                    chunk = link.call_20(dev_idx, name_idx, 1, [len(raw_name)])
                    if not chunk:
                        break
                    take = min(16, total - len(raw_name))
                    raw_name.extend(chunk[:take])
                text = raw_name.decode("utf-8", "ignore").rstrip("\x00").strip()
                if text:
                    slot.name = text if text.lower().startswith("logitech") else f"Logitech {text}"
            kind_res = link.call_20(dev_idx, name_idx, 2)
            if kind_res:
                k = kind_res[0]
                if k in (0, 2):
                    slot.kind = KIND_KEYBOARD
                elif k in (3, 4, 5):
                    slot.kind = KIND_MOUSE
                elif k == 8:
                    slot.kind = KIND_HEADSET
                else:
                    slot.kind = KIND_OTHER

        for feat_id in BATTERY_FEATURES:
            fidx = link.get_feature(dev_idx, feat_id)
            if fidx:
                slot.feature_id = feat_id
                slot.feature_index = fidx
                break
        return slot

    def _poll_headsets(self, hid_snapshot: list[dict]) -> list[DeviceBattery]:
        out: list[DeviceBattery] = []
        seen_pids: set[int] = set()
        for d in hid_snapshot:
            if d.get("vendor_id") != LOGITECH_VID:
                continue
            pid = d.get("product_id", 0)
            if pid not in LOGITECH_HEADSETS or pid in seen_pids:
                continue
            name, up, u, fidx, cmd, curve = LOGITECH_HEADSETS[pid]
            if d.get("usage_page") != up or d.get("usage") != u:
                continue
            path = d.get("path")
            if not path:
                continue
            seen_pids.add(pid)

            dev = hid.device()
            parsed = None
            try:
                dev.open_path(path)
                hid_drain(dev, 20, 4, 10)
                pkt = pad_report(20, [0x11, 0xFF, fidx, cmd])
                dev.write(pkt)
                for _ in range(4):
                    raw = dev.read(20, 250)
                    if not raw:
                        break
                    if len(raw) >= 7 and raw[0] == 0x11 and raw[2] == fidx:
                        parsed = parse_logitech_headset_voltage(raw, curve)
                        break
            except OSError:
                parsed = None
            finally:
                try:
                    dev.close()
                except Exception:
                    pass

            if parsed is not None:
                online, pct, charging, mv = parsed
                out.append(
                    DeviceBattery(
                        device_id=f"logitech:headset:{pid:04x}",
                        name=name,
                        brand="Logitech",
                        kind=KIND_HEADSET,
                        connection_mode="2.4G",
                        vid=LOGITECH_VID,
                        pid=pid,
                        connected=True,
                        online=online,
                        asleep=not online,
                        percent=pct,
                        charging=charging,
                        voltage_mv=mv,
                        support_status=STATUS_PROTOCOL,
                        status_detail="" if online else "耳机离线或休眠",
                        provider_name=self.name,
                    )
                )
        return out

    def poll(self, hid_snapshot: list[dict]) -> list[DeviceBattery]:
        results = self._poll_headsets(hid_snapshot)

        # 按 USB 接口分组处理 HID++ 接收器与有线设备（排除摄像头 0x0800..0x09FF 与已处理的耳机）
        channels: dict[str, list[dict]] = {}
        for d in hid_snapshot:
            if d.get("vendor_id") != LOGITECH_VID:
                continue
            pid = d.get("product_id", 0)
            if 0x0800 <= pid <= 0x09FF or pid in LOGITECH_HEADSETS:
                continue
            path = d.get("path")
            if not path:
                continue
            # 跳过 BLE HID（由 Windows Bluetooth 统一读取）
            if b"{00001812-" in path.lower():
                continue
            channels.setdefault(_channel_key(path), []).append(d)

        for ch_key, colls in channels.items():
            short_path: Optional[bytes] = None
            long_path: Optional[bytes] = None
            pid = colls[0].get("product_id", 0)
            for c in colls:
                if c.get("usage_page", 0) < 0xFF00:
                    continue
                _, out_len, _ = get_hid_report_lengths(c["path"])
                if out_len == 7 and short_path is None:
                    short_path = c["path"]
                elif out_len == 20 and long_path is None:
                    long_path = c["path"]
            if not short_path and not long_path:
                continue

            is_receiver = 0xC500 <= pid <= 0xC5FF
            conn_mode = "2.4G" if is_receiver else "有线"
            indices = (1, 2, 3, 4, 5, 6) if is_receiver else (0xFF,)

            link: Optional[_HidppLink] = None
            try:
                link = _HidppLink(short_path, long_path)
                for dev_idx in indices:
                    slot_key = f"{ch_key}#{dev_idx}"
                    ping_res = link.ping(dev_idx)
                    if ping_res == "empty":
                        continue
                    if ping_res == "offline":
                        cached = self._slots.get(slot_key)
                        if cached and cached.feature_index:
                            results.append(
                                DeviceBattery(
                                    device_id=f"logitech:{pid:04x}:{dev_idx}",
                                    name=cached.name,
                                    brand="Logitech",
                                    kind=cached.kind,
                                    connection_mode="休眠",
                                    vid=LOGITECH_VID,
                                    pid=pid,
                                    connected=True,
                                    online=False,
                                    asleep=True,
                                    percent=cached.last_percent,
                                    voltage_mv=cached.last_voltage,
                                    support_status=STATUS_PROTOCOL,
                                    status_detail="休眠中",
                                    provider_name=self.name,
                                )
                            )
                        continue
                    if ping_res != "hidpp20":
                        continue

                    slot = self._slots.get(slot_key)
                    if slot is None:
                        slot = self._describe_slot(link, dev_idx, pid)
                        if slot:
                            self._slots[slot_key] = slot
                    if not slot or not slot.feature_index:
                        continue

                    func_id = 1 if slot.feature_id == 0x1004 else 0
                    params = link.call_20(dev_idx, slot.feature_index, func_id)
                    parsed = parse_hidpp_battery(slot.feature_id, params) if params else None
                    if parsed is None:
                        continue
                    online, pct, charging, full, mv = parsed
                    if pct is not None:
                        slot.last_percent = pct
                    if mv is not None:
                        slot.last_voltage = mv
                    results.append(
                        DeviceBattery(
                            device_id=f"logitech:{pid:04x}:{dev_idx}",
                            name=slot.name,
                            brand="Logitech",
                            kind=slot.kind,
                            connection_mode="有线" if (not is_receiver or charging) else conn_mode,
                            vid=LOGITECH_VID,
                            pid=pid,
                            connected=True,
                            online=online,
                            asleep=not online,
                            percent=pct if online else slot.last_percent,
                            charging=charging,
                            full=full,
                            voltage_mv=mv,
                            support_status=STATUS_PROTOCOL,
                            status_detail="" if online else "休眠中",
                            provider_name=self.name,
                        )
                    )
            except OSError:
                pass
            finally:
                if link is not None:
                    link.close()
        return results
