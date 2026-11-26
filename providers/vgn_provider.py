"""VGN / VXE / ATK / CompX / MCHOSE / LAMZU / Rapoo 无线鼠标适配器。

核心保护说明：
- VGN Dragonfly F2 Pro Max (0x3554:0xFB3E / 0xFB3D) 直接复用现有已实机验证的
  `vgn_battery.VgnBatteryReader`（17 字节会话协议 0x02 -> 0x03 -> 0x04 -> 0x02），
  绝不改动或破坏已验证的底层通信。
- 额外兼容同属 CompX/Nordic52 族的 VXE / ATK / LAMZU / Zaopin / Scyrox / Dareu，
  以及 MCHOSE (XOR 0xFF Feature Report 0x11) 与雷柏 Rapoo 无线鼠标。
"""

from __future__ import annotations

import time
from typing import Optional

import hid

from vgn_battery import VgnBatteryReader

from .base import (
    BatteryProvider,
    DeviceBattery,
    KIND_MOUSE,
    STATUS_PROTOCOL,
    STATUS_VERIFIED,
    get_hid_report_lengths,
)

# 已知其他 CompX 17 字节鼠标（非主 VGN F2 Pro Max，供扩展识别）
EXTRA_COMPX_MODELS: dict[tuple[int, int], tuple[str, str, bool]] = {
    # (vid, pid): (型号名, 品牌, 是否为有线 PID)
    (0x373B, 0x1031): ("ATK F1 Ultimate", "ATK", False),
    (0x373B, 0x102E): ("ATK F1 Ultimate", "ATK", True),
    (0x373B, 0x11D9): ("ATK A9 Ultimate", "ATK", False),
    (0x373B, 0x11B6): ("ATK A9 Ultimate", "ATK", True),
    (0x373B, 0x104D): ("VXE MAD R", "VXE", False),
    (0x373B, 0x103F): ("VXE MAD R", "VXE", True),
    (0x373B, 0x1040): ("VXE MAD R Major+", "VXE", False),
    (0x373B, 0x104C): ("VXE MAD R Major+", "VXE", True),
    (0x373B, 0x1085): ("VXE R1 SE+ (1K)", "VXE", False),
    (0x3554, 0xF524): ("Zaopin Z2 Mini", "Zaopin", False),
    (0x3554, 0xF526): ("Zaopin Z2 Mini", "Zaopin", True),
    (0x3554, 0xF5F7): ("Scyrox V8", "Scyrox", False),
    (0x3554, 0xF5F6): ("Scyrox V8", "Scyrox", True),
    (0x373E, 0x001E): ("LAMZU Maya / Thorn (4K)", "LAMZU", False),
    (0x373E, 0x001C): ("LAMZU Atlantis Mini 4K", "LAMZU", False),
    (0x373E, 0x0015): ("LAMZU Atlantis OG V2", "LAMZU", False),
}

# MCHOSE 迈从无线鼠标 (参考 MIT: JKWTCN/BatteryMonitor MchoseHidProvider.cpp)
MCHOSE_MODELS: dict[tuple[int, int], str] = {
    (0x3837, 0x4018): "MCHOSE A7 V2 Pro",
    (0x3837, 0x4023): "MCHOSE A7 V2 Pro+",
    (0x3837, 0x4019): "MCHOSE A7 V2 Ultra",
    (0x3837, 0x4021): "MCHOSE A7 V2 Ultra+",
    (0x3837, 0x100A): "MCHOSE A7 V2 (1K Dongle)",
    (0x3837, 0x100B): "MCHOSE A7 V2 (8K Dongle)",
    (0x5253, 0x1020): "MCHOSE L7 / A7 V2 (Dongle)",
}

MCHOSE_LOGICAL_NAMES: dict[int, str] = {
    0x4018: "MCHOSE A7 V2 Pro",
    0x4023: "MCHOSE A7 V2 Pro+",
    0x4019: "MCHOSE A7 V2 Ultra",
    0x4021: "MCHOSE A7 V2 Ultra+",
}

# 雷柏 Rapoo 2.4G 无线鼠标（VID 0x24AE，公开 32 字节命令协议）
RAPOO_MODELS: dict[int, str] = {
    0x412C: "Rapoo VT9 Pro / VT9 Air",
    0x412D: "Rapoo VT9 Pro (Wired)",
    0x4132: "Rapoo VT1 Pro Max / Air Max",
    0x4133: "Rapoo VT1 Pro Max (Wired)",
    0x4126: "Rapoo VT3 Pro Max",
}


def parse_mchose_feature_reply(raw: list[int] | bytes) -> Optional[tuple[int, int, int, bool]]:
    """解析 MCHOSE Feature Report 0x11 回包（XOR 0xFF 编码），返回 (vid, pid, percent, charging)。"""
    if not raw:
        return None
    offset = 1 if raw[0] == 0x11 else 0
    if len(raw) < offset + 12:
        return None
    decoded = [raw[offset + i] ^ 0xFF for i in range(12)]
    if decoded[0] != 0x06:
        return None
    logical_vid = decoded[1] | (decoded[2] << 8)
    logical_pid = decoded[3] | (decoded[4] << 8)
    pct = decoded[10]
    charging = decoded[11] != 0
    if logical_vid == 0 or logical_pid == 0 or not (0 <= pct <= 100):
        return None
    return logical_vid, logical_pid, pct, charging


class VgnCompxProvider(BatteryProvider):
    """主 VGN 适配（直通已验证的 VgnBatteryReader）+ 扩展 CompX / MCHOSE / Rapoo 鼠标。"""

    name = "vgn_compx"
    brand = "VGN"

    def __init__(self) -> None:
        self._vgn_reader = VgnBatteryReader()
        self._mchose_cache: dict[str, DeviceBattery] = {}
        self._last_query_stats: dict[str, object] = {}

    def get_last_query_stats(self) -> dict[str, object]:
        return dict(self._last_query_stats)

    def _poll_primary_vgn(self, hid_snapshot: list[dict], force: bool = False) -> Optional[DeviceBattery]:
        # 快速判断当前是否存在 CompX/VGN/ATK 的 FF02:0002 设备
        has_vgn = any(
            d.get("vendor_id") in (0x3554, 0x373B)
            and d.get("usage_page") == 0xFF02
            and d.get("usage") == 0x0002
            for d in hid_snapshot
        )
        if not has_vgn:
            self._last_query_stats = {}
            return None

        r = self._vgn_reader.read(hid_snapshot=hid_snapshot, force=force)
        self._last_query_stats = self._vgn_reader.get_last_query_stats()
        if not r.connected:
            return None

        # 确定匹配的 VID/PID 以准确标记验证状态
        matched_vid, matched_pid = 0x3554, 0xFB3E
        for d in hid_snapshot:
            if d.get("vendor_id") in (0x3554, 0x373B) and d.get("usage_page") == 0xFF02 and d.get("usage") == 0x0002:
                matched_vid = int(d.get("vendor_id", 0x3554))
                matched_pid = int(d.get("product_id", 0xFB3E))
                break

        brand = "VGN"
        if (matched_vid, matched_pid) in EXTRA_COMPX_MODELS:
            _, brand, _ = EXTRA_COMPX_MODELS[(matched_vid, matched_pid)]
        elif "VXE" in r.device_name.upper():
            brand = "VXE"
        elif "ATK" in r.device_name.upper():
            brand = "ATK"

        # 仅 3554:FB3E / 3554:FB3D 标记为已实机验证，其余诚实标记为协议已实现待实测
        support_status = (
            STATUS_VERIFIED
            if (matched_vid == 0x3554 and matched_pid in (0xFB3E, 0xFB3D))
            else STATUS_PROTOCOL
        )

        is_full = bool(r.charging and r.percent is not None and r.percent >= 100)
        return DeviceBattery(
            device_id=f"vgn:{matched_vid:04x}:{matched_pid:04x}",
            name=r.device_name.replace("DragonFly", "Dragonfly"),
            brand=brand,
            kind=KIND_MOUSE,
            connection_mode=r.connection_mode,
            vid=matched_vid,
            pid=matched_pid,
            connected=True,
            online=r.online,
            asleep=r.asleep,
            percent=r.percent,
            charging=r.charging and not is_full,
            full=is_full,
            voltage_mv=r.voltage_mv,
            support_status=support_status,
            status_detail="" if r.online else ("休眠中" if r.asleep else "未响应"),
            provider_name=self.name,
            timestamp=r.timestamp or time.time(),
        )

    def _poll_mchose(self, hid_snapshot: list[dict]) -> list[DeviceBattery]:
        results: list[DeviceBattery] = []
        seen_keys: set[tuple[int, int]] = set()
        for d in hid_snapshot:
            vid = d.get("vendor_id", 0)
            pid = d.get("product_id", 0)
            if (vid, pid) not in MCHOSE_MODELS:
                continue
            if d.get("interface_number") != 2 or d.get("usage_page") not in (0xFF01, 0xFF0B):
                continue
            if (vid, pid) in seen_keys:
                continue
            seen_keys.add((vid, pid))
            path = d.get("path")
            if not path:
                continue

            dev = hid.device()
            parsed = None
            try:
                dev.open_path(path)
                req = [0xFF] * 21
                req[0] = 0x11
                req[1] = 0x06 ^ 0xFF
                if dev.send_feature_report(req) >= 21:
                    time.sleep(0.012)
                    raw = dev.get_feature_report(0x11, 65)
                    parsed = parse_mchose_feature_reply(raw)
            except OSError:
                parsed = None
            finally:
                try:
                    dev.close()
                except Exception:
                    pass

            dev_id = f"mchose:{vid:04x}:{pid:04x}"
            if parsed is not None:
                lvid, lpid, pct, charging = parsed
                name = MCHOSE_LOGICAL_NAMES.get(lpid, MCHOSE_MODELS[(vid, pid)])
                is_full = charging and pct >= 100
                item = DeviceBattery(
                    device_id=f"mchose:{lvid:04x}:{lpid:04x}",
                    name=name,
                    brand="MCHOSE",
                    kind=KIND_MOUSE,
                    connection_mode="有线" if charging else "2.4G",
                    vid=vid,
                    pid=pid,
                    connected=True,
                    online=True,
                    percent=pct,
                    charging=charging and not is_full,
                    full=is_full,
                    support_status=STATUS_PROTOCOL,
                    provider_name=self.name,
                )
                self._mchose_cache[dev_id] = item
                results.append(item)
            elif dev_id in self._mchose_cache:
                prev = self._mchose_cache[dev_id]
                results.append(
                    DeviceBattery(
                        device_id=prev.device_id,
                        name=prev.name,
                        brand="MCHOSE",
                        kind=KIND_MOUSE,
                        connection_mode="休眠",
                        vid=vid,
                        pid=pid,
                        connected=True,
                        online=False,
                        asleep=True,
                        percent=prev.percent,
                        support_status=STATUS_PROTOCOL,
                        status_detail="休眠中",
                        provider_name=self.name,
                        timestamp=prev.timestamp,
                    )
                )
            else:
                results.append(
                    DeviceBattery(
                        device_id=dev_id,
                        name=MCHOSE_MODELS[(vid, pid)],
                        brand="MCHOSE",
                        kind=KIND_MOUSE,
                        connection_mode="2.4G",
                        vid=vid,
                        pid=pid,
                        connected=True,
                        online=False,
                        asleep=True,
                        percent=None,
                        support_status=STATUS_PROTOCOL,
                        status_detail="未响应",
                        provider_name=self.name,
                    )
                )
        return results

    def _poll_rapoo(self, hid_snapshot: list[dict]) -> list[DeviceBattery]:
        """检测已知雷柏 2.4G 鼠标；若无法确认私有回报长度则仅安全报告连接状态，绝不盲写。"""
        results: list[DeviceBattery] = []
        seen: set[int] = set()
        for d in hid_snapshot:
            if d.get("vendor_id") != 0x24AE:
                continue
            pid = d.get("product_id", 0)
            if pid not in RAPOO_MODELS or pid in seen:
                continue
            if d.get("usage_page", 0) < 0xFF00:
                continue
            in_len, out_len, _ = get_hid_report_lengths(d.get("path", b""))
            if out_len not in (32, 33, 64, 65) or in_len == 0:
                continue
            seen.add(pid)
            results.append(
                DeviceBattery(
                    device_id=f"rapoo:24ae:{pid:04x}",
                    name=RAPOO_MODELS[pid],
                    brand="Rapoo",
                    kind=KIND_MOUSE,
                    connection_mode="有线" if "Wired" in RAPOO_MODELS[pid] else "2.4G",
                    vid=0x24AE,
                    pid=pid,
                    connected=True,
                    online=False,
                    percent=None,
                    support_status=STATUS_PROTOCOL,
                    status_detail="待实机抓包确认电量帧",
                    provider_name=self.name,
                )
            )
        return results

    def poll(self, hid_snapshot: list[dict], force: bool = False) -> list[DeviceBattery]:
        out: list[DeviceBattery] = []
        primary = self._poll_primary_vgn(hid_snapshot, force=force)
        if primary is not None:
            out.append(primary)
        out.extend(self._poll_mchose(hid_snapshot))
        out.extend(self._poll_rapoo(hid_snapshot))
        return out
