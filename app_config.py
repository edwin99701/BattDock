"""应用配置持久化、多设备独立偏好与 Windows 开机自启管理（兼容 Win10/11 与 PyInstaller 打包）。"""

from __future__ import annotations

import json
import os
import shutil
import sys
import winreg
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from brand import (
    APP_NAME,
    APP_VERSION,
    CONFIG_DIR_NAME,
    LEGACY_CONFIG_DIR_NAME,
    LEGACY_RUN_VALUE_NAME,
    RUN_REG_PATH,
    RUN_VALUE_NAME,
)

APP_AUTHOR = ""

IS_FROZEN = getattr(sys, "frozen", False)

if IS_FROZEN:
    APP_DIR = Path(sys.executable).resolve().parent
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
    _LOCAL_APP = Path(os.environ.get("LOCALAPPDATA", str(APP_DIR)))
    DATA_DIR = _LOCAL_APP / CONFIG_DIR_NAME
    LEGACY_DATA_DIR = _LOCAL_APP / LEGACY_CONFIG_DIR_NAME
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH = DATA_DIR / "config.json"
    LEGACY_CONFIG_PATH = LEGACY_DATA_DIR / "config.json"
else:
    APP_DIR = Path(__file__).resolve().parent
    RESOURCE_DIR = APP_DIR
    DATA_DIR = APP_DIR
    LEGACY_DATA_DIR = APP_DIR
    CONFIG_PATH = APP_DIR / "config.json"
    LEGACY_CONFIG_PATH = APP_DIR / "config.json"

APP_SCRIPT = APP_DIR / "mouse_battery_app.py"

DEFAULT_ALERT_TIERS: list[int] = [30, 20, 10]


def normalize_tiers(tiers: list[int] | tuple[int, ...] | None) -> list[int]:
    """规范化提醒阈值列表（降序去重，1..95）。"""
    if tiers is None:
        return list(DEFAULT_ALERT_TIERS)
    clean = sorted({int(t) for t in tiers if isinstance(t, (int, float)) and 1 <= int(t) <= 95}, reverse=True)
    return clean


def _default_tier_rules() -> list[dict[str, Any]]:
    return [
        {"id": "tier1", "label": "电量预警（一级）", "threshold": 30, "enabled": True, "color": "yellow"},
        {"id": "tier2", "label": "电量偏低（二级）", "threshold": 20, "enabled": True, "color": "orange"},
        {"id": "tier3", "label": "电量紧急（三级）", "threshold": 10, "enabled": True, "color": "red"},
    ]


@dataclass
class DevicePreference:
    """单台设备的独立偏好配置（优先于全局设置）。"""

    alias: str = ""  # 自定义重命名，空表示使用原设备名
    hidden: bool = False  # 是否在主列表中隐藏
    monitor_enabled: bool = True  # 是否启用监控
    order: int = 1000  # 显示排序权重（越小越靠前）
    custom_tiers_enabled: bool = False  # 是否覆盖全局提醒阈值
    custom_tiers: list[int] = field(default_factory=lambda: [30, 20, 10])


@dataclass
class FloatingWidgetConfig:
    """桌面悬浮窗配置（保留原有功能并增强透明度、尺寸、位置与设备选择）。"""

    enabled: bool = False
    topmost: bool = True
    opacity: int = 92  # 40..100
    size: str = "medium"  # small | medium | large
    position_preset: str = "bottom_right"  # top_left | top_right | bottom_left | bottom_right | custom
    x: Optional[int] = None
    y: Optional[int] = None
    device_id: str = "auto"  # "auto" 表示跟随最优先/最低电量设备
    locked: bool = True


@dataclass
class AppConfig:
    # 窗口位置与尺寸（保留历史字段向后兼容）
    x: Optional[int] = None
    y: Optional[int] = None
    width: int = 760
    height: int = 480
    lock_position: bool = False
    topmost: bool = False

    # 常规设置
    start_minimized_to_tray: bool = True
    close_to_tray: bool = True
    auto_monitor: bool = True
    poll_interval_sec: int = 25
    auto_check_updates: bool = True

    # 电量提醒（全局）
    alerts_master_enabled: bool = True
    tier_rules: list[dict[str, Any]] = field(default_factory=_default_tier_rules)
    custom_alerts_enabled: bool = False
    custom_thresholds: list[int] = field(default_factory=list)
    popup_alert_enabled: bool = True
    windows_notify_enabled: bool = False
    sound_enabled: bool = False
    sound_name: str = "default"  # default | asterisk | exclamation
    repeat_alert_enabled: bool = False
    repeat_interval_min: int = 10

    # 外观设置
    theme: str = "system"  # light | dark | system
    ui_scale: int = 100  # 90 | 100 | 110 | 125
    color_scheme: str = "standard"  # standard | high_contrast | soft
    list_density: str = "comfortable"  # compact | standard | comfortable
    show_progress_bar: bool = True
    show_device_icon: bool = True
    animations_enabled: bool = True  # 界面动画开关（默认开启，并遵循系统动画偏好）

    # 桌面悬浮窗
    floating: dict[str, Any] = field(default_factory=lambda: asdict(FloatingWidgetConfig()))

    # 设备独立偏好（key 为 device_id）
    device_prefs: dict[str, dict[str, Any]] = field(default_factory=dict)

    # 向后兼容旧版配置字段
    low_battery_threshold: int = 20
    selected_device_id: Optional[str] = None
    device_alert_tiers: dict[str, list[int]] = field(default_factory=dict)


def get_floating_config(cfg: AppConfig) -> FloatingWidgetConfig:
    raw = cfg.floating if isinstance(cfg.floating, dict) else {}
    valid = FloatingWidgetConfig.__dataclass_fields__.keys()
    return FloatingWidgetConfig(**{k: v for k, v in raw.items() if k in valid})


def get_device_pref(cfg: AppConfig, device_id: str) -> DevicePreference:
    raw = cfg.device_prefs.get(device_id, {}) if isinstance(cfg.device_prefs, dict) else {}
    valid = DevicePreference.__dataclass_fields__.keys()
    pref = DevicePreference(**{k: v for k, v in raw.items() if k in valid})
    # 向后兼容 v2.0 的 device_alert_tiers
    if not raw and device_id in cfg.device_alert_tiers:
        pref.custom_tiers_enabled = True
        pref.custom_tiers = normalize_tiers(cfg.device_alert_tiers[device_id])
    return pref


def set_device_pref(cfg: AppConfig, device_id: str, updates: dict[str, Any]) -> DevicePreference:
    cur = get_device_pref(cfg, device_id)
    for k, v in updates.items():
        if hasattr(cur, k):
            if k == "custom_tiers":
                setattr(cur, k, normalize_tiers(v))
            elif k == "order":
                setattr(cur, k, int(v))
            elif k in ("hidden", "monitor_enabled", "custom_tiers_enabled"):
                setattr(cur, k, bool(v))
            elif k == "alias":
                setattr(cur, k, str(v).strip()[:48])
            else:
                setattr(cur, k, v)
    cfg.device_prefs[device_id] = asdict(cur)
    return cur


def get_global_active_tiers(cfg: AppConfig) -> list[int]:
    """返回全局生效的所有低电量阈值（降序去重）。"""
    if not cfg.alerts_master_enabled:
        return []
    vals: list[int] = []
    for rule in cfg.tier_rules:
        if isinstance(rule, dict) and rule.get("enabled", True):
            t = rule.get("threshold")
            if isinstance(t, (int, float)) and 1 <= int(t) <= 95:
                vals.append(int(t))
    if cfg.custom_alerts_enabled and isinstance(cfg.custom_thresholds, list):
        for t in cfg.custom_thresholds:
            if isinstance(t, (int, float)) and 1 <= int(t) <= 95:
                vals.append(int(t))
    return normalize_tiers(vals)


def get_device_tiers(cfg: AppConfig, device_id: str) -> list[int]:
    """获取指定设备实际生效的低电量提醒档位（设备独立设置优先于全局设置）。"""
    if not cfg.alerts_master_enabled:
        return []
    if device_id:
        pref = get_device_pref(cfg, device_id)
        if not pref.monitor_enabled:
            return []
        if pref.custom_tiers_enabled:
            return normalize_tiers(pref.custom_tiers)
    return get_global_active_tiers(cfg)


def set_device_tiers(cfg: AppConfig, device_id: str, tiers: list[int]) -> list[int]:
    """设置单台设备独立提醒档位（保留向后兼容签名）。"""
    norm = normalize_tiers(tiers)
    if device_id:
        set_device_pref(cfg, device_id, {"custom_tiers_enabled": True, "custom_tiers": norm})
        cfg.device_alert_tiers[device_id] = norm
    cfg.low_battery_threshold = max(norm) if norm else 0
    return norm


def detect_windows_dark_mode() -> bool:
    """检测 Windows 10/11 系统应用深色模式（AppsUseLightTheme == 0 为深色）。"""
    if sys.platform != "win32":
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            0,
            winreg.KEY_READ,
        ) as key:
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return int(val) == 0
    except OSError:
        return False


def resolve_effective_theme(theme_pref: str) -> str:
    if theme_pref == "dark":
        return "dark"
    if theme_pref == "light":
        return "light"
    return "dark" if detect_windows_dark_mode() else "light"


def detect_windows_animations_enabled() -> bool:
    """读取 Windows 系统动画偏好（SPI_GETCLIENTAREAANIMATION = 0x1042），Win10/11 通用。"""
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        enabled = ctypes.c_int(1)
        if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0):
            return bool(enabled.value)
    except Exception:
        pass
    return True


def resolve_effective_animations(user_enabled: bool) -> bool:
    """结合用户开关与 Windows 系统动画偏好决定最终是否启用界面动画。"""
    return bool(user_enabled) and detect_windows_animations_enabled()


def migrate_legacy_config(
    target_path: Optional[Path] = None,
    legacy_path: Optional[Path] = None,
) -> bool:
    """若新版 BattDock 配置尚不存在且存在旧版 VGNMouseBattery 配置，则无损复制迁移。"""
    dst = target_path or CONFIG_PATH
    src = legacy_path or LEGACY_CONFIG_PATH
    if dst == src or dst.exists() or not src.exists():
        return False
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return True
    except OSError:
        return False


def load_config() -> AppConfig:
    migrate_legacy_config()
    if not CONFIG_PATH.exists():
        return AppConfig()
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        valid_fields = AppConfig.__dataclass_fields__.keys()
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        cfg = AppConfig(**filtered)
        # 校验 tier_rules 完整性
        if not isinstance(cfg.tier_rules, list) or len(cfg.tier_rules) < 3:
            cfg.tier_rules = _default_tier_rules()
        if not isinstance(cfg.device_prefs, dict):
            cfg.device_prefs = {}
        if not isinstance(cfg.floating, dict):
            cfg.floating = asdict(FloatingWidgetConfig())
        # 兼容极早期旧配置（若旧版将宽高写死为 356x580，不覆盖新版默认 760x480）
        if cfg.width < 600:
            cfg.width = 760
        if cfg.height < 400:
            cfg.height = 480
        return cfg
    except Exception:
        return AppConfig()


def save_config(cfg: AppConfig) -> None:
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(asdict(cfg), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def _get_autostart_command(minimized: bool = True) -> str:
    flag = " --background" if minimized else ""
    if IS_FROZEN:
        return f'"{Path(sys.executable).resolve()}"{flag}'
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    launcher = str(pythonw) if pythonw.exists() else str(exe)
    return f'"{launcher}" "{APP_SCRIPT}"{flag}'


def migrate_legacy_autostart(start_minimized: bool = True) -> bool:
    """将旧版 VGNMouseBattery 开机自启项自动迁移至 BattDock 并删除旧键，避免重复自启。"""
    if sys.platform != "win32":
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_REG_PATH, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
            try:
                old_val, _ = winreg.QueryValueEx(key, LEGACY_RUN_VALUE_NAME)
            except FileNotFoundError:
                return False
            use_bg = "--background" in str(old_val).lower() or bool(start_minimized)
            winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, _get_autostart_command(use_bg))
            try:
                winreg.DeleteValue(key, LEGACY_RUN_VALUE_NAME)
            except FileNotFoundError:
                pass
            return True
    except OSError:
        return False


def is_autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_REG_PATH, 0, winreg.KEY_READ) as key:
            for reg_name in (RUN_VALUE_NAME, LEGACY_RUN_VALUE_NAME):
                try:
                    val, _ = winreg.QueryValueEx(key, reg_name)
                except FileNotFoundError:
                    continue
                val_low = str(val).lower()
                if IS_FROZEN:
                    if str(Path(sys.executable).resolve()).lower() in val_low:
                        return True
                    if reg_name == LEGACY_RUN_VALUE_NAME and "vgnmousebattery.exe" in val_low:
                        return True
                elif str(APP_SCRIPT).lower() in val_low:
                    return True
            return False
    except OSError:
        return False


def set_autostart(enabled: bool, start_minimized: bool = True) -> bool:
    """配置 Windows 开机自启（统一写入 BattDock 键并清理旧版 VGNMouseBattery 键，默认 --background 静默启动）。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, _get_autostart_command(start_minimized))
            else:
                try:
                    winreg.DeleteValue(key, RUN_VALUE_NAME)
                except FileNotFoundError:
                    pass
            # 无论开启或关闭，均顺手清理旧版残留注册表项，杜绝重复自启
            try:
                winreg.DeleteValue(key, LEGACY_RUN_VALUE_NAME)
            except FileNotFoundError:
                pass
        return True
    except OSError:
        return False
