"""VGN / CompX 鼠标 HID 电量读取模块（无需官方驱动，内置重试、休眠防抖与热插拔容错）。"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional

import hid

VENDOR_COMPX = 0x3554
VENDOR_ATK = 0x373B

USAGE_PAGE = 0xFF02
USAGE = 0x0002
REPORT_LEN = 17
REPORT_ID = 0x08
CHECKSUM_TARGET = 0x55

# 已知 VGN / VXE 型号与连接模式映射: (vid, pid) -> (型号名, 连接模式)
KNOWN_DEVICES: dict[tuple[int, int], tuple[str, str]] = {
    (0x3554, 0xFB3E): ("VGN DragonFly F2 Pro Max", "2.4G"),
    (0x3554, 0xFB3D): ("VGN DragonFly F2 Pro Max", "有线"),
    (0x3554, 0xFB56): ("VGN DragonFly F2 Master+", "2.4G"),
    (0x3554, 0xF503): ("VGN F1 Pro", "2.4G"),
    (0x3554, 0xF502): ("VGN F1 Pro", "有线"),
    (0x3554, 0xF505): ("VGN Dragonfly 4K", "2.4G"),
    (0x3554, 0xF506): ("VGN F1 MOBA", "有线"),
    (0x3554, 0xF58A): ("VXE R1 Pro Max", "2.4G"),
    (0x3554, 0xF58C): ("VXE R1 Pro Max", "有线"),
    (0x3554, 0xF58E): ("VXE R1 SE+", "2.4G"),
    (0x3554, 0xF58F): ("VXE R1 SE+", "有线"),
}

WIRED_PIDS = {0xFB3D, 0xF502, 0xF506, 0xF58C, 0xF58F}


@dataclass
class BatteryReading:
    connected: bool
    online: bool = False
    asleep: bool = False
    percent: Optional[int] = None
    charging: bool = False
    voltage_mv: Optional[int] = None
    device_name: str = "VGN 鼠标"
    connection_mode: str = "未连接"
    timestamp: float = 0.0


def _make_frame(cmd: int, b5: int = 0, b6: int = 0) -> list[int]:
    frame = [REPORT_ID, cmd, 0x00, 0x00, 0x00, b5, b6] + [0x00] * 9
    frame.append((CHECKSUM_TARGET - sum(frame)) % 256)
    return frame


def _is_valid_battery_reply(data: list[int]) -> bool:
    if len(data) != REPORT_LEN:
        return False
    if data[0] != REPORT_ID or data[1] != 0x04:
        return False
    if sum(data) % 256 != CHECKSUM_TARGET:
        return False
    return 0 <= data[6] <= 100


class VgnBatteryReader:
    """线程安全的 VGN 鼠标 HID 电量读取器，内置自动重试、休眠防抖与退避降频。"""

    SLEEP_MISS_THRESHOLD = 3  # 连续 3 次无应答才判定为休眠，避免偶发丢包闪烁
    SLEEP_BACKOFF_STEPS_SEC = (45.0, 90.0, 180.0)  # 休眠/持续无应答退避间隔，避免频繁唤醒休眠设备

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_valid: Optional[BatteryReading] = None
        self._consecutive_misses = 0
        self._last_query_mono: float = 0.0
        self._last_query_stats: dict[str, object] = {
            "ok": False,
            "duration_ms": 0.0,
            "timeouts": 0,
            "retries": 0,
            "io_error": False,
            "skipped_backoff": False,
            "consecutive_misses": 0,
        }

    def get_last_query_stats(self) -> dict[str, object]:
        with self._lock:
            return dict(self._last_query_stats)

    def _select_candidate(self, devices: list[dict]) -> Optional[tuple[dict, str, str]]:
        """从候选 HID 设备列表中优先挑选已知 VGN/CompX 设备（有线直连优先于 2.4G 接收器）。"""
        candidates: list[tuple[int, dict, str, str]] = []
        for d in devices:
            vid = d.get("vendor_id", 0)
            if vid not in (VENDOR_COMPX, VENDOR_ATK):
                continue
            if d.get("usage_page") != USAGE_PAGE or d.get("usage") != USAGE:
                continue
            pid = d.get("product_id", 0)
            if (vid, pid) in KNOWN_DEVICES:
                name, mode = KNOWN_DEVICES[(vid, pid)]
                # 优先有线直连(0)，其次 F2 Pro Max 2.4G(1)，其次其他已知型号(2)
                if pid == 0xFB3D:
                    priority = 0
                elif pid == 0xFB3E:
                    priority = 1
                else:
                    priority = 2
                candidates.append((priority, d, name, mode))
            else:
                prod = (d.get("product_string") or "").strip() or f"VGN/CompX ({vid:04X}:{pid:04X})"
                mode = "有线" if pid in WIRED_PIDS else "2.4G"
                candidates.append((3, d, prod, mode))

        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        _, dev_info, name, mode = candidates[0]
        return dev_info, name, mode

    def _find_target(self, hid_snapshot: Optional[list[dict]] = None) -> Optional[tuple[dict, str, str]]:
        """优先复用共享 HID 快照查找已知 VGN 设备，避免重复触发 USB 总线枚举。"""
        if hid_snapshot is not None:
            return self._select_candidate(hid_snapshot)

        all_devices: list[dict] = []
        for vid in (VENDOR_COMPX, VENDOR_ATK):
            try:
                all_devices.extend(hid.enumerate(vid, 0))
            except OSError:
                continue
        return self._select_candidate(all_devices)

    def _current_backoff_sec(self) -> float:
        if self._consecutive_misses < self.SLEEP_MISS_THRESHOLD:
            return 0.0
        step = min(
            len(self.SLEEP_BACKOFF_STEPS_SEC) - 1,
            self._consecutive_misses - self.SLEEP_MISS_THRESHOLD,
        )
        return self.SLEEP_BACKOFF_STEPS_SEC[step]

    def _drain_nonblocking(self, dev: hid.device) -> None:
        """非阻塞快速排空残留输入报告（避免阻塞读取浪费 15–25ms）。"""
        try:
            dev.set_nonblocking(1)
            try:
                for _ in range(8):
                    if not dev.read(REPORT_LEN):
                        break
            finally:
                dev.set_nonblocking(0)
        except Exception:
            for _ in range(4):
                try:
                    if not dev.read(REPORT_LEN, 10):
                        break
                except OSError:
                    break

    def _query_once(
        self,
        path: bytes,
        max_attempts: int = 2,
    ) -> tuple[Optional[list[int]], dict[str, object]]:
        """执行一次完整的 HID 会话查询（严格保留已验证的 0x02 -> 0x03 -> 0x04 -> 0x02 协议序列）。"""
        t0 = time.perf_counter()
        stats: dict[str, object] = {
            "ok": False,
            "duration_ms": 0.0,
            "timeouts": 0,
            "retries": 0,
            "io_error": False,
            "skipped_backoff": False,
        }
        dev = hid.device()
        session_opened = False
        try:
            dev.open_path(path)
            self._drain_nonblocking(dev)

            # 1. 开启 PCDriverStatus 会话
            dev.write(_make_frame(0x02, b5=0x01, b6=0x01))
            if not dev.read(REPORT_LEN, 200):
                stats["timeouts"] = int(stats["timeouts"]) + 1
            session_opened = True

            # 2. 激活在线查询 (0x03, b5=1)
            dev.write(_make_frame(0x03, b5=0x01, b6=0x00))
            if not dev.read(REPORT_LEN, 200):
                stats["timeouts"] = int(stats["timeouts"]) + 1
            time.sleep(0.05)

            # 3. 查询电量 (0x04)，正常在线时最多 2 轮防高回报率偶发丢包，已确认休眠时仅 1 轮降低总线占用
            attempts = max(1, int(max_attempts))
            for attempt in range(attempts):
                if attempt > 0:
                    stats["retries"] = int(stats["retries"]) + 1
                dev.write(_make_frame(0x04, b5=0x00, b6=0x00))
                got_any = False
                for _ in range(4):
                    raw = dev.read(REPORT_LEN, 250)
                    if not raw:
                        stats["timeouts"] = int(stats["timeouts"]) + 1
                        break
                    got_any = True
                    if _is_valid_battery_reply(raw):
                        stats["ok"] = True
                        return list(raw), stats
                    time.sleep(0.02)
                if attempt + 1 < attempts:
                    time.sleep(0.08 if got_any else 0.05)
            return None, stats
        except OSError:
            stats["io_error"] = True
            return None, stats
        finally:
            if session_opened:
                try:
                    dev.write(_make_frame(0x02, b5=0x01, b6=0x00))
                    dev.read(REPORT_LEN, 150)
                except OSError:
                    pass
            try:
                dev.close()
            except Exception:
                pass
            stats["duration_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)

    def read(self, hid_snapshot: Optional[list[dict]] = None, force: bool = False) -> BatteryReading:
        with self._lock:
            found = self._find_target(hid_snapshot)
            if found is None:
                self._consecutive_misses = 0
                self._last_query_stats = {
                    "ok": False,
                    "duration_ms": 0.0,
                    "timeouts": 0,
                    "retries": 0,
                    "io_error": False,
                    "skipped_backoff": False,
                    "consecutive_misses": 0,
                }
                return BatteryReading(
                    connected=False,
                    online=False,
                    asleep=False,
                    percent=None,
                    charging=False,
                    voltage_mv=None,
                    device_name="未检测到 VGN 鼠标",
                    connection_mode="未连接",
                    timestamp=time.time(),
                )

            dev_info, name, mode = found
            path = dev_info["path"]
            is_wired_pid = dev_info.get("product_id") in WIRED_PIDS

            # 若设备已确认处于休眠状态且非手动/唤醒强制查询，按退避间隔跳过本次 HID 访问，避免反复唤醒休眠鼠标
            now_mono = time.monotonic()
            backoff_sec = self._current_backoff_sec()
            if (
                not force
                and not is_wired_pid
                and backoff_sec > 0.0
                and self._last_query_mono > 0.0
                and (now_mono - self._last_query_mono) < backoff_sec
            ):
                self._last_query_stats = {
                    "ok": False,
                    "duration_ms": 0.0,
                    "timeouts": 0,
                    "retries": 0,
                    "io_error": False,
                    "skipped_backoff": True,
                    "consecutive_misses": self._consecutive_misses,
                }
                if self._last_valid is not None:
                    return BatteryReading(
                        connected=True,
                        online=False,
                        asleep=True,
                        percent=self._last_valid.percent,
                        charging=False,
                        voltage_mv=self._last_valid.voltage_mv,
                        device_name=name,
                        connection_mode="休眠",
                        timestamp=self._last_valid.timestamp,
                    )
                return BatteryReading(
                    connected=True,
                    online=False,
                    asleep=True,
                    percent=None,
                    charging=False,
                    voltage_mv=None,
                    device_name=name,
                    connection_mode="休眠",
                    timestamp=time.time(),
                )

            already_asleep = self._consecutive_misses >= self.SLEEP_MISS_THRESHOLD
            max_attempts = 1 if (already_asleep and not force) else 2
            reply, qstats = self._query_once(path, max_attempts=max_attempts)
            self._last_query_mono = time.monotonic()

            if reply is not None:
                self._consecutive_misses = 0
                qstats["consecutive_misses"] = 0
                self._last_query_stats = qstats
                percent = reply[6]
                charging_flag = bool(reply[7])
                voltage = (reply[8] << 8) | reply[9]
                charging = charging_flag or is_wired_pid
                reading = BatteryReading(
                    connected=True,
                    online=True,
                    asleep=False,
                    percent=percent,
                    charging=charging,
                    voltage_mv=voltage if 2500 <= voltage <= 5000 else None,
                    device_name=name,
                    connection_mode="有线" if charging else mode,
                    timestamp=time.time(),
                )
                self._last_valid = reading
                return reading

            # 本次未收到回包：防抖计数
            self._consecutive_misses += 1
            qstats["consecutive_misses"] = self._consecutive_misses
            self._last_query_stats = qstats
            is_asleep = self._consecutive_misses >= self.SLEEP_MISS_THRESHOLD

            if self._last_valid is not None:
                return BatteryReading(
                    connected=True,
                    online=not is_asleep,
                    asleep=is_asleep,
                    percent=self._last_valid.percent,
                    charging=False,
                    voltage_mv=self._last_valid.voltage_mv,
                    device_name=name,
                    connection_mode="休眠" if is_asleep else self._last_valid.connection_mode,
                    timestamp=self._last_valid.timestamp,
                )

            return BatteryReading(
                connected=True,
                online=False,
                asleep=True,
                percent=None,
                charging=False,
                voltage_mv=None,
                device_name=name,
                connection_mode="休眠",
                timestamp=time.time(),
            )
