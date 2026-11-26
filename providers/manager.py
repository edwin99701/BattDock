"""统一多设备管理层：聚合所有品牌适配器、单次 HID 快照共享、热插拔管理与脱敏诊断导出。"""

from __future__ import annotations

import platform
import time
from datetime import datetime
from typing import Optional

import hid

from .base import (
    BatteryProvider,
    DeviceBattery,
    STATUS_PROTOCOL,
    STATUS_UNSUPPORTED,
    STATUS_VERIFIED,
)
from .bluetooth_provider import BluetoothBatteryProvider
from .corsair_hid import CorsairHidProvider
from .extra_brands import ExtraBrandsProvider
from .hyperx_hid import HyperXHidProvider
from .logitech_hidpp import LogitechHidppProvider
from .razer_hid import RazerHidProvider
from .steelseries_hid import SteelSeriesHidProvider
from .vgn_provider import VgnCompxProvider


def _device_score(dev: DeviceBattery) -> tuple[int, int, int, int]:
    """同 device_id 去重时的优先级评分（在线 > 有电量 > 充电中 > 已验证）。"""
    return (
        1 if dev.online else 0,
        1 if dev.percent is not None else 0,
        1 if dev.charging else 0,
        1 if dev.support_status == STATUS_VERIFIED else 0,
    )


def sanitize_device_reading(dev: DeviceBattery) -> DeviceBattery:
    """强制数据一致性不变量：离线或未知设备绝不允许伪造 0% 电量。"""
    if not dev.connected or (not dev.online and not dev.asleep):
        if dev.percent == 0:
            dev.percent = None
    if dev.percent is not None:
        dev.percent = max(0, min(100, int(dev.percent)))
        if dev.charging and dev.percent >= 100:
            dev.full = True
    return dev


class DeviceManager:
    """统一多品牌无线外设电量管理层。"""

    def __init__(self, providers: Optional[list[BatteryProvider]] = None) -> None:
        self.providers: list[BatteryProvider] = providers if providers is not None else [
            VgnCompxProvider(),
            LogitechHidppProvider(),
            RazerHidProvider(),
            SteelSeriesHidProvider(),
            CorsairHidProvider(),
            HyperXHidProvider(),
            ExtraBrandsProvider(),
            BluetoothBatteryProvider(),
        ]
        self._last_devices: list[DeviceBattery] = []
        self._provider_errors: dict[str, str] = {}
        self._last_hid_count: int = 0
        self._last_poll_ts: float = 0.0

    def poll(self, hid_snapshot: Optional[list[dict]] = None) -> list[DeviceBattery]:
        """执行一轮多品牌轮询，返回去重并按优先级排序的统一设备列表。"""
        if hid_snapshot is None:
            try:
                hid_snapshot = list(hid.enumerate(0, 0))
            except Exception:
                hid_snapshot = []

        self._last_hid_count = len(hid_snapshot)
        self._last_poll_ts = time.time()
        raw_devices: list[DeviceBattery] = []
        self._provider_errors.clear()

        for provider in self.providers:
            try:
                found = provider.poll(hid_snapshot)
                if found:
                    raw_devices.extend(found)
            except Exception as exc:
                self._provider_errors[provider.name] = f"{type(exc).__name__}: {exc}"

        # 按 device_id 智能去重（如同时检测到有线与接收器，保留在线/充电的读数）
        dedup: dict[str, DeviceBattery] = {}
        for dev in raw_devices:
            dev = sanitize_device_reading(dev)
            prev = dedup.get(dev.device_id)
            if prev is None or _device_score(dev) > _device_score(prev):
                dedup[dev.device_id] = dev

        # 排序：已真机验证优先 -> 在线优先 -> 名称稳定排序
        ordered = sorted(
            dedup.values(),
            key=lambda d: (
                0 if d.support_status == STATUS_VERIFIED else 1,
                0 if d.online else (1 if d.asleep else 2),
                d.brand.lower(),
                d.name.lower(),
            ),
        )
        self._last_devices = ordered
        return ordered

    def get_last_devices(self) -> list[DeviceBattery]:
        return list(self._last_devices)

    def stop(self) -> None:
        for provider in self.providers:
            try:
                provider.stop()
            except Exception:
                pass

    def export_diagnostics(self, hid_snapshot: Optional[list[dict]] = None) -> dict:
        """生成脱敏设备诊断报告字典（不包含敏感用户路径或序列号原文）。"""
        if hid_snapshot is None:
            try:
                hid_snapshot = list(hid.enumerate(0, 0))
            except Exception:
                hid_snapshot = []

        # 按 (vid, pid, product_string) 汇总 HID 设备，脱敏路径和序列号
        hid_summary_map: dict[tuple[int, int, str], dict] = {}
        for item in hid_snapshot:
            vid = int(item.get("vendor_id", 0))
            pid = int(item.get("product_id", 0))
            prod = str(item.get("product_string") or "").strip()
            key = (vid, pid, prod)
            entry = hid_summary_map.setdefault(
                key,
                {
                    "vid": f"0x{vid:04X}",
                    "pid": f"0x{pid:04X}",
                    "manufacturer": str(item.get("manufacturer_string") or "").strip(),
                    "product": prod,
                    "collections": [],
                },
            )
            col = {
                "interface": int(item.get("interface_number", -1)),
                "usage_page": f"0x{int(item.get('usage_page', 0)):04X}",
                "usage": f"0x{int(item.get('usage', 0)):04X}",
            }
            if col not in entry["collections"]:
                entry["collections"].append(col)

        devices = self.poll(hid_snapshot)
        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "app_version": "2.0.0",
            "system": {
                "os": platform.platform(),
                "python": platform.python_version(),
            },
            "providers": [
                {
                    "name": p.name,
                    "brand": p.brand,
                    "error": self._provider_errors.get(p.name, ""),
                }
                for p in self.providers
            ],
            "detected_devices": [d.to_dict() for d in devices],
            "hid_summary_count": len(hid_summary_map),
            "hid_devices": list(hid_summary_map.values()),
            "verification_legend": {
                STATUS_VERIFIED: "已在本机真实硬件验证",
                STATUS_PROTOCOL: "协议已实现并通过单元测试，待实机验证",
                STATUS_UNSUPPORTED: "暂不支持读取真实电量",
            },
        }
