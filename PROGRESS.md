# PROGRESS.md — BattDock 项目真实开发进度看板

> 最后更新：2026-11-26  
> 当前最新正式版本：**BattDock v2.5.1**（Git 提交 `4e7df67`）  
> 关键历史基线：v1 单设备基线 `8075917` ｜ v2.0 多品牌底层基线 `45e9cd4` ｜ v2.3.0 品牌升级 `7a3bb61` ｜ v2.4.0 图标与更新重构 `7efafee` ｜ v2.5.0 体验升级 `448cd83`

---

## 一、已完成里程碑（切勿重复开发）

### 阶段 1–2：VGN 真机协议与多品牌只读架构（v1.x – v2.0.0）
- [x] `vgn_battery.py`：`VGN Dragonfly F2 Pro Max (3554:FB3E / FB3D)` 17 字节 HID 协议实现与真机回归验证。
- [x] `providers/` 8 大模块化只读适配器 + `DeviceManager`（单次 HID 快照共享、异常隔离、去重、禁止伪造 `0%`、脱敏 JSON 诊断导出）：覆盖 VGN/VXE/ATK/MCHOSE/LAMZU/CompX、Logitech HID++ 2.0 & G 耳机、Razer 91B、SteelSeries、Corsair Bragi/Void、HyperX、ASUS ROG/TUF、Sony INZONE、Windows 标准蓝牙与 Apple AirPods Continuity BLE 解析。
- [x] 开源许可证合规审计记录（`THIRD_PARTY_LICENSES.md`）与 MIT 许可证（`LICENSE`）。

### 阶段 3：现代化双窗口 UI、桌面悬浮窗与零闪烁动效（v2.1.0 – v2.2.0）
- [x] 浅/深/跟随系统双主题双窗口架构（主窗口 `760×480` + 独立设置窗口 `840×742`），脱离 Win11 Acrylic 硬依赖；开机 `--background` 静默驻留托盘。
- [x] 启动与设置窗口零闪烁居中定位（`Opacity=0` 预渲染 + 前端双 `rAF` 显现 + 设置窗口隐藏复用，每次打开默认进入「常规设置」）。
- [x] 支持设备清单重构为设置内独立子页面（14 个独立可折叠中性色品牌列表，面向用户隐藏测试状态词）与全局轻量 Ease-Out 非阻塞动效。
- [x] 原生 WinForms 轻量桌面悬浮窗（`floating_widget.py`）与基于 GitHub Releases 的零依赖在线检查更新（`updater.py`）；仓库 `edwin99701/wireless-peripheral-battery-monitor` 正式公开。

### 阶段 4：BattDock 品牌升级、黑白图标统一与自动更新根治（v2.3.0 – v2.4.0）
- [x] `brand.py` 集中品牌常量，全链路更名至 **BattDock**（`BattDock.exe`、`BattDock.App`、Windows 文件版本属性、新旧配置/自启/互斥量无缝迁移与 `v2.2.0` 升级桥接包）。
- [x] 全新纯黑白圆角主 Logo（`512×512` 透明 PNG + 9 规格 ICO），系统托盘保留状态缓存式动态矢量电池图标。
- [x] `providers/device_naming.py` 官方标准设备名称映射层与简洁中文连接副标题（未知/休眠统一显示 `—`）。
- [x] `device_icons.py` + `assets/icons/*.svg` 全局统一 24×24 黑白实心设备类型图标库（鼠标/耳机/键盘，浅黑深白），覆盖全部 5 大展示位置并保留设置左侧导航图标与主 Logo。
- [x] 桌面悬浮窗精简为「图标 + 品牌名 + 百分比 + 平滑电量条」（支持自定义名、同品牌多设备自动区分与悬停完整详情）。
- [x] 彻底修复跨盘符自动覆盖更新与自动重启（同盘回滚目录 + `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP` + `os._exit(0)`，已在 C→E 盘真实冻结版 `BattDock.exe` 上端到端实测通过）；软件内「关于软件」升级为分层简明更新摘要面板（读取 `update-summary.json`，避免在 Release 正文插入 HTML 注释）。

### 阶段 5：设备管理重构、紧凑提醒弹窗、标准安装程序与 Win10 圆角根治（v2.5.0 – v2.5.1）
- [x] **设备管理重构**：可独立展开/折叠的行式设置卡片 + 左侧六点拖拽手柄（仅多设备显示，单设备隐藏，FLIP 平滑交换并自动同步主窗口与悬浮窗）+ 独立三级数值步进器（黄/橙/红严格递减校验）+ 移除底层协议名显示。
- [x] **设置窗口优化**：最大化/宽屏（`>= 1040px`）内容居中自适应（最大 `860px`），移除设置标题栏「设置」左侧齿轮图标（保留返回箭头与左侧 6 导航图标）。
- [x] **低电量提醒弹窗紧凑化**：按实际字体与文本宽度动态自适应（`250–360 × 56` 逻辑像素，圆角 `8px`），展示完整标准设备名（超长仅裁尾部营销修饰词，支持悬停完整名）与浅/深高对比三级色。
- [x] **Inno Setup 6 标准中文安装程序**：新增 `installer/BattDock.iss`、`installer/ChineseSimplified.isl` 并接入 `build_release.ps1`，支持任意盘符管理员安装 + 目录 `users-modify` 权限授权（保障软件内一键自动更新免 UAC）+ 快捷方式与标准卸载，已实测 `E:\` 顶层目录安装、授权与卸载全链路通过。
- [x] **Windows 10 窗口圆角与 1px 白框根治（v2.5.1）**：禁用 Win10 下 `pywebview` 默认 `shadow=True`（`ExtendFrameIntoClientArea(1,1,1,1)`），显式设置 `DWMNCRP_DISABLED` + 零扩展边距 + 64 位 `HRGN` `SetWindowRgn` + `SizeChanged/Resize/VisibleChanged/DpiChanged` 同步 + Win10 CSS 边框对齐。
- [x] 30/30 单元测试全部通过，全部 5 个 GitHub Release `v2.5.1` 产物上传并完成线上更新与直链 HTTP 200 校验。

---

## 二、当前状态

- **BattDock v2.5.1** 已正式发布至 GitHub Releases（Latest），源码、文档、自动化测试与发布产物全部保持同步。

---

## 三、待真机验证项与已知边界（诚实记录）

1. **Windows 10 22H2 实体机目视复核（v2.5.1）**：本机为 Windows 11 x64，v2.5.1 已通过源码核查 `pywebview` 根因修复 `shadow=is_windows_11()` + `DWMNCRP_DISABLED` + 零扩展边距并通过单元测试与 Win10 模式裁剪验证，仍待用户在 Windows 10 实体机上升级至 `v2.5.1` 后目视确认 1px 白框已彻底消失。
2. **非 VGN 品牌真实硬件实测**：本机仅物理连接 `VGN Dragonfly F2 Pro Max` 且无蓝牙适配器，其余品牌（Logitech / Razer / SteelSeries / Corsair / HyperX / ASUS ROG / Sony INZONE / Apple AirPods / 标准蓝牙）均处于「协议已实现待实测」状态，后续需结合真实硬件或用户导出的脱敏 `diagnostics_*.json` 逐项验证晋升。
3. **可选 BLE 广播被动监听依赖**：Windows 标准 PnP 蓝牙电量已零依赖内置；如需实时被动监听 Apple AirPods Continuity BLE 广播，需在含蓝牙适配器的机器上额外集成 WinRT BLE 依赖（`winrt-Windows.Devices.Bluetooth.Advertisement`、`winrt-Windows.Storage.Streams`）。
4. **雷柏（Rapoo）多代私有协议**：待收集真实 2.4G 设备诊断报文后再补充安全只读实现（严禁盲写）。

---

## 四、后续迭代入口建议

1. 收集用户在 Windows 10 22H2 上升级至 `v2.5.1` 后的窗口四角实测反馈；
2. 结合用户提交的新品牌无线外设 `diagnostics_*.json`，逐步扩充并实机验证 `SUPPORTED_DEVICES.md` 中的设备列表。
