"""标准 Windows 蓝牙电量服务（Bluetooth Battery Service / HFP）与 Apple AirPods Continuity BLE 解析适配器。

设计说明：
1. 标准蓝牙设备：直接通过 Windows SetupAPI 只读查询系统已维护的
   `DEVPKEY_Device_BatteryLevel` (`{104EA319-6EE2-4701-BD47-8DDBF425BBE5}, 2`) 与
   `DEVPKEY_Device_IsConnected` (`{83DA6326-97A6-4088-9453-A1923F573B29}, 15`) 属性，
   无需安装任何第三方驱动或蓝牙服务，无蓝牙适配器时静默返回空列表且零报错。
2. Apple AirPods / Beats：实现完整的 Apple Continuity 邻近配对 BLE 广播报文解析器
   `parse_airpods_continuity()`（参考 MIT 许可项目 JKWTCN/BatteryMonitor 与 qu1ncky/BatteryTray），
   支持左耳、右耳、充电盒独立电量与充电状态（以及左右翻转位与 AirPods Max +5 偏移）。
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from ctypes import wintypes
from typing import Optional

from .base import (
    BatteryProvider,
    DeviceBattery,
    KIND_EARBUDS,
    KIND_HEADSET,
    KIND_KEYBOARD,
    KIND_MOUSE,
    KIND_OTHER,
    STATUS_PROTOCOL,
    SubBattery,
)

APPLE_COMPANY_ID = 0x004C
AIRPODS_ADV_TYPE = 0x07

# Apple AirPods / Beats 蓝牙型号映射表
APPLE_AUDIO_MODELS: dict[int, tuple[str, str]] = {
    0x2002: ("AirPods (第 1 代)", KIND_EARBUDS),
    0x200F: ("AirPods (第 2 代)", KIND_EARBUDS),
    0x2013: ("AirPods (第 3 代)", KIND_EARBUDS),
    0x2019: ("AirPods 4", KIND_EARBUDS),
    0x201B: ("AirPods 4 (主动降噪)", KIND_EARBUDS),
    0x200E: ("AirPods Pro", KIND_EARBUDS),
    0x2014: ("AirPods Pro (第 2 代)", KIND_EARBUDS),
    0x2024: ("AirPods Pro 2 (USB-C)", KIND_EARBUDS),
    0x2027: ("AirPods Pro 3", KIND_EARBUDS),
    0x200A: ("AirPods Max", KIND_HEADSET),
    0x201F: ("AirPods Max (USB-C)", KIND_HEADSET),
    0x202D: ("AirPods Max 2", KIND_HEADSET),
    # Beats
    0x2005: ("BeatsX", KIND_EARBUDS),
    0x2010: ("Beats Flex", KIND_EARBUDS),
    0x2006: ("Beats Solo 3", KIND_HEADSET),
    0x200C: ("Beats Solo Pro", KIND_HEADSET),
    0x2025: ("Beats Solo 4", KIND_HEADSET),
    0x2026: ("Beats Solo Buds", KIND_EARBUDS),
    0x2007: ("Beats Studio 3", KIND_HEADSET),
    0x2009: ("Beats Studio 3", KIND_HEADSET),
    0x2011: ("Beats Studio Buds", KIND_EARBUDS),
    0x2016: ("Beats Studio Buds+", KIND_EARBUDS),
    0x2017: ("Beats Studio Pro", KIND_HEADSET),
    0x2003: ("Powerbeats 3", KIND_EARBUDS),
    0x200D: ("Powerbeats 4", KIND_EARBUDS),
    0x200B: ("Powerbeats Pro", KIND_EARBUDS),
    0x201D: ("Powerbeats Pro 2", KIND_EARBUDS),
    0x2012: ("Beats Fit Pro", KIND_EARBUDS),
}

AIRPODS_MAX_MODELS = {0x200A, 0x201F, 0x202D}


def _nibble_to_percent(nib: int, model_id: int) -> Optional[int]:
    """将 Apple Continuity 4-bit 电量 nibble 解码为百分比（15 表示未知/不可用）。"""
    if nib == 0x0F or nib < 0:
        return None
    if nib >= 10:
        return 100
    base = nib * 10
    if model_id in AIRPODS_MAX_MODELS:
        return min(100, base + 5)
    return base


def parse_airpods_continuity(
    data: bytes | bytearray | list[int],
    address: int = 0,
    provider_name: str = "bluetooth",
) -> Optional[DeviceBattery]:
    """解析 Apple CompanyId 0x004C Continuity BLE 广播负载 -> DeviceBattery（含左/右/盒独立电量）。"""
    buf = bytes(data)
    if len(buf) < 25 or buf[0] != AIRPODS_ADV_TYPE:
        return None

    model_id = buf[3] | (buf[4] << 8)
    model_name, kind = APPLE_AUDIO_MODELS.get(model_id, (f"Apple Audio ({model_id:04X})", KIND_EARBUDS))

    left_nib = (buf[6] & 0xF0) >> 4
    right_nib = buf[6] & 0x0F
    case_nib = buf[7] & 0x0F
    status_nib = (buf[7] & 0xF0) >> 4

    # buf[10] bit 1 指示左右声道 nibble 与充电位翻转
    flipped = (buf[10] & 0x02) != 0
    a_nib = right_nib if flipped else left_nib
    b_nib = left_nib if flipped else right_nib

    case_chg = bool(status_nib & 0x04)
    left_chg = bool(status_nib & (0x02 if flipped else 0x01))
    right_chg = bool(status_nib & (0x01 if flipped else 0x02))
    any_chg = left_chg or right_chg or case_chg

    left_pct = _nibble_to_percent(a_nib, model_id)
    right_pct = _nibble_to_percent(b_nib, model_id)
    case_pct = _nibble_to_percent(case_nib, model_id)

    valid_levels = [v for v in (left_pct, right_pct, case_pct) if v is not None]
    main_pct = min(valid_levels) if valid_levels else None

    sub = None
    if kind == KIND_EARBUDS:
        sub = SubBattery(
            left_percent=left_pct,
            left_charging=left_chg,
            right_percent=right_pct,
            right_charging=right_chg,
            case_percent=case_pct,
            case_charging=case_chg,
        )

    addr_key = f"{address:012x}" if address else f"{model_id:04x}"
    return DeviceBattery(
        device_id=f"airpods:{addr_key}",
        name=model_name,
        brand="Apple",
        kind=kind,
        connection_mode="蓝牙 BLE",
        vid=APPLE_COMPANY_ID,
        pid=model_id,
        connected=True,
        online=True,
        asleep=False,
        percent=main_pct,
        charging=any_chg,
        full=any_chg and main_pct == 100,
        sub_batteries=sub,
        support_status=STATUS_PROTOCOL,
        status_detail="" if main_pct is not None else "电量读取中",
        provider_name=provider_name,
    )


# ================= Windows SetupAPI 只读查询系统蓝牙设备电量 =================

class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _DEVPROPKEY(ctypes.Structure):
    _fields_ = [
        ("fmtid", _GUID),
        ("pid", wintypes.ULONG),
    ]


class _SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("ClassGuid", _GUID),
        ("DevInst", wintypes.DWORD),
        ("Reserved", ctypes.c_void_p),
    ]


def _make_guid(d1: int, d2: int, d3: int, d4_hex: str) -> _GUID:
    raw = bytes.fromhex(d4_hex)
    arr = (ctypes.c_ubyte * 8)(*raw)
    return _GUID(d1, d2, d3, arr)


# DEVPKEY_Device_BatteryLevel: {104EA319-6EE2-4701-BD47-8DDBF425BBE5}, 2 (BYTE 0..100)
_PKEY_BATTERY_LEVEL = _DEVPROPKEY(_make_guid(0x104EA319, 0x6EE2, 0x4701, "BD478DDBF425BBE5"), 2)
# DEVPKEY_Device_IsConnected: {83DA6326-97A6-4088-9453-A1923F573B29}, 15 (DEVPROP_TYPE_BOOLEAN)
_PKEY_IS_CONNECTED = _DEVPROPKEY(_make_guid(0x83DA6326, 0x97A6, 0x4088, "9453A1923F573B29"), 15)
# DEVPKEY_Device_FriendlyName: {A45C254E-DF1C-4EFD-8020-67D146A850E0}, 14 (STRING)
_PKEY_FRIENDLY_NAME = _DEVPROPKEY(_make_guid(0xA45C254E, 0xDF1C, 0x4EFD, "802067D146A850E0"), 14)
# DEVPKEY_NAME: {B725F130-47EF-101A-A5F1-02608C9EEBAC}, 10 (STRING)
_PKEY_NAME = _DEVPROPKEY(_make_guid(0xB725F130, 0x47EF, 0x101A, "A5F102608C9EEBAC"), 10)


def _infer_bt_brand_and_kind(name: str) -> tuple[str, str]:
    low = name.lower()
    brand = "Bluetooth"
    for kw, b in (
        ("airpods", "Apple"),
        ("beats", "Apple"),
        ("sony", "Sony"),
        ("wh-", "Sony"),
        ("wf-", "Sony"),
        ("inzone", "Sony"),
        ("logitech", "Logitech"),
        ("mx master", "Logitech"),
        ("mx anywhere", "Logitech"),
        ("razer", "Razer"),
        ("steelseries", "SteelSeries"),
        ("arctis", "SteelSeries"),
        ("corsair", "Corsair"),
        ("hyperx", "HyperX"),
        ("rog ", "ASUS ROG"),
        ("asus", "ASUS ROG"),
        ("vgn", "VGN"),
        ("vxe", "VXE"),
        ("atk", "ATK"),
        ("mchose", "MCHOSE"),
        ("rapoo", "Rapoo"),
        ("lamzu", "LAMZU"),
    ):
        if kw in low:
            brand = b
            break

    kind = KIND_OTHER
    if any(k in low for k in ("airpods", "buds", "wf-", "earbud", "freebuds", "pods")):
        kind = KIND_EARBUDS
    elif any(k in low for k in ("headset", "headphone", "arctis", "wh-", "cloud", "void", "hs", "audio", "耳机", "max")):
        kind = KIND_HEADSET
    elif any(k in low for k in ("mouse", "master", "anywhere", "viper", "deathadder", "aerox", "鼠标", "dragonfly")):
        kind = KIND_MOUSE
    elif any(k in low for k in ("keyboard", "keychron", "azoth", "falchion", "键盘")):
        kind = KIND_KEYBOARD
    return brand, kind


def query_windows_bluetooth_pnp_batteries(provider_name: str = "bluetooth") -> list[DeviceBattery]:
    """通过 Windows SetupAPI 只读枚举带 DEVPKEY_Device_BatteryLevel 的蓝牙设备。"""
    if sys.platform != "win32":
        return []
    devices: list[DeviceBattery] = []
    seen_names: set[str] = set()
    try:
        setupapi = ctypes.windll.setupapi
        DIGCF_PRESENT = 0x00000002
        DIGCF_ALLCLASSES = 0x00000004
        INVALID_HANDLE = ctypes.c_void_p(-1).value

        setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]
        setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
        setupapi.SetupDiEnumDeviceInfo.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_SP_DEVINFO_DATA)]
        setupapi.SetupDiEnumDeviceInfo.restype = wintypes.BOOL
        setupapi.SetupDiGetDevicePropertyW.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_SP_DEVINFO_DATA),
            ctypes.POINTER(_DEVPROPKEY),
            ctypes.POINTER(wintypes.ULONG),
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.DWORD,
        ]
        setupapi.SetupDiGetDevicePropertyW.restype = wintypes.BOOL
        setupapi.SetupDiGetDeviceInstanceIdW.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_SP_DEVINFO_DATA),
            wintypes.LPWSTR,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        setupapi.SetupDiGetDeviceInstanceIdW.restype = wintypes.BOOL
        setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
        setupapi.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL

        for enumerator in ("BTHENUM", "BTHLE", "BTHLEDEVICE"):
            hdev = setupapi.SetupDiGetClassDevsW(None, enumerator, None, DIGCF_PRESENT | DIGCF_ALLCLASSES)
            if not hdev or hdev == INVALID_HANDLE:
                continue
            try:
                idx = 0
                while True:
                    dev_data = _SP_DEVINFO_DATA()
                    dev_data.cbSize = ctypes.sizeof(_SP_DEVINFO_DATA)
                    if not setupapi.SetupDiEnumDeviceInfo(hdev, idx, ctypes.byref(dev_data)):
                        break
                    idx += 1

                    # 读取电量属性（1 字节 0..100）
                    prop_type = wintypes.ULONG(0)
                    bat_buf = (ctypes.c_ubyte * 4)()
                    req_size = wintypes.DWORD(0)
                    ok = setupapi.SetupDiGetDevicePropertyW(
                        hdev,
                        ctypes.byref(dev_data),
                        ctypes.byref(_PKEY_BATTERY_LEVEL),
                        ctypes.byref(prop_type),
                        bat_buf,
                        4,
                        ctypes.byref(req_size),
                        0,
                    )
                    if not ok or req_size.value < 1:
                        continue
                    pct = int(bat_buf[0])
                    if not (0 <= pct <= 100):
                        continue

                    # 检查是否在线（若无 IsConnected 属性，则默认在线）
                    conn_buf = (ctypes.c_ubyte * 4)()
                    conn_type = wintypes.ULONG(0)
                    conn_req = wintypes.DWORD(0)
                    is_online = True
                    if setupapi.SetupDiGetDevicePropertyW(
                        hdev,
                        ctypes.byref(dev_data),
                        ctypes.byref(_PKEY_IS_CONNECTED),
                        ctypes.byref(conn_type),
                        conn_buf,
                        4,
                        ctypes.byref(conn_req),
                        0,
                    ):
                        is_online = conn_buf[0] != 0
                    if not is_online:
                        continue

                    # 读取设备名称
                    name = ""
                    for pkey in (_PKEY_FRIENDLY_NAME, _PKEY_NAME):
                        str_buf = ctypes.create_unicode_buffer(256)
                        st_type = wintypes.ULONG(0)
                        st_req = wintypes.DWORD(0)
                        if setupapi.SetupDiGetDevicePropertyW(
                            hdev,
                            ctypes.byref(dev_data),
                            ctypes.byref(pkey),
                            ctypes.byref(st_type),
                            str_buf,
                            ctypes.sizeof(str_buf),
                            ctypes.byref(st_req),
                            0,
                        ):
                            cand = str_buf.value.strip()
                            if cand:
                                name = cand
                                break
                    if not name:
                        continue
                    # 清理 Windows HFP 后缀
                    for suffix in (" Hands-Free AG", " Hands-Free", " Stereo", " Avrcp Transport"):
                        if name.endswith(suffix):
                            name = name[: -len(suffix)].strip()

                    inst_buf = ctypes.create_unicode_buffer(256)
                    inst_req = wintypes.DWORD(0)
                    inst_id = name
                    if setupapi.SetupDiGetDeviceInstanceIdW(
                        hdev, ctypes.byref(dev_data), inst_buf, 256, ctypes.byref(inst_req)
                    ):
                        inst_id = inst_buf.value.strip() or name

                    norm_key = name.lower()
                    if norm_key in seen_names:
                        continue
                    seen_names.add(norm_key)

                    brand, kind = _infer_bt_brand_and_kind(name)
                    devices.append(
                        DeviceBattery(
                            device_id=f"bt:{norm_key}",
                            name=name,
                            brand=brand,
                            kind=kind,
                            connection_mode="蓝牙",
                            connected=True,
                            online=True,
                            asleep=False,
                            percent=pct,
                            charging=False,
                            support_status=STATUS_PROTOCOL,
                            status_detail="Windows 蓝牙电量服务",
                            provider_name=provider_name,
                        )
                    )
            finally:
                setupapi.SetupDiDestroyDeviceInfoList(hdev)
    except Exception:
        return []
    return devices


class BluetoothBatteryProvider(BatteryProvider):
    """标准 Windows 蓝牙电量服务 + Apple AirPods Continuity BLE 广播适配器。"""

    name = "bluetooth"
    brand = "Bluetooth / Apple"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ble_cache: dict[str, tuple[float, DeviceBattery]] = {}
        self._ble_stale_sec = 40.0
        self._ble_watcher = None
        self._ble_available = False
        self._ble_init_attempted = False

    def ingest_airpods_advertisement(self, address: int, manufacturer_data: bytes) -> Optional[DeviceBattery]:
        """供可选 BLE 监听器或单元测试注入 Apple Continuity 广播报文。"""
        dev = parse_airpods_continuity(manufacturer_data, address=address, provider_name=self.name)
        if dev is None:
            return None
        with self._lock:
            self._ble_cache[dev.device_id] = (time.time(), dev)
        return dev

    def _try_start_optional_ble_watcher(self) -> None:
        """若本机安装了 WinRT BLE 绑定且蓝牙适配器可用，被动监听 Apple 广播；否则仅检查一次后静默跳过。"""
        if self._ble_watcher is not None or self._ble_init_attempted:
            return
        self._ble_init_attempted = True
        try:
            from winrt.windows.devices.bluetooth.advertisement import (  # type: ignore
                BluetoothLEAdvertisementWatcher,
                BluetoothLEScanningMode,
            )
            from winrt.windows.storage.streams import DataReader  # type: ignore

            watcher = BluetoothLEAdvertisementWatcher()
            watcher.scanning_mode = BluetoothLEScanningMode.PASSIVE

            def _on_rx(_sender, args) -> None:
                try:
                    if args.raw_signal_strength_in_d_bm < -75:
                        return
                    for md in args.advertisement.manufacturer_data:
                        if md.company_id != APPLE_COMPANY_ID:
                            continue
                        reader = DataReader.from_buffer(md.data)
                        raw = bytearray(md.data.length)
                        reader.read_bytes(raw)
                        self.ingest_airpods_advertisement(int(args.bluetooth_address), bytes(raw))
                        break
                except Exception:
                    pass

            watcher.add_received(_on_rx)
            watcher.start()
            self._ble_watcher = watcher
            self._ble_available = True
        except Exception:
            self._ble_available = False

    def stop(self) -> None:
        if self._ble_watcher is not None:
            try:
                self._ble_watcher.stop()
            except Exception:
                pass
            self._ble_watcher = None

    def poll(self, _hid_snapshot: list[dict]) -> list[DeviceBattery]:
        self._try_start_optional_ble_watcher()

        # 1. 标准 Windows 蓝牙电量服务（无蓝牙硬件时快速返回空列表）
        results = query_windows_bluetooth_pnp_batteries(provider_name=self.name)
        by_name = {d.name.lower(): idx for idx, d in enumerate(results)}

        # 2. 合并近期收到的 Apple AirPods Continuity 分体电量（优先覆盖单值 HFP 读数）
        now = time.time()
        with self._lock:
            expired = [k for k, (ts, _) in self._ble_cache.items() if now - ts > self._ble_stale_sec]
            for k in expired:
                del self._ble_cache[k]
            ble_items = [dev for _, dev in self._ble_cache.values()]

        for air in ble_items:
            air_low = air.name.lower()
            matched_idx = None
            for k, idx in by_name.items():
                if "airpods" in k and "airpods" in air_low:
                    matched_idx = idx
                    break
            if matched_idx is not None:
                results[matched_idx] = air
            else:
                results.append(air)

        return results
