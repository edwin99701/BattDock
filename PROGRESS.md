# PROGRESS.md — 项目真实开发进度看板

> 最后更新：2026-11-26  
> 当前版本：v2.1.0 ｜ 升级前单设备基线：`8075917` ｜ v2.0 底层多品牌基线：`45e9cd4`

---

## 一、已完成里程碑（切勿重复开发）

### 第三阶段：现代化双窗口 UI 重构、悬浮窗与 Win10/11 兼容升级（v2.1.0）
- [x] `app_config.py` 扩展：完整常规/提醒/外观/桌面悬浮窗/单设备独立偏好持久化（兼容旧配置，作者 `Ed`）
- [x] `floating_widget.py`：原生 WinForms 轻量桌面悬浮窗（零 WebView2 额外开销，Win10/11 通用）与系统提示音
- [x] `mouse_battery_app.py`：主窗口（`760×480`）+ 独立设置窗口（`840×742`）双窗口管理、单设备独立配置优先、自定义提醒与重复提醒冷却、Windows 系统通知与悬浮窗联动、去除 Win11 专属 Acrylic 硬依赖
- [x] `ui/common.css`、`ui/index.html`、`ui/settings.html`：高度还原两张设计参考图，实现浅/深/跟随系统主题、动态多设备卡片、多电池耳塞三列组合卡片、6 分类完整设置页与内嵌文档预览
- [x] 22 项自动化单元测试全部通过（`tests/test_providers.py`）+ 本机 VGN 真机回归通过
- [x] 实际运行主窗口与设置窗口截取实测图并通过视觉对比验收（已修复「休眠·休眠中」重复文案、步进器紧凑排版与设置窗首屏完整展示）
- [x] 新增可重复打包脚本 `build_release.ps1` 并重新生成 `release\VGNMouseBattery\VGNMouseBattery.exe`
- [x] UI 细节优化与交互修复：主窗口启动/托盘恢复精确工作区居中（误差 `0,0`）、设置窗口以主窗口为基准居中且默认进入「常规设置」、关于页面精简为图标+名称+动态版本号（浅/深双主题验证通过）、23/23 单元测试通过
- [x] 启动与设置窗口零闪烁修复：引入 WinForms `Opacity=0` 预渲染、前端双 `rAF` 就绪后原子显现及设置窗口隐藏复用（15ms 逐帧实测主窗口启动与设置窗口首次/二次打开跳变均为 `0` 次，二次打开 `23ms`）

### 第一阶段：VGN 单设备监控工具（基线 `8075917`）
- [x] VGN Dragonfly F2 Pro Max（`3554:FB3E`）17 字节 HID 协议实现与真机验证（`vgn_battery.py`）
- [x] Windows 11 原生 DWM Acrylic 液态玻璃主窗口与透明矢量电池托盘图标
- [x] 右下角固定定位（可解锁拖拽）、多显示器与 DPI 缩放适配、单实例唤醒事件
- [x] 开机 `--background` 静默驻留托盘（已修复 pywebview 6.2.1 透明隐藏弹窗 Bug）
- [x] 原生 WinForms 极速纯色无边框最高置顶低电量迷你弹窗（5 秒自动关闭、不抢游戏焦点）+ 托盘右键测试
- [x] 独立 PyInstaller 打包（`release\VGNMouseBattery\VGNMouseBattery.exe`）与 `卸载程序.bat`

### 第二阶段：通用多品牌无线外设电量监控升级（v2.0，`45e9cd4`）
- [x] 开源参考仓库 LICENSE 合规审查与协议调研（结果记录于 `THIRD_PARTY_LICENSES.md`）
- [x] 模块化适配器基类与 8 大 Provider 实现（`providers/`）：
  - VGN / VXE / ATK / CompX / MCHOSE / Rapoo
  - Logitech HID++ 2.0 & G 耳机
  - Razer 91 字节 Feature Report 鼠键
  - SteelSeries 鼠标 & Arctis / Nova / GameBuds 耳机
  - Corsair SLIPSTREAM Bragi & Void / HS70 耳机
  - HyperX Cloud 耳机 & Pulsefire 鼠标
  - ASUS ROG / TUF 鼠键 / Omni / SpeedNova / 耳机 & Sony INZONE H5 / H9 II / Buds
  - Windows SetupAPI 标准蓝牙电量服务 + Apple AirPods / Beats Continuity BLE 解析
- [x] `DeviceManager` 统一管理层（单次 HID 快照共享、异常隔离、去重、禁伪造 0%、脱敏 JSON 诊断导出）
- [x] 多设备持久化配置（`app_config.py`）与每设备独立三级低电量提醒状态机（`30% / 20% / 10%` 滞回防抖）
- [x] Liquid Glass 主界面升级（`ui/index.html`：多设备切换胶囊、分体耳塞 L/R/盒独立电量、三级档位多选、导出诊断）
- [x] 21 项自动化单元测试全部通过（`tests/test_providers.py`）
- [x] 本机 VGN Dragonfly F2 Pro Max 真实硬件回归验证通过
- [x] 重建 `release\VGNMouseBattery\VGNMouseBattery.exe` 并完成 `--background` 静默启动冒烟验证（`IsWindowVisible=False`）
- [x] 文档体系建立：`README.md`、`CHANGELOG.md`、`SUPPORTED_DEVICES.md`、`THIRD_PARTY_LICENSES.md`、`AGENTS.md`、`PROJECT_CONTEXT.md`、`PROGRESS.md`

---

## 二、正在进行

- 当前第二阶段核心开发、测试、打包与持久化上下文管理机制已全部收尾，等待用户下一阶段真实外设实测反馈或新需求指示。

---

## 三、尚未完成 / 已知待验证项

1. **非 VGN 品牌真实硬件实测**：当前测试机仅物理连接了 VGN Dragonfly F2 Pro Max 且无蓝牙适配器，其余品牌（Logitech / Razer / SteelSeries / Corsair / HyperX / ASUS ROG / Sony INZONE / AirPods / 标准蓝牙）均处于「协议已实现待实测」状态，需接入对应实机或收集用户导出的 `diagnostics_*.json` 后逐项晋升为「已真实设备验证」。
2. **可选 BLE 广播实时监听依赖**：`BluetoothBatteryProvider` 的 Windows 标准 PnP 蓝牙电量已零依赖内置；如需在带蓝牙适配器的电脑上实时被动监听 Apple AirPods Continuity BLE 广播，可选安装 WinRT Python 绑定（`winrt-Windows.Devices.Bluetooth.Advertisement` 与 `winrt-Windows.Storage.Streams`）或后续打包进独立版本。
3. **雷柏（Rapoo）多代私有协议细化**：待收集真实雷柏 2.4G 设备诊断报告后再补充只读查询协议（严格禁止盲写）。

---

## 四、下一步建议操作

1. 在用户机器上实际运行新版 `release\VGNMouseBattery\VGNMouseBattery.exe`，体验多设备界面、三级提醒档位与「导出诊断」功能；
2. 若接入了罗技、雷蛇、赛睿、海盗船、HyperX、ROG、索尼或蓝牙耳机等其他无线外设，直接运行测试或导出 `diagnostics_*.json`，据此逐台做真机适配微调并更新 `SUPPORTED_DEVICES.md`。
