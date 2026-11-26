"""应用配置持久化与 Windows 开机自启管理（兼容源码运行与 PyInstaller EXE 打包）。"""

from __future__ import annotations

import json
import os
import sys
import winreg
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

IS_FROZEN = getattr(sys, "frozen", False)

if IS_FROZEN:
    APP_DIR = Path(sys.executable).resolve().parent
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
    _DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(APP_DIR))) / "VGNMouseBattery"
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH = _DATA_DIR / "config.json"
else:
    APP_DIR = Path(__file__).resolve().parent
    RESOURCE_DIR = APP_DIR
    CONFIG_PATH = APP_DIR / "config.json"

APP_SCRIPT = APP_DIR / "mouse_battery_app.py"
RUN_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "VGNMouseBattery"


@dataclass
class AppConfig:
    x: Optional[int] = None
    y: Optional[int] = None
    lock_position: bool = True  # 默认固定在屏幕右下角，不允许拖动；用户可在设置中取消固定
    topmost: bool = False  # 默认关闭窗口置顶，用户可在设置中主动开启
    low_battery_threshold: int = 20  # 0 表示关闭低电量提醒
    poll_interval_sec: int = 30


def load_config() -> AppConfig:
    if not CONFIG_PATH.exists():
        return AppConfig()
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        valid_fields = AppConfig.__dataclass_fields__.keys()
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return AppConfig(**filtered)
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


def _get_autostart_command() -> str:
    if IS_FROZEN:
        return f'"{Path(sys.executable).resolve()}" --background'
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    launcher = str(pythonw) if pythonw.exists() else str(exe)
    return f'"{launcher}" "{APP_SCRIPT}" --background'


def is_autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_REG_PATH, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, RUN_VALUE_NAME)
            val_low = str(val).lower()
            if IS_FROZEN:
                return str(Path(sys.executable).resolve()).lower() in val_low
            return str(APP_SCRIPT).lower() in val_low
    except OSError:
        return False


def set_autostart(enabled: bool) -> bool:
    """开启开机自启时传入 --background，确保开机后静默驻留托盘、无任何弹窗。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, _get_autostart_command())
            else:
                try:
                    winreg.DeleteValue(key, RUN_VALUE_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False
