"""独立、可维护的设备显示名称规范化与连接状态文案映射层。

设计原则：
1. 保留底层读取的原始设备名称（raw_name），仅对面向用户的标准显示名称进行规范化，
   绝不影响底层 VID/PID 识别、HID/蓝牙通信协议与电量读取。
2. 优先依据精确 (VID, PID) 映射与已核实的固件型号表进行映射，绝不凭模糊子串猜测具体型号，
   严格区分不同型号（例如 Logitech G Pro 2 Lightspeed 与 Logitech G Pro X Superlight 2）。
3. 严禁对任意字符串执行简单 .title()；仅对明确识别的全大写硬件名按词表做自然大小写规范，
   并保留 VGN / VXE / ATK / ASUS / ROG / JBL / HyperX / SteelSeries / AirPods / WH-1000XM5 等官方写法。
4. 记录各品牌官方来源链接，便于在 SUPPORTED_DEVICES.md 中追溯核实依据。
"""

from __future__ import annotations

import re
from typing import Optional

# 各品牌官方产品与支持主页（用于数据库来源记录与核实追溯）
OFFICIAL_BRAND_SOURCES: dict[str, str] = {
    "VGN": "https://www.vgnlab.com/",
    "VXE": "https://www.atk.store/",
    "ATK": "https://www.atk.store/",
    "MCHOSE": "https://www.mchose.store/",
    "LAMZU": "https://lamzu.com/",
    "Rapoo": "https://www.rapoo.com/",
    "Logitech": "https://www.logitechg.com/",
    "Razer": "https://www.razer.com/",
    "SteelSeries": "https://steelseries.com/",
    "Corsair": "https://www.corsair.com/",
    "HyperX": "https://hyperx.com/",
    "ASUS": "https://rog.asus.com/",
    "Sony": "https://www.sony.com/",
    "Apple": "https://www.apple.com/",
    "AULA": "https://www.aulastar.com/",
    "AJAZZ": "https://www.a-jazz.com/",
    "Attack Shark": "https://attackshark.com/",
    "CHERRY": "https://www.cherry.de/",
    "EPOMAKER": "https://epomaker.com/",
    "EWEADN": "https://www.eweadn.com/",
    "Redragon": "https://www.redragonzone.com/",
    "Alienware": "https://www.dell.com/alienware",
    "ASTRO": "https://www.logitechg.com/astro",
    "JBL": "https://www.jbl.com/",
    "EPOS": "https://www.eposaudio.com/",
    "Audeze": "https://www.audeze.com/",
    "AKG": "https://www.akg.com/",
    "Skullcandy": "https://www.skullcandy.com/",
    "FIFINE": "https://fifinemicrophone.com/",
    "Lenovo": "https://www.lenovo.com/",
}

# 1. 精确 (VID, PID) -> 官方规范显示名称（优先级最高）
VID_PID_OFFICIAL_NAMES: dict[tuple[int, int], tuple[str, str]] = {
    # VGN (已实机验证核心型号)
    (0x3554, 0xFB3E): ("VGN Dragonfly F2 Pro Max", "https://www.vgnlab.com/"),
    (0x3554, 0xFB3D): ("VGN Dragonfly F2 Pro Max", "https://www.vgnlab.com/"),
    # Logitech G 无线耳机（修正历史全大写 PRO）
    (0x046D, 0x0A66): ("Logitech G533 Wireless", "https://www.logitechg.com/"),
    (0x046D, 0x0AC4): ("Logitech G535 Lightspeed", "https://www.logitechg.com/"),
    (0x046D, 0x0A5C): ("Logitech G633", "https://www.logitechg.com/"),
    (0x046D, 0x0A89): ("Logitech G635", "https://www.logitechg.com/"),
    (0x046D, 0x0A5B): ("Logitech G933", "https://www.logitechg.com/"),
    (0x046D, 0x0A87): ("Logitech G935", "https://www.logitechg.com/"),
    (0x046D, 0x0AB5): ("Logitech G733 Lightspeed", "https://www.logitechg.com/"),
    (0x046D, 0x0AFE): ("Logitech G733 Lightspeed", "https://www.logitechg.com/"),
    (0x046D, 0x0B1F): ("Logitech G733 Lightspeed", "https://www.logitechg.com/"),
    (0x046D, 0x0AA7): ("Logitech G Pro Wireless Headset", "https://www.logitechg.com/"),
    (0x046D, 0x0AAA): ("Logitech G Pro X Wireless", "https://www.logitechg.com/"),
    (0x046D, 0x0ABA): ("Logitech G Pro X Wireless", "https://www.logitechg.com/"),
    (0x046D, 0x0AFB): ("Logitech G Pro X 2 Lightspeed", "https://www.logitechg.com/"),
    (0x046D, 0x0AFC): ("Logitech G Pro X 2 Lightspeed", "https://www.logitechg.com/"),
    # Logitech 已知有线/直连精确 PID（严格区分 G Pro 2 Lightspeed 与 G Pro X Superlight 2）
    (0x046D, 0xC088): ("Logitech G Pro Wireless", "https://www.logitechg.com/"),
    (0x046D, 0xC094): ("Logitech G Pro X Superlight", "https://www.logitechg.com/"),
    (0x046D, 0xC09B): ("Logitech G Pro X Superlight 2", "https://www.logitechg.com/products/gaming-mice/pro-x2-superlight-wireless-mouse.html"),
    (0x046D, 0xC0A4): ("Logitech G Pro 2 Lightspeed", "https://www.logitechg.com/products/gaming-mice/pro-2-lightspeed.html"),
    # Sony INZONE
    (0x054C, 0x0EBF): ("Sony INZONE H5", "https://www.sony.com/"),
    (0x054C, 0x0FA8): ("Sony INZONE H9 II", "https://www.sony.com/"),
    (0x054C, 0x0EC2): ("Sony INZONE Buds", "https://www.sony.com/"),
}

# 2. 精确原始固件/蓝牙报告名称（去首尾空白并转大写作为精确键，绝不做模糊子串匹配）
EXACT_RAW_NAME_MAP: dict[str, str] = {
    # Logitech HID++ 0x0005 常见官方全大写固件名（严格区分不同型号）
    "PRO 2 LIGHTSPEED": "Logitech G Pro 2 Lightspeed",
    "G PRO 2 LIGHTSPEED": "Logitech G Pro 2 Lightspeed",
    "LOGITECH G PRO 2 LIGHTSPEED": "Logitech G Pro 2 Lightspeed",
    "PRO X SUPERLIGHT 2": "Logitech G Pro X Superlight 2",
    "G PRO X SUPERLIGHT 2": "Logitech G Pro X Superlight 2",
    "LOGITECH G PRO X SUPERLIGHT 2": "Logitech G Pro X Superlight 2",
    "PRO X SUPERLIGHT 2 DEX": "Logitech G Pro X Superlight 2 DEX",
    "PRO X SUPERLIGHT": "Logitech G Pro X Superlight",
    "G PRO X SUPERLIGHT": "Logitech G Pro X Superlight",
    "LOGITECH G PRO X SUPERLIGHT": "Logitech G Pro X Superlight",
    "PRO WIRELESS": "Logitech G Pro Wireless",
    "G PRO WIRELESS": "Logitech G Pro Wireless",
    "G PRO WIRELESS HEADSET": "Logitech G Pro Wireless Headset",
    "LOGITECH G PRO WIRELESS HEADSET": "Logitech G Pro Wireless Headset",
    "LOGITECH G PRO X WIRELESS": "Logitech G Pro X Wireless",
    "LOGITECH G PRO X 2 LIGHTSPEED": "Logitech G Pro X 2 Lightspeed",
    "G502 LIGHTSPEED": "Logitech G502 Lightspeed",
    "G502 X LIGHTSPEED": "Logitech G502 X Lightspeed",
    "G502 X PLUS": "Logitech G502 X Plus",
    "G304": "Logitech G304 Lightspeed",
    "G305": "Logitech G305 Lightspeed",
    "G305 LIGHTSPEED": "Logitech G305 Lightspeed",
    "G309 LIGHTSPEED": "Logitech G309 Lightspeed",
    "G703 LIGHTSPEED": "Logitech G703 Lightspeed",
    "G903 LIGHTSPEED": "Logitech G903 Lightspeed",
    "MX MASTER 3": "Logitech MX Master 3",
    "MX MASTER 3S": "Logitech MX Master 3S",
    "MX MASTER 2S": "Logitech MX Master 2S",
    "MX ANYWHERE 3": "Logitech MX Anywhere 3",
    "MX ANYWHERE 3S": "Logitech MX Anywhere 3S",
    "MX VERTICAL": "Logitech MX Vertical",
    "MX ERGO": "Logitech MX Ergo",
    "MX KEYS": "Logitech MX Keys",
    "MX KEYS S": "Logitech MX Keys S",
    "MX KEYS MINI": "Logitech MX Keys Mini",
    "MX MECHANICAL": "Logitech MX Mechanical",
    "MX MECHANICAL MINI": "Logitech MX Mechanical Mini",
    # Razer 常见全大写硬件字符串
    "RAZER VIPER V3 PRO": "Razer Viper V3 Pro",
    "RAZER VIPER V2 PRO": "Razer Viper V2 Pro",
    "RAZER VIPER ULTIMATE": "Razer Viper Ultimate",
    "RAZER VIPER V3 HYPERSPEED": "Razer Viper V3 HyperSpeed",
    "RAZER DEATHADDER V3 PRO": "Razer DeathAdder V3 Pro",
    "RAZER DEATHADDER V2 PRO": "Razer DeathAdder V2 Pro",
    "RAZER DEATHADDER V3 HYPERSPEED": "Razer DeathAdder V3 HyperSpeed",
    "RAZER BASILISK V3 PRO": "Razer Basilisk V3 Pro",
    "RAZER BASILISK X HYPERSPEED": "Razer Basilisk X HyperSpeed",
    "RAZER BLACKWIDOW V3 PRO": "Razer BlackWidow V3 Pro",
    "RAZER DEATHSTALKER V2 PRO": "Razer DeathStalker V2 Pro",
    # SteelSeries / HyperX / Corsair / Sony / Apple 常见蓝牙/硬件上报名称
    "STEELSERIES ARCTIS NOVA 7": "SteelSeries Arctis Nova 7",
    "STEELSERIES ARCTIS NOVA PRO WIRELESS": "SteelSeries Arctis Nova Pro Wireless",
    "HYPERX CLOUD III WIRELESS": "HyperX Cloud III Wireless",
    "HYPERX CLOUD ALPHA WIRELESS": "HyperX Cloud Alpha Wireless",
    "CORSAIR VIRTUOSO RGB WIRELESS": "Corsair Virtuoso RGB Wireless",
    "WH-1000XM5": "Sony WH-1000XM5",
    "SONY WH-1000XM5": "Sony WH-1000XM5",
    "WH-1000XM4": "Sony WH-1000XM4",
    "WF-1000XM5": "Sony WF-1000XM5",
    "AIRPODS PRO": "Apple AirPods Pro",
    "AIRPODS MAX": "Apple AirPods Max",
}

# 3. 明确词表规范（仅用于处理官方未收录但原始上报为大写的英文词元）
EXACT_TOKEN_CASE: dict[str, str] = {
    # 需保留的官方缩写与品牌大小写
    "VGN": "VGN",
    "VXE": "VXE",
    "ATK": "ATK",
    "ASUS": "ASUS",
    "ROG": "ROG",
    "TUF": "TUF",
    "JBL": "JBL",
    "HYPERX": "HyperX",
    "STEELSERIES": "SteelSeries",
    "AIRPODS": "AirPods",
    "MCHOSE": "MCHOSE",
    "LAMZU": "LAMZU",
    "INZONE": "INZONE",
    "AULA": "AULA",
    "AJAZZ": "AJAZZ",
    "CHERRY": "CHERRY",
    "EPOMAKER": "EPOMAKER",
    "EWEADN": "EWEADN",
    "ASTRO": "ASTRO",
    "EPOS": "EPOS",
    "AKG": "AKG",
    "FIFINE": "FIFINE",
    "OMNISOUND": "OMNISOUND",
    "TKL": "TKL",
    "RGB": "RGB",
    "USB": "USB",
    "USB-C": "USB-C",
    "ANC": "ANC",
    "MX": "MX",
    "SE": "SE",
    "SE+": "SE+",
    "MOBA": "MOBA",
    "DPI": "DPI",
    "DEX": "DEX",
    "OLED": "OLED",
    "II": "II",
    "III": "III",
    "IV": "IV",
    "V2": "V2",
    "V3": "V3",
    "V4": "V4",
    "1K": "1K",
    "2K": "2K",
    "4K": "4K",
    "8K": "8K",
    "35K": "35K",
    "G": "G",
    "X": "X",
    "S": "S",
    "RX": "RX",
    "TX": "TX",
    "KJP": "KJP",
    "EVA": "EVA",
    "EVA-02": "EVA-02",
    # 按规则转为自然首字母大写或特定品牌大小写的词元
    "PRO": "Pro",
    "PRO+": "Pro+",
    "SUPERLIGHT": "Superlight",
    "LIGHTSPEED": "Lightspeed",
    "VIPER": "Viper",
    "DEATHADDER": "DeathAdder",
    "HYPERSPEED": "HyperSpeed",
    "BASILISK": "Basilisk",
    "OROCHI": "Orochi",
    "NAGA": "Naga",
    "COBRA": "Cobra",
    "BLACKWIDOW": "BlackWidow",
    "DEATHSTALKER": "DeathStalker",
    "HYPERPOLLING": "HyperPolling",
    "LOGITECH": "Logitech",
    "RAZER": "Razer",
    "CORSAIR": "Corsair",
    "SONY": "Sony",
    "APPLE": "Apple",
    "RAPOO": "Rapoo",
    "ZAOPIN": "Zaopin",
    "SCYROX": "Scyrox",
    "WIRELESS": "Wireless",
    "WIRED": "Wired",
    "GAMING": "Gaming",
    "MOUSE": "Mouse",
    "HEADSET": "Headset",
    "KEYBOARD": "Keyboard",
    "EARBUDS": "Earbuds",
    "DRAGONFLY": "Dragonfly",
    "ULTIMATE": "Ultimate",
    "ULTRA": "Ultra",
    "ULTRA+": "Ultra+",
    "MASTER": "Master",
    "MASTER+": "Master+",
    "ANYWHERE": "Anywhere",
    "MINI": "Mini",
    "MAX": "Max",
    "PLUS": "Plus",
    "AIR": "Air",
    "CORE": "Core",
    "PRIME": "Prime",
    "ELITE": "Elite",
    "EXTREME": "Extreme",
    "ORIGIN": "Origin",
    "VERTICAL": "Vertical",
    "ERGO": "Ergo",
    "KEYS": "Keys",
    "MECHANICAL": "Mechanical",
    "CLOUD": "Cloud",
    "ALPHA": "Alpha",
    "STINGER": "Stinger",
    "PULSEFIRE": "Pulsefire",
    "HASTE": "Haste",
    "DART": "Dart",
    "VIRTUOSO": "Virtuoso",
    "ARCTIS": "Arctis",
    "NOVA": "Nova",
    "AEROX": "Aerox",
    "RIVAL": "Rival",
    "GAMEBUDS": "GameBuds",
    "SLIPSTREAM": "Slipstream",
    "SPEEDNOVA": "SpeedNova",
    "DARK": "Dark",
    "IRONCLAW": "Ironclaw",
    "HARPOON": "Harpoon",
    "SABRE": "Sabre",
    "SCIMITAR": "Scimitar",
    "NIGHTSABRE": "Nightsabre",
    "DARKSTAR": "Darkstar",
    "KATAR": "Katar",
    "VOID": "Void",
    "CHAKRAM": "Chakram",
    "GLADIUS": "Gladius",
    "AIMPOINT": "AimPoint",
    "HARPE": "Harpe",
    "ACE": "Ace",
    "KERIS": "Keris",
    "SPATHA": "Spatha",
    "PUGIO": "Pugio",
    "STRIX": "Strix",
    "IMPACT": "Impact",
    "CARRY": "Carry",
    "AZOTH": "Azoth",
    "FALCHION": "Falchion",
    "SCOPE": "Scope",
    "MORPH": "Morph",
    "PELTA": "Pelta",
    "DELTA": "Delta",
    "CETRA": "Cetra",
    "OPEN": "Open",
    "PROART": "ProArt",
    "SMARTO": "SmartO",
    "DONGLE": "Dongle",
    "RECEIVER": "Receiver",
}

_MODEL_CODE_RE = re.compile(r"^[A-Z]{1,4}[-]?\d+[A-Z0-9-]*$")


def _looks_all_caps_phrase(text: str) -> bool:
    """判断字符串主体是否为全大写英文（避免误伤已经大小写自然的正常型号名）。"""
    letters = [ch for ch in text if ch.isalpha() and ch.isascii()]
    if len(letters) < 3:
        return False
    upper_cnt = sum(1 for ch in letters if ch.isupper())
    return upper_cnt / len(letters) >= 0.85


def _normalize_token(tok: str, all_caps_mode: bool) -> str:
    if not tok:
        return tok
    upper = tok.upper()
    # 1. 优先命中显式词表（无论整体是否全大写，修正 PRO / SUPERLIGHT / LIGHTSPEED 等已知全大写词）
    if upper in EXACT_TOKEN_CASE:
        # 仅当原始词元为全大写（或已知特殊大小写词）时替换，保留原本合理的写法
        if tok == upper or upper in ("DEATHADDER", "HYPERSPEED", "HYPERX", "STEELSERIES", "AIRPODS", "BLACKWIDOW", "DEATHSTALKER", "AIMPOINT", "GAMEBUDS", "SPEEDNOVA", "PROART", "SMARTO"):
            return EXACT_TOKEN_CASE[upper]
        return tok
    # 2. 保护型号编码（如 WH-1000XM5, G502, MD200, HS70, K70, VT9 等）
    if _MODEL_CODE_RE.match(upper):
        return upper
    # 3. 仅在整段明显为全大写硬件字符串且纯字母长度 >= 4 时，转为自然首字母大写
    if all_caps_mode and tok.isascii() and tok.isalpha() and tok.isupper() and len(tok) >= 4:
        return tok[0].upper() + tok[1:].lower()
    return tok


def normalize_device_display_name(
    raw_name: str,
    vid: Optional[int] = None,
    pid: Optional[int] = None,
    brand: str = "",
) -> str:
    """返回符合官方规范的设备显示名称（无法确认时保留合理原始型号，绝不编造）。"""
    clean_raw = re.sub(r"\s+", " ", (raw_name or "").strip())
    if not clean_raw:
        clean_raw = brand.strip() or "未知设备"

    # 1. 优先依据精确 (VID, PID) 映射
    if vid is not None and pid is not None:
        hit = VID_PID_OFFICIAL_NAMES.get((int(vid), int(pid)))
        if hit:
            return hit[0]

    # 2. 其次依据精确原始型号名映射
    exact = EXACT_RAW_NAME_MAP.get(clean_raw.upper())
    if exact:
        return exact

    # 3. 逐词规范化（不盲目执行 .title()，保留缩写与型号编码）
    all_caps = _looks_all_caps_phrase(clean_raw)
    parts = re.split(r"(\s+|/|\(|\))", clean_raw)
    normalized = "".join(
        _normalize_token(p, all_caps) if p and not p.isspace() and p not in ("/", "(", ")") else p
        for p in parts
    )
    normalized = re.sub(r"\s+", " ", normalized).strip()

    # 4. 清理括号内不规范的英文状态后缀（如 "(Wired)" 改由副标题展示，不混在型号名中）
    normalized = re.sub(r"\s*\(Wired\)\s*$", "", normalized, flags=re.IGNORECASE).strip()

    # 5. 对 Logitech HID++ 无品牌前缀的型号补充规范品牌前缀
    if brand.lower() == "logitech" and not normalized.lower().startswith("logitech"):
        if re.match(r"^(G\d+|MX\b|Pro\b)", normalized, flags=re.IGNORECASE):
            normalized = f"Logitech {normalized}"

    return normalized or clean_raw


def format_connection_mode_cn(connection_mode: str) -> str:
    """将底层连接方式规范为简洁自然的中文连接方式（绝不展示品牌技术词，无法确认则留空）。

    允许输出：
    - 2.4GHz 无线连接（仅当确认使用 2.4GHz 接收器时）
    - 蓝牙连接
    - USB 有线连接
    - 无线连接（通用无线或无法确认频段时）
    - ""（完全无法确认连接方式时，不编造）
    """
    m = (connection_mode or "").strip().lower()
    if not m or m in ("unknown", "none", "n/a"):
        return ""
    if m in ("wired", "usb", "usb wired", "usb-wired", "cable"):
        return "USB 有线连接"
    if m in ("bluetooth", "bt", "ble"):
        return "蓝牙连接"
    if m in ("2.4g", "2.4ghz", "2.4g无线", "dongle", "lightspeed", "hyperspeed", "slipstream", "omni", "speednova", "unifying", "bolt"):
        return "2.4GHz 无线连接"
    if m in ("wireless", "rf"):
        return "无线连接"
    return ""


def format_device_subtitle(
    connection_mode: str,
    connected: bool,
    online: bool,
    asleep: bool,
    charging: bool,
    full: bool,
    percent: Optional[int],
) -> str:
    """生成规范副标题：“连接方式” 或 “连接方式 · 特殊状态”。

    - 正常连接状态不重复添加“已连接”。
    - 无法确认连接方式时省略连接方式，仅在有特殊状态时显示状态。
    """
    conn = format_connection_mode_cn(connection_mode)
    state = ""
    if not connected:
        state = "未连接"
    elif asleep:
        state = "休眠中"
    elif full or (charging and percent is not None and percent >= 100):
        state = "已充满"
    elif charging:
        state = "充电中"
    elif not online and percent is None:
        state = "未连接"

    if conn and state:
        return f"{conn} · {state}"
    return conn or state


_CANONICAL_BRAND_MAP: dict[str, str] = {
    "vgn": "VGN",
    "vxe": "VXE",
    "atk": "ATK",
    "mchose": "MCHOSE",
    "lamzu": "LAMZU",
    "rapoo": "Rapoo",
    "zaopin": "Zaopin",
    "scyrox": "Scyrox",
    "logitech": "Logitech",
    "razer": "Razer",
    "steelseries": "SteelSeries",
    "corsair": "Corsair",
    "hyperx": "HyperX",
    "asus": "ASUS",
    "rog": "ROG",
    "sony": "Sony",
    "apple": "Apple",
    "beats": "Beats",
    "jbl": "JBL",
    "aula": "AULA",
    "ajazz": "AJAZZ",
    "attack shark": "Attack Shark",
    "cherry": "CHERRY",
    "epomaker": "EPOMAKER",
    "eweadn": "EWEADN",
    "redragon": "Redragon",
    "alienware": "Alienware",
    "astro": "ASTRO",
    "epos": "EPOS",
    "audeze": "Audeze",
    "akg": "AKG",
    "skullcandy": "Skullcandy",
    "fifine": "FIFINE",
    "lenovo": "Lenovo",
}

_GENERIC_BRANDS = {"", "generic", "bluetooth", "unknown", "hid", "other", "usb", "标准蓝牙"}


def canonical_brand_name(brand: str, device_name: str = "") -> str:
    """提取官方规范品牌名（无法识别品牌时不编造，返回空字符串）。"""
    b = (brand or "").strip()
    bl = b.lower()
    if bl in _CANONICAL_BRAND_MAP:
        return _CANONICAL_BRAND_MAP[bl]
    if b and bl not in _GENERIC_BRANDS:
        return b
    clean = (device_name or "").strip()
    if clean:
        first = clean.split()[0]
        if first.lower() in _CANONICAL_BRAND_MAP:
            return _CANONICAL_BRAND_MAP[first.lower()]
        if clean.lower().startswith("airpods"):
            return "Apple"
    return ""


def _canonical_icon_group(kind: str) -> str:
    k = (kind or "").strip().lower()
    if k in ("headset", "earbuds"):
        return "headset"
    return k or "other"


def resolve_compact_device_label(
    device,
    all_devices: list,
    custom_label: str = "",
    alias: str = "",
) -> str:
    """生成悬浮窗与提醒弹窗使用的精简品牌标签（默认仅品牌名，同品牌多设备自动补型号，无品牌不编造）。"""
    if (custom_label or "").strip():
        return custom_label.strip()
    if (alias or "").strip():
        return alias.strip()
    if device is None:
        return "未连接外设"

    full_name = (getattr(device, "name", "") or "").strip()
    brand = canonical_brand_name(getattr(device, "brand", ""), full_name)
    if not brand:
        return full_name or "外设"

    my_group = _canonical_icon_group(getattr(device, "kind", ""))
    same_brand_peers = [
        d for d in (all_devices or [])
        if canonical_brand_name(getattr(d, "brand", ""), getattr(d, "name", "")) == brand
        and _canonical_icon_group(getattr(d, "kind", "")) == my_group
    ]
    if len(same_brand_peers) >= 2 and full_name:
        return full_name
    return brand


_ALERT_TRAILING_FLUFF_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\s+Wireless\s+Gaming\s+(?:Mouse|Headset|Keyboard|Earbuds)\s*$", re.IGNORECASE),
    re.compile(r"\s+Wireless\s+Mechanical\s+(?:Gaming\s+)?Keyboard\s*$", re.IGNORECASE),
    re.compile(r"\s+Mechanical\s+Gaming\s+Keyboard\s*$", re.IGNORECASE),
    re.compile(r"\s+Gaming\s+(?:Mouse|Headset|Keyboard|Earbuds)\s*$", re.IGNORECASE),
    re.compile(r"\s+Wireless\s+(?:Mouse|Headset|Keyboard|Earbuds)\s*$", re.IGNORECASE),
    re.compile(r"\s+(?:Special|Collector'?s|Esports|Limited)\s+Edition\s*$", re.IGNORECASE),
    re.compile(r"\s+(?:RGB|2\.4\s*GHz|Bluetooth|Dongle|Receiver|Edition)\s*$", re.IGNORECASE),
    re.compile(r"\s+Wireless\s*$", re.IGNORECASE),
)


def format_alert_device_name(
    device,
    alias: str = "",
    max_chars: int = 34,
) -> tuple[str, str]:
    """为低电量提醒弹窗生成设备名称，返回 (display_name, full_name)。

    规则：
    1. 用户自定义名称（alias）优先级最高。
    2. 优先使用完整标准设备名称（保持自然大小写），绝不直接缩减为单独品牌名。
    3. 仅当名称过长（超过 max_chars）时，优先去除尾部冗余营销修饰词，完整保留品牌、核心系列与型号。
    """
    custom = re.sub(r"\s+", " ", (alias or "").strip())
    if custom:
        full_name = custom
    elif device is not None:
        raw_name = (getattr(device, "name", "") or "").strip()
        vid = getattr(device, "vid", None)
        pid = getattr(device, "pid", None)
        brand = (getattr(device, "brand", "") or "").strip()
        full_name = normalize_device_display_name(raw_name, vid=vid, pid=pid, brand=brand)
    else:
        full_name = "VGN Dragonfly F2 Pro Max"

    if len(full_name) <= max_chars:
        return full_name, full_name

    # 仅移除冗余营销后缀，同时保证至少保留品牌 + 系列/型号（>=2 个词元且不等于纯品牌名）
    brand_only = canonical_brand_name(
        getattr(device, "brand", "") if device is not None else "",
        full_name,
    ).lower()
    trimmed = full_name
    for pat in _ALERT_TRAILING_FLUFF_PATTERNS:
        if len(trimmed) <= max_chars:
            break
        candidate = pat.sub("", trimmed).strip(" -/·")
        if (
            candidate
            and len(candidate.split()) >= 2
            and candidate.lower() != brand_only
        ):
            trimmed = candidate

    return trimmed, full_name
