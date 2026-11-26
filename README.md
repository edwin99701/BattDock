<div align="center">

<img src="assets/app_logo.png" width="96" height="96" alt="BattDock Logo" />

# BattDock

**轻量化 Windows 无线外设电量管理工具**

[![Release](https://img.shields.io/github/v/release/edwin99701/wireless-peripheral-battery-monitor?label=Release&style=flat-square&color=111827)](https://github.com/edwin99701/wireless-peripheral-battery-monitor/releases/latest)
[![Windows](https://img.shields.io/badge/Windows-10%20%2F%2011-0078D6?style=flat-square)](https://github.com/edwin99701/wireless-peripheral-battery-monitor/releases/latest)
[![License](https://img.shields.io/github/license/edwin99701/wireless-peripheral-battery-monitor?label=Open%20Source&style=flat-square&color=16A34A)](./LICENSE)
[![Downloads](https://img.shields.io/github/downloads/edwin99701/wireless-peripheral-battery-monitor/total?label=Downloads&style=flat-square&color=2563EB)](https://github.com/edwin99701/wireless-peripheral-battery-monitor/releases)

**简体中文** · [English](./README_EN.md)

<br />

<a href="https://github.com/edwin99701/wireless-peripheral-battery-monitor/releases/latest">
  <img src="https://img.shields.io/badge/%E2%AC%87%20%E4%B8%8B%E8%BD%BD%E6%9C%80%E6%96%B0%E7%89%88%E6%9C%AC-BattDock%20v2.3.0-111827?style=for-the-badge" alt="下载最新版本 BattDock" />
</a>

</div>

---

## 软件简介

**BattDock** 致力于在一处轻量、简洁的界面中统一管理多个品牌无线外设的实时电量，让您无需为了查看电量而同时在后台常驻多套庞大的官方驱动软件。

- **免装第三方驱动**：通过标准 Windows HID 与只读蓝牙系统接口获取电量，绝不安装内核驱动或修改设备 DPI / 灯光 / 固件设置。
- **使用边界说明**：
  - 蓝牙电量读取依赖本机蓝牙适配器及 Windows 蓝牙电量服务（无蓝牙硬件时自动静默跳过，不影响 2.4GHz USB 设备）；
  - 极少数仅通过闭源加密驱动通信的设备无法免驱读取；离线或休眠设备会明确显示「休眠中」或「—」，绝不伪造 `0%` 电量。

---

## Features · 核心功能

| | |
| :--- | :--- |
| **实时电量监控**<br>多品牌无线鼠标、耳机、分体耳塞与键盘统一管理，自动热插拔检测与规范设备命名 | **智能电量提醒**<br>默认 `30% / 20% / 10%` 三级提醒与自定义阈值、滞回防抖、不抢游戏焦点的 5 秒迷你弹窗 |
| **动态托盘电池**<br>系统托盘图标随实际电量填充与低电量色阶联动，仅状态变化时刷新，零冗余后台开销 | **桌面悬浮窗**<br>基于原生 WinForms 的轻量悬浮窗（零额外浏览器内存），支持置顶、透明度、尺寸与位置锁定 |
| **浅色与深色主题**<br>融合 Win11 与 macOS 的简洁设计语言，支持浅色 / 深色 / 跟随系统与轻量平滑动效，原生兼容 Win10/11 | **在线检查与一键更新**<br>内置免 Token GitHub Releases 更新检查、SHA-256 完整性校验与自动覆盖升级，完整保留个人配置 |

---

## 界面截图

> 以下均为 **BattDock v2.3.0** 实际运行截取画面。主窗口深色模式为展示多设备卡片、低电量警示与分体耳塞独立电量的**演示界面**，不代表对应全部外设均已完成实体硬件测试（真实硬件验证状态见下方表格与 [`SUPPORTED_DEVICES.md`](./SUPPORTED_DEVICES.md)）。

<table>
  <tr>
    <td width="50%" align="center">
      <img src="docs/screenshots/main-light.png" alt="BattDock 主窗口浅色模式（本机实机实拍）" /><br />
      <sub><b>主窗口 · 浅色模式</b>（本机 VGN Dragonfly F2 Pro Max 实拍）</sub>
    </td>
    <td width="50%" align="center">
      <img src="docs/screenshots/main-dark.png" alt="BattDock 主窗口深色模式（多设备演示界面）" /><br />
      <sub><b>主窗口 · 深色模式</b>（多设备卡片与分体耳塞演示界面）</sub>
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <img src="docs/screenshots/settings.png" alt="BattDock 设置页面" /><br />
      <sub><b>设置中心</b>（常规 / 设备管理 / 电量提醒 / 外观 / 悬浮窗 / 关于）</sub>
    </td>
    <td width="50%" align="center">
      <img src="docs/screenshots/supported-devices.png" alt="BattDock 支持设备清单" /><br />
      <sub><b>支持设备清单</b>（独立品牌折叠列表、类型筛选与实时搜索）</sub>
    </td>
  </tr>
</table>

<div align="center">
  <img src="docs/screenshots/tray-battery.png" width="640" alt="系统托盘动态电池图标多状态展示" /><br />
  <sub><b>系统托盘动态电池图标</b>（正常 / 充电 / 三级低电量 / 离线休眠）</sub>
  <br /><br />
  <img src="docs/screenshots/floating-widget.png" alt="BattDock 桌面悬浮窗" />
  &nbsp;&nbsp;&nbsp;&nbsp;
  <img src="docs/screenshots/low-battery-alert.png" alt="BattDock 低电量提醒弹窗" /><br />
  <sub><b>桌面悬浮窗</b>（左）与 <b>5 秒不抢焦点低电量迷你弹窗</b>（右）</sub>
</div>

---

## 支持设备概览

完整型号、VID/PID、协议来源及官网核实依据请查阅 [**支持设备清单（SUPPORTED_DEVICES.md）**](./SUPPORTED_DEVICES.md)。

| 品牌 | 覆盖设备类型 | 连接方式 | 当前验证状态 |
| :--- | :--- | :--- | :--- |
| **VGN**（Dragonfly F2 Pro Max） | 无线鼠标 | 2.4GHz 无线连接 / USB 有线连接 | **已实机验证** |
| **VGN / VXE / ATK / MCHOSE / LAMZU** | 无线鼠标 | 2.4GHz 无线连接 / USB 有线连接 | 协议已适配，待实机验证 |
| **Logitech 罗技** | 无线鼠标、键盘、G 系列耳机 | 2.4GHz 无线连接 / 蓝牙连接 / USB 有线连接 | 协议已适配，待实机验证 |
| **Razer 雷蛇** | 无线鼠标、无线键盘 | 2.4GHz 无线连接 / USB 有线连接 | 协议已适配，待实机验证 |
| **SteelSeries 赛睿** | 无线鼠标、Arctis / Nova 耳机与耳塞 | 2.4GHz 无线连接 / USB 有线连接 | 协议已适配，待实机验证 |
| **Corsair 海盗船** | SLIPSTREAM 鼠键、Void / HS / Virtuoso 耳机 | 2.4GHz 无线连接 / USB 有线连接 | 协议已适配，待实机验证 |
| **HyperX** | Cloud 无线耳机、Pulsefire 无线鼠标 | 2.4GHz 无线连接 / USB 有线连接 | 协议已适配，待实机验证 |
| **ASUS ROG / TUF** | 无线鼠标、键盘、Omni 接收器、ROG 耳机 | 2.4GHz 无线连接 / USB 有线连接 | 协议已适配，待实机验证 |
| **Sony 索尼** | INZONE H5 / H9 II / Buds、WH-1000XM5 等 | 2.4GHz 无线连接 / 蓝牙连接 | 协议已适配，待实机验证 |
| **Apple / Beats & 标准蓝牙外设** | AirPods 全系、Beats 及标准蓝牙鼠键耳机 | 蓝牙连接 | 协议已适配，待实机验证 |

> 实际兼容性可能因设备固件版本与连接方式而异；部分旧款雷柏（Rapoo）私有加密协议设备目前暂不支持。

---

## 下载与安装

### 系统要求
- **操作系统**：Windows 10 22H2 x64 及以上 / Windows 11 x64（依赖系统内置 Edge WebView2 运行时，无需安装 Python）。

### 发布产物说明
前往 [GitHub Releases](https://github.com/edwin99701/wireless-peripheral-battery-monitor/releases/latest) 下载：
- **`BattDock-v2.3.0-Windows-x64-Portable.zip`**（**推荐，便携免安装版**）：解压至任意本地目录，双击 `BattDock.exe` 即可运行；如需创建快捷方式，可运行目录内的 `创建桌面与开始菜单快捷方式.bat`。
- **`SHA256SUMS.txt`**：所有发布压缩包的 SHA-256 校验值清单，用于核对文件完整性。
- **`VGNMouseBattery-v2.3.0-win64-UpgradeBridge.zip`**：仅供旧版 `v2.2.0` 软件内一键自动升级平滑迁移使用，新用户无需手动下载。

### 首次启动与在线更新
1. **开机静默自启**：在「设置 → 常规设置」中开启开机自启，默认以 `--background` 静默驻留系统托盘，不弹出窗口。
2. **在线检查与自动升级**：在「设置 → 关于软件」或托盘右键点击「检查更新」；发现新版本后点击「立即更新」即可自动下载、校验 SHA-256 完整性并重启完成升级。
3. **配置保存与卸载**：个人配置保存于 `%LOCALAPPDATA%\BattDock\config.json`（旧版 `VGNMouseBattery` 配置首次启动时自动无损迁移）；如需卸载，运行目录内的 `卸载BattDock.bat` 即可一键清理自启项与快捷方式。

### 常见问题与排查
- **未显示设备或显示 `—`**：请确认 2.4GHz 接收器已插稳或设备未进入深度休眠（晃动鼠标即可自动唤醒并刷新）。
- **在线更新下载缓慢或失败**：软件自动遵循 Windows 系统代理；如网络无法直连 GitHub，可点击更新面板中的「前往下载页」手动下载压缩包覆盖程序目录（个人配置不会丢失）。
- **提交新设备兼容反馈**：点击「设置 → 关于软件 → 导出诊断」生成脱敏 `diagnostics_*.json`，对照设备适配模板提交 Issue 即可。

---

## 开发与贡献

### 本地运行与构建

```powershell
# 1. 安装依赖（Python 3.12+）
pip install -r requirements.txt

# 2. 运行全部单元测试（28 项）
python -m unittest discover -s tests -v

# 3. 源码启动 BattDock
python mouse_battery_app.py

# 4. 一键测试并构建 Windows 便携版与 SHA256SUMS.txt
powershell -ExecutionPolicy Bypass -File .\build_release.ps1
```

### 参与贡献
欢迎提交 Issue 与 Pull Request：
- 遇到问题请使用 [Bug 反馈模板](./.github/ISSUE_TEMPLATE/bug_report.md)；
- 申请适配新外设请使用 [设备适配申请模板](./.github/ISSUE_TEMPLATE/device_support.md)。
- **隐私提醒**：在公开 Issue 中反馈问题时，请**不要**上传包含个人用户名、本地绝对路径、设备序列号或其他敏感信息的完整日志。

---

## 开源许可

本项目代码基于 [**MIT License**](./LICENSE) 开源发布。第三方运行库与公开硬件协议参考的详细许可证合规声明请参阅 [**THIRD_PARTY_LICENSES.md**](./THIRD_PARTY_LICENSES.md)。
