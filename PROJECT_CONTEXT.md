# PROJECT_CONTEXT.md — BattDock 技术架构与关键决策

> 本文档是 **BattDock** 跨会话的唯一技术真值来源。新开会话或切换模型时，与 `AGENTS.md`、`PROGRESS.md` 一并读取即可完整掌握项目全貌，无需依赖历史聊天记录。

---

## 一、项目定位、运行环境与技术栈

- **软件名称**：**BattDock**（轻量化 Windows 无线外设电量管理工具，开源协议 MIT）
- **GitHub 仓库**：`https://github.com/edwin99701/wireless-peripheral-battery-monitor`（公开仓库，主分支 `master`，当前版本 `v2.7.1`）
- **兼容目标**：Windows 10 22H2 x64 及以上 / Windows 11 x64（依赖系统内置 Edge WebView2 运行时，免 Python 环境、免官方驱动）
- **开发与构建环境**：Python `3.12+`（验证版本 `3.12.10`）、`hidapi 0.15.0`、`pywebview 6.2.1`（WinForms + EdgeChromium）、`pystray 0.19.5`、`Pillow 13.0.0`、`pythonnet` / `clr-loader`、`PyInstaller 6.22.3`、`Inno Setup 6.7.3`（用户级安装于 `%LOCALAPPDATA%\Programs\Inno Setup 6`）
- **当前本机硬件环境**：Windows 11 x64，物理连接 `VGN Dragonfly F2 Pro Max (VID 0x3554, PID 0xFB3E)`；本机**无蓝牙适配器**（蓝牙适配器缺失时 `BluetoothBatteryProvider` 必须静默返回 `[]` 且零报错）。

---

## 二、模块架构总览

```text
brand.py                      品牌常量单一真值来源（BattDock / 版本号 / EXE 名 / AppUserModelID / 互斥量 / GitHub 地址）
device_icons.py               全局统一 24x24 黑白实心设备类型图标库（SVG + 8x 超采样 Pillow 渲染，浅黑/深白）
assets/
  ├── app_logo.png            512x512 纯黑圆角底 + 白色无线耳机/鼠标主 Logo（透明背景）
  ├── app_icon.ico            9 规格多分辨率 Windows ICO（16/20/24/32/40/48/64/128/256 px）
  └── icons/*.svg             mouse.svg / headset.svg / keyboard.svg / other.svg 统一实心矢量源
mouse_battery_app.py          主控制器：主窗口(760x480) + 独立设置窗口(840x742)、紧凑自适应低电量提醒窗、托盘、状态机、JS 桥
floating_widget.py            原生 WinForms 轻量桌面悬浮窗、Win10/11 跨版本圆角与 1px 抗锯齿细边工具、系统提示音
updater.py                    零依赖 GitHub Releases 在线检查更新、摘要提取、SHA-256/ZIP 校验、同盘回滚与自动重启
legacy_shim.py                旧版 VGNMouseBattery v2.2.0 自动升级至 BattDock 的过渡迁移桥接器
app_config.py                 配置持久化（%LOCALAPPDATA%\BattDock\config.json）、旧版配置/自启无损迁移、设备偏好与阈值
vgn_battery.py                已真机验证的 VGN Dragonfly F2 Pro Max 17 字节 HID 读取器（保持零破坏）
ui/
  ├── common.css              设计令牌、浅/深双主题、配色方案、--ui-zoom 圆角补偿、Win10 边框对齐、统一动效曲线
  ├── index.html              主窗口（动态多设备卡片、低电量暖色卡片、分体耳塞三列卡、空状态、底栏更新提示）
  └── settings.html           设置窗口（左 6 分类导航 + 右自适应居中内容区、设备管理可折叠拖拽卡片、支持设备子页、关于与更新卡片）
providers/
  ├── base.py                 DeviceBattery / SubBattery / BatteryProvider + 只读 HidP_GetCaps / output_report_id / HidD_GetInputReport 与标准四舍五入工具
  ├── device_naming.py        官方标准设备名称规范化、中文连接副标题、悬浮窗品牌标签、低电量弹窗智能完整名
  ├── manager.py              DeviceManager（单次 hid.enumerate 共享、异常隔离、去重、禁伪造 0%、专用认领表防 standard_hid 重复卡片、脱敏诊断导出）
  ├── vgn_provider.py         VGN（封装 vgn_battery）/ VXE / ATK / CompX / MCHOSE / Rapoo
  ├── logitech_hidpp.py       Logitech HID++ 2.0 (0x1004/0x1000/0x1001/0x1F20 + 0x0005) & G 耳机
  ├── razer_hid.py            Razer 91 字节 Feature Report (0x07/0x80, 0x07/0x84, XOR CRC)
  ├── steelseries_hid.py      SteelSeries Aerox/Prime/Rival 鼠标 & Arctis/Nova/GameBuds 耳机
  ├── corsair_hid.py          Corsair SLIPSTREAM Bragi (FF42:0001) & Void/HS70 耳机
  ├── hyperx_hid.py           HyperX Cloud 耳机 & Pulsefire 鼠标
  ├── extra_brands.py         ASUS ROG/TUF 鼠键/Omni/SpeedNova/耳机 & Sony INZONE H5/H9 II/Buds
  ├── wireless_headsets.py    Razer Audio / Logitech Centurion / ASTRO / JBL Quantum / EPOS / Airoha RACE (含 Audeze Maxwell 有线 0x4B1A) / Alienware AW920H / Poly BT600 / Jabra GN / Fractal Scape / MOONDROP GM01 Pro / Sony PULSE 3D (常驻只读句柄) / MCHOSE (多集合自适应与受控通用探测) / VGN OMNISOUND / FIFINE / Lenovo 无线耳机
  ├── wireless_keyboards.py   CompX BY / SONiX(隔离QMK) / Evision / Semico / 荣元 Rongyuan 2.4G / URX Core75 / MCHOSE K87 V3 / Alienware / Apple Magic Keyboard 无线键盘（180s 低打扰节流）
  ├── standard_hid.py         标准 USB HID Battery Strength (0x06:0x20) 零写操作通用电池兜底适配器（按精确 (vid, pid) 跳过专用适配器在线及休眠占位设备）
  └── bluetooth_provider.py   Windows SetupAPI DEVPKEY_Device_BatteryLevel（按 MAC 聚合根节点名/在线态与 HFP/BLE 子节点电量）+ Apple AirPods Continuity BLE 解析
installer/
  ├── BattDock.iss            Inno Setup 6 标准安装脚本（管理员安装 + 目录 users-modify 权限 + 防重复安装 + 卸载）
  └── ChineseSimplified.isl   UTF-8 BOM 简体中文安装向导语言包（Microsoft YaHei UI）
tests/test_providers.py       39 项自动化单元测试（全协议解析 + 取整精度 + 迈从安全护栏 + PULSE 3D 长句柄释放 + standard_hid 精准去重 + 提醒状态机 + 命名/图标/摘要/UI/托盘同步 + 国内优先更新与静默回退）
build_release.ps1             一键测试 → PyInstaller 构建 → Inno Setup 编译 Setup.exe → ZIP 打包 → SHA256SUMS.txt
version_info.txt              Windows EXE 文件版本属性元数据（ProductName=BattDock）
```

---

## 三、已验证核心硬件协议基线（不可破坏）

- **VGN Dragonfly F2 Pro Max**（`vgn_battery.py`）：
  - `VID 0x3554`，`PID 0xFB3E`（2.4G）/ `0xFB3D`（有线），`Interface 1`，`Usage Page 0xFF02`，`Usage 0x0002`
  - 17 字节 HID 报告（Report ID `0x08`），校验和目标 `sum(frame) % 256 == 0x55`
  - 会话查询序列：`0x02(1) -> 0x03(1) -> 0x04 -> 0x02(0)`
  - 解析：`Byte 6` 电量百分比，`Byte 7` 充电/有线状态，`Bytes 8–9` 电压（mV），连续 3 次无应答判休眠（返回 `percent=None`，绝不伪造 `0%`）

---

## 四、关键技术决策与已攻克的坑

1. **Windows 10 / 11 跨版本圆角与消除 1px 白色直角框（v2.4.0 → v2.5.1）**：
   - **坑 1（64 位句柄截断）**：`ctypes.windll.gdi32.CreateRoundRectRgn` 默认返回 32 位 `c_int`，在 64 位 Python 下截断 `HRGN` 导致 `SetWindowRgn` 失败。已显式声明 `argtypes`/`restype = wintypes.HRGN`，并传入 `(0, 0, w + 1, h + 1, diam, diam)` 实现四边四角完全对称裁剪。
   - **坑 2（`pywebview` 强制矩形 DWM 外框导致 Win10 圆角外 1px 白色直角 `┌` 框）**：`webview/platforms/winforms.py` 在默认 `shadow=True` 下调用 `DwmExtendFrameIntoClientArea(1,1,1,1)` 和 `DWMWA_NCRENDERING_POLICY = DWMNCRP_ENABLED`，令 Windows 10 DWM 无视 `SetWindowRgn` 在矩形外圈硬画白边。**根治方案**：主/设置窗口统一传 `shadow=is_windows_11()`，且 `apply_window_rounded_corners()` Win10 分支显式执行 `DWMNCRP_DISABLED` + 零 `MARGINS` 清零，最大化时调用 `SetWindowRgn(hwnd, 0, True)` 恢复直角。
   - **坑 3（`ui_scale` 缩放与 `body` 角部缝隙）**：先定位 `_set_window_pos` 再执行 `_apply_window_chrome`，同时挂载 `SizeChanged`、`Resize`、`VisibleChanged`、`DpiChanged` 钩子；CSS 通过 `--ui-zoom` 反向补偿 `.app-shell` 圆角并在 `:root[data-os="win10"]` 下将 `body` 背景与 `--border-window` 对齐，实现零子像素残留。
2. **启动与设置窗口零闪烁 + 开机 `--background` 静默无弹窗**：
   - 通过 `_install_flicker_free_patch()` 在 `BrowserForm.__init__` 置 `Opacity = 0.0` + 主题匹配 `background_color`，在不可见态完成精确居中、圆角裁剪及前端双 `requestAnimationFrame` 首帧合成后由 `ui_ready()` 原子显现；设置窗口关闭时改为隐藏复用（仅退出程序时销毁），消除冷启动闪烁。
   - 严禁在句柄创建后修改 WinForms `ShowInTaskbar`（会触发 `RecreateHandle()` 导致 WebView2 `E_ABORT` 崩溃）。
3. **在线自动覆盖更新与自动重启（v2.4.0 彻底根治）**：
   - **坑 1（跨盘符 `Move-Item` 崩溃）**：旧版 `v2.3.0` 将回滚目录建在 `C:\Temp`，当程序位于 `D:`/`E:`/`F:` 时 `Move-Item _internal` 抛出跨卷异常。已改为在目标程序同盘同目录建立 `._battdock_rollback_<pid>`。
   - **坑 2（互斥进程创建标志）**：Windows 下 `CREATE_NO_WINDOW | DETACHED_PROCESS` 互斥导致隐藏 `powershell.exe` 无法启动。已改为 `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP` + `stdin/stdout/stderr=DEVNULL`。
   - **坑 3（文件锁释放）**：主进程启动更新脚本后调用 `quit_app()` 并立即 `os._exit(0)`，彻底释放 WebView2 / CLR 对 `_internal` 的句柄锁；脚本自动重试替换、失败自动完整回滚、自动拉起新版 `BattDock.exe` 并核验 PID、清理全部临时文件。
   - **坑 4（旧版客户端纯文本展示乱码）**：绝不在 GitHub Release 正文顶部放 `<!-- BATTDOCK_SUMMARY_START -->` 注释；软件内简明摘要由 Release 资产 `update-summary.json` 提供，Release 正文自身保持纯净简洁 `•` 列表。
4. **标准 Windows 安装程序与自动更新权限兼容（Inno Setup 6）**：
   - `installer/BattDock.iss` 与 `ChineseSimplified.isl` 必须保存为 **UTF-8 BOM**，否则 Inno Setup 6 按 GBK 解析中文导致乱码。
   - `PrivilegesRequired=lowest` 无法在 `E:\BattDock` 等根目录创建文件夹（`Error 5`）；已改为 `PrivilegesRequired=admin` + `[Dirs] Name: "{app}"; Permissions: users-modify` + `[Run] Flags: ... runasoriginaluser`，同时实现「任意盘符无报错安装 + 后续普通权限软件内一键自动覆盖更新 + 配置路径与桌面用户会话一致」。
5. **原生 WinForms 桌面悬浮窗与紧凑低电量提醒弹窗**：
   - 均不引入额外 WebView2 进程，通过 `native_main.BeginInvoke` 在 UI 线程极速渲染并绘制 1px 抗锯齿圆角细边（`paint_winforms_rounded_border`）。
   - 悬浮窗默认仅显示品牌名（悬停显示完整名）；低电量提醒弹窗按 `TextRenderer.MeasureText` 动态计算宽度（`250–360 × 56` 逻辑像素），显示完整标准设备名（超长仅裁冗余后缀，绝不缩减为纯品牌名），加 `WS_EX_TOPMOST | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW` 避免抢夺游戏/全屏焦点。
6. **设备管理拖拽排序与顺序同步**：
   - `ui/settings.html` 使用 Pointer Events + FLIP 位移交换实现无闪影拖拽排序，松手调用 `reorder_devices(ids)` 持久化至 `config.json`，并同步刷新主窗口（`_sorted_devices`）、托盘与桌面悬浮窗（`_pick_floating_device`）。
7. **窗口生命周期、防交互残留与 HID 通信稳定化（v2.5.2 – v2.6.0）**：
   - **拦截任务栏右键关闭 / Alt+F4 与原生任务栏点击切换**：主窗口与设置窗口统一订阅 `events.closing`（`should_lock=True`）；开启 `close_to_tray` 时取消销毁并隐藏复用，关闭时触发 `quit_app()` 完整退出；`show_main_window()` 校验 `_is_window_alive()`、自动还原最小化窗口（含最小化后隐藏至托盘再唤出时先 `SW_RESTORE` 再居中）并在窗口意外销毁时安全重建，后台监控线程由 `_bg_started` 保护绝不重复启动。通过 `_ensure_taskbar_toggle_style()` 为无边框 `BrowserForm` 幂等补齐 `WS_MINIMIZEBOX | WS_SYSMENU`（不添加 `WS_CAPTION`/`WS_THICKFRAME`/`WS_BORDER`），原生支持 Windows 10/11 任务栏点击切换（前台点击最小化、已最小化恢复激活、后台可见切换前台），同时 `apply_window_rounded_corners()` 在 `IsIconic` 时跳过区域重算并在 `minimized`/`restored`/`maximized` 事件中同步圆角、最大化状态与交互残留清理。
   - **彻底消除隐藏/重开残留选中态（v2.6.0 根治）**：隐藏与显现前通过 `resetInteractionState()` 持久挂载 `:root.ui-await-pointer` 压制 Chromium 残留 `:hover`/`:active`（不阻挡点击与键盘 Tab 导航），直到窗口显现 120ms 后检测到用户真实位移 >3px 的 `pointermove` 或 `pointerdown` 才解除；并配合 `EnumChildWindows` 递归向深层 `Chrome_RenderWidgetHostHWND` 投递 `WM_CANCELMODE` / `WM_MOUSELEAVE`。
   - **事件驱动 HID 拓扑缓存与串行退避轮询**：Win32 `WM_DEVICECHANGE` 监听 HID 热插拔，`DeviceManager` 串行加锁并缓存 HID 快照（消除常规 25 秒轮询触发 46–83ms 全总线 `hid.enumerate(0, 0)`）；`VgnBatteryReader` 复用共享快照、改用非阻塞排空并对休眠设备执行阶梯退避（`45s → 90s → 180s`），同步提供内存环形轻量诊断缓冲（零持续磁盘写）。
8. **开源合规决策**：
   - 仅参考 MIT 仓库（`qu1ncky/BatteryTray`、`JKWTCN/BatteryMonitor`）的公开报文规范独立实现；未从 GPL-3.0（`Sapd/HeadsetControl`）或无 LICENSE 仓库复制代码，详情记录于 `THIRD_PARTY_LICENSES.md`。

---

## 五、标准构建与 GitHub 发布流程

1. **版本递增**：同步更新 `brand.py`（`APP_VERSION` / `APP_VERSION_TUPLE`）、`version_info.txt`、`CHANGELOG.md`、`PROGRESS.md`、`README.md`、`README_EN.md`。
2. **一键构建**：执行 `powershell -ExecutionPolicy Bypass -File .\build_release.ps1`，自动跑通 30 项单元测试并生成 `release\assets_vX.Y.Z\` 下的：
   - `BattDock-vX.Y.Z-Setup.exe`（标准中文安装程序）
   - `BattDock-vX.Y.Z-Windows-x64-Portable.zip`（便携免安装版，供软件内自动更新使用）
   - `VGNMouseBattery-vX.Y.Z-win64-UpgradeBridge.zip`（旧版 `v2.2.0` 迁移桥接包）
   - `SHA256SUMS.txt`
3. **准备摘要文件**：在构建产物目录放入 `update-summary.json`（3–5 条简明中文更新要点 + 可选 `important_notice`）以及纯净无 Markdown/HTML 噪音的 Release 正文。
4. **隐私检查与 Git 提交**：扫描确认无个人路径/Token，排除本地参考原图（`极简白色电脑图标组.png`、`黑底白色外设图标目录.png`），提交代码并打注释标签 `git tag -a vX.Y.Z -m "BattDock vX.Y.Z"` 后推送 `master` 与 tag。
5. **草稿校验 → 正式发布 → 线上联调**：
   - `gh release create vX.Y.Z --draft ...` 上传全部 5 个资产；
   - `gh release view vX.Y.Z` 确认 5 个资产均为 `uploaded` 且大小准确；
   - `gh release edit vX.Y.Z --draft=false --latest` 正式发布；
   - 调用 `updater.check_for_update("<prev_ver>")` 与 HTTP HEAD 验证新版检出、便携 ZIP 命中、摘要解析与全部 5 个直链 HTTP 200。
