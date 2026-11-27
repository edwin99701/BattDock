# 更新日志（CHANGELOG）

> 本文件完整保留 BattDock（含早期历史版本）的真实发布记录，不篡改历史事实。后续新版本统一按「新增功能 / 功能优化 / Bug 修复 / 兼容性改进 / 已知问题」分类记录。

## BattDock v2.7.4（2026-11-27）— 游戏场景防白屏与防抢焦点加固、低电量提醒独立置顶优化及仓库地址统一

### Bug 修复
- **修复 WinForms `Opacity` 动画抹除 `WS_EX_NOACTIVATE` / `WS_EX_TOOLWINDOW` 缺陷（`floating_widget.py`、`mouse_battery_app.py`）**：改用原生 Win32 `SetWindowLongW` + `SetLayeredWindowAttributes` + `SetWindowPos(SWP_NOACTIVATE | SWP_NOOWNERZORDER)` 管理低电量提醒弹窗与桌面悬浮窗的透明度和淡入淡出动画，彻底防止 WinForms `Form.Opacity` / `Form.TopMost` 触发 `UpdateStyles()` 清除不抢焦点和工具窗扩展样式，杜绝游戏场景误抢焦点与混入 Alt+Tab 列表。
- **修复桌面悬浮窗每 25 秒无条件刷新与 GDI 字体持续新建问题（`floating_widget.py`）**：为悬浮窗补充 `WS_EX_NOACTIVATE`，新增布局/样式/文案状态签名差异检查（无变化轮询零 Win32/DWM 扰动与零重绘），缓存并复用 `Font` 对象并在关闭时统一释放。
- **消除隐藏窗口多余后台刷新与显示变更重绘（`mouse_battery_app.py`、`tray_icon.py`）**：后台定时轮询不再向已隐藏的 WebView2 主/设置窗口注入 JS；Win10 圆角重算钩子跳过不可见或最小化窗口；托盘与热插拔原生隐藏消息窗口补齐 `WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE`。

### 功能优化与兼容性改进
- **低电量提醒窗口独立最高优先级与防打扰机制（`mouse_battery_app.py`、`floating_widget.py`）**：提醒窗口设为独立非模态顶层窗（`Owner=None`），通过 `SWP_NOOWNERZORDER | SWP_NOACTIVATE` 单独提升显示优先级（不连带主窗口、设置窗口或悬浮窗置顶，不改变 `GetForegroundWindow()`），关闭前显式降级释放置顶状态；基于 `SHQueryUserNotificationState` 仅在 Direct3D 独占全屏游戏（`QUNS_RUNNING_D3D_FULL_SCREEN`）下静默避让悬浮窗并暂缓低电量弹窗（不消耗档位，退出全屏后补提醒），无边框窗口与普通窗口模式正常兼容。
- **统一 GitHub 新仓库地址与在线更新验证（`brand.py`、`installer/BattDock.iss`）**：未来版本更新源统一指向 `edwin99701/BattDock`，实网验证旧版本直连与 4 个国内加速节点通过 301 重定向继续兼容；新增 4 组窗口焦点、独立置顶与全屏防干扰自动化回归测试（全量 47/47 项通过）。

---

## BattDock v2.7.3（2026-11-27）— 彻底修复系统托盘动态电池图标消失回归并建立长期回归保护机制

### 系统托盘核心功能根治修复
- **自研独立原生 Win32 动态电池托盘控制器（`tray_icon.py`、`mouse_battery_app.py`）**：
  - 排查定位旧版 `pystray 0.19.5` 导致托盘动态电池图标消失的四项根因（无线程锁 `HICON`/`HMENU` 竞态、忽略 `Shell_NotifyIcon(NIM_ADD)` 返回值且永不重试、`ChangeWindowMessageFilterEx` 权限失败崩溃以及自动更新 `os._exit(0)` 前未同步执行 `NIM_DELETE`）；
  - 改用独立顶层隐藏消息窗口与 `RLock` 线程安全架构，与主窗口/设置窗口生命周期彻底解耦（关闭、隐藏、最小化、恢复及监控暂停/恢复均不影响托盘图标），完整保留原有动态矢量电池图标与三级电量颜色映射；
  - 纯内存 32 位 ARGB `HICON` 生成（零磁盘临时文件、先新后旧原子替换），补齐 `NIM_ADD` 退避重试、`NIM_MODIFY` 失败自动补注册、`WM_TASKBARCREATED`/`WM_DISPLAYCHANGE` 自愈、右键现场实时勾选菜单及退出同步 `NIM_DELETE`；显式保持 `uID=0` 兼容既有 Windows 11 托盘置顶偏好（`IsPromoted=1`），并在诊断报告中新增 `tray` 健康状态快照。
- **建立长期回归保护机制与发布前检查清单（`AGENTS.md`、`RELEASE_CHECKLIST.md`、`tests/test_providers.py`）**：明确 9 大核心受保护功能，新增 3 组托盘生命周期回归自动化测试（全量 43/43 通过），并完成 Windows 11 交互桌面实机验证（托盘动态图标、菜单、任务栏切换与 VGN 真机电量 `75%` 全通过）。

---

## BattDock v2.7.2（2026-11-27）— 支持任务栏点击切换主窗口与窗口状态同步加固

### 窗口交互与稳定性修复
- **支持 Windows 10/11 原生任务栏点击切换主窗口（`mouse_battery_app.py`、`floating_widget.py`）**：
  - 通过 Win32 原生样式辅助函数 `_ensure_taskbar_toggle_style()` 为无边框 `BrowserForm` 幂等补齐 `WS_MINIMIZEBOX | WS_SYSMENU`（绝不添加 `WS_CAPTION` / `WS_THICKFRAME` / `WS_BORDER`，保持纯无边框零边框侵入与 Win10/11 圆角无损，且零全局鼠标钩子）；
  - 实现与标准桌面软件一致的任务栏交互：主窗口处于前台且可见时再次点击任务栏图标自动最小化、已最小化时点击恢复并激活、后台仍可见时点击置前而不误最小化；
  - 完整保留「关闭窗口时最小化至托盘」、系统托盘唤出、任务栏右键菜单及右键关闭恢复机制，最小化与恢复过程绝不退出软件、不中断后台电量监控且不重复创建主窗口或监控任务；
  - 同步加固 `apply_window_rounded_corners()` 最小化 `IsIconic` 跳过保护、`minimized`/`restored`/`maximized` 状态与残留清理同步，以及「主窗口先最小化再右键关闭至托盘后由托盘唤出」的 `SW_RESTORE` + 居中恢复边界；全量 40/40 项单元测试与 Windows 11 真实 Edge WebView2 端到端验收全部通过。

---

## BattDock v2.7.1（2026-11-27）— 全适配器通信与电量精度修复、关于页精简与托盘悬浮窗开关

### 无线外设通信稳定性、迈从耳机识别与电量精度修复
- **彻底修复迈从（MCHOSE）无线耳机识别与多集合锁死（`providers/wireless_headsets.py`、`providers/base.py`）**：新增只读 Win32 `output_report_id` 描述符检测，无编号报告自动补前导 `0x00`；多 Vendor 集合改为按 `(vid, pid)` 聚合逐一尝试，杜绝首个无效集合提前锁死；提升读包帧数并过滤全零空包；新增 VID `0x3837 / 0x291D` 迈从耳机受控通用探测（严格排除标准鼠键输入集合 `0x01` 与已知鼠键 PID）。（协议已实现待真机实测）
- **修复多品牌耳机/键鼠通信与常驻句柄释放（协议已实现待实测）**：
  - **Airoha RACE & Alienware AW920H**：发查询帧后优先走只读控制管道 `HidD_GetInputReport(0x07)` 并兼容中断读取；补齐 Audeze Maxwell 有线 PID `0x4B1A`；
  - **JBL / Jabra / Fractal Scape / MOONDROP GM01 Pro / Poly BT600**：统一改为多集合尝试与按真实报表长度定长补齐，Poly BT600 补齐 Hello ACK 握手流程；
  - **Sony PULSE 3D**：改用锁保护常驻只读异步监听句柄，并在设备拔出、读写异常、`WM_DEVICECHANGE` 热插拔、`WM_POWERBROADCAST` 系统休眠唤醒及软件退出时彻底关闭释放；
  - **全量其余适配器加固**：修复 MCHOSE 鼠标、无线键盘（CompX / SONiX / Evision / Semico / K87 V3 / Alienware / URX / 荣元）、HyperX、SteelSeries、Corsair、Logitech G 耳机、ASUS ROG / Sony INZONE 的多集合锁死、空包打断与休眠占位缓存，蓝牙 SetupAPI 兼容 4 字节 `UINT32` 电量值读取；
  - **标准 HID 通用兜底（`providers/standard_hid.py`、`providers/manager.py`）**：放宽固定 VID 屏蔽，改由 `DeviceManager` 按精确 `(vid, pid)` 跳过专用适配器已在线及已登记休眠占位的设备，既覆盖同品牌新款标准 HID 设备又杜绝重复卡片。
- **全适配器电量取整与插值精度修正**：统一 `providers/base.py` 为标准半入整四舍五入；修正 Corsair Bragi 千分比向下截断、HyperX Stinger Core 与 ASUS ROG Strix Go 2.4 电压分段线性插值、Poly BT600 向下整除以及 Razer / `standard_hid` 极低电量 `raw == 1` 被误判为休眠的边界问题；`VGN Dragonfly F2 Pro Max (3554:FB3E)` 经本机实测核验继续原样透传固件原生 `Byte[6]`。

### 关于页精简、一键复制诊断与托盘悬浮窗开关
- **精简「关于软件」页面与更新策略（`ui/settings.html`、`updater.py`、`app_config.py`）**：移除「更新下载线路」与「自定义加速前缀」设置项（后台默认国内高速通道优先并静默回退 GitHub，自动兼容升级旧配置）、移除检查更新时间戳、「GitHub 项目仓库」更新为黑白单色图标 +「项目主页」，底部诊断栏并排新增轻量「复制诊断」按钮（直接复制脱敏 JSON 至剪贴板）。
- **新增托盘「显示桌面悬浮窗」原生勾选菜单（`mouse_battery_app.py`）**：在右键菜单「打开 BattDock」下方、「设置」上方新增原生勾选开关，与设置页实时双向同步并持久化。

---

## BattDock v2.7.0（2026-11-26）— 修复 iKF 与蓝牙耳机漏识别、新增标准 HID 通用电池读取与多品牌耳机/键盘扩展

### 修复 iKF 与 Windows 蓝牙耳机/键盘漏识别
- **重构 Windows 蓝牙 PnP MAC 跨节点聚合（`providers/bluetooth_provider.py`）**：定位并修复包括 **iKF**、漫步者 Edifier、水月雨、Bose、Sony 及蓝牙无线键盘在 Windows 下经常无法识别的根因——Windows 通常将真实型号名与 `IsConnected` 挂在 `DEV_<MAC>` 根节点，而将电量属性挂在 HFP 音频子节点（名称为泛化服务名 `Microsoft Bluetooth Hands-Free Profile Audio Device`）或 BLE `Battery Service` 子节点。新版按 12 位蓝牙 MAC 地址跨节点聚合型号名、在线状态、HFP/A2DP 音频类型与电量，自动过滤离线节点并新增 iKF、漫步者、Keychron、NuPhy、Royal Kludge、Akko、DAREU、MelGeek、Lofree 等 25+ 品牌智能归类。
- **说明（iKF 2.4G 接收器边界）**：若 iKF 2.4G 接收器在 HID 描述符中暴露标准 `Battery Strength (0x06:0x20)` 将自动识别；对仅注册为纯 USB Audio 音频设备而未公开私有 HID 通道的 2.4G 接收器型号（如部分 `0E6A:0110` 方案），建议切换蓝牙模式连接或导出脱敏诊断报告协助适配。

### 新增标准 USB HID 通用电池兜底适配器（`providers/standard_hid.py`）
- **零写操作、免驱读取标准 HID `0x06:0x20` 电量**：通过 Win32 只读 `HidD_GetPreparsedData` / `HidP_GetSpecificValueCaps` / `HidD_GetFeature` 自动发现并读取所有遵循 USB HID Generic Device Controls `Battery Strength (0x06:0x20)` 规范的 2.4G/有线无线耳机、无线键盘与鼠标，自动按报告描述符 `LogicalMin..LogicalMax` 归一化并跳过已有专用适配器的品牌与蓝牙 HID，内置 120 秒节流且绝不伪造 `0%`。

### 新增无线耳机与无线键盘品牌协议支持（协议已实现待实测）
- **新增无线耳机只读协议（`providers/wireless_headsets.py`）**：新增 **Alienware AW920H**（`413C:A515`）、**Poly Voyager (BT600)**（`047F`）、**Jabra Link 380 / Link 390 / Evolve2 65 Flex / Evolve3 75**（`0B0E`）、**Fractal Design Scape**（`36BC`）、**MOONDROP 水月雨 GM01 Pro**（`35D8:0133`）、**Sony PULSE 3D**（`054C:0D5E`，被动只读 `0xB0` 报告）及 **JBL Quantum 520X**（`0ECB:21A7/21A9`）。
- **新增无线键盘只读协议（`providers/wireless_keyboards.py`）**：新增 **荣元（Rongyuan）2.4G 接收器平台**（`Feature 0xF7`，覆盖 Attack Shark / Akko / Royuan / MSI / Trust 等 80+ 无线键盘/双通道接收器 PID）与 **URX Core75**（`36B0:3002`，VIA `08 00 07` 仅严格匹配产品名）。
- **同步更新设置页品牌目录、命名规范与单元测试**：扩展 `providers/device_naming.py` 规范品牌映射与设置页支持设备目录；全量 38 项单元测试全部通过。

---

## BattDock v2.6.1（2026-11-26）— 新增国内多节点更新加速与故障自动切换

### 在线更新加速与稳定性优化
- **内置国内多节点 HTTPS 加速与并发测速择优（`updater.py`）**：针对国内访问 GitHub 下载更新慢或中断的问题，内置 4 个实测可用国内加速节点（`gh-proxy.org`、`gh-proxy.com`、`ghfast.top`、`ghfile.geekertao.top`）；下载前自动并发测速挑选最快健康节点，任一节点超时或中断时无缝切换至下一个备用节点并保留 GitHub 官方直连兜底。
- **支持纯国内免直连检查更新与 SHA-256 校验**：当 `api.github.com` 无法访问或限流时，自动通过国内加速通道读取 `releases/latest/download/update-summary.json` 完成版本检查，并通过多通道拉取 `SHA256SUMS.txt` 强制校验下载包哈希，兼顾下载速度与安装包完整性安全。
- **新增「更新下载线路」设置与实时速率提示**：在「设置 → 关于软件」中新增下载线路选择（`自动优选（国内加速）` / `仅国内加速镜像` / `GitHub 官方直连` / `自定义加速源`），支持用户填写自有 HTTPS 加速前缀；下载进度实时显示当前加速节点与下载速率（如 `MB/s` / `KB/s`）。

---

## BattDock v2.6.0（2026-11-26）— 根治关闭按钮红色悬停残留、大幅扩展无线耳机与无线键盘支持

### 窗口交互 Bug 彻底修复
- **根治主窗口重开后关闭按钮残留红色高亮**：定位 `v2.5.2` 残留根因为 Chromium Blink 在窗口隐藏时保留了旧鼠标坐标，且 2 帧后自动移除重置类导致 `:hover` 立即重新命中 `.win-btn.close`（`#E81123`），同时原 `GetWindow(GW_CHILD)` 未递归触达深层 `Chrome_RenderWidgetHostHWND`。现改用 `:root.ui-await-pointer` 持久屏蔽残留 `:hover`/`:active` 样式（不阻塞点击与键盘 `Tab` 导航），直到重开后 120ms 且收到真实位移超过 3px 的用户 `pointermove` 或 `pointerdown` 才解除，并配合 `EnumChildWindows` 递归向所有 WebView2 子窗口投递 `WM_CANCELMODE` / `WM_MOUSELEAVE`，已在 Edge WebView2 实机验证通过。

### 新增无线键盘只读电量支持（协议已实现待实测）
- **新增多品牌无线键盘适配器（`providers/wireless_keyboards.py`）**：基于 MIT 许可公开只读协议规范独立实现，内置 180 秒在线低打扰节流（避免频繁唤醒休眠键盘，手动刷新立即穿透）：
  - **CompX BY 2.4G**：AULA F75 / F75 Max、MCHOSE G75 / G87 / G98 / K87 / K99 / X75 / Z75 / GX87 / KX75 / UT98 系列、VGN V98 Pro V3 / V87 V2 / N75 V2 / V108、Redragon Horus Pro / V2；
  - **SONiX 2.4G**：Attack Shark X85、EWEADN X87、AJAZZ AK820 Pro / MAX、AULA F87 Pro V2 / F99 MAX、EPOMAKER EA75（对共享 `05AC:024F` 严格限定 Interface 3，绝不误触 QMK/VIA Interface 1）；
  - **Evision 2.4G/有线**：CHERRY MX 3.0S / MX 2.0S / MX 2.0S WL Pro / PIXIU 75、ATK V75X / Z87、VGN S99 / V98 Pro / V98 Pro V2 / N75 Pro / VXE75 / VXE V87、AJAZZ AK992；
  - **Semico / MCHOSE K87 V3 / Alienware / Apple Magic Keyboard**：Attack Shark X98、AJAZZ AK820 Max Plus、MCHOSE K87 V3、Alienware Pro Wireless Gaming Keyboard 及多代 Apple Magic Keyboard（只读 `HidD_GetInputReport(0x90)`）。
- **扩展 Razer & Corsair 无线键盘**：补全 Razer 9 款无线键盘（BlackWidow V3 Mini / V4 Mini / V4 TKL / V4 Low-Profile / V4 Low-Profile TKL HyperSpeed、DeathStalker V2 Pro TKL、Pro Type Ultra / Ergo、Joro）以及 Corsair K70 Core TKL Wireless、MAKR 75 与 K65 Plus / K70 Pro Mini 多 PID。

### 新增无线耳机只读电量支持（协议已实现待实测）
- **新增多品牌无线耳机适配器（`providers/wireless_headsets.py`）**：
  - **Razer 无线耳机**：BlackShark V2 Pro (2020/2023) / V2 HyperSpeed / V3（内置 5 分钟防断连节流）/ V3 X HyperSpeed、Kraken V4 / V4 Pro / Kitty V3 Pro、Barracuda Pro；
  - **Logitech Centurion & ASTRO**：Logitech G Pro X 2 / G Pro X 3 / G522 Lightspeed、ASTRO A50 Gen 4 / A50 Gen 5 / A50 X / A20 X；
  - **JBL / EPOS / Audeze / AKG / Skullcandy / MCHOSE / VGN / FIFINE / Lenovo**：JBL Quantum 350 / 360 / 520 / 610 / 650 / 650X / 810 / 850 / 910 / 950 / 950X Wireless、EPOS H3PRO Hybrid、Audeze Maxwell / Maxwell 2、AKG N9 Hybrid、Skullcandy PLYR / Crusher PLYR 720、MCHOSE X9 / V9 Pro / V9 Pro 2、VGN OMNISOUND、FIFINE HT6、Lenovo Wireless VoIP Headset。
- **升级 Corsair / SteelSeries / HyperX 无线耳机**：正式启用 Corsair Virtuoso / SE / XT / MAX、HS80 RGB / HS80 MAX、Void v2 耳机轮询；补全 SteelSeries Arctis 1 / Pro Wireless / Nova Elite / Nova Pro Omni、Arctis Nova 7 完整 15 PID 与 Nova 3P；补全 HyperX Cloud III S、Cloud Alpha 2、Cloud Flight / Flight S、Cloud Stinger Core (DTS) 与 Cloud II (Kingston)。
- **同步更新设置页支持设备目录与开源合规文档**：新增 36 项自动化单元测试全部通过，所有新增外设严格标明为「协议已实现待实测」，完整保留 VGN Dragonfly F2 Pro Max 已验证通信基线。

---

## BattDock v2.5.2（2026-11-26）— 窗口交互状态与生命周期修复、HID 轮询稳定性优化

### 窗口交互与生命周期修复
- **修复主窗口关闭后残留选中与悬停状态**：主窗口及设置窗口隐藏至托盘或重新唤出前自动清除控件焦点（`activeElement.blur()`）、文本选中、拖拽状态及 Chromium 残留 `:hover`/`:active` 伪类，同时向原生窗口与 WebView2 子窗口投递 `WM_CANCELMODE` / `WM_MOUSELEAVE`，彻底消除重新打开后关闭按钮仍高亮或保留蓝框的现象；完整保留键盘 `Tab` 导航与无障碍支持、窗口居中、设备数据及既有过渡动画。
- **修复任务栏右键关闭或 Alt+F4 后无法重新唤出主窗口**：在窗口生命周期层统一拦截主窗口与设置窗口的 `closing` 事件（覆盖右上角关闭、任务栏右键关闭窗口与 `Alt+F4`）：开启「关闭窗口时最小化至托盘」时安全隐藏而不销毁窗口实例；关闭该设置时走完整退出链路释放 HID/托盘/子窗口资源且不残留后台进程；同步补齐最小化窗口还原、单实例唤出恢复、意外销毁安全重建及后台任务防重复启动保护。

### 外设电量查询与 HID 通信稳定性优化
- **消除高频全量 USB/HID 总线枚举**：`DeviceManager` 改用事件驱动 HID 拓扑缓存（通过轻量 Win32 `WM_DEVICECHANGE` 监听热插拔，仅在启动、插拔、手动刷新、IO 异常恢复或长周期兜底时执行全量 `hid.enumerate(0, 0)`），同时 `VgnBatteryReader` 直接复用共享快照，消除常规 25 秒轮询期间对鼠标接收器与总线设备的重复全量枚举。
- **串行防并发与休眠退避降频**：全链路轮询加锁串行执行，手动刷新与自动刷新/唤醒探测防并发防连点（唤醒探测新增 15 秒冷却）；`VgnBatteryReader` 改用非阻塞缓冲区排空，对已确认休眠的无线鼠标实行阶梯退避（`45s → 90s → 180s`）并在休眠探测时缩减重试轮次，避免高频访问或反复唤醒休眠设备；同步修复 `LogitechHidppProvider` 局部打开异常的潜在句柄泄漏及 `BluetoothBatteryProvider` 重复尝试导入可选 WinRT 依赖的问题。
- **完善轻量本地诊断信息**：在内存环形缓冲区记录轮询起止时间、耗时、是否触发全量扫描及触发原因、超时与重试次数和后台监控任务数并随脱敏诊断报告导出（默认零持续磁盘写入，仅调试模式按需写日志）。

---

## BattDock v2.5.1（2026-11-26）— 彻底消除 Windows 10 窗口圆角外 1px 白色直角框残留

### Bug 修复与交付
- **根治 Windows 10 圆角外 1px 白色直角边框**：排查定位 `pywebview` 在默认 `shadow=True` 下调用 `DwmExtendFrameIntoClientArea(1,1,1,1)` 与 `DWMWA_NCRENDERING_POLICY = DWMNCRP_ENABLED` 导致 Windows 10 DWM 仍在 `SetWindowRgn` 圆角外绘制矩形 1px 白边的问题；现已对 Win10 主窗口与设置窗口关闭 `shadow=is_windows_11()` 并在 `apply_window_rounded_corners()` 中显式关闭 `DWMNCRP_DISABLED` 且清零扩展边距，Windows 11 原生圆角与阴影保持完全不变。
- **同步打包发布**：构建并发布 `BattDock-v2.5.1-Setup.exe`、`BattDock-v2.5.1-Windows-x64-Portable.zip`、`VGNMouseBattery-v2.5.1-win64-UpgradeBridge.zip`、`SHA256SUMS.txt` 与 `update-summary.json`。

---

## BattDock v2.5.0（2026-11-26）— 设备管理重构、Win10 圆角精细修复、紧凑低电量弹窗与最大化自适应

### 设备管理页面重构
- **可折叠设置卡片 + 左侧六点拖拽排序**：取消独立占行的上下排序按钮，改用卡片左侧六点拖拽手柄实现平滑 FLIP 位移交换排序（仅多设备时显示，单设备自动隐藏），排序结果自动保存并实时同步主窗口与悬浮窗显示顺序。
- **与常规设置统一的行式布局**：点击卡片可独立展开/折叠（200ms 平滑高度过渡），展开后依次提供「自定义设备名称」输入框、「在主窗口中显示」开关、「启用电量监控」开关与「提醒阈值（跟随全局设置 / 自定义）」分段选择；自定义模式采用独立的三级数值步进控件（一级黄 / 二级橙 / 三级红），带严格递减校验，彻底移除逗号文本输入框及底层协议名称（如 `vgn_compx`）。

### Windows 10 窗口圆角与设置窗口优化
- **彻底消除 Windows 10 四角像素残留**：修正主窗口与设置窗口在打开、复用、居中、缩放、最大化/还原及 DPI 变化时的 `SetWindowRgn` 重算时机与 `ui_scale` 圆角半径反向补偿，并在 Win10 模式下消除 `body` 与 `.app-shell` 之间的子像素角部缝隙；原生悬浮窗与低电量提醒弹窗同步绘制 1px 抗锯齿圆角外细边。
- **设置窗口最大化自适应布局与标题栏精简**：最大化或宽屏拉伸时右侧设置内容区平滑扩展并居中平衡，消除偏左大面积留白；移除设置窗口顶部标题栏「设置」左侧多余齿轮图标，完整保留返回箭头及左侧导航栏全部图标。

### 低电量提醒弹窗紧凑化
- **内容自适应紧凑尺寸 + 完整标准设备名**：弹窗高度收紧至约 56px，宽度按实际字体与设备名称长度在 250–360px 间自适应（不因固定大宽造成留白，也不整体缩小字体），严格钳制在当前显示器工作区内不遮挡任务栏；优先展示用户自定义名或完整标准型号名，超长营销后缀自动精简并保留品牌/系列/型号，支持悬停查看完整名称；悬浮窗继续保持默认仅品牌名规则。

### 标准 Windows 安装程序
- 随附 `BattDock-v2.5.0-Setup.exe`（Inno Setup 6 简体中文向导），支持自定义任意盘符路径、自动为安装目录配置用户读写权限（保障后续软件内一键自动覆盖更新免弹窗）、防重复安装、桌面/开始菜单快捷方式及 Windows 标准卸载。

---

## BattDock v2.4.0（2026-11-26）— 统一设备图标、悬浮窗精简、Win10 圆角与自动更新全链路修复

### 统一设备类型图标
- **全局黑白实心剪影图标库（`device_icons.py` + `assets/icons/*.svg`）**：参照项目黑白外设参考图重绘 24×24 纯单色实心鼠标、头戴式耳机与紧凑键盘矢量图标（透明背景、浅色主题黑色、深色主题白色，16/20/24px 小尺寸清晰可辨），在主窗口设备卡片、桌面悬浮窗、低电量提醒弹窗、设备管理页与支持设备清单中 100% 统一调用；完整保留设置左侧导航图标、BattDock 主 Logo 与系统托盘动态电池图标。

### 悬浮窗与低电量提醒弹窗优化
- **桌面悬浮窗精简为品牌名展示**：默认采用「实心设备图标 + 品牌名称 + 电量百分比 + 底部平滑进度条」紧凑布局（如 `VGN`、`Logitech`、`Razer`、`SteelSeries`、`HyperX`、`Sony`、`Apple`），消除长型号截断；鼠标悬停显示完整设备名、连接方式与电量状态；同品牌多台同类型设备自动补充型号区分；设置页新增「自定义显示名称」。
- **三级低电量提醒弹窗焕新**：左侧切换为统一黑白实心设备图标（严格单色不随电量变色），两行结构展示分级标题与品牌名；文案与配色严格联动用户阈值——一级黄色「电量偏低 · 剩余 X%」、二级橙色「电量不足 · 剩余 X%」、三级红色「电量紧急 · 剩余 X%」，适配浅色/深色双主题，正式提醒不含任何测试字样。

### Windows 10 圆角与在线更新修复
- **修复 Windows 10 窗口圆角显示**：新增跨版本圆角实现（Win11 沿用原生 DWM 圆角；Win10 22H2 自动采用高 DPI 适配的 `CreateRoundRectRgn + SetWindowRgn` 外轮廓裁剪，最大化自动清除圆角区域、缩放/还原自动重算），覆盖主窗口、设置窗口、悬浮窗与低电量提醒弹窗。
- **修复自动覆盖更新与重启全链路**：定位并修复旧版 `updater.py` 将回滚目录建在 `C:\Temp` 导致非 C 盘（如 `D:\`、`E:\`）执行 `Move-Item` 跨卷失败的根因，改为目标目录同盘回滚 + 退出后 `os._exit(0)` 立即释放 WebView2/CLR 锁 + 重试替换 + 自动重启新版并核验新进程运行 + 清理临时文件。
- **分层更新界面与简明用户摘要**：软件内「关于软件」升级为清晰的版本对比 + 3–5 条简明中文摘要卡片（无原始 Markdown、无源码路径），支持「立即更新」直接执行完整自动升级、「稍后更新」与「查看完整更新日志」（直达对应 Release 页面），实时展示检查/下载/校验/准备安装/重启各阶段进度。

---

## BattDock v2.3.0（2026-11-26）— 品牌升级、黑白 Logo、设备名称与状态规范化

### 品牌升级与视觉焕新
- **正式更名为 BattDock**：集中定义 `brand.py` 品牌常量单一真值来源，统一主窗口标题、设置窗口标题、托盘名称、系统通知来源、桌面悬浮窗标题、Windows AppUserModelID（`BattDock.App`）、EXE 名称（`BattDock.exe`）、Windows 文件版本属性（`ProductName=BattDock`）与卸载/快捷方式脚本。
- **更换全新黑白品牌 Logo**：提取纯黑圆角底 + 纯白耳机/无线波/鼠标高清透明 PNG（`512×512`）及 9 规格多分辨率 Windows ICO（`16 / 20 / 24 / 32 / 40 / 48 / 64 / 128 / 256` px），统一应用于主窗口标题栏、关于软件页面、EXE 嵌入式图标、任务栏、Alt+Tab 及 GitHub 项目主页。
- **保留并优化系统托盘动态电池图标**：系统托盘继续使用随实时电量与三级阈值变化的动态矢量电池，新增状态缓存，仅在电量或设备状态真实变动时重绘，消除冗余资源开销。

### 设备显示规范与关于页优化
- **独立设备名称规范化映射层（`providers/device_naming.py`）**：保留底层原始硬件名称（`raw_name`）供诊断追溯，按精确 VID/PID 与官方型号表规范显示（如 `PRO → Pro`、`SUPERLIGHT → Superlight`、`LIGHTSPEED → Lightspeed`、`DEATHADDER → DeathAdder`、`HYPERSPEED → HyperSpeed`，保留 `VGN / VXE / ATK / ASUS / ROG / JBL / HyperX / SteelSeries / AirPods / WH-1000XM5`，严格区分 `Logitech G Pro 2 Lightspeed` 与 `Logitech G Pro X Superlight 2`）；同步规范支持设备清单，长名称支持单行省略与鼠标悬停完整展示。
- **设备副标题与状态统一**：副标题仅展示简洁中文连接方式（`2.4GHz 无线连接` / `蓝牙连接` / `USB 有线连接` / `无线连接`）及必要特殊状态（`休眠中` / `充电中` / `已充满` / `未连接`），不再展示 `LIGHTSPEED` / `HyperSpeed` 等品牌技术词，正常连接不重复显示「已连接」；未知/休眠电量统一显示 `—`，绝不伪造 `0%`。
- **关于软件页面完善**：顶部精简为黑白 Logo + `BattDock` + 动态版本号（无作者与冗余描述），保留 GitHub 仓库直达、在线检查更新、支持设备清单、开源许可与脱敏诊断导出。

### 在线更新完善与旧版本无缝升级兼容
- **在线更新增强（`updater.py`）**：严格过滤草稿与预发布版（仅识别稳定正式版），仅允许 HTTPS 下载，支持 `SHA256SUMS.txt` 完整性校验、覆盖失败自动回滚及防高频请求冷却；绝不误删用户目录中的无关文件。
- **旧版 `VGNMouseBattery` 平滑迁移**：
  - 首次启动自动从 `%LOCALAPPDATA%\VGNMouseBattery\config.json` 无损迁移配置至 `%LOCALAPPDATA%\BattDock\config.json`；
  - 自动迁移开机自启注册表项并清理旧键，双互斥量防止新旧版本同时运行；
  - Release 随附旧版 `v2.2.0` 升级桥接包（`VGNMouseBattery-v2.3.0-win64-UpgradeBridge.zip`），旧版一键更新后自动切换为纯 `BattDock.exe` 并清理桥接残留。

---

## v2.2.0（2026-11-26）— GitHub 公开开源与内置一键在线更新

### 新增功能
- **在线检查更新与 Windows 一键覆盖升级（`updater.py`）**：
  - 零第三方依赖接入 GitHub Releases 最新版本检测，支持「启动时自动检查更新」开关（启动 12 秒后后台静默检查，不拖慢启动与不打扰使用）以及「关于软件」/ 托盘右键手动检查更新；
  - 主窗口底栏在发现新版时自动浮现轻量 `发现新版 vX.Y.Z` 胶囊，一键直达关于页更新面板；
  - 打包版支持一键流式下载 `.zip` 更新包（实时显示下载进度条与 MB 进度，支持随时取消）、ZIP CRC 完整性与防路径遍历（Zip Slip）安全校验，并通过 UTF-8 BOM 隐藏 PowerShell 脚本在进程退出后自动替换程序并重启，完整保留用户配置（`%LOCALAPPDATA%\VGNMouseBattery\config.json`）与 `卸载程序.bat`。
- **公开 GitHub 开源仓库**：仓库 `edwin99701/wireless-peripheral-battery-monitor` 正式公开，「关于软件」页新增一键打开线上仓库与 Release 下载页入口。

---

## v2.1.0（2026-11-26）— 现代化双窗口 UI 重构、桌面悬浮窗与 Win10/11 全兼容升级

### UI 重构与体验升级
- **统一现代化桌面设计体系（`ui/common.css`）**：重构为浅灰白 / 深色 / 跟随系统双主题界面，支持界面缩放（90%–125%）、电量状态配色方案、列表密度、进度条/图标显示开关；不再依赖 Windows 11 专属 Mica / Acrylic，原生兼容 Windows 10 22H2 x64 及 Windows 11（Win11 上能力检测式启用圆角并自动降级）。
- **全新主窗口（`ui/index.html`，默认 `760×480` 可调整大小）**：
  - 简洁标题栏（蓝底软件图标 + 「外设电量」 + 设置/最小化/最大化/关闭，支持拖拽与双击最大化）；
  - 动态多设备列表卡片：支持标准鼠标/耳机/键盘卡片、低电量/紧急电量柔和暖色高亮卡片、多电池耳塞（AirPods / Sony INZONE Buds / ROG Cetra）左耳/右耳/充电盒三列组合卡片、以及无设备空状态页面；
  - 底部状态栏显示最近更新时间、自动监控状态指示与带旋转反馈的手动刷新按钮。
- **全新独立设置窗口（`ui/settings.html`，默认 `840×742`）**：
  - 左侧 6 大分类导航（常规设置 / 设备管理 / 电量提醒 / 外观设置 / 悬浮窗 / 关于软件）+ 右侧分组卡片布局，所有修改自动保存并即时同步至主窗口、托盘与悬浮窗；
  - **设备管理**：支持单台设备自定义重命名、主列表隐藏/恢复、启用/暂停监控、上移/下移排序、独立提醒阈值覆盖及兼容验证状态显示；
  - **电量提醒**：支持总开关、可自定义数值的一/二/三级阈值（默认 `30% / 20% / 10%`）与紧凑步进器、自定义提醒阈值增删、弹窗通知、Windows 系统通知、提示音选择与试听、以及可配置防重复/重复提醒间隔；
  - **关于软件**：展示版本号 `v2.1.0`、作者 `Ed`、内嵌文档阅读器（支持设备清单/第三方许可说明）与一键诊断报告导出。
- **新增轻量桌面悬浮窗（`floating_widget.py`）**：基于原生 WinForms 实现（零额外 WebView2 内存开销），支持启用开关、置顶、45%–100% 透明度、小/中/大尺寸、四角预设与自定义拖拽、指定显示设备、位置锁定及双击唤起主窗口。
- **GitHub 发布准备**：新增可重复一键测试与构建脚本 `build_release.ps1`，完善 `.gitignore` 与持久化上下文文档体系。

### 交互与细节修复（v2.1.1 增量优化）
- **主窗口与设置窗口无闪烁居中定位**：启动主窗口与从系统托盘重新打开主窗口时，按当前显示器可用工作区精确居中（实测偏移 `(0, 0)`），兼容多显示器与多档 DPI 缩放并严格防止超出边界或被任务栏遮挡；打开设置窗口时以主窗口为中心居中对齐且首帧零闪跳（不影响桌面悬浮窗用户自定义位置）。
- **设置窗口默认页修复**：打开或关闭后重新打开设置窗口，始终默认进入「常规设置」页并同步高亮左侧对应导航项；修复历史配置 `poll_interval_sec=30` 时检测间隔下拉框空白的问题。
- **关于软件页面精简**：删除作者与软件描述文字，仅保留软件图标、「外设电量监控」与动态读取的「版本 v2.1.0」，优化顶部垂直对齐与间距，浅色/深色主题视觉一致。
- **彻底修复启动与打开设置闪烁**：采用 WinForms `Opacity=0` 预渲染 + 主题匹配 `background_color` + 前端双 `requestAnimationFrame` 就绪后原子显现（`Opacity 0 -> 1`），并改为设置窗口关闭时隐藏复用实例；15ms 逐帧实测主窗口启动与设置窗口首次/二次打开可见帧跳变均为 `0` 次，二次打开设置耗时仅 `23ms`。
- **支持设备清单重构为设置内独立子页面**：取消大尺寸遮罩弹窗，改为设置窗口右侧独立子页面（支持 220ms 横向滑入与反向返回）；拆分为 14 个独立可折叠品牌列表（默认折叠、搜索自动展开、按全部/鼠标/耳机/键盘筛选），统一中性色与细边框，隐藏面向用户的测试状态标签（底层数据库、诊断与文档完整保留），底部注明「实际兼容性可能因设备固件及连接方式而异。」。
- **全局轻量交互动效体系**：统一 Ease-Out / Ease-In-Out 缓动（无弹簧回弹/呼吸灯），落地主窗口 180ms 淡入、设置窗 220ms 淡入+8px 轻位移、分类切换 180ms+6px、子页 220ms 横向滑入/返回、品牌手风琴 200ms 高度+箭头旋转、导航 150ms、按钮 120ms/100ms、开关 150ms、自绘深浅一致下拉菜单 150ms、主界面增量复用的 350ms 电量条与 200ms 状态色过渡、低电量弹窗 220ms 滑入/140ms 淡出；外观设置新增「界面动画」开关并自动遵循 Windows 系统动画偏好。
- **品牌图标升级与设置页精简**：
  - 设置窗口各分类右侧页面标题移除冗余大图标，仅保留左侧导航栏简洁小图标；
  - 更换全新蓝色圆角无线耳机+鼠标品牌 Logo（透明背景 `assets/app_logo.png` 与多分辨率 `assets/app_icon.ico`），同步应用于程序 EXE/文件夹图标、主窗口标题栏及「关于软件」页面；
  - 系统托盘继续沿用动态矢量电池图标，并随当前设备实时电量与三级低电量阈值动态改变电量条填充与配色。
- **GitHub 私有仓库发布**：新增标准 `LICENSE`（MIT），完成脚本与文档本地路径脱敏，发布至 GitHub 私有仓库。

---

## v2.0.0（2026-11-26）— 通用多品牌无线外设电量监控升级

### 新增功能
- **模块化多品牌适配器架构（`providers/`）**：新增 `DeviceManager` 统一设备管理层与 8 大独立协议适配器，新增品牌无需修改 UI 或其他品牌协议。
- **第一阶段主流外设协议实现**：
  - **Logitech 罗技**：HID++ 2.0（`0x1004`/`0x1000`/`0x1001`/`0x1F20` + `0x0005` 设备名称查询），支持 Unifying / Bolt / Lightspeed 接收器多槽位（1–6）、有线直连以及 G533/G535/G633/G635/G733/G933/G935/G PRO X 无线耳机。
  - **Razer 雷蛇**：91 字节只读 Feature Report（含严格 `feature_length == 91` 保护与 XOR CRC 校验），支持主流无线鼠标与无线键盘。
  - **SteelSeries 赛睿**：支持 Aerox 3/5/9、Aerox 3 Gen 2、Prime、Rival 3/650 鼠标及 Arctis 7/7+/9/Nova 5/Nova 7/Nova Pro/GameBuds 无线耳机。
  - **Corsair 海盗船**：支持 SLIPSTREAM Bragi 鼠标/键盘与 Void/HS70 无线耳机。
  - **HyperX**：支持 Cloud Alpha/II/III/II Core/Stinger 2 无线耳机及 Pulsefire Haste 2/Haste/Dart 无线鼠标。
- **第二阶段扩展品牌与蓝牙协议实现**：
  - **ASUS ROG / TUF**：支持主流 ROG/TUF 鼠标、键盘、ROG Omni / SpeedNova 8K 接收器配对表查询，以及 ROG Pelta / Delta II / Cetra SpeedNova / Cetra Open / Strix Go 2.4 耳机。
  - **Sony 索尼**：支持 Sony INZONE H5、INZONE H9 II、INZONE Buds（含左/右/盒独立电量解析）。
  - **Apple AirPods / Beats & 标准蓝牙**：实现 Windows SetupAPI 只读蓝牙电量读取（无蓝牙硬件时静默返回零报错），以及 Apple Continuity BLE 广播报文解析（左耳、右耳、充电盒独立电量与充电状态）。
  - **国产品牌扩展**：在保留原版 `VGN Dragonfly F2 Pro Max` 协议零修改的前提下，扩展支持 VXE、ATK、CompX 通用方案、MCHOSE（Feature Report `0x11` XOR-0xFF）与 Rapoo 安全识别。
- **多设备主界面与分体式耳机展示**：
  - 检测到 `>= 2` 台外设时自动显示多设备切换胶囊条；单设备时保持极简视图。
  - 支持分体式耳塞（AirPods / Sony INZONE Buds / ROG Cetra）的**左耳 / 右耳 / 充电盒**三列独立电量与充电状态显示。
  - 完整区分**在线 / 充电中 / 已充满 / 休眠中 / 未知未响应**，离线或未知状态严禁伪造 `0%`。
- **每设备独立三级低电量提醒**：
  - 默认启用 `30%`、`20%`、`10%` 三级提醒，每台设备独立持久化配置。
  - 引入滞回防抖（回升 `+5%` 或充电重置），同一周期跨多级时仅弹出最紧急档位，杜绝重复弹窗轰炸。
- **设备诊断报告导出**：支持从主界面底部与托盘右键菜单一键导出脱敏 JSON 诊断报告。
- **自动化测试体系**：新增 `tests/test_providers.py`，包含 21 项单元测试，全面覆盖全部品牌协议报文解析、去重逻辑、防伪造 0% 与三级防抖状态机。
- **持久化项目上下文管理**：在项目根目录建立 `AGENTS.md`、`PROJECT_CONTEXT.md`、`PROGRESS.md`，并与 `CHANGELOG.md`、`SUPPORTED_DEVICES.md` 联动，支持跨会话/压缩后无损续接。

### 保留与兼容
- **VGN Dragonfly F2 Pro Max（`3554:FB3E`）零破坏兼容**：保留 `vgn_battery.py` 原有协议实现并在本机真实硬件上完成回归验证。
- 保留 Windows 11 原生 Acrylic 毛玻璃主窗口、开机 `--background` 静默驻留托盘、固定/解锁位置切换、托盘右键「测试低电量弹窗」及原生 WinForms 5 秒不抢焦点最高置顶提醒弹窗。

---

## v1.x（历史阶段 — VGN 单设备版）
- 完成 VGN Dragonfly F2 Pro Max 17 字节 HID 协议逆向验证与实时电量/电压监控。
- 实现 Windows 11 原生 DWM Acrylic 液态玻璃主窗口与透明矢量电池托盘图标。
- 实现右下角固定定位、开机 `--background` 静默启动、WinForms 5 秒不抢焦点最高置顶低电量迷你弹窗及独立 PyInstaller 打包与卸载脚本。
