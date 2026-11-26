"""统一多设备管理层：聚合所有品牌适配器、单次 HID 快照共享、热插拔管理与脱敏诊断导出。"""

from __future__ import annotations

from collections import deque
import json
import os
from pathlib import Path
import platform
import threading
import time
from datetime import datetime
from typing import Any, Optional

import hid

from brand import APP_VERSION

from .base import (
    BatteryProvider,
    DeviceBattery,
    STATUS_PROTOCOL,
    STATUS_UNSUPPORTED,
    STATUS_VERIFIED,
    clear_hid_caps_cache,
)
from .bluetooth_provider import BluetoothBatteryProvider
from .corsair_hid import CorsairHidProvider
from .device_naming import normalize_device_display_name
from .extra_brands import ExtraBrandsProvider
from .hyperx_hid import HyperXHidProvider
from .logitech_hidpp import LogitechHidppProvider
from .razer_hid import RazerHidProvider
from .standard_hid import StandardHidBatteryProvider
from .steelseries_hid import SteelSeriesHidProvider
from .vgn_provider import VgnCompxProvider
from .wireless_headsets import WirelessHeadsetsProvider
from .wireless_keyboards import WirelessKeyboardsProvider


def _device_score(dev: DeviceBattery) -> tuple[int, int, int, int]:
    """同 device_id 去重时的优先级评分（在线 > 有电量 > 充电中 > 已验证）。"""
    return (
        1 if dev.online else 0,
        1 if dev.percent is not None else 0,
        1 if dev.charging else 0,
        1 if dev.support_status == STATUS_VERIFIED else 0,
    )


def sanitize_device_reading(dev: DeviceBattery) -> DeviceBattery:
    """强制数据一致性与标准显示名称规范：保留原始硬件名，离线/未知绝不伪造 0%。"""
    if not dev.raw_name:
        dev.raw_name = dev.name
    dev.name = normalize_device_display_name(
        dev.raw_name,
        vid=dev.vid,
        pid=dev.pid,
        brand=dev.brand,
    )
    if not dev.connected or (not dev.online and not dev.asleep):
        if dev.percent == 0:
            dev.percent = None
    if dev.percent is not None:
        dev.percent = max(0, min(100, int(dev.percent)))
        if dev.charging and dev.percent >= 100:
            dev.full = True
    return dev


class DeviceManager:
    """统一多品牌无线外设电量管理层（串行防并发、事件驱动 HID 缓存与轻量诊断记录）。"""

    # 仅在硬件热插拔、手动刷新、IO 异常恢复或兜底长周期时执行全量 hid.enumerate(0, 0)
    RESCAN_INTERVAL_WITH_DEVICES_SEC = 300.0
    RESCAN_INTERVAL_EMPTY_SEC = 60.0
    DEBUG_LOG_MAX_BYTES = 512 * 1024

    def __init__(
        self,
        providers: Optional[list[BatteryProvider]] = None,
        debug_log_path: Optional[Path] = None,
    ) -> None:
        self.providers: list[BatteryProvider] = providers if providers is not None else [
            VgnCompxProvider(),
            LogitechHidppProvider(),
            RazerHidProvider(),
            SteelSeriesHidProvider(),
            CorsairHidProvider(),
            HyperXHidProvider(),
            ExtraBrandsProvider(),
            WirelessHeadsetsProvider(),
            WirelessKeyboardsProvider(),
            StandardHidBatteryProvider(),
            BluetoothBatteryProvider(),
        ]
        self._poll_lock = threading.RLock()
        self._last_devices: list[DeviceBattery] = []
        self._provider_errors: dict[str, str] = {}
        self._last_hid_count: int = 0
        self._last_poll_ts: float = 0.0

        # 事件驱动 HID 拓扑缓存（消除每 25s 无故全总线 USB 描述符扫描）
        self._cached_hid_snapshot: Optional[list[dict]] = None
        self._last_hid_scan_mono: float = 0.0
        self._hid_dirty: bool = True
        self._hid_dirty_reason: str = "startup"

        # 轻量内存诊断环形缓冲（默认零持续磁盘写入；仅显式开启调试模式时才写本地日志）
        self._poll_history: deque[dict[str, Any]] = deque(maxlen=60)
        self._total_polls: int = 0
        self._total_full_scans: int = 0
        self._total_timeouts: int = 0
        self._total_retries: int = 0
        # 记录已由专用适配器接管（含在线与休眠占位）的 (vid, pid)，供 standard_hid 兜底精确跳过防重复卡片
        self._dedicated_claimed_vps: set[tuple[int, int]] = set()
        self._debug_logging: bool = os.environ.get("BATTDOCK_DEBUG_LOG", "").strip().lower() in ("1", "true", "yes")
        self._debug_log_path: Optional[Path] = debug_log_path

    def set_debug_logging(self, enabled: bool, log_path: Optional[Path] = None) -> None:
        with self._poll_lock:
            self._debug_logging = bool(enabled) or (
                os.environ.get("BATTDOCK_DEBUG_LOG", "").strip().lower() in ("1", "true", "yes")
            )
            if log_path is not None:
                self._debug_log_path = log_path

    def mark_hid_dirty(self, reason: str = "device_change") -> None:
        """标记 HID 拓扑已变化（由 Windows WM_DEVICECHANGE 或 IO 异常恢复触发），并通知适配器重置旧句柄。"""
        with self._poll_lock:
            self._hid_dirty = True
            self._hid_dirty_reason = str(reason or "device_change")
            clear_hid_caps_cache()
            for provider in self.providers:
                try:
                    provider.on_device_change()
                except Exception:
                    pass

    def notify_power_event(self, event: str = "resume") -> None:
        """系统进入休眠或从休眠唤醒时通知全部适配器释放常驻句柄并刷新拓扑缓存。"""
        with self._poll_lock:
            self._hid_dirty = True
            self._hid_dirty_reason = f"power_{event}"
            clear_hid_caps_cache()
            for provider in self.providers:
                try:
                    provider.on_power_resume()
                except Exception:
                    pass

    def _should_rescan_hid(self, now_mono: float, force_rescan: bool, reason: str) -> tuple[bool, str]:
        if self._cached_hid_snapshot is None:
            return True, "startup"
        if force_rescan:
            return True, reason or "manual_refresh"
        if self._hid_dirty:
            return True, self._hid_dirty_reason or "device_change"
        limit = (
            self.RESCAN_INTERVAL_WITH_DEVICES_SEC
            if self._last_devices
            else self.RESCAN_INTERVAL_EMPTY_SEC
        )
        if (now_mono - self._last_hid_scan_mono) >= limit:
            return True, "periodic_rescan"
        return False, "cached"

    def _append_debug_log(self, entry: dict[str, Any]) -> None:
        if not self._debug_logging or self._debug_log_path is None:
            return
        try:
            self._debug_log_path.parent.mkdir(parents=True, exist_ok=True)
            if self._debug_log_path.exists() and self._debug_log_path.stat().st_size > self.DEBUG_LOG_MAX_BYTES:
                # 防止调试日志长期无限增长造成磁盘 I/O 压力
                tail = self._debug_log_path.read_text(encoding="utf-8", errors="ignore").splitlines()[-120:]
                self._debug_log_path.write_text("\n".join(tail) + "\n", encoding="utf-8")
            with self._debug_log_path.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _invoke_provider(
        self,
        provider: BatteryProvider,
        hid_snapshot: list[dict],
        force_query: bool,
        *,
        exclude_vps: Optional[set[tuple[int, int]]] = None,
    ) -> list[DeviceBattery]:
        kwargs: dict[str, Any] = {}
        if force_query:
            kwargs["force"] = True
        if exclude_vps is not None and provider.name == "standard_hid":
            kwargs["exclude_vps"] = exclude_vps
        if kwargs:
            try:
                return provider.poll(hid_snapshot, **kwargs)  # type: ignore[call-arg]
            except TypeError:
                if "exclude_vps" in kwargs:
                    try:
                        return provider.poll(hid_snapshot, exclude_vps=exclude_vps)  # type: ignore[call-arg]
                    except TypeError:
                        pass
                if force_query:
                    try:
                        return provider.poll(hid_snapshot, force=True)  # type: ignore[call-arg]
                    except TypeError:
                        pass
                return provider.poll(hid_snapshot)
        return provider.poll(hid_snapshot)

    def poll(
        self,
        hid_snapshot: Optional[list[dict]] = None,
        *,
        reason: str = "scheduled",
        force_rescan: bool = False,
        force_query: bool = False,
        active_monitor_tasks: int = 0,
    ) -> list[DeviceBattery]:
        """串行执行一轮多品牌轮询，复用事件驱动 HID 缓存并返回排序去重后的设备列表。"""
        with self._poll_lock:
            start_iso = datetime.now().isoformat(timespec="milliseconds")
            t0 = time.perf_counter()
            now_mono = time.monotonic()

            hid_scanned = False
            scan_reason = "external_snapshot"
            hid_enum_ms = 0.0

            if hid_snapshot is None:
                need_scan, scan_reason = self._should_rescan_hid(now_mono, force_rescan, reason)
                if need_scan:
                    te0 = time.perf_counter()
                    try:
                        hid_snapshot = list(hid.enumerate(0, 0))
                    except Exception:
                        hid_snapshot = []
                    hid_enum_ms = round((time.perf_counter() - te0) * 1000.0, 2)
                    self._cached_hid_snapshot = hid_snapshot
                    self._last_hid_scan_mono = time.monotonic()
                    self._hid_dirty = False
                    self._hid_dirty_reason = ""
                    hid_scanned = True
                    self._total_full_scans += 1
                else:
                    hid_snapshot = list(self._cached_hid_snapshot or [])

            self._last_hid_count = len(hid_snapshot)
            self._last_poll_ts = time.time()
            raw_devices: list[DeviceBattery] = []
            self._provider_errors.clear()

            # 清理已拔出设备的历史专用认领记录，保留当前在场硬件
            present_vps: set[tuple[int, int]] = {
                (int(item.get("vendor_id", 0)), int(item.get("product_id", 0)))
                for item in hid_snapshot
                if int(item.get("vendor_id", 0)) and int(item.get("product_id", 0))
            }
            self._dedicated_claimed_vps &= present_vps

            round_timeouts = 0
            round_retries = 0
            round_io_error = False
            round_skipped_backoff = False

            # 先执行所有专用适配器（及蓝牙），再将全部已接管（含在线与休眠占位）的 (vid, pid) 传给 standard_hid 防重复卡片
            dedicated_providers = [p for p in self.providers if p.name != "standard_hid"]
            fallback_providers = [p for p in self.providers if p.name == "standard_hid"]

            for provider in dedicated_providers:
                try:
                    found = self._invoke_provider(provider, hid_snapshot, force_query)
                    if found:
                        raw_devices.extend(found)
                        for dev in found:
                            if dev.vid and dev.pid:
                                self._dedicated_claimed_vps.add((int(dev.vid), int(dev.pid)))
                    get_stats = getattr(provider, "get_last_query_stats", None)
                    if callable(get_stats):
                        pstats = get_stats() or {}
                        round_timeouts += int(pstats.get("timeouts", 0) or 0)
                        round_retries += int(pstats.get("retries", 0) or 0)
                        if pstats.get("io_error"):
                            round_io_error = True
                        if pstats.get("skipped_backoff"):
                            round_skipped_backoff = True
                except Exception as exc:
                    self._provider_errors[provider.name] = f"{type(exc).__name__}: {exc}"
                    if isinstance(exc, OSError):
                        round_io_error = True

            claimed_snapshot = set(self._dedicated_claimed_vps)
            for provider in fallback_providers:
                try:
                    found = self._invoke_provider(
                        provider,
                        hid_snapshot,
                        force_query,
                        exclude_vps=claimed_snapshot,
                    )
                    if found:
                        raw_devices.extend(found)
                except Exception as exc:
                    self._provider_errors[provider.name] = f"{type(exc).__name__}: {exc}"
                    if isinstance(exc, OSError):
                        round_io_error = True

            if round_io_error:
                self._hid_dirty = True
                self._hid_dirty_reason = "io_error_recovery"

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

            duration_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            end_iso = datetime.now().isoformat(timespec="milliseconds")
            self._total_polls += 1
            self._total_timeouts += round_timeouts
            self._total_retries += round_retries

            record: dict[str, Any] = {
                "start_time": start_iso,
                "end_time": end_iso,
                "duration_ms": duration_ms,
                "reason": reason,
                "hid_scanned": hid_scanned,
                "scan_reason": scan_reason,
                "hid_enum_ms": hid_enum_ms,
                "ok": len(self._provider_errors) == 0 and not round_io_error,
                "timeouts": round_timeouts,
                "retries": round_retries,
                "skipped_backoff": round_skipped_backoff,
                "device_count": len(ordered),
                "active_monitor_tasks": int(active_monitor_tasks),
            }
            if self._provider_errors:
                record["provider_errors"] = dict(self._provider_errors)
            self._poll_history.append(record)
            self._append_debug_log(record)

            return ordered

    def get_last_devices(self) -> list[DeviceBattery]:
        with self._poll_lock:
            return list(self._last_devices)

    def get_poll_diagnostics(self) -> dict[str, Any]:
        """返回轻量级本地轮询与 HID 通信诊断汇总。"""
        with self._poll_lock:
            records = list(self._poll_history)
            durations = [float(r["duration_ms"]) for r in records]
            return {
                "total_polls": self._total_polls,
                "total_full_hid_scans": self._total_full_scans,
                "total_timeouts": self._total_timeouts,
                "total_retries": self._total_retries,
                "debug_logging_enabled": self._debug_logging,
                "avg_poll_ms": round(sum(durations) / len(durations), 2) if durations else 0.0,
                "max_poll_ms": round(max(durations), 2) if durations else 0.0,
                "recent_polls": records[-20:],
            }

    def stop(self) -> None:
        for provider in self.providers:
            try:
                provider.stop()
            except Exception:
                pass

    def export_diagnostics(
        self,
        hid_snapshot: Optional[list[dict]] = None,
        active_monitor_tasks: int = 0,
    ) -> dict:
        """生成脱敏设备诊断报告字典（不包含敏感用户路径或序列号原文）。"""
        with self._poll_lock:
            if hid_snapshot is None:
                try:
                    hid_snapshot = list(hid.enumerate(0, 0))
                except Exception:
                    hid_snapshot = []
                self._cached_hid_snapshot = hid_snapshot
                self._last_hid_scan_mono = time.monotonic()
                self._hid_dirty = False
                self._hid_dirty_reason = ""

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

            devices = self.poll(
                hid_snapshot,
                reason="diagnostics",
                force_query=True,
                active_monitor_tasks=active_monitor_tasks,
            )
            return {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "app_version": APP_VERSION,
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
                "poll_diagnostics": self.get_poll_diagnostics(),
                "hid_summary_count": len(hid_summary_map),
                "hid_devices": list(hid_summary_map.values()),
                "verification_legend": {
                    STATUS_VERIFIED: "已在本机真实硬件验证",
                    STATUS_PROTOCOL: "协议已实现并通过单元测试，待实机验证",
                    STATUS_UNSUPPORTED: "暂不支持读取真实电量",
                },
            }
