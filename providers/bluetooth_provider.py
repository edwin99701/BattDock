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
import struct
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
# DEVPKEY_Device_DeviceDesc: {A45C254E-DF1C-4EFD-8020-67D146A850E0}, 2 (STRING)
_PKEY_DEVICE_DESC = _DEVPROPKEY(_make_guid(0xA45C254E, 0xDF1C, 0x4EFD, "802067D146A850E0"), 2)

# Windows 蓝牙服务通用占位名（绝不能直接当作设备型号名，应从同 MAC 的根设备节点获取真实型号）
_GENERIC_BT_SERVICE_NAMES = {
    "bluetooth hands-free audio device",
    "bluetooth hands-free ag audio",
    "microsoft bluetooth hands-free profile audio device",
    "microsoft 蓝牙免提配置文件音频设备",
    "蓝牙免提音频设备",
    "免提 ag 音频",
    "bluetooth avrcp transport driver",
    "microsoft bluetooth avrcp transport driver",
    "bluetooth device",
    "bluetooth low energy gatt compliant hid device",
    "generic attribute profile",
    "battery service",
    "电池服务",
    "device information service",
    "hid over gatt",
    "bluetooth hid device",
    "蓝牙 hid 设备",
    "bluetooth le generic attribute service",
}


def parse_bluetooth_address(instance_id: str) -> str:
    """从 Windows 蓝牙设备 InstanceId 提取 12 位十六进制 MAC 地址（取最后一组恰好 12 位 hex）。"""
    s = (instance_id or "").strip()
    last = ""
    i = 0
    n = len(s)
    while i < n:
        if s[i] not in "0123456789abcdefABCDEF":
            i += 1
            continue
        start = i
        while i < n and s[i] in "0123456789abcdefABCDEF":
            i += 1
        if i - start == 12:
            last = s[start:i].upper()
    return last


def _clean_bt_device_name(raw_name: str) -> str:
    name = (raw_name or "").strip()
    for suffix in (
        " Hands-Free AG Audio",
        " Hands-Free AG",
        " Hands-Free Audio",
        " Hands-Free",
        " Stereo",
        " Avrcp Transport",
        " 免提 AG 音频",
        " 免提",
        " 立体声",
    ):
        if name.lower().endswith(suffix.lower()):
            name = name[: -len(suffix)].strip()
    return name


def _is_generic_bt_service_name(name: str) -> bool:
    low = (name or "").strip().lower()
    if not low:
        return True
    if low in _GENERIC_BT_SERVICE_NAMES:
        return True
    if low.startswith(("microsoft bluetooth", "bluetooth generic", "bluetooth le ", "标准蓝牙")):
        return True
    return False


def _infer_bt_brand_and_kind(name: str, has_audio_profile: bool = False) -> tuple[str, str]:
    low = (name or "").lower()
    brand = "Bluetooth"
    for kw, b in (
        ("ikf", "iKF"),
        ("airpods", "Apple"),
        ("magic keyboard", "Apple"),
        ("magic mouse", "Apple"),
        ("beats", "Apple"),
        ("edifier", "Edifier"),
        ("hecate", "Edifier"),
        ("漫步者", "Edifier"),
        ("moondrop", "MOONDROP"),
        ("水月雨", "MOONDROP"),
        ("sony", "Sony"),
        ("wh-", "Sony"),
        ("wf-", "Sony"),
        ("inzone", "Sony"),
        ("bose", "Bose"),
        ("sennheiser", "Sennheiser"),
        ("momentum", "Sennheiser"),
        ("marshall", "Marshall"),
        ("jbl", "JBL"),
        ("akg", "AKG"),
        ("soundcore", "Anker"),
        ("anker", "Anker"),
        ("shokz", "Shokz"),
        ("openrun", "Shokz"),
        ("audio-technica", "Audio-Technica"),
        ("ath-", "Audio-Technica"),
        ("jabra", "Jabra"),
        ("poly", "Poly"),
        ("epos", "EPOS"),
        ("audeze", "Audeze"),
        ("skullcandy", "Skullcandy"),
        ("xiaomi", "Xiaomi"),
        ("redmi", "Xiaomi"),
        ("huawei", "HUAWEI"),
        ("freebuds", "HUAWEI"),
        ("oppo", "OPPO"),
        ("enco", "OPPO"),
        ("samsung", "Samsung"),
        ("galaxy buds", "Samsung"),
        ("nothing", "Nothing"),
        ("logitech", "Logitech"),
        ("mx master", "Logitech"),
        ("mx anywhere", "Logitech"),
        ("mx keys", "Logitech"),
        ("mx mechanical", "Logitech"),
        ("razer", "Razer"),
        ("steelseries", "SteelSeries"),
        ("arctis", "SteelSeries"),
        ("corsair", "Corsair"),
        ("hyperx", "HyperX"),
        ("rog ", "ASUS ROG"),
        ("asus", "ASUS ROG"),
        ("keychron", "Keychron"),
        ("nuphy", "NuPhy"),
        ("royal kludge", "Royal Kludge"),
        ("rk ", "Royal Kludge"),
        ("rk-", "Royal Kludge"),
        ("akko", "Akko"),
        ("dareu", "DAREU"),
        ("melgeek", "MelGeek"),
        ("lofree", "Lofree"),
        ("wobkey", "WOBKEY"),
        ("cidoo", "CIDOO"),
        ("leobog", "LEOBOG"),
        ("aula", "AULA"),
        ("ajazz", "AJAZZ"),
        ("attack shark", "Attack Shark"),
        ("epomaker", "EPOMAKER"),
        ("cherry", "CHERRY"),
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
    if any(k in low for k in ("airpods", "buds", "wf-", "earbud", "freebuds", "enco", "pods", "tws", "t3", "nano")):
        kind = KIND_EARBUDS
    elif any(
        k in low
        for k in (
            "ikf",
            "headset",
            "headphone",
            "arctis",
            "wh-",
            "cloud",
            "void",
            "hs70",
            "hs80",
            "virtuoso",
            "quantum",
            "blackshark",
            "kraken",
            "barracuda",
            "audio",
            "edifier",
            "hecate",
            "bose",
            "sennheiser",
            "marshall",
            "soundcore",
            "shokz",
            "moondrop",
            "jabra",
            "epos",
            "audeze",
            "skullcandy",
            "耳机",
            "耳麦",
            "max",
        )
    ):
        kind = KIND_HEADSET
    elif any(k in low for k in ("mouse", "master", "anywhere", "viper", "deathadder", "aerox", "鼠标", "dragonfly")):
        kind = KIND_MOUSE
    elif any(
        k in low
        for k in (
            "keyboard",
            "keychron",
            "nuphy",
            "royal kludge",
            "rk ",
            "rk-",
            "azoth",
            "falchion",
            "mx keys",
            "mx mechanical",
            "akko",
            "lofree",
            "melgeek",
            "wobkey",
            "cidoo",
            "leobog",
            "hhkb",
            "niz",
            "键盘",
        )
    ):
        kind = KIND_KEYBOARD
    elif has_audio_profile:
        kind = KIND_HEADSET
    return brand, kind


def aggregate_bluetooth_pnp_nodes(
    raw_nodes: list[dict],
    provider_name: str = "bluetooth",
) -> list[DeviceBattery]:
    """按 12 位蓝牙 MAC 地址聚合同一设备的主节点与 HFP/A2DP/BLE GATT 子节点。

    彻底解决 Windows 上蓝牙耳机（如 iKF、漫步者、Sony 等）电量挂在 HFP 子节点、
    而真实型号名与 IsConnected 挂在 DEV_<MAC> 根节点的漏识别问题。
    """
    groups: dict[str, dict] = {}
    for node in raw_nodes:
        inst_id = str(node.get("instance_id") or "")
        mac = parse_bluetooth_address(inst_id)
        if not mac:
            continue
        grp = groups.setdefault(
            mac,
            {
                "mac": mac,
                "root_name": "",
                "best_name": "",
                "battery": None,
                "root_connected": None,
                "any_connected": False,
                "any_conn_reported": False,
                "has_audio_profile": False,
            },
        )
        inst_up = inst_id.upper()
        is_root = "\\DEV_" in inst_up
        if any(guid in inst_up for guid in ("0000111E-", "0000110B-", "00001108-", "0000111F-")):
            grp["has_audio_profile"] = True

        pct = node.get("battery")
        if pct is not None and 0 <= int(pct) <= 100:
            # 优先保留非 0 的有效读数，或尚未有读数时记录
            if grp["battery"] is None or (grp["battery"] == 0 and int(pct) > 0):
                grp["battery"] = int(pct)

        conn = node.get("is_connected")
        if conn is not None:
            grp["any_conn_reported"] = True
            if bool(conn):
                grp["any_connected"] = True
            if is_root:
                grp["root_connected"] = bool(conn)

        cleaned = _clean_bt_device_name(str(node.get("name") or ""))
        if cleaned and not _is_generic_bt_service_name(cleaned):
            if is_root and not grp["root_name"]:
                grp["root_name"] = cleaned
            if not grp["best_name"]:
                grp["best_name"] = cleaned

    devices: list[DeviceBattery] = []
    seen_ids: set[str] = set()
    for mac, grp in groups.items():
        if grp["battery"] is None:
            continue
        # 若主节点或任一服务节点明确在线则视为在线；若系统未提供 IsConnected 属性默认在线；若全为离线则跳过
        if grp["root_connected"] is True or grp["any_connected"]:
            is_online = True
        elif grp["root_connected"] is False and not grp["any_connected"]:
            is_online = False
        elif grp["any_conn_reported"]:
            is_online = False
        else:
            is_online = True
        if not is_online:
            continue

        name = grp["root_name"] or grp["best_name"]
        if not name:
            continue
        dev_id = f"bt:{mac.lower()}"
        if dev_id in seen_ids:
            continue
        seen_ids.add(dev_id)

        brand, kind = _infer_bt_brand_and_kind(name, has_audio_profile=grp["has_audio_profile"])
        devices.append(
            DeviceBattery(
                device_id=dev_id,
                name=name,
                brand=brand,
                kind=kind,
                connection_mode="蓝牙",
                connected=True,
                online=True,
                asleep=False,
                percent=int(grp["battery"]),
                charging=False,
                support_status=STATUS_PROTOCOL,
                status_detail="Windows 蓝牙电量服务",
                provider_name=provider_name,
            )
        )
    return devices


def query_windows_bluetooth_pnp_batteries(provider_name: str = "bluetooth") -> list[DeviceBattery]:
    """通过 Windows SetupAPI 只读枚举 BTHENUM / BTHLE / BTHLEDEVICE 节点并按蓝牙 MAC 聚合电量。"""
    if sys.platform != "win32":
        return []
    raw_nodes: list[dict] = []
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

                    inst_buf = ctypes.create_unicode_buffer(512)
                    inst_req = wintypes.DWORD(0)
                    if not setupapi.SetupDiGetDeviceInstanceIdW(
                        hdev, ctypes.byref(dev_data), inst_buf, 512, ctypes.byref(inst_req)
                    ):
                        continue
                    inst_id = inst_buf.value.strip()
                    if not inst_id:
                        continue

                    # 1. 读取电量属性（兼容 1 字节 BYTE 与 4 字节小端 UINT32，防止高位非零值截断误报）
                    pct: Optional[int] = None
                    prop_type = wintypes.ULONG(0)
                    bat_buf = (ctypes.c_ubyte * 4)()
                    req_size = wintypes.DWORD(0)
                    if (
                        setupapi.SetupDiGetDevicePropertyW(
                            hdev,
                            ctypes.byref(dev_data),
                            ctypes.byref(_PKEY_BATTERY_LEVEL),
                            ctypes.byref(prop_type),
                            bat_buf,
                            4,
                            ctypes.byref(req_size),
                            0,
                        )
                        and req_size.value >= 1
                    ):
                        if req_size.value >= 4:
                            raw_bat = struct.unpack_from("<I", bytes(bat_buf), 0)[0]
                        elif req_size.value == 2:
                            raw_bat = struct.unpack_from("<H", bytes(bat_buf), 0)[0]
                        else:
                            raw_bat = int(bat_buf[0])
                        if 0 <= raw_bat <= 100:
                            pct = int(raw_bat)

                    # 2. 读取在线状态
                    is_conn: Optional[bool] = None
                    conn_buf = (ctypes.c_ubyte * 4)()
                    conn_type = wintypes.ULONG(0)
                    conn_req = wintypes.DWORD(0)
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
                        is_conn = conn_buf[0] != 0

                    # 3. 读取设备名称（FriendlyName -> DEVPKEY_NAME -> DeviceDesc）
                    name = ""
                    for pkey in (_PKEY_FRIENDLY_NAME, _PKEY_NAME, _PKEY_DEVICE_DESC):
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
                            if cand and not _is_generic_bt_service_name(_clean_bt_device_name(cand)):
                                name = cand
                                break
                            if cand and not name:
                                name = cand

                    raw_nodes.append(
                        {
                            "instance_id": inst_id,
                            "name": name,
                            "battery": pct,
                            "is_connected": is_conn,
                        }
                    )
            finally:
                setupapi.SetupDiDestroyDeviceInfoList(hdev)
    except Exception:
        return []
    return aggregate_bluetooth_pnp_nodes(raw_nodes, provider_name=provider_name)


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
