"""BattDock 品牌常量与版本信息单一真值来源（集中定义，禁止在其他模块重复硬编码）。"""

from __future__ import annotations

APP_NAME = "BattDock"
APP_VERSION = "2.5.1"
APP_VERSION_TUPLE = (2, 5, 1, 0)
APP_DESCRIPTION_ZH = "轻量化 Windows 无线外设电量管理工具"

APP_EXE_NAME = "BattDock.exe"
LEGACY_EXE_NAME = "VGNMouseBattery.exe"

# Windows AppUserModelID（任务栏分组、Alt+Tab 与系统通知来源标识）
APP_USER_MODEL_ID = "BattDock.App"

# 窗口与托盘标题
APP_MAIN_TITLE = APP_NAME
APP_SETTINGS_TITLE = f"{APP_NAME} 设置"
APP_FLOATING_TITLE = f"{APP_NAME} 悬浮窗"
APP_ALERT_TITLE = f"{APP_NAME} 低电量提醒"
APP_TRAY_NAME = APP_NAME

# 配置目录与开机自启注册表项（保留旧版标识用于无缝迁移与防重复）
CONFIG_DIR_NAME = APP_NAME
LEGACY_CONFIG_DIR_NAME = "VGNMouseBattery"

RUN_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = APP_NAME
LEGACY_RUN_VALUE_NAME = "VGNMouseBattery"

# 单实例互斥量与唤醒事件（同时持有新旧标识，彻底避免新旧版本同时运行）
MUTEX_NAME = "Local\\BattDock_SingleInstance"
LEGACY_MUTEX_NAME = "Local\\VGNMouseBatteryMonitor_SingleInstance"
SHOW_EVENT_NAME = "Local\\BattDock_ShowEvent"
LEGACY_SHOW_EVENT_NAME = "Local\\VGNMouseBatteryMonitor_ShowEvent"

# GitHub 公开仓库与 Releases 更新源（保持原仓库地址，确保 v2.2.0 等旧版本在线更新 100% 兼容）
GITHUB_OWNER = "edwin99701"
GITHUB_REPO = "wireless-peripheral-battery-monitor"
GITHUB_REPO_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
RELEASES_PAGE_URL = f"{GITHUB_REPO_URL}/releases"
LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
