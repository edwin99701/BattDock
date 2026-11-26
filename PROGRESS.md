# PROGRESS.md — BattDock 项目真实开发进度看板

> 最后更新：2026-11-27  
> 当前开发版本：**BattDock v2.7.1**（全适配器通信与电量精度修复、迈从耳机与 PULSE 3D 专项加固、关于页精简与托盘悬浮窗开关；本地待验收）  
> 关键历史基线：v1 单设备基线 `8075917` ｜ v2.0 多品牌底层基线 `45e9cd4` ｜ v2.3.0 品牌升级 `7a3bb61` ｜ v2.4.0 图标与更新重构 `7efafee` ｜ v2.5.0 体验升级 `448cd83` ｜ v2.5.1 Win10 圆角修复 `4e7df67` ｜ v2.5.2 稳定性修复 `1432b35` ｜ v2.6.0 无线键鼠耳机扩展 `e20a534` ｜ v2.6.1 国内更新加速 `757abf6` ｜ v2.7.0 蓝牙聚合与标准 HID `8ce3fdb`

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

### 阶段 5：设备管理重构、紧凑提醒弹窗、安装程序、Win10 圆角与稳定性修复（v2.5.0 – v2.5.2）
- [x] **设备管理重构**：可独立展开/折叠的行式设置卡片 + 左侧六点拖拽手柄（仅多设备显示，单设备隐藏，FLIP 平滑交换并自动同步主窗口与悬浮窗）+ 独立三级数值步进器（黄/橙/红严格递减校验）+ 移除底层协议名显示。
- [x] **设置窗口优化**：最大化/宽屏（`>= 1040px`）内容居中自适应（最大 `860px`），移除设置标题栏「设置」左侧齿轮图标（保留返回箭头与左侧 6 导航图标）。
- [x] **低电量提醒弹窗紧凑化**：按实际字体与文本宽度动态自适应（`250–360 × 56` 逻辑像素，圆角 `8px`），展示完整标准设备名（超长仅裁尾部营销修饰词，支持悬停完整名）与浅/深高对比三级色。
- [x] **Inno Setup 6 标准中文安装程序**：新增 `installer/BattDock.iss`、`installer/ChineseSimplified.isl` 并接入 `build_release.ps1`，支持任意盘符管理员安装 + 目录 `users-modify` 权限授权（保障软件内一键自动更新免 UAC）+ 快捷方式与标准卸载，已实测 `E:\` 顶层目录安装、授权与卸载全链路通过。
- [x] **Windows 10 窗口圆角与 1px 白框根治（v2.5.1）**：禁用 Win10 下 `pywebview` 默认 `shadow=True`（`ExtendFrameIntoClientArea(1,1,1,1)`），显式设置 `DWMNCRP_DISABLED` + 零扩展边距 + 64 位 `HRGN` `SetWindowRgn` + `SizeChanged/Resize/VisibleChanged/DpiChanged` 同步 + Win10 CSS 边框对齐。
- [x] **窗口交互状态、任务栏关闭生命周期与 HID 通信稳定性修复（v2.5.2）**：
  - 修复主窗口/设置窗口隐藏再唤出后关闭按钮焦点框与悬停状态残留（`resetInteractionState` + `WM_CANCELMODE`/`WM_MOUSELEAVE` + 标题栏按钮鼠标防驻留焦点，保留 Tab 键盘导航）；
  - 统一拦截 `closing` 事件（右上角关闭 / 任务栏右键关闭 / `Alt+F4` 一致遵循 `close_to_tray`）、补齐最小化还原与销毁安全重建机制、严格防止重复启动后台监控线程；
  - `DeviceManager` 落地 `WM_DEVICECHANGE` 事件驱动 HID 拓扑缓存 + 串行锁 + 轻量内存诊断缓冲；`VgnBatteryReader` 复用共享快照、非阻塞排空并加入休眠阶梯退避（`45s → 90s → 180s`）；33/33 单元测试及 Win11 真机 E2E 回归全部通过。

### 阶段 6：关闭按钮红框残留根治与无线耳机/无线键盘大幅扩展（v2.6.0）
- [x] **根治主窗口重开后关闭按钮红色 `:hover` 残留**：将 2 帧自动撤销改为 `:root.ui-await-pointer` 持久压制（不阻挡点击与键盘导航），直到重开 120ms 后检测到真实位移 >3px 的 `pointermove` 或 `pointerdown` 才解除，同时通过 `EnumChildWindows` 递归向深层 `Chrome_RenderWidgetHostHWND` 发送 `WM_CANCELMODE` / `WM_MOUSELEAVE`，已通过真实 Edge WebView2 DOM 验证。
- [x] **新增无线键盘与无线耳机独立只读适配器**：新增 `providers/wireless_keyboards.py`（CompX BY / SONiX 含 QMK/VIA 隔离 / Evision / Semico / MCHOSE K87 V3 / Alienware / Apple Magic Keyboard，内置 180s 在线节流）与 `providers/wireless_headsets.py`（Razer Audio / Logitech Centurion / ASTRO A50 / JBL Quantum / EPOS / Airoha RACE / C-Media / MCHOSE V9 Pro 2 / VGN OMNISOUND / Lenovo VoIP），并同步升级 Razer、Corsair、SteelSeries、HyperX 现有适配器及设置页支持设备目录；36/36 单元测试通过。

- [x] **新增国内多节点更新加速与故障自动切换（v2.6.1）**：内置 4 个实测可用国内 HTTPS 加速节点，支持并发测速择优、故障无缝切源、纯国内免 `api.github.com` 检查更新、SHA-256 强制校验与设置页自定义 HTTPS 加速前缀；37/37 单元测试通过并已正式发布。

### 阶段 7：iKF 与蓝牙漏识别修复、标准 USB HID 通用电池与耳机/键盘再扩展（v2.7.0）
- [x] **修复 iKF 与 Windows 蓝牙耳机/键盘漏识别**：在 `providers/bluetooth_provider.py` 实现按 12 位蓝牙 MAC 跨节点聚合主节点型号/在线态与 HFP/BLE 子节点电量，自动识别 HFP/A2DP 音频耳机类型并新增 iKF / 漫步者 / 水月雨 / Bose / Sennheiser / Marshall / Soundcore / Shokz / Keychron / NuPhy / RK / Akko / DAREU / MelGeek / Lofree 等 25+ 品牌智能归类。
- [x] **新增标准 USB HID 通用电池兜底适配器（`providers/standard_hid.py`）**：零写操作只读读取 USB HID `Battery Strength (0x06:0x20)` 特征报告，广谱覆盖所有遵循标准 HID 电量规范的无线耳机、键盘与鼠标。
- [x] **继续扩充无线耳机与无线键盘品牌协议**：新增 Alienware AW920H、Poly Voyager (BT600)、Jabra Link 380/390/Evolve2/3、Fractal Design Scape、MOONDROP 水月雨 GM01 Pro、Sony PULSE 3D、JBL Quantum 520X 无线耳机以及荣元（Rongyuan）2.4G 键盘接收器平台（80+ PID）与 URX Core75 无线键盘；全量 38/38 单元测试通过。

### 阶段 8：全适配器通信与取整精度修复、关于页精简与托盘悬浮窗开关（v2.7.1）
- [x] **VGN 实机原始报文核查与全适配器取整精度修复**：实测确认 `VGN Dragonfly F2 Pro Max (3554:FB3E)` 固件原生按 5% 步进上报 `Byte[6]`，保持原样透传；全量修复 Corsair Bragi 千分比四舍五入、HyperX Stinger Core 与 ASUS ROG Strix Go 2.4 电压分段线性插值、Poly BT600 四舍五入、Razer/`standard_hid` `raw=1` 保底 `1%` 及 `base.py` 统一标准半入整舍入。
- [x] **迈从耳机识别与全部 11 个适配器通信/休眠占位加固**：补齐 `output_report_id` 只读检测与自动前导 `0x00` 补齐、多集合聚合防锁死、空包过滤、VID `0x3837/0x291D` 迈从耳机受控通用探测（严禁触碰鼠键标准输入集合 `0x01`）、Airoha RACE / Alienware AW920H 控制管道 `HidD_GetInputReport(0x07)` + Audeze Maxwell 有线 `0x4B1A`、Poly BT600 定长补齐与 Hello ACK 握手、`Sony PULSE 3D` 常驻只读句柄全生命周期释放（拔出/异常/`WM_DEVICECHANGE`/`WM_POWERBROADCAST` 休眠唤醒/退出）、`standard_hid.py` 按精确 `(vid, pid)` 跳过专用适配器在线及休眠占位防重复卡片、蓝牙 SetupAPI 兼容 4 字节 `UINT32` 电量属性。
- [x] **关于页精简与「复制诊断」**：移除「更新下载线路」与自定义前缀（后台默认国内高速通道优先并静默回退 GitHub，自动兼容老配置）、移除检查更新时间戳、「GitHub 仓库」改为黑白单色图标 +「项目主页」、底部并排新增轻量「复制诊断」按钮（原生 Win32 剪贴板写入）。
- [x] **系统托盘右键菜单补充**：在「打开 BattDock」下方、「设置」上方新增原生勾选菜单项「显示桌面悬浮窗」，与设置页双向同步并持久化。

---

## 二、当前状态

- **BattDock v2.7.1** 已完成全部代码改动、文档同步、39/39 自动化单元测试与本地安装包/便携包构建，待用户本地实测验收后再推送 GitHub Release。

---

## 三、待真机验证项与已知边界（诚实记录）

1. **鼠标偶发卡顿与 BattDock 的因果归属尚未最终定论**：自动化对照测试期间鼠标处于静止态（未采集到人工连续移动时的 Raw Input 异常抖动），未能直接复现用户反馈的偶发鼠标卡顿；本次已针对实测暴露的每 25 秒全量 `hid.enumerate(0, 0)`（46–83ms）、休眠态 ~765ms 阻塞查询及无锁并发轮询完成了优化，仍需用户升级至 `v2.5.2` 后在日常连续移动/高回报率场景下观察反馈。
2. **Windows 10 22H2 实体机目视复核**：本机为 Windows 11 x64，v2.5.1/v2.5.2 的 Win10 圆角及窗口关闭/唤出逻辑已通过源码核查、单元测试与 Win11 真机回归，仍待在 Windows 10 22H2 实体机上复核。
3. **非 VGN 品牌真实硬件实测**：本机仅物理连接 `VGN Dragonfly F2 Pro Max` 且无蓝牙适配器，其余品牌（Logitech / Razer / SteelSeries / Corsair / HyperX / ASUS ROG / Sony INZONE / Apple AirPods / 标准蓝牙）均处于「协议已实现待实测」状态，后续需结合真实硬件或用户导出的脱敏 `diagnostics_*.json` 逐项验证晋升。
4. **可选 BLE 广播被动监听依赖**：Windows 标准 PnP 蓝牙电量已零依赖内置；如需实时被动监听 Apple AirPods Continuity BLE 广播，需在含蓝牙适配器的机器上额外集成 WinRT BLE 依赖（`winrt-Windows.Devices.Bluetooth.Advertisement`、`winrt-Windows.Storage.Streams`）。
5. **雷柏（Rapoo）多代私有协议**：待收集真实 2.4G 设备诊断报文后再补充安全只读实现（严禁盲写）。

---

## 四、待做事项与后续迭代计划

1. **收集 iKF 2.4G 纯音频接收器脱敏诊断报告**：若用户使用不暴露标准 HID `0x06:0x20` 的特定 iKF 2.4G 接收器（如部分 Megawin `0E6A:0110` 型号），欢迎通过「设置 → 关于软件 → 导出诊断」提交 `diagnostics_*.json` 以便后续研究是否存在公开安全的只读接口（当前推荐使用蓝牙模式读取电量）。
2. **收集用户升级至 `v2.7.0` 后的多品牌真机反馈**：持续跟进 iKF / 漫步者 / Keychron / NuPhy / 荣元 2.4G / 新耳机与键盘品牌实测反馈，以及国内更新加速、日常高频移动鼠标场景与 Windows 10 22H2 实体机目视复核。
3. **持续补充新品牌只读协议**：结合社区提交的脱敏 `diagnostics_*.json` 与 MIT 开源协议资料，逐步扩充并实机验证 `SUPPORTED_DEVICES.md` 中的设备列表（含雷柏 2.4G 私有协议调研）。
