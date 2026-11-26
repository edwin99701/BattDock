# PROJECT_CONTEXT.md — 项目技术上下文与关键决策

> 本文档取代旧版 `PROJECT.md`，作为项目跨会话的唯一技术真值来源。

---

## 一、项目定位与技术栈

- **定位**：轻量、免官方驱动的 Windows 通用多品牌无线外设电量监控工具（由 VGN 单设备版平滑升级而来）。
- **工作区目录**：`e:\反重力\vgn-mouse-battery`（独立 Git 仓库，分支 `master`）。
- **运行环境**：Windows 11 x64（Build 26200），Python `3.12.10`（`C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe`）。
- **核心依赖**：`hidapi 0.15.0`、`pywebview 6.2.1`（Edge WebView2）、`pystray 0.19.5`、`Pillow 13.0.0`、`pythonnet` / `clr-loader`、`PyInstaller 6.22.3`。
- **本机硬件现状**：物理连接 `VGN Dragonfly F2 Pro Max (VID 0x3554, PID 0xFB3E)`；本机**无蓝牙适配器**（蓝牙模块须在无硬件时静默返回 `[]` 且零报错）。

---

## 二、模块架构

```text
mouse_battery_app.py       主控制器、Win11 DWM 毛玻璃、WinForms 极速迷你弹窗、托盘、三级防抖状态机、JS 桥
app_config.py              配置持久化（源码: config.json；打包: %LOCALAPPDATA%\VGNMouseBattery\config.json）与自启注册表
vgn_battery.py             已真机验证的 VGN 17 字节 HID 读取器（保持原样，不破坏）
ui/index.html              Liquid Glass 多设备前端（多设备切换胶囊、分体耳塞 L/R/盒电量、每设备三级档位、诊断导出）
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
tests/test_providers.py    21 项单元测试（全协议模拟报文 + 去重 + 禁伪造 0% + 三级防抖状态机）
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

1. **开机 `--background` 静默无弹窗（pywebview 6.2.1 Bug 规避）**：
   - `pywebview` 在 `transparent=True` 且 `hidden=True` 时，导航完成回调 `EdgeChrome.on_navigation_start` 会强行调用 `form.Show()`。
   - **已解决**：启动参数含 `--background` 时，对 `edgechromium.EdgeChrome.on_navigation_start` 打补丁跳过隐藏态 `Show()`；实测进程存活且 `IsWindowVisible == False`。
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
