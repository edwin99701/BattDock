# 通用 Windows 无线外设电量监控工具

> **当前版本**：v2.0（第二阶段：多品牌、多设备统一电量监控）  
> **适用平台**：Windows 10 / Windows 11（x64，推荐 Windows 11 原生 Acrylic 毛玻璃效果）  
> **硬件验证基线**：完整保留并实机回归验证 `VGN Dragonfly F2 Pro Max (3554:FB3E)`

一款轻量、免安装官方驱动的 Windows 无线外设电量监控工具。在原有 VGN 鼠标电量监控工具基础上平滑扩展为**模块化多品牌适配器架构**，支持同时监控多台无线鼠标、无线耳机、分体式耳塞与无线键盘的电量、充电状态与连接状态。

---

## 核心特性

- **原版 VGN 协议 100% 兼容**：完整保留 `vgn_battery.py` 中经过真机验证的 17 字节 HID 查询协议（VID `0x3554`, PID `0xFB3E` / `0xFB3D`，Interface 1，Usage Page `0xFF02`，Usage `0x0002`）。
- **模块化多品牌适配器架构（8 大 Provider）**：
  - `VgnCompxProvider`：VGN / VXE / ATK / CompX / MCHOSE / Rapoo / LAMZU / Zaopin / Scyrox
  - `LogitechHidppProvider`：Logitech 罗技 HID++ 2.0（Unifying / Bolt / Lightspeed 接收器及有线）+ G 系列无线耳机
  - `RazerHidProvider`：Razer 雷蛇 91 字节 Feature Report 无线鼠标与键盘
  - `SteelSeriesHidProvider`：SteelSeries 赛睿 Aerox / Prime / Rival 鼠标 + Arctis / Nova / GameBuds 耳机
  - `CorsairHidProvider`：Corsair 海盗船 SLIPSTREAM Bragi 鼠键 + Void / HS70 无线耳机
  - `HyperXHidProvider`：HyperX Cloud Alpha / II / III / Core / Stinger 耳机 + Pulsefire Haste 2 / Haste / Dart 鼠标
  - `ExtraBrandsProvider`：ASUS ROG / TUF 鼠键与 Omni 接收器、ROG 耳机 + Sony INZONE H5 / H9 II / Buds
  - `BluetoothBatteryProvider`：标准 Windows 蓝牙电量服务（SetupAPI `DEVPKEY_Device_BatteryLevel`）+ Apple AirPods / Beats Continuity BLE 广播解析（支持左耳 / 右耳 / 充电盒独立电量）
- **多设备同时监控与热插拔**：单次共享 HID 快照轮询，异常隔离、智能去重；离线或未响应设备绝不伪造 `0%`，准确显示「休眠中」或「未知 / 未响应」。
- **每设备独立三级低电量提醒**：默认启用 **30% / 20% / 10%** 三级提醒，支持对每台设备分别开关任意档位；内置滞回防抖与充电重置，同一放电周期不重复轰炸。
- **最高置顶极速迷你提醒弹窗**：原生 WinForms 纯色无边框迷你弹窗，0ms 即时弹出、不抢游戏或全屏应用焦点、停留 5 秒自动关闭；托盘右键支持一键「测试低电量弹窗」。
- **设备诊断报告导出**：一键导出脱敏 JSON 诊断文件（不含隐私路径与序列号），便于排查新设备兼容问题。
- **Windows 11 液态玻璃主界面与静默自启**：延续 Liquid Glass 视觉语言，默认固定于右下角（可自由解锁拖拽），开机自启自动以 `--background` 静默驻留系统托盘。

---

## 运行方式

### 方式一：直接运行已打包程序（推荐）

双击运行独立打包程序（无需安装 Python）：

```text
release\VGNMouseBattery\VGNMouseBattery.exe
```

- 配置文件保存位置：`%LOCALAPPDATA%\VGNMouseBattery\config.json`
- 如需彻底卸载（含清理自启项与配置）：运行 `release\VGNMouseBattery\卸载程序.bat`。

### 方式二：源码运行与自动化测试

```powershell
# 安装依赖
pip install -r requirements.txt

# 运行全部协议与状态机单元测试
python -m unittest discover -s tests -v

# 启动主程序（显示窗口）
python mouse_battery_app.py

# 静默驻留系统托盘（无启动弹窗）
pythonw mouse_battery_app.py --background
```

---

## 目录结构

```text
vgn-mouse-battery/
├── mouse_battery_app.py          # 主程序：窗口、DWM 玻璃、托盘、三级提醒状态机、JS 桥接
├── app_config.py                 # 多设备独立阈值持久化与开机自启管理
├── vgn_battery.py                # 原版真机验证的 VGN 17 字节 HID 协议模块（保持零破坏）
├── providers/                    # 模块化品牌协议适配器包
│   ├── base.py                   # DeviceBattery / SubBattery / BatteryProvider 基类与只读 HID 工具
│   ├── manager.py                # DeviceManager 统一设备管理层与诊断导出
│   ├── vgn_provider.py           # VGN / VXE / ATK / CompX / MCHOSE / Rapoo 适配器
│   ├── logitech_hidpp.py         # Logitech HID++ 2.0 & G 耳机适配器
│   ├── razer_hid.py              # Razer 91 字节 Feature Report 适配器
│   ├── steelseries_hid.py        # SteelSeries 鼠标与 Arctis/Nova 耳机适配器
│   ├── corsair_hid.py            # Corsair Bragi 与 Void/HS70 适配器
│   ├── hyperx_hid.py             # HyperX Cloud 耳机与 Pulsefire 鼠标适配器
│   ├── extra_brands.py           # ASUS ROG/TUF 与 Sony INZONE 适配器
│   └── bluetooth_provider.py     # Windows 蓝牙电量服务 + Apple AirPods Continuity 解析器
├── tests/
│   └── test_providers.py         # 21 项协议解析与防抖状态机单元测试
├── ui/
│   └── index.html                # Liquid Glass 多设备主界面
├── release/VGNMouseBattery/      # PyInstaller 打包产物与卸载脚本
├── SUPPORTED_DEVICES.md          # 设备支持清单与验证状态说明
├── CHANGELOG.md                  # 版本更新日志
└── THIRD_PARTY_LICENSES.md       # 开源协议参考与第三方许可证声明
```

---

## 文档导航

- 完整支持设备列表与验证等级（已真机验证 / 协议已实现待实测 / 暂不支持）：见 [`SUPPORTED_DEVICES.md`](./SUPPORTED_DEVICES.md)
- 开源协议合规与许可证声明：见 [`THIRD_PARTY_LICENSES.md`](./THIRD_PARTY_LICENSES.md)
- 变更记录：见 [`CHANGELOG.md`](./CHANGELOG.md)
