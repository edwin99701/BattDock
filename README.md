# VGN 鼠标电量显示工具

> **项目状态**：活跃开发中（可正常运行）  
> **当前版本**：v6（基于源码 `mouse_battery_app.py` 与已打包 `VGNMouseBattery.exe`）  
> **适用平台**：Windows 10 / Windows 11（推荐 Windows 11 原生 Acrylic 毛玻璃效果）

一款无需安装官方驱动的 VGN / VXE 系列鼠标实时电量监控工具，通过 USB HID 协议直接读取鼠标电量、充电状态与电压，提供 Windows 11 原生毛玻璃主窗口、系统托盘实时数字图标、低电量提醒弹窗及开机自启动功能。

---

## 核心功能

- **免驱动 HID 电量读取**：直接通过 CompX / ATK HID 接口通信（`Usage Page 0xFF02`），内置自动重试、连续 3 次无应答休眠防抖与热插拔容错。
- **多型号兼容**：支持 VGN DragonFly F2 Pro Max / F2 Master+ / F1 Pro / F1 MOBA / Dragonfly 4K、VXE R1 Pro Max / R1 SE+ 等有线与 2.4G 模式（有线直连优先于 2.4G 接收器）。
- **原生毛玻璃主窗口**：基于 `pywebview`（Edge WebView2）与 Windows 11 DWM Acrylic 实现液态玻璃界面，支持位置固定/拖拽、置顶切换与多显示器工作区适配。
- **托盘常驻与静默自启**：支持系统托盘图标显示与快捷菜单，开启开机自启后以 `--background` 参数静默驻留托盘。
- **低电量提醒与单实例保护**：支持自定义低电量阈值（默认 `20%`，`0` 为关闭）弹窗提醒；内置命名互斥量单实例保护，重复启动自动唤起已有窗口。

---

## 运行方式

### 方式一：直接运行已打包版本（推荐日常使用）

双击运行独立打包程序（无需配置 Python 环境）：

```text
release\VGNMouseBattery\VGNMouseBattery.exe
```

- 打包版配置文件保存在：`%LOCALAPPDATA%\VGNMouseBattery\config.json`
- 如需彻底卸载，可运行 `release\VGNMouseBattery\卸载程序.bat`。

### 方式二：通过 Python 源码运行（开发调试）

1. 确认已安装 Python 3.12+ 并安装依赖：
   ```powershell
   pip install -r requirements.txt
   ```
2. 启动应用：
   - **有控制台调试**：
     ```powershell
     python mouse_battery_app.py
     ```
   - **无黑框静默启动**：双击项目根目录下的 `启动鼠标电量监控.vbs`。
   - **静默驻留托盘**：
     ```powershell
     pythonw mouse_battery_app.py --background
     ```

---

## 目录结构

```text
vgn-mouse-battery/
├── mouse_battery_app.py       # 主程序入口：窗口管理、DWM 毛玻璃、托盘、JS 桥接
├── vgn_battery.py             # HID 协议电量读取模块（重试、休眠防抖、型号映射）
├── app_config.py              # 配置持久化与 Windows 开机自启注册表管理
├── config.json                # 源码运行模式下的本地配置文件
├── requirements.txt           # Python 第三方依赖清单
├── 启动鼠标电量监控.vbs        # 无控制台窗口快速启动脚本
├── assets/
│   └── app_icon.ico           # 应用与托盘图标资源
├── ui/
│   ├── index.html             # 主界面前端页面
│   └── alert.html             # 低电量提醒弹窗页面
├── release/
│   └── VGNMouseBattery/       # PyInstaller 打包发布产物与卸载脚本
├── archive/
│   ├── history-backups/       # 历史版本源码/页面备份（.bak）
│   ├── unused-assets/         # 设计对比图等非运行时素材
│   └── temp-cache/            # 历史 __pycache__ 缓存归档
├── README.md                  # 项目说明文档
└── PROJECT.md                 # 项目架构与维护档案
```

---

## 已知问题与注意事项

1. **目录迁移后的开机自启路径**：若此前在旧目录（`e:\反重力\release\...`）开启过「开机自启」，迁移至本目录后请在程序内关闭再重新开启「开机自启」，使注册表项 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\VGNMouseBattery` 更新为新路径。
2. **源码启动脚本 Python 路径**：`启动鼠标电量监控.vbs` 优先查找本机 `Python312\pythonw.exe`，若未找到则回退到系统 PATH 中的 `pythonw.exe`。
3. **尚未初始化 Git 仓库**：当前项目历史版本以 `archive/history-backups/*.bak` 方式保留，建议后续在独立工作区中执行 `git init` 纳入 Git 版本管理。
