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
    """线程安全的 VGN 鼠标 HID 电量读取器，内置自动重试与休眠防抖。"""

    SLEEP_MISS_THRESHOLD = 3  # 连续 3 次无应答才判定为休眠，避免偶发丢包闪烁

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_valid: Optional[BatteryReading] = None
        self._consecutive_misses = 0

    def _find_target(self) -> Optional[tuple[dict, str, str]]:
        """优先查找已知 VGN 设备（有线直连优先于 2.4G 接收器）。"""
        candidates: list[tuple[int, dict, str, str]] = []
        for vid in (VENDOR_COMPX, VENDOR_ATK):
            try:
                devices = hid.enumerate(vid, 0)
            except OSError:
                continue
            for d in devices:
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

    def _query_once(self, path: bytes) -> Optional[list[int]]:
        """执行一次完整的 HID 会话查询（内置 2 次 0x04 重试防止高回报率偶发丢包）。"""
        dev = hid.device()
        session_opened = False
        try:
            dev.open_path(path)
            for _ in range(4):
                if not dev.read(REPORT_LEN, 15):
                    break

            # 1. 开启 PCDriverStatus 会话
            dev.write(_make_frame(0x02, b5=0x01, b6=0x01))
            dev.read(REPORT_LEN, 200)
            session_opened = True

            # 2. 激活在线查询 (0x03, b5=1)
            dev.write(_make_frame(0x03, b5=0x01, b6=0x00))
            dev.read(REPORT_LEN, 200)
            time.sleep(0.05)

            # 3. 查询电量 (0x04)，最多尝试 2 轮
            for _attempt in range(2):
                dev.write(_make_frame(0x04, b5=0x00, b6=0x00))
                for _ in range(4):
                    raw = dev.read(REPORT_LEN, 250)
                    if not raw:
                        break
                    if _is_valid_battery_reply(raw):
                        return list(raw)
                    time.sleep(0.02)
                time.sleep(0.08)
            return None
        except OSError:
            return None
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

    def read(self) -> BatteryReading:
        with self._lock:
            found = self._find_target()
            if found is None:
                self._consecutive_misses = 0
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

            reply = self._query_once(path)
            if reply is not None:
                self._consecutive_misses = 0
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
