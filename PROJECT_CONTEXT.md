# PROJECT_CONTEXT.md — 项目技术上下文与关键决策

> 本文档取代旧版 `PROJECT.md`，作为项目跨会话的唯一技术真值来源。

---

## 一、项目定位与技术栈

- **定位**：轻量、免官方驱动的 Windows 通用多品牌无线外设电量监控工具（由 VGN 单设备版平滑升级而来）。
- **工作区目录**：项目根目录（独立 Git 仓库，分支 `master`）。
- **运行环境**：Windows 10 / 11 x64，Python `3.12+`（本机验证版本 `3.12.10`）。
- **核心依赖**：`hidapi 0.15.0`、`pywebview 6.2.1`（Edge WebView2）、`pystray 0.19.5`、`Pillow 13.0.0`、`pythonnet` / `clr-loader`、`PyInstaller 6.22.3`。
- **本机硬件现状**：物理连接 `VGN Dragonfly F2 Pro Max (VID 0x3554, PID 0xFB3E)`；本机**无蓝牙适配器**（蓝牙模块须在无硬件时静默返回 `[]` 且零报错）。

---

## 二、模块架构

```text
mouse_battery_app.py       主控制器、主窗口(760x480) + 独立设置窗口(840x742)、WinForms 迷你提醒窗、托盘、状态机、JS 桥
floating_widget.py         原生 WinForms 轻量桌面悬浮窗（零 WebView2 开销，Win10/11 通用）与系统提示音
updater.py                 零依赖 GitHub Releases 在线检查更新与 Windows 安全覆盖重启升级模块
app_config.py              配置持久化（AppConfig / DevicePreference / FloatingWidgetConfig）与自启注册表（v2.2.0）
vgn_battery.py             已真机验证的 VGN 17 字节 HID 读取器（保持原样，不破坏）
ui/
  ├── common.css           统一设计令牌与组件样式（浅色/深色/跟随系统、配色方案、步进器、蓝色胶囊开关）
  ├── index.html           主窗口（设备列表、低电量高亮卡片、多电池耳塞三列组合卡片、空状态、底部刷新栏）
  └── settings.html        设置窗口（左 6 分类导航 + 右分组设置卡片：常规/设备管理/电量提醒/外观/悬浮窗/关于）
providers/
  ├── base.py              DeviceBattery / SubBattery / BatteryProvider + 只读 HidP_GetCaps 报表长度检测
  ├── manager.py           DeviceManager（单次 hid.enumerate 共享、异常隔离、去重、禁伪造 0%、脱敏诊断导出）
  ├── vgn_provider.py      VGN（封装 vgn_battery）/ VXE / ATK / CompX / MCHOSE / Rapoo
  ├── logitech_hidpp.py    Logitech HID++ 2.0 (0x1004/0x1000/0x1001/0x1F20 + 0x0005) & G 耳机
  ├── razer_hid.py         Razer 91 字节 Feature Report (0x07/0x80, 0x07/0x84, XOR CRC)
  ├── steelseries_hid.py   SteelSeries Aerox/Prime/Rival 鼠标 & Arctis/Nova/GameBuds 耳机
  ├── corsair_hid.py       Corsair SLIPSTREAM Bragi (FF42:0001) & Void/HS70 耳机
  ├── hyperx_hid.py        HyperX Cloud 耳机 & Pulsefire 鼠标
  ├── extra_brands.py      ASUS ROG/TUF 鼠键/Omni/SpeedNova/耳机 & Sony INZONE H5/H9 II/Buds
  └── bluetooth_provider.py Windows SetupAPI DEVPKEY_Device_BatteryLevel + Apple AirPods Continuity BLE 解析
tests/test_providers.py    26 项单元测试（全协议模拟报文 + 去重 + 禁伪造 0% + 提醒状态机 + 在线更新与安全解压校验）
build_release.ps1          可重复执行的一键测试 + PyInstaller 打包发布脚本
```

---

## 三、已验证核心协议基线（不可破坏）

- **VGN Dragonfly F2 Pro Max**（`vgn_battery.py`）：
  - `VID 0x3554`，`PID 0xFB3E`（2.4G）/ `0xFB3D`（有线），`Interface 1`，`Usage Page 0xFF02`，`Usage 0x0002`
  - 17 字节 HID 报告（Report ID `0x08`），校验和目标 `sum(frame) % 256 == 0x55`
  - 会话查询序列：`0x02(1) -> 0x03(1) -> 0x04 -> 0x02(0)`
  - 解析：`Byte 6` 电量百分比，`Byte 7` 充电/有线状态，`Bytes 8–9` 电压（mV），连续 3 次无应答判休眠

---

## 四、关键技术决策与已攻克的坑

1. **启动与设置窗口零闪烁 + 开机 `--background` 静默无弹窗**：
   - `pywebview` 6.2.1 在 Windows WinForms 上会在网页未加载完时直接 `browser.Show()`（甚至 `hidden=True` 时执行 `browser.Show(); browser.Hide()`），且切 `FormBorderStyle=None` 时会裁掉非客户区宽高导致二次 resize 抖动。
   - **已彻底解决**：通过 `_install_flicker_free_patch()` 在 `BrowserForm.__init__` 末尾先置 `Opacity = 0.0` + 传入匹配主题的 `background_color`，在不可见态完成精确居中尺寸、DWM 装饰、前端 `applyState()` 及双 `requestAnimationFrame` 首帧合成后，由前端 `ui_ready()` 通知后端一次性 `Opacity = 1.0` 原子显现；同时设置窗口关闭改为隐藏复用（仅退出程序时销毁），消除每次点设置的冷启动白屏与闪跳。
2. **禁止创建句柄后修改 `native.ShowInTaskbar`**：
   - 修改 WinForms `ShowInTaskbar` 会触发 `RecreateHandle()` 导致 WebView2 抛出 `E_ABORT` 崩溃；保持默认即可。
3. **Win11 原生毛玻璃参数**：
   - `native.BackColor = Color.Black` + `DwmExtendFrameIntoClientArea(-1)` + `DWMWA_USE_IMMERSIVE_DARK_MODE(20)=1` + `DWMWA_WINDOW_CORNER_PREFERENCE(33)=2` + `DWMWA_BORDER_COLOR(34)=0xFFFFFFFE`（去外描边）+ `DWMWA_SYSTEMBACKDROP_TYPE(38)=3`（Desktop Acrylic）。
4. **低电量迷你弹窗改用原生 WinForms（取代 WebView2 弹窗）**：
   - 原因：WebView2 弹窗存在响应延迟与右键多次触发不稳定问题。
   - 方案：通过 `native_main.BeginInvoke` 在 UI 线程直接创建无边框纯色 WinForms `Form`（`#181B22`，`296×68`，无毛玻璃无描边），加 `WS_EX_TOPMOST | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW` 与 `SW_SHOWNOACTIVATE`，实现 0ms 即时弹出、不抢游戏焦点、5 秒自动关闭。
5. **Flex 布局防挤压**：`ui/index.html` 内所有区块必须保留 `flex-shrink: 0`，避免 `.metrics-strip` 在多区块同时显示时被压缩。
6. **PyInstaller 打包要点**：
   - 必须包含 `--hidden-import pystray._win32 --hidden-import providers --collect-submodules providers --collect-all webview --collect-all clr_loader --collect-all pythonnet`；
   - 替换 `release\VGNMouseBattery\` 前须保留 `卸载程序.bat`；
   - 打包时输出目录 `release/` 已加入 `.gitignore`，不污染 Git 仓库体积。
7. **开源合规决策**：仅参考 MIT 仓库（`qu1ncky/BatteryTray`、`JKWTCN/BatteryMonitor`）的公开报文规范独立实现；未从 GPL-3.0（`Sapd/HeadsetControl`）或无 LICENSE 仓库复制任何代码。
