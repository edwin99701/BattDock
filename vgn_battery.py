"""VGN / CompX 鼠标 HID 电量读取模块（无需官方驱动，内置重试、17B 严格隔离、休眠退避与异常跳变复核）。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import threading
import time
from typing import Any, Optional

import hid

VENDOR_COMPX = 0x3554
VENDOR_ATK = 0x373B

USAGE_PAGE = 0xFF02
USAGE = 0x0002
REPORT_LEN = 17
REPORT_ID = 0x08
CHECKSUM_TARGET = 0x55

# 已知 20B CompX 键盘 PID（同属 VID 0x3554 + FF02:0002，必须严格排除，防止跨设备串线）
COMPX_KEYBOARD_PIDS: set[tuple[int, int]] = {
    (0x3554, 0xFA09),
    (0x3554, 0xFB40),
}

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

# 同款鼠标有线/无线 PID 归并组（插线充电切换接口时保持同一逻辑设备并优先读有线口）
LOGICAL_PAIR_MAP: dict[tuple[int, int], str] = {
    (0x3554, 0xFB3E): "pair:vgn-f2-pro-max",
    (0x3554, 0xFB3D): "pair:vgn-f2-pro-max",
    (0x3554, 0xF503): "pair:vgn-f1-pro",
    (0x3554, 0xF502): "pair:vgn-f1-pro",
    (0x3554, 0xF58A): "pair:vxe-r1-pro-max",
    (0x3554, 0xF58C): "pair:vxe-r1-pro-max",
    (0x3554, 0xF58E): "pair:vxe-r1-se-plus",
    (0x3554, 0xF58F): "pair:vxe-r1-se-plus",
    (0x373B, 0x1031): "pair:atk-f1-ultimate",
    (0x373B, 0x102E): "pair:atk-f1-ultimate",
    (0x373B, 0x11D9): "pair:atk-a9-ultimate",
    (0x373B, 0x11B6): "pair:atk-a9-ultimate",
    (0x373B, 0x104D): "pair:vxe-mad-r",
    (0x373B, 0x103F): "pair:vxe-mad-r",
    (0x373B, 0x1040): "pair:vxe-mad-r-major-plus",
    (0x373B, 0x104C): "pair:vxe-mad-r-major-plus",
    (0x3554, 0xF524): "pair:zaopin-z2-mini",
    (0x3554, 0xF526): "pair:zaopin-z2-mini",
    (0x3554, 0xF5F7): "pair:scyrox-v8",
    (0x3554, 0xF5F6): "pair:scyrox-v8",
}

WIRED_PIDS = {0xFB3D, 0xF502, 0xF506, 0xF58C, 0xF58F, 0x102E, 0x11B6, 0x103F, 0x104C, 0xF526, 0xF5F6}


def _safe_report_lengths(path: bytes) -> tuple[int, int, int]:
    """只读查询 HID 报告长度（在无 Win32 描述符的测试环境下返回 (0, 0, 0)）。"""
    try:
        from providers.base import get_hid_report_lengths

        return get_hid_report_lengths(path)
    except Exception:
        return (0, 0, 0)


def _path_tag(path: object) -> str:
    raw = path if isinstance(path, (bytes, bytearray)) else str(path or "").encode("utf-8", "ignore")
    return hashlib.sha256(raw).hexdigest()[:8]


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
    vid: Optional[int] = None
    pid: Optional[int] = None
    interface_number: int = -1
    report_length: int = REPORT_LEN
    last_success_ts: Optional[float] = None
    from_cache: bool = False
    stale: bool = False
    status_detail: str = ""
    diagnostic: Optional[dict[str, Any]] = None
    instance_key: str = ""


@dataclass
class _VgnDeviceState:
    last_valid: Optional[BatteryReading] = None
    consecutive_misses: int = 0
    last_query_mono: float = 0.0
    last_vid: Optional[int] = None
    last_pid: Optional[int] = None


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
    if not (0 <= data[6] <= 100):
        return False
    # 拦截未同步/离线全零假 0%（非充电且电压为 0 时 0% 视为无效帧）
    voltage = (data[8] << 8) | data[9]
    if data[6] == 0 and data[7] == 0 and voltage == 0:
        return False
    return True


def _is_vgn_mouse_collection(d: dict) -> bool:
    """严格筛选 17B VGN/CompX 鼠标集合，排除 20B CompX 键盘与其他非 17B 设备。"""
    vid = int(d.get("vendor_id", 0) or 0)
    pid = int(d.get("product_id", 0) or 0)
    if vid not in (VENDOR_COMPX, VENDOR_ATK):
        return False
    if (vid, pid) in COMPX_KEYBOARD_PIDS:
        return False
    if d.get("usage_page") != USAGE_PAGE or d.get("usage") != USAGE:
        return False
    prod_low = str(d.get("product_string") or "").strip().lower()
    if (vid, pid) not in KNOWN_DEVICES and any(kw in prod_low for kw in ("keyboard", "键盘")):
        return False
    path = d.get("path")
    if path:
        in_len, out_len, _ = _safe_report_lengths(path)
        # 当系统返回了真实描述符长度时，严格要求 17 字节（隔离 20B CompX 键盘）
        if (in_len > 0 or out_len > 0) and (in_len != REPORT_LEN or out_len != REPORT_LEN):
            return False
    return True


class VgnBatteryReader:
    """线程安全的 VGN 鼠标 HID 电量读取器：多设备隔离、17B 严格校验、休眠退避与异常跳变复核。"""

    SLEEP_MISS_THRESHOLD = 3  # 连续 3 次无应答才判定为休眠，前 2 次如实标记读取失败（绝不伪装在线）
    SLEEP_BACKOFF_STEPS_SEC = (45.0, 90.0, 180.0)  # 休眠/持续无应答退避间隔，避免频繁唤醒休眠设备
    ANOMALY_JUMP_DELTA = 15  # 单次电量变化 >= 15 个百分点触发有效性复核读取
    ANOMALY_NON_CHARGING_UP_DELTA = 10  # 非充电态单次突然上升 >= 10 个百分点触发复核
    ANOMALY_CONFIRM_TOLERANCE = 5  # 复核读数与候选值差值 <= 5% 视为硬件稳定确认（兼容固件 5% 步进）

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._device_states: dict[str, _VgnDeviceState] = {}
        self._last_valid: Optional[BatteryReading] = None  # 兼容属性：镜像主设备最近有效读数
        self._consecutive_misses = 0  # 兼容属性：镜像主设备连续失联次数
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

    def reset_backoff_for_reconnect(self) -> None:
        """热插拔或休眠唤醒时立即解除休眠退避，确保插线充电/重连可即时读取真实硬件。"""
        with self._lock:
            for st in self._device_states.values():
                st.last_query_mono = 0.0
            self._last_query_mono = 0.0

    def clear_cache(self) -> None:
        """彻底清理所有内部电量缓存与失联计数。"""
        with self._lock:
            self._device_states.clear()
            self._last_valid = None
            self._consecutive_misses = 0
            self._last_query_mono = 0.0

    def _collect_logical_candidates(self, devices: list[dict]) -> list[tuple[str, dict, str, str]]:
        """按逻辑设备分组并隔离多只 CompX 鼠标；同款鼠标有线与 2.4G 共存时优先有线直连。"""
        grouped: dict[str, list[tuple[int, dict, str, str]]] = {}
        seen_paths: set[bytes] = set()
        vp_counts: dict[tuple[int, int], int] = {}

        filtered: list[dict] = []
        for d in devices:
            if not _is_vgn_mouse_collection(d):
                continue
            path = d.get("path")
            if isinstance(path, (bytes, bytearray)):
                if path in seen_paths:
                    continue
                seen_paths.add(bytes(path))
            filtered.append(d)
            vp = (int(d.get("vendor_id", 0)), int(d.get("product_id", 0)))
            vp_counts[vp] = vp_counts.get(vp, 0) + 1

        for d in filtered:
            vid = int(d.get("vendor_id", 0))
            pid = int(d.get("product_id", 0))
            vp = (vid, pid)
            if vp in KNOWN_DEVICES:
                name, mode = KNOWN_DEVICES[vp]
                if pid == 0xFB3D:
                    priority = 0
                elif pid == 0xFB3E:
                    priority = 1
                elif pid in WIRED_PIDS:
                    priority = 1
                else:
                    priority = 2
            else:
                prod = (d.get("product_string") or "").strip() or f"VGN/CompX ({vid:04X}:{pid:04X})"
                name = prod
                mode = "有线" if pid in WIRED_PIDS else "2.4G"
                priority = 2 if pid in WIRED_PIDS else 3

            # 若同 (vid, pid) 接了多只同型号接收器/鼠标，按物理路径哈希拆分为独立逻辑设备防串线
            if vp_counts.get(vp, 0) > 1 and d.get("path"):
                logical_key = f"inst:{vid:04x}:{pid:04x}:{_path_tag(d.get('path'))}"
            elif vp in LOGICAL_PAIR_MAP:
                logical_key = LOGICAL_PAIR_MAP[vp]
            else:
                logical_key = f"vp:{vid:04x}:{pid:04x}"

            grouped.setdefault(logical_key, []).append((priority, d, name, mode))

        selected: list[tuple[int, str, dict, str, str]] = []
        for lkey, items in grouped.items():
            items.sort(key=lambda it: it[0])
            prio, dev_info, name, mode = items[0]
            selected.append((prio, lkey, dev_info, name, mode))

        selected.sort(key=lambda it: (it[0], it[1]))
        return [(lkey, dev_info, name, mode) for _, lkey, dev_info, name, mode in selected]

    def _select_candidate(self, devices: list[dict]) -> Optional[tuple[dict, str, str]]:
        """兼容方法：返回优先级最高的一只 VGN/CompX 鼠标。"""
        items = self._collect_logical_candidates(devices)
        if not items:
            return None
        _lkey, dev_info, name, mode = items[0]
        return dev_info, name, mode

    def _enumerate_if_needed(self, hid_snapshot: Optional[list[dict]] = None) -> list[dict]:
        if hid_snapshot is not None:
            return hid_snapshot
        all_devices: list[dict] = []
        for vid in (VENDOR_COMPX, VENDOR_ATK):
            try:
                all_devices.extend(hid.enumerate(vid, 0))
            except OSError:
                continue
        return all_devices

    def _find_target(self, hid_snapshot: Optional[list[dict]] = None) -> Optional[tuple[dict, str, str]]:
        """优先复用共享 HID 快照查找已知 VGN 设备，避免重复触发 USB 总线枚举。"""
        return self._select_candidate(self._enumerate_if_needed(hid_snapshot))

    def _current_backoff_sec(self, consecutive_misses: Optional[int] = None) -> float:
        misses = self._consecutive_misses if consecutive_misses is None else consecutive_misses
        if misses < self.SLEEP_MISS_THRESHOLD:
            return 0.0
        step = min(
            len(self.SLEEP_BACKOFF_STEPS_SEC) - 1,
            misses - self.SLEEP_MISS_THRESHOLD,
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

    @staticmethod
    def _parse_reply_fields(reply: list[int], is_wired_pid: bool) -> tuple[int, bool, bool, Optional[int], str]:
        """严格保留 VGN Byte[6] 原始百分比直传，返回 (raw_pct, raw_chg_flag, charging, voltage_mv, hex_str)。"""
        raw_pct = int(reply[6])
        raw_chg_flag = bool(reply[7])
        voltage = (int(reply[8]) << 8) | int(reply[9])
        voltage_mv = voltage if 2500 <= voltage <= 5000 else None
        charging = raw_chg_flag or is_wired_pid
        raw_hex = " ".join(f"{int(b) & 0xFF:02X}" for b in reply[:REPORT_LEN])
        return raw_pct, raw_chg_flag, charging, voltage_mv, raw_hex

    def _is_anomalous_jump(
        self,
        prev: Optional[BatteryReading],
        new_pct: int,
        new_charging: bool,
    ) -> bool:
        if prev is None or prev.percent is None:
            return False
        delta = new_pct - int(prev.percent)
        if abs(delta) >= self.ANOMALY_JUMP_DELTA:
            return True
        if (not new_charging) and (not prev.charging) and delta >= self.ANOMALY_NON_CHARGING_UP_DELTA:
            return True
        return False

    def _read_single_logical(
        self,
        lkey: str,
        dev_info: dict,
        name: str,
        mode: str,
        *,
        force: bool = False,
    ) -> tuple[BatteryReading, dict[str, object]]:
        vid = int(dev_info.get("vendor_id", VENDOR_COMPX))
        pid = int(dev_info.get("product_id", 0))
        iface = int(dev_info.get("interface_number", -1))
        path = dev_info["path"]
        is_wired_pid = pid in WIRED_PIDS
        src_if = f"{'wired' if is_wired_pid else '2.4G'}({vid:04X}:{pid:04X}/if{iface})"

        state = self._device_states.setdefault(lkey, _VgnDeviceState())
        # 若从 2.4G 切换为有线（如插入充电线），立刻穿透退避强制查询真实状态
        interface_switched = (
            state.last_pid is not None
            and state.last_pid != pid
        )
        state.last_vid = vid
        state.last_pid = pid

        now_mono = time.monotonic()
        now_ts = time.time()
        backoff_sec = self._current_backoff_sec(state.consecutive_misses)
        if (
            not force
            and not is_wired_pid
            and not interface_switched
            and backoff_sec > 0.0
            and state.last_query_mono > 0.0
            and (now_mono - state.last_query_mono) < backoff_sec
        ):
            qstats: dict[str, object] = {
                "ok": False,
                "duration_ms": 0.0,
                "timeouts": 0,
                "retries": 0,
                "io_error": False,
                "skipped_backoff": True,
                "consecutive_misses": state.consecutive_misses,
            }
            if state.last_valid is not None:
                prev = state.last_valid
                last_ok = prev.last_success_ts if prev.last_success_ts is not None else prev.timestamp
                diag = {
                    "charging_state": False,
                    "previous_charging_state": bool(prev.charging),
                    "raw_percent": prev.percent,
                    "previous_raw_percent": prev.percent,
                    "voltage_mv": prev.voltage_mv,
                    "previous_voltage_mv": prev.voltage_mv,
                    "last_success_ts": last_ok,
                    "current_sample_ts": now_ts,
                    "percentage_delta": 0 if prev.percent is not None else None,
                    "charging_transition": "none",
                    "source_interface": src_if,
                    "report_length": REPORT_LEN,
                    "from_cache": True,
                    "read_duration_ms": 0.0,
                    "anomaly_detected": False,
                    "failure_reason": "sleep_backoff",
                }
                return (
                    BatteryReading(
                        connected=True,
                        online=False,
                        asleep=True,
                        percent=prev.percent,
                        charging=False,
                        voltage_mv=prev.voltage_mv,
                        device_name=name,
                        connection_mode="休眠",
                        timestamp=last_ok,
                        vid=vid,
                        pid=pid,
                        interface_number=iface,
                        report_length=REPORT_LEN,
                        last_success_ts=last_ok,
                        from_cache=True,
                        stale=True,
                        status_detail="休眠中",
                        diagnostic=diag,
                        instance_key=lkey,
                    ),
                    qstats,
                )
            return (
                BatteryReading(
                    connected=True,
                    online=False,
                    asleep=True,
                    percent=None,
                    charging=False,
                    voltage_mv=None,
                    device_name=name,
                    connection_mode="休眠",
                    timestamp=now_ts,
                    vid=vid,
                    pid=pid,
                    interface_number=iface,
                    report_length=REPORT_LEN,
                    last_success_ts=None,
                    from_cache=False,
                    stale=True,
                    status_detail="休眠中",
                    diagnostic={
                        "charging_state": False,
                        "previous_charging_state": None,
                        "raw_percent": None,
                        "previous_raw_percent": None,
                        "voltage_mv": None,
                        "previous_voltage_mv": None,
                        "last_success_ts": None,
                        "current_sample_ts": now_ts,
                        "percentage_delta": None,
                        "charging_transition": "none",
                        "source_interface": src_if,
                        "report_length": REPORT_LEN,
                        "from_cache": False,
                        "read_duration_ms": 0.0,
                        "anomaly_detected": False,
                        "failure_reason": "sleep_backoff",
                    },
                    instance_key=lkey,
                ),
                qstats,
            )

        already_asleep = state.consecutive_misses >= self.SLEEP_MISS_THRESHOLD
        max_attempts = 1 if (already_asleep and not force and not interface_switched) else 2
        reply, qstats = self._query_once(path, max_attempts=max_attempts)
        state.last_query_mono = time.monotonic()
        sample_ts = time.time()

        if reply is not None:
            raw_pct, raw_chg_flag, charging, voltage_mv, raw_hex = self._parse_reply_fields(reply, is_wired_pid)
            prev = state.last_valid
            prev_pct = prev.percent if prev is not None else None
            prev_chg = prev.charging if prev is not None else None
            prev_mv = prev.voltage_mv if prev is not None else None
            prev_ok_ts = (prev.last_success_ts if prev.last_success_ts is not None else prev.timestamp) if prev else None
            delta = (raw_pct - prev_pct) if prev_pct is not None else None

            anomaly = self._is_anomalous_jump(prev, raw_pct, charging)
            confirmation_reads: list[dict[str, Any]] = []
            anomaly_resolution = "none"
            total_dur_ms = float(qstats.get("duration_ms", 0.0) or 0.0)

            if anomaly and prev is not None and prev_pct is not None:
                # 发现异常大幅跳变（例如 50% -> 75%）：额外复核读取确认真伪，绝不人为平滑/限制
                confirmed_samples: list[tuple[int, bool, bool, Optional[int], str]] = []
                for _ in range(2):
                    time.sleep(0.08)
                    c_reply, c_stats = self._query_once(path, max_attempts=1)
                    total_dur_ms += float(c_stats.get("duration_ms", 0.0) or 0.0)
                    if c_reply is not None:
                        c_pct, c_raw_chg, c_chg, c_mv, c_hex = self._parse_reply_fields(c_reply, is_wired_pid)
                        confirmed_samples.append((c_pct, c_raw_chg, c_chg, c_mv, c_hex))
                        confirmation_reads.append(
                            {
                                "raw_percent": c_pct,
                                "charging": c_chg,
                                "raw_charging_flag": c_raw_chg,
                                "voltage_mv": c_mv,
                                "raw_frame_hex": c_hex,
                            }
                        )
                        # 首次复核即与候选新值一致，可提前确认以减少 HID 总线占用
                        if abs(c_pct - raw_pct) <= self.ANOMALY_CONFIRM_TOLERANCE:
                            break
                        # 若首次复核立即回落至原有效电量附近，继续再确认一次确保稳定
                if confirmed_samples and any(abs(s[0] - raw_pct) <= self.ANOMALY_CONFIRM_TOLERANCE for s in confirmed_samples):
                    # 连续有效读取一致确认新电量（例如两次均返回 75%），如实接受硬件报告值
                    final_s = confirmed_samples[-1]
                    raw_pct, raw_chg_flag, charging, voltage_mv, raw_hex = final_s
                    delta = raw_pct - prev_pct
                    anomaly_resolution = "confirmed_hardware_reading"
                elif confirmed_samples and all(abs(s[0] - prev_pct) <= self.ANOMALY_CONFIRM_TOLERANCE for s in confirmed_samples):
                    # 仅单次异常报文，后续复核立即回到原有效区间 -> 拒绝异常值覆盖，采用复核稳定值
                    final_s = confirmed_samples[-1]
                    raw_pct, raw_chg_flag, charging, voltage_mv, raw_hex = final_s
                    delta = raw_pct - prev_pct
                    anomaly_resolution = "rejected_transient_spike"
                else:
                    # 复核失败或数据持续剧烈抖动 -> 不允许未确认异常值覆盖最后一次确认的有效电量
                    state.consecutive_misses += 1
                    qstats["ok"] = False
                    qstats["duration_ms"] = round(total_dur_ms, 2)
                    qstats["consecutive_misses"] = state.consecutive_misses
                    diag_rej = {
                        "charging_state": bool(prev.charging),
                        "previous_charging_state": bool(prev.charging),
                        "raw_percent": raw_pct,
                        "previous_raw_percent": prev_pct,
                        "voltage_mv": voltage_mv,
                        "previous_voltage_mv": prev_mv,
                        "last_success_ts": prev_ok_ts,
                        "current_sample_ts": sample_ts,
                        "percentage_delta": delta,
                        "charging_transition": "none",
                        "source_interface": src_if,
                        "report_length": REPORT_LEN,
                        "from_cache": True,
                        "read_duration_ms": round(total_dur_ms, 2),
                        "anomaly_detected": True,
                        "anomaly_resolution": "unconfirmed_rejected",
                        "confirmation_reads": confirmation_reads,
                        "raw_frame_hex": raw_hex,
                        "failure_reason": "anomaly_unconfirmed",
                    }
                    return (
                        BatteryReading(
                            connected=True,
                            online=False,
                            asleep=False,
                            percent=prev.percent,
                            charging=prev.charging,
                            voltage_mv=prev.voltage_mv,
                            device_name=name,
                            connection_mode=prev.connection_mode,
                            timestamp=prev_ok_ts or sample_ts,
                            vid=vid,
                            pid=pid,
                            interface_number=iface,
                            report_length=REPORT_LEN,
                            last_success_ts=prev_ok_ts,
                            from_cache=True,
                            stale=True,
                            status_detail="读数复核中",
                            diagnostic=diag_rej,
                            instance_key=lkey,
                        ),
                        qstats,
                    )

            state.consecutive_misses = 0
            qstats["duration_ms"] = round(total_dur_ms, 2)
            qstats["consecutive_misses"] = 0

            if prev_chg is None or prev_chg == charging:
                chg_trans = "none"
            elif charging:
                chg_trans = "started_charging"
            else:
                chg_trans = "stopped_charging"

            diag = {
                "charging_state": charging,
                "raw_charging_flag": raw_chg_flag,
                "previous_charging_state": prev_chg,
                "raw_percent": raw_pct,
                "previous_raw_percent": prev_pct,
                "voltage_mv": voltage_mv,
                "previous_voltage_mv": prev_mv,
                "last_success_ts": sample_ts,
                "current_sample_ts": sample_ts,
                "percentage_delta": delta,
                "charging_transition": chg_trans,
                "source_interface": src_if,
                "report_length": REPORT_LEN,
                "from_cache": False,
                "read_duration_ms": round(total_dur_ms, 2),
                "anomaly_detected": anomaly,
                "anomaly_resolution": anomaly_resolution,
                "confirmation_reads": confirmation_reads,
                "raw_frame_hex": raw_hex,
                "interface_switched": interface_switched,
                "failure_reason": "",
            }
            reading = BatteryReading(
                connected=True,
                online=True,
                asleep=False,
                percent=raw_pct,
                charging=charging,
                voltage_mv=voltage_mv,
                device_name=name,
                connection_mode="有线" if is_wired_pid else ("2.4G" if mode == "2.4G" else mode),
                timestamp=sample_ts,
                vid=vid,
                pid=pid,
                interface_number=iface,
                report_length=REPORT_LEN,
                last_success_ts=sample_ts,
                from_cache=False,
                stale=False,
                status_detail="",
                diagnostic=diag,
                instance_key=lkey,
            )
            state.last_valid = reading
            return reading, qstats

        # 本次未收到有效回包：累计失联次数；绝不在失败前 2 次伪装 online=True，也绝不错误翻转充电状态
        state.consecutive_misses += 1
        qstats["consecutive_misses"] = state.consecutive_misses
        is_asleep = (not is_wired_pid) and (state.consecutive_misses >= self.SLEEP_MISS_THRESHOLD)
        fail_reason = "io_error" if qstats.get("io_error") else ("device_asleep" if is_asleep else "timeout")

        if state.last_valid is not None:
            prev = state.last_valid
            last_ok = prev.last_success_ts if prev.last_success_ts is not None else prev.timestamp
            # 读取失败时不错误翻转充电状态；已确认无线休眠时按非充电处理
            kept_chg = False if is_asleep else bool(prev.charging)
            diag_fail = {
                "charging_state": kept_chg,
                "previous_charging_state": bool(prev.charging),
                "raw_percent": prev.percent,
                "previous_raw_percent": prev.percent,
                "voltage_mv": prev.voltage_mv,
                "previous_voltage_mv": prev.voltage_mv,
                "last_success_ts": last_ok,
                "current_sample_ts": sample_ts,
                "percentage_delta": 0 if prev.percent is not None else None,
                "charging_transition": "none",
                "source_interface": src_if,
                "report_length": REPORT_LEN,
                "from_cache": True,
                "read_duration_ms": float(qstats.get("duration_ms", 0.0) or 0.0),
                "anomaly_detected": False,
                "failure_reason": fail_reason,
            }
            return (
                BatteryReading(
                    connected=True,
                    online=False,
                    asleep=is_asleep,
                    percent=prev.percent,
                    charging=kept_chg,
                    voltage_mv=prev.voltage_mv,
                    device_name=name,
                    connection_mode="休眠" if is_asleep else prev.connection_mode,
                    timestamp=last_ok,
                    vid=vid,
                    pid=pid,
                    interface_number=iface,
                    report_length=REPORT_LEN,
                    last_success_ts=last_ok,
                    from_cache=True,
                    stale=True,
                    status_detail="休眠中" if is_asleep else "读取失败",
                    diagnostic=diag_fail,
                    instance_key=lkey,
                ),
                qstats,
            )

        return (
            BatteryReading(
                connected=True,
                online=False,
                asleep=is_asleep,
                percent=None,
                charging=False,
                voltage_mv=None,
                device_name=name,
                connection_mode="休眠" if is_asleep else mode,
                timestamp=sample_ts,
                vid=vid,
                pid=pid,
                interface_number=iface,
                report_length=REPORT_LEN,
                last_success_ts=None,
                from_cache=False,
                stale=True,
                status_detail="休眠中" if is_asleep else "读取失败",
                diagnostic={
                    "charging_state": False,
                    "previous_charging_state": None,
                    "raw_percent": None,
                    "previous_raw_percent": None,
                    "voltage_mv": None,
                    "previous_voltage_mv": None,
                    "last_success_ts": None,
                    "current_sample_ts": sample_ts,
                    "percentage_delta": None,
                    "charging_transition": "none",
                    "source_interface": src_if,
                    "report_length": REPORT_LEN,
                    "from_cache": False,
                    "read_duration_ms": float(qstats.get("duration_ms", 0.0) or 0.0),
                    "anomaly_detected": False,
                    "failure_reason": fail_reason,
                },
                instance_key=lkey,
            ),
            qstats,
        )

    def read_all(self, hid_snapshot: Optional[list[dict]] = None, force: bool = False) -> list[BatteryReading]:
        """读取当前所有已接入的 VGN / CompX 17B 鼠标（多设备隔离、拔出自动清空对应缓存）。"""
        with self._lock:
            devices = self._enumerate_if_needed(hid_snapshot)
            candidates = self._collect_logical_candidates(devices)
            present_keys = {lkey for lkey, _, _, _ in candidates}

            # 设备拔出时立刻清理已不存在设备的 _last_valid 与失联计数，防止重插/换设备缓存污染
            for old_key in list(self._device_states.keys()):
                if old_key not in present_keys:
                    del self._device_states[old_key]

            if not candidates:
                self._last_valid = None
                self._consecutive_misses = 0
                self._last_query_mono = 0.0
                self._last_query_stats = {
                    "ok": False,
                    "duration_ms": 0.0,
                    "timeouts": 0,
                    "retries": 0,
                    "io_error": False,
                    "skipped_backoff": False,
                    "consecutive_misses": 0,
                }
                return []

            readings: list[BatteryReading] = []
            agg_stats: dict[str, object] = {
                "ok": False,
                "duration_ms": 0.0,
                "timeouts": 0,
                "retries": 0,
                "io_error": False,
                "skipped_backoff": False,
                "consecutive_misses": 0,
            }
            for idx, (lkey, dev_info, name, mode) in enumerate(candidates):
                r, st = self._read_single_logical(lkey, dev_info, name, mode, force=force)
                readings.append(r)
                agg_stats["duration_ms"] = round(float(agg_stats["duration_ms"]) + float(st.get("duration_ms", 0.0) or 0.0), 2)
                agg_stats["timeouts"] = int(agg_stats["timeouts"]) + int(st.get("timeouts", 0) or 0)
                agg_stats["retries"] = int(agg_stats["retries"]) + int(st.get("retries", 0) or 0)
                if st.get("ok"):
                    agg_stats["ok"] = True
                if st.get("io_error"):
                    agg_stats["io_error"] = True
                if st.get("skipped_backoff"):
                    agg_stats["skipped_backoff"] = True
                if idx == 0:
                    prim_state = self._device_states.get(lkey)
                    self._last_valid = prim_state.last_valid if prim_state else None
                    self._consecutive_misses = prim_state.consecutive_misses if prim_state else 0
                    self._last_query_mono = prim_state.last_query_mono if prim_state else 0.0
                    agg_stats["consecutive_misses"] = self._consecutive_misses
            self._last_query_stats = agg_stats
            return readings

    def read(self, hid_snapshot: Optional[list[dict]] = None, force: bool = False) -> BatteryReading:
        """兼容单设备入口：返回主 VGN/CompX 鼠标读数，拔出时彻底清理缓存。"""
        readings = self.read_all(hid_snapshot=hid_snapshot, force=force)
        if not readings:
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
                last_success_ts=None,
                from_cache=False,
                stale=False,
            )
        return readings[0]
