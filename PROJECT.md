# PROJECT.md — VGN 鼠标电量显示工具（v1.x 历史归档）

> **说明**：本项目已正式升级并定名为 **BattDock**（标准本地目录 `BattDock`，原目录 `vgn-mouse-battery`）。最新架构、长期规范与开发进度请统一查阅 [`AGENTS.md`](./AGENTS.md)、[`PROJECT_CONTEXT.md`](./PROJECT_CONTEXT.md) 与 [`PROGRESS.md`](./PROGRESS.md)。本文件仅作为 v1.x 历史存档保留，不再更新。

## 基本信息

| 字段 | 说明 |
| :--- | :--- |
| **项目名称** | VGN 鼠标电量显示工具（VGNMouseBattery） |
| **目录路径** | 项目根目录（`vgn-mouse-battery`） |
| **开发状态** | 活跃开发中（Active） |
| **当前版本** | v6（以 `archive/history-backups/*.v5.bak` 之后的当前源码与 `release/VGNMouseBattery/VGNMouseBattery.exe` 为准） |
| **版本控制** | 暂无 `.git` 仓库（已配置 `.gitignore`，历史版本归档于 `archive/history-backups/`） |
| **目标平台** | Windows 10 / Windows 11（x64） |
| **独立工作区** | 支持直接作为独立工作区打开并独立创建 AI 对话 |

---

## 项目用途

在无需运行 VGN / ATK 官方后台驱动的前提下，实时监控 VGN / VXE 系列无线/有线鼠标的电池百分比、充电状态与连接模式（2.4G / 有线），通过轻量化的桌面毛玻璃面板与系统托盘图标展示电量，并在电量低于设定阈值时触发桌面提醒。

---

## 技术架构

### 技术栈
- **后端语言**：Python 3.12（本机已验证 `Python 3.12.10`）
- **硬件通信**：`hidapi >= 0.14.0`（通过 `hid` 模块直接收发 17 字节 HID 报告）
- **桌面界面**：`pywebview >= 5.0`（Edge WebView2 / `edgechromium` 渲染后端）+ 原生 HTML/CSS/JS
- **系统托盘与图标**：`pystray >= 0.19.5` + `Pillow >= 10.0.0`
- **系统原生能力**：`ctypes` / `winreg` 调用 Win32 API（DPI 感知、DWM 毛玻璃、单实例互斥量、跨实例唤醒事件、多显示器工作区查询、开机自启注册表）
- **打包方式**：PyInstaller 目录模式（`release/VGNMouseBattery/VGNMouseBattery.exe` + `_internal/`）

### 模块划分
- `vgn_battery.py`：`VgnBatteryReader` 线程安全 HID 读取器，封装帧构造（`_make_frame`）、校验和验证（`CHECKSUM_TARGET = 0x55`）、设备列表 `KNOWN_DEVICES` 及连续 3 次无应答的休眠防抖逻辑。
- `app_config.py`：`AppConfig` 数据类与 JSON 持久化。自动区分源码模式（读取同目录 `config.json`）与冻结打包模式（读取 `%LOCALAPPDATA%\VGNMouseBattery\config.json`），并管理 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 自启键。
- `mouse_battery_app.py`：主应用控制器 `MouseBatteryApp` 与前端 JS 接口桥 `_JsApi`，负责轮询调度、托盘动态数字图标绘制、主窗口与低电量提醒窗口生命周期及单实例唤醒。
- `ui/index.html`、`ui/alert.html`：透明液态玻璃风格主面板与低电量提醒浮窗。
- `assets/app_icon.ico`：运行时应用与托盘基础图标。

---

## 运行与打包方式

1. **直接运行打包版**：运行 `release\VGNMouseBattery\VGNMouseBattery.exe`。
2. **源码运行**：
   ```powershell
   pip install -r requirements.txt
   python mouse_battery_app.py
   ```
3. **无控制台启动**：双击 `启动鼠标电量监控.vbs`（使用相对脚本目录自动定位 `mouse_battery_app.py`）。

---

## 已知问题与待办

- **旧路径自启项与运行中进程**：若此前从旧目录运行过 `release\VGNMouseBattery\VGNMouseBattery.exe`，退出旧进程并改从新路径启动后，请重新切换一次「开机自启」以更新注册表路径。
- **缺乏 Git 历史管理**：目前尚未初始化 Git 仓库，迭代依赖手动 `.bak` 备份；建议后续开发前执行 `git init` 建立规范提交历史。
- **新增鼠标型号需手动补充 PID**：未列入 `KNOWN_DEVICES` 的 VGN/VXE 新型号需要补充对应的 `(VID, PID)` 映射。
- **缺少自动化单元测试**：目前无 `tests/` 目录，HID 协议解析与配置读写尚未建立自动化回归测试。

---

## 整理记录（2026-11-25）

- 从原根目录完整迁移至独立项目目录 `vgn-mouse-battery/`。
- 保留全部源码、运行配置、前端页面、图标与打包产物，未修改任何业务代码。
- 12 个历史 `.bak` 备份文件归档至 `archive/history-backups/`；未被引用的设计对比图 `tray_icon_compare.png` 归档至 `archive/unused-assets/`；历史 `__pycache__` 归档至 `archive/temp-cache/`。
