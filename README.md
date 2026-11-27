<div align="center">

<img src="assets/app_logo.png" width="96" height="96" alt="BattDock Logo" />

# BattDock

**轻量化 Windows 无线外设电量管理工具**

[![Release](https://img.shields.io/github/v/release/edwin99701/BattDock?label=Release&style=flat-square&color=111827)](https://github.com/edwin99701/BattDock/releases/latest)
[![Windows](https://img.shields.io/badge/Windows-10%20%2F%2011-0078D6?style=flat-square)](https://github.com/edwin99701/BattDock/releases/latest)
[![License](https://img.shields.io/github/license/edwin99701/BattDock?label=Open%20Source&style=flat-square&color=16A34A)](./LICENSE)
[![Downloads](https://img.shields.io/github/downloads/edwin99701/BattDock/total?label=Downloads&style=flat-square&color=2563EB)](https://github.com/edwin99701/BattDock/releases)

**简体中文** · [English](./README_EN.md)

<br />

<a href="https://github.com/edwin99701/BattDock/releases/latest">
  <img src="https://img.shields.io/badge/%E2%AC%87%20%E4%B8%8B%E8%BD%BD%E6%9C%80%E6%96%B0%E7%89%88%E6%9C%AC-BattDock%20v2.7.4-111827?style=for-the-badge" alt="下载最新版本 BattDock" />
</a>

</div>

---

## 软件简介

**BattDock** 致力于在一处轻量、简洁的界面中统一管理多个品牌无线外设的实时电量，让您无需为了查看电量而同时在后台常驻多套庞大的官方驱动软件。

- **只读且免装第三方驱动**：通过标准 Windows HID 与只读蓝牙系统接口获取电量，绝不安装内核驱动，绝不修改设备 DPI、回报率、灯光或固件设置。
- **诚实的兼容边界说明**：
  - 蓝牙电量读取依赖本机蓝牙适配器及 Windows 蓝牙电量服务（无蓝牙硬件时自动静默跳过，不影响 2.4GHz USB 设备）；
  - 仅通过闭源加密驱动通信或纯 USB Audio 无 HID 通道的设备无法免驱读取；离线或休眠设备会明确显示「休眠中」或 `—`，绝不伪造 `0%` 电量。

---

## Features · 核心功能

| | |
| :--- | :--- |
| **实时电量监控**<br>统一黑白实心设备类型图标（鼠标 / 耳机 / 键盘），多品牌只读适配、事件驱动热插拔缓存与官方规范型号命名 | **三级低电量提醒**<br>默认 `30% / 20% / 10%` 黄/橙/红分级提醒、单设备独立阈值与不抢游戏焦点的 5 秒紧凑迷你弹窗 |
| **原生 Win32 动态托盘电池**<br>独立原生托盘控制器，动态矢量电池图标随实际电量与色阶联动，支持自愈重连、右键一键切换桌面悬浮窗 | **轻量桌面悬浮窗**<br>原生 WinForms 悬浮窗（零额外 WebView2 开销），默认精简为品牌名 + 悬停完整详情 + 同品牌自动区分，支持自定义名与位置锁定 |
| **Win10 / 11 双主题与任务栏原生切换**<br>浅色 / 深色 / 跟随系统自适应，Win11 原生 DWM 圆角 + Win10 兼容外轮廓圆角，支持任务栏点击切换与轻量平滑动效 | **一键在线更新与自动重启**<br>后台默认国内多节点高速通道优先并静默回退 GitHub，软件内展示简明更新摘要、SHA-256 校验、同盘安全回滚与自动重启升级 |

---

## 界面截图

> 以下为 **BattDock** 实际运行截取画面（主视觉截取自 `v2.4.0`；`v2.5.0–v2.7.4` 在保持相同设计语言的前提下持续优化了设备管理拖拽排序、紧凑独立置顶提醒弹窗、游戏防抢焦点、关于页精简与原生托盘稳定性）。主窗口深色模式为展示统一设备图标、多设备卡片与分体耳塞独立电量的**演示界面**，不代表对应全部外设均已完成实体硬件测试（真实硬件验证状态见下方表格与 [`SUPPORTED_DEVICES.md`](./SUPPORTED_DEVICES.md)）。

<table>
  <tr>
    <td width="50%" align="center">
      <img src="docs/screenshots/main-light.png" alt="BattDock 主窗口浅色模式（本机实机实拍）" /><br />
      <sub><b>主窗口 · 浅色模式</b>（本机 VGN Dragonfly F2 Pro Max 实拍）</sub>
    </td>
    <td width="50%" align="center">
      <img src="docs/screenshots/main-dark.png" alt="BattDock 主窗口深色模式（统一设备图标演示界面）" /><br />
      <sub><b>主窗口 · 深色模式</b>（统一黑白设备图标与多设备演示界面）</sub>
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <img src="docs/screenshots/settings.png" alt="BattDock 设置页面" /><br />
      <sub><b>设置中心</b>（常规 / 设备管理 / 电量提醒 / 外观 / 悬浮窗 / 关于）</sub>
    </td>
    <td width="50%" align="center">
      <img src="docs/screenshots/update-panel.png" alt="BattDock 软件内简明更新界面" /><br />
      <sub><b>软件内在线更新</b>（简明更新摘要、真实下载进度与自动重启升级）</sub>
    </td>
  </tr>
</table>

<div align="center">
  <img src="docs/screenshots/supported-devices.png" width="540" alt="BattDock 支持设备清单" /><br />
  <sub><b>支持设备清单</b>（独立品牌折叠列表、统一设备图标、类型筛选与实时搜索）</sub>
  <br /><br />
  <img src="docs/screenshots/tray-battery.png" width="640" alt="系统托盘动态电池图标多状态展示" /><br />
  <sub><b>系统托盘动态电池图标</b>（正常 / 充电 / 三级低电量 / 离线休眠）</sub>
  <br /><br />
  <img src="docs/screenshots/floating-widget.png" alt="BattDock 桌面悬浮窗" />
  &nbsp;&nbsp;&nbsp;&nbsp;
  <img src="docs/screenshots/low-battery-alert.png" alt="BattDock 低电量提醒弹窗" /><br />
  <sub><b>精简品牌桌面悬浮窗</b>（左）与 <b>统一设备图标三级低电量提醒</b>（右）</sub>
</div>

---

## 支持设备概览

完整型号、VID/PID、协议来源及四级验证状态说明请查阅 [**支持设备清单（SUPPORTED_DEVICES.md）**](./SUPPORTED_DEVICES.md)。

| 品牌 | 覆盖设备类型 | 连接方式 | 实体设备验证状态 |
| :--- | :--- | :--- | :--- |
| **VGN**（Dragonfly F2 Pro Max） | 无线鼠标 | 2.4GHz 无线连接 / USB 有线连接 | **已通过实体设备验证** |
| **VGN / VXE / ATK / MCHOSE / LAMZU** | 无线鼠标、无线键盘、无线耳机（OMNISOUND / X9 / V9 Pro 等） | 2.4GHz 无线连接 / USB 有线连接 | 已实现协议，缺少实体设备验证 |
| **AULA / AJAZZ / Attack Shark / CHERRY / EPOMAKER / Redragon / Alienware / URX** | 2.4GHz / 三模无线键盘（CompX BY / SONiX / Evision / Semico / 荣元 2.4G / URX Core75） | 2.4GHz 无线连接 / USB 有线连接 | 已实现协议，缺少实体设备验证 |
| **Logitech 罗技 / ASTRO** | 无线鼠标、键盘、G 系列与 Centurion / ASTRO A50 / A20 X 无线耳机 | 2.4GHz 无线连接 / 蓝牙连接 / USB 有线连接 | 已实现协议，缺少实体设备验证 |
| **Razer 雷蛇** | 无线鼠标、无线键盘（11 款）、BlackShark / Kraken / Barracuda 无线耳机 | 2.4GHz 无线连接 / USB 有线连接 | 已实现协议，缺少实体设备验证 |
| **SteelSeries 赛睿** | 无线鼠标、Arctis 1/7/9/Pro / Nova 3P/5/7/Pro/Elite 无线耳机与 GameBuds | 2.4GHz 无线连接 / USB 有线连接 | 已实现协议，缺少实体设备验证 |
| **Corsair 海盗船** | SLIPSTREAM 鼠键（含 K70 Core TKL / MAKR 75）、Void / HS70 / HS80 / Virtuoso 耳机 | 2.4GHz 无线连接 / USB 有线连接 | 已实现协议，缺少实体设备验证 |
| **HyperX** | Cloud Alpha / Alpha 2 / II / III / III S / Flight / Stinger 耳机、Pulsefire 鼠标 | 2.4GHz 无线连接 / USB 有线连接 | 已实现协议，缺少实体设备验证 |
| **ASUS ROG / TUF** | 无线鼠标、键盘、Omni 接收器、ROG 耳机 / 耳塞 | 2.4GHz 无线连接 / USB 有线连接 | 已实现协议，缺少实体设备验证 |
| **JBL / EPOS / Audeze / AKG / Skullcandy / Jabra / Poly / Fractal / 水月雨 / Alienware** | Quantum 全系（含 520X）、H3PRO、Maxwell / 2、N9、PLYR、Jabra Link、Poly BT600、Scape、GM01 Pro、AW920H 等 | 2.4GHz 无线连接 / USB 有线连接 | 已实现协议，缺少实体设备验证 |
| **Sony 索尼** | INZONE H5 / H9 II / Buds、PULSE 3D、WH-1000XM5 等 | 2.4GHz 无线连接 / 蓝牙连接 | 已实现协议，缺少实体设备验证 |
| **iKF / 漫步者 / Keychron / NuPhy / Apple & 标准蓝牙 / 标准 HID 通用设备** | iKF / 漫步者 / Bose / Sennheiser / Marshall / Shokz 蓝牙耳机，Keychron / NuPhy / RK / Akko / DAREU / Lofree 蓝牙键盘，Magic Keyboard 及标准 USB HID `0x06:0x20` 通用外设 | 蓝牙连接 / 2.4GHz / USB 标准 HID | 已实现协议，缺少实体设备验证 |

> 实际兼容性可能因设备固件版本与连接方式而异；部分纯 USB Audio 型 2.4G 接收器及旧款雷柏（Rapoo）私有协议鼠标目前暂不支持 2.4G 电量读取。

---

## 下载与安装

### 系统要求
- **操作系统**：Windows 10 22H2 x64 及以上 / Windows 11 x64（依赖系统内置 Edge WebView2 运行时，无需安装 Python）。
- 注：当前已在 Windows 11 x64 完成本机实测；Windows 10 22H2 x64 兼容性已完成代码核查与单元测试，待实体机进一步复核。

### 发布产物说明
前往 [GitHub Releases（最新版本）](https://github.com/edwin99701/BattDock/releases/latest) 下载（国内用户可直接点击下方国内加速直链）：

- **`BattDock-v2.7.4-Setup.exe`**（**推荐，Windows 标准安装程序**）：双击下一步即可安装（支持任意盘符与自定义路径），自动配置目录读写权限、创建桌面与开始菜单快捷方式，支持 Windows「应用与功能」一键标准卸载及后续软件内免 UAC 一键自动更新。
  - 国内高速下载：[国内加速节点 1](https://gh-proxy.org/https://github.com/edwin99701/BattDock/releases/download/v2.7.4/BattDock-v2.7.4-Setup.exe) ｜ [国内加速节点 2](https://ghfast.top/https://github.com/edwin99701/BattDock/releases/download/v2.7.4/BattDock-v2.7.4-Setup.exe)
- **`BattDock-v2.7.4-Windows-x64-Portable.zip`**（**绿色便携版**）：免安装，解压至任意本地目录后双击 `BattDock.exe` 即可运行。
  - 国内高速下载：[国内加速节点 1](https://gh-proxy.org/https://github.com/edwin99701/BattDock/releases/download/v2.7.4/BattDock-v2.7.4-Windows-x64-Portable.zip) ｜ [国内加速节点 2](https://ghfast.top/https://github.com/edwin99701/BattDock/releases/download/v2.7.4/BattDock-v2.7.4-Windows-x64-Portable.zip)
- **`SHA256SUMS.txt`**：所有发布文件的 SHA-256 校验值清单，用于核对文件完整性。
- **`update-summary.json`**：供软件内部直接读取的简明中文更新摘要。
- **`VGNMouseBattery-v2.7.4-win64-UpgradeBridge.zip`**：仅供早期 `v2.2.0` 旧版平滑升级迁移使用，新用户无需手动下载。

### 首次启动与在线更新
1. **开机静默自启**：在安装向导或「设置 → 常规设置」中开启开机自启，默认以 `--background` 静默驻留系统托盘，不弹出窗口。
2. **国内加速自动在线更新**：软件后台默认采用国内多节点加速优先，故障时自动切源并静默回退 GitHub 官方直连；在「设置 → 关于软件」点击「检查更新 → 立即更新」后自动校验 `SHA256SUMS.txt` 完整性、原地替换并在重启后自动恢复系统托盘动态电池图标。
3. **配置保存与卸载**：个人配置保存于 `%LOCALAPPDATA%\BattDock\config.json`（历史旧版配置与自启项在首次启动时自动无损迁移）；安装版可在 Windows「设置 → 应用」中一键卸载，便携版可运行目录内的 `卸载BattDock.bat`。

### 常见问题与排查
- **未显示设备或显示 `—`**：请确认 2.4GHz 接收器已插稳或设备未进入深度休眠（晃动鼠标即可自动唤醒并刷新）。
- **在线更新下载缓慢或失败**：软件自动遵循 Windows 系统代理；若网络无法访问，可点击「前往下载页」手动下载便携包或安装程序覆盖升级（个人配置不会丢失）。
- **提交新设备兼容反馈**：在「设置 → 关于软件」点击「**复制诊断**」或「**导出诊断**」生成脱敏 `diagnostics_*.json`，对照设备适配模板提交 Issue 即可。

---

## 开发与贡献

### 本地运行与构建

```powershell
# 1. 安装依赖（Python 3.12+）
pip install -r requirements.txt

# 2. 运行全部自动化单元测试（47 项）
python -m unittest discover -s tests -v

# 3. 源码启动 BattDock
python mouse_battery_app.py

# 4. 一键测试并构建安装程序、便携版与 SHA256SUMS.txt
powershell -ExecutionPolicy Bypass -File .\build_release.ps1
```

### 项目维护文档
- 长期开发规范：[`AGENTS.md`](./AGENTS.md)
- 技术架构文档：[`PROJECT_CONTEXT.md`](./PROJECT_CONTEXT.md)
- 开发进度看板：[`PROGRESS.md`](./PROGRESS.md)
- 支持设备清单：[`SUPPORTED_DEVICES.md`](./SUPPORTED_DEVICES.md)
- 发布检查清单：[`RELEASE_CHECKLIST.md`](./RELEASE_CHECKLIST.md)
- 版本更新日志：[`CHANGELOG.md`](./CHANGELOG.md)

### 参与贡献
欢迎提交 Issue 与 Pull Request：
- 遇到问题请使用 [Bug 反馈模板](./.github/ISSUE_TEMPLATE/bug_report.md)；
- 申请适配新外设请使用 [设备适配申请模板](./.github/ISSUE_TEMPLATE/device_support.md)。
- **隐私提醒**：在公开 Issue 中反馈问题时，请**不要**上传包含个人用户名、本地绝对路径、设备序列号或其他敏感信息的完整日志。

---

## 开源许可

本项目代码基于 [**MIT License**](./LICENSE) 开源发布。第三方运行库与公开硬件协议参考的详细许可证合规声明请参阅 [**THIRD_PARTY_LICENSES.md**](./THIRD_PARTY_LICENSES.md)。
