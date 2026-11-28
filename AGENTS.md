# AGENTS.md — BattDock 长期开发规范与维护约束

本文件是 **BattDock**（标准本地目录 `BattDock`，原历史目录 `vgn-mouse-battery`）的长期开发规范、架构保护规则与跨会话交接准则。无论在 Antigravity 中新建对话、触发上下文压缩还是切换模型，所有开发、修复、文档整理与发布工作均须严格遵守本文件。

---

## 一、新对话启动与长期维护规则

1. **先读文档，再查实况，后动手**：每次新建 BattDock 对话或经历上下文压缩后，必须按以下顺序同步上下文：
   - 自动读取 `AGENTS.md`（长期约束与核心功能保护）
   - 读取 `PROJECT_CONTEXT.md`（权威技术架构、模块依赖与实现边界）
   - 读取 `PROGRESS.md`（当前正式版本、分支状态、验证状态与下一阶段建议）
   - 涉及外设协议或兼容列表时，读取 `SUPPORTED_DEVICES.md`
   - 涉及版本发布、打包或回归检查时，读取 `CHANGELOG.md` 与 `RELEASE_CHECKLIST.md`
2. **以当前源码和 Git 状态为准**：严禁依赖旧对话中未写入文档的临时信息，严禁盲目继承已经完成或过时的开发计划。
3. **禁止重复造轮子**：严禁重复实现已在 `PROGRESS.md` 标注完成的模块，或无故重写现有稳定 UI、动效与硬件协议。
4. **阶段收尾同步文档**：每次功能迭代、Bug 修复或版本发布后，必须同步更新 `PROGRESS.md`、`CHANGELOG.md`（涉及架构、规范、设备或发布检查变更时同步更新 `PROJECT_CONTEXT.md`、`AGENTS.md`、`SUPPORTED_DEVICES.md`、`RELEASE_CHECKLIST.md`），并在本地提交干净的 Git commit 作为回滚点。
5. **文档精简零冲突原则**：保持文档高信息密度与跨文件一致，及时清理被新方案替代的过期表述。

---

## 二、10 项核心受保护功能（绝对不可破坏）

以下 10 项为 **BattDock 核心受保护功能**。任何新增功能、UI 调整、重构或依赖升级，**均不得以破坏下述任一项为代价**：

1. **HID、蓝牙及其他设备通信和电量读取**：11 大只读适配器架构、`DeviceManager` 单次 HID 快照共享与专用认领去重、`VGN Dragonfly F2 Pro Max (3554:FB3E / FB3D)` 已验证协议基线、离线/休眠返回 `None`（展示 `—`，绝不伪造 `0%`）。
2. **Windows NotifyIcon 系统托盘动态电池图标**：`tray_icon.py` 独立原生 Win32 `TrayIconController` + `draw_battery_icon()`（纯内存 32 位 ARGB `HICON`、动态矢量电量/充电/低电色阶、`NIM_ADD` 重试与 `NIM_MODIFY` 自愈、`WM_TASKBARCREATED` 重建、保留 `uID=0` 兼容 Win11 `IsPromoted=1` 置顶偏好）。
3. **后台电量监控**：`WM_DEVICECHANGE` 事件驱动热插拔缓存、`WM_POWERBROADCAST` 休眠唤醒句柄释放、串行防并发轮询、休眠退避与 `_bg_started` 单次启动保护（绝不产生重复后台轮询线程）。
4. **主窗口隐藏、关闭、最小化及恢复**：关闭至托盘隐藏复用不销毁、异常销毁安全重建、零闪烁居中显现、隐藏/唤出零 `:hover`/`:active` 残留。
5. **任务栏点击切换主窗口**：无边框窗体幂等补齐 `WS_MINIMIZEBOX | WS_SYSMENU`（绝不添加 `WS_CAPTION`/`WS_THICKFRAME`/`WS_BORDER`），前台点击最小化、已最小化恢复激活、后台可见点击置前不误最小化。
6. **系统托盘唤出、右键菜单及退出机制**：左键唤出主窗口、右键现场构建最新菜单（含「显示桌面悬浮窗」双向实时勾选）、主窗口隐藏/最小化/关闭及暂停监控均不销毁托盘、退出前同步执行 `NIM_DELETE` 与句柄释放无残留僵尸进程。
7. **三级低电量提醒**：迟滞防抖（防重复轰炸）、单设备独立阈值覆盖、原生 WinForms 紧凑不抢焦点置顶弹窗与 Windows 系统通知。
8. **桌面悬浮窗**：原生 WinForms 轻量窗（零额外 WebView2 开销）、统一黑白实心设备图标 + 品牌精简展示、透明度/尺寸/位置锁定持久化、托盘与设置页开关双向同步。
9. **用户配置及设备设置持久化**：`%LOCALAPPDATA%\BattDock\config.json` 读写无损、旧版 `VGNMouseBattery` 配置与开机自启自动平滑迁移、设备别名/隐藏/排序/阈值完整保留。
10. **GitHub 在线更新、程序替换及自动重启**：国内多节点高速通道优先并静默回退 GitHub、仅识别正式稳定版、HTTPS 下载 + `SHA256SUMS.txt` 与防 Zip Slip 校验、目标同盘目录回滚（`._battdock_rollback_<pid>`）、同步注销托盘后 `os._exit(0)` 释放锁并自动重启新版、自动恢复托盘图标与用户配置。

---

## 三、修改前保护措施与范围控制

### 1. 修改前必做检查
- 读取相关项目文档并核对当前 `git status`、分支名、`HEAD` 提交及未提交改动。
- 分析目标模块与其他模块的导入、事件、生命周期及构建脚本依赖关系。
- 对已有用户改动和重要节点建立可恢复的 Git 回滚点。
- 明确本次修改范围；**严禁覆盖用户未提交工作、严禁擅自切换分支、重置历史提交或删除未知/未跟踪文件**（例如本地参考图片 `极简白色电脑图标组.png`、`黑底白色外设图标目录.png` 必须保留且未经确认不得加入 Git 提交）。

### 2. 修改范围控制
- 优先局部修复，不随意重构已稳定运行的模块；不修改与本次需求无关的文件。
- 不随意更换技术栈及第三方依赖；不为了界面装饰牺牲软件稳定性。
- **只读 HID 安全红线**：严禁向未知 HID 设备盲发写报文；严禁修改鼠标 DPI、回报率、灯光、固件或安装系统内核驱动/系统服务。
- 默认采用**单 Agent 自主执行**，普通开发、修复、UI 优化与文档维护严禁主动启用 Swarm，优先控制上下文与 Token 消耗。
- 若确需大规模重构或存在破坏性风险，必须先说明原因、影响范围与回滚方案并征得确认。

---

## 四、核心功能回归测试与真实性纪律

### 1. 按影响范围执行联动回归
- 每次代码改动后必须运行全量自动化单元测试（`python -m unittest discover -s tests -v`），并按影响范围执行对应回归：
  - **修改 UI**：不得仅看界面，还须核验窗口状态同步、托盘联动与配置读写；
  - **修改窗口生命周期**：必须额外验证托盘图标存活、任务栏点击切换、任务栏右键关闭恢复与后台监控单实例；
  - **修改 HID / 蓝牙通信**：必须额外检查句柄释放、休眠/唤醒、断连/重连，以及鼠标正常输入是否受干扰；
  - **修改在线更新 / 打包 / 命名**：必须额外验证用户配置保留、旧版自启与快捷方式迁移及更新重启后托盘图标恢复。

### 2. 测试结果必须严格分级、严禁造假
所有测试与兼容结论必须严格区分以下五级，**绝不混为一谈**：
1. **代码检查通过**：仅完成静态审查、语法/配置核对或逻辑确认。
2. **自动化测试通过**：通过 `unittest` 等自动化模拟/单元测试（不得等同于实体设备验证）。
3. **本机实际运行通过**：在当前开发机（Windows 11 x64）真实运行程序并目视/行为验收通过。
4. **实体设备实测通过**：接入真实物理外设完成完整只读通信与状态变化验证。
5. **尚未验证**：受硬件或系统环境限制未实际运行验证（如 Windows 10 22H2 实体机、非 VGN 物理外设），必须如实标注，严禁虚构截图、日志或兼容性结论。

---

## 五、品牌、UI、图标与命名统一规范

1. **语言规范**：交流、文档、注释、UI 文案与汇报统一使用**简体中文**；代码标识符、命令、API 与官方设备英文型号保留英文。
2. **品牌单一真值来源**：正式产品名统一为 **`BattDock`**，主程序统一为 **`BattDock.exe`**，所有品牌常量集中于 `brand.py`，禁止在其他模块分散硬编码。
3. **内部模块命名原则**：不为了追求表面一致而批量重命名职责清晰的内部 Python 模块（如 `mouse_battery_app.py`、`vgn_battery.py`、`app_config.py`、`tray_icon.py`、`floating_widget.py`、`updater.py`）；仅清理或规范对外暴露的产品名、程序名、安装包、快捷方式与文档。
4. **双窗口与交互约定**：
   - 浅色 / 深色 / 跟随系统双主题；主窗口 `760×480`（工作区居中）、独立设置窗口 `840×742`（以主窗口居中、关闭隐藏复用、每次打开默认进入「常规设置」）。
   - 设置窗口标题栏仅保留返回箭头 `←` 与「设置」文字（无齿轮图标）；左侧 6 分类导航栏及其图标、选中动效保持原样；宽屏/最大化（`>= 1040px`）右侧内容区自动扩展并居中平衡（最大 `860px`）。
   - 设备管理页采用可折叠行式卡片，多设备显示左侧六点拖拽手柄（单设备隐藏）；严禁向普通用户界面暴露底层协议名（仅保留于诊断报告）。
   - 支持设备清单为设置窗口内独立子页面，面向用户隐藏测试状态标签；真实测试状态保留于 `SUPPORTED_DEVICES.md` 与诊断报告。
   - 全局采用轻量 Ease-Out / Ease-In-Out 动效。循环动效限于主页面自动监控运行时的绿点和充电中的闪电，遵循「界面动画」开关、Windows 系统减少动画偏好和页面可见状态。禁止弹簧回弹。
5. **图标统一规范**：
   - 设备类型图标（鼠标/耳机/键盘）统一由 `device_icons.py` + `assets/icons/*.svg` 提供 24×24 纯黑白单色实心剪影，全局一致应用于主窗口、悬浮窗、低电量弹窗、设备管理与支持设备清单。
   - 保留 BattDock 黑白圆角主 Logo（`assets/app_logo.png` / `assets/app_icon.ico`）、系统托盘动态矢量电池图标与设置左侧导航图标，不得擅自替换。
6. **分场景设备名称规则**：
   - 主窗口 / 设备管理 / 支持设备清单：完整标准设备名（由 `providers/device_naming.py` 规范化，别名优先），副标题仅显示简洁中文连接方式与必要状态，未知电量统一显示 `—`。
   - 桌面悬浮窗：默认「实心图标 + 品牌名 + 电量 + 进度条」，同品牌同类型多设备自动补充型号，悬停显示完整详情。
   - 低电量提醒弹窗：紧凑自适应（`250–360×56px`、圆角 `8px`、停留 5 秒、工作区钳制不抢焦点），左侧单色实心图标不变色，第一行随三级阈值变色，第二行优先显示自定义名或完整标准名（绝不退化为纯品牌名），正式提醒不含「测试」字样。

---

## 六、Windows 10 / 11 兼容性约束

1. **最低兼容基线**：Windows 10 22H2 x64 及以上与 Windows 11 x64；严禁引入仅 Win11 可用的 Mica / Acrylic 硬依赖。
2. **跨版本圆角与无边框保护（切勿破坏）**：
   - **Windows 11（Build `>= 22000`）**：`shadow=True` + 原生 `DWMWA_WINDOW_CORNER_PREFERENCE = DWMWCP_ROUND` + `DWMWA_BORDER_COLOR = NONE`。
   - **Windows 10（Build `< 22000`）**：主/设置窗口必须传 `shadow=is_windows_11()`（即 Win10 下 `False`），`apply_window_rounded_corners()` 显式设 `DWMWA_NCRENDERING_POLICY = DWMNCRP_DISABLED` 并清零 `DwmExtendFrameIntoClientArea(0,0,0,0)`，再以显式 64 位 `HRGN` 签名的 `CreateRoundRectRgn(0, 0, w+1, h+1, diam, diam)` + `SetWindowRgn` 按显示器真实 DPI 裁剪；最大化时清除区域，最小化 `IsIconic` 时跳过重算；前端 `:root[data-os="win10"]` 配合 `--ui-zoom` 反向补偿圆角并对齐 `body` 边框色。
3. **开机静默自启**：通过 `--background` 静默驻留系统托盘，启动时不弹出任何窗口。

---

## 七、在线更新、打包、GitHub 发布与安全纪律

1. **仓库与历史保护**：公开仓库为 `edwin99701/BattDock`（原仓库名 `wireless-peripheral-battery-monitor`，已完成正式更名并由 GitHub 自动保留 301 重定向）。**严禁在同账号下重新创建同名旧仓库 `wireless-peripheral-battery-monitor`**（会破坏旧版本重定向链路）；未经完整兼容性评估与用户明确确认，严禁再次更改仓库名称，严禁删除历史 Release、修改既有 Git Tag 或重写 Git 历史，以保证旧版本在线更新链路（含国内加速节点）长期可用。
2. **标准发布产物命名（与现有更新器 100% 兼容）**：
   - 主程序：`BattDock.exe`
   - 安装程序：`BattDock-v<版本号>-Setup.exe`
   - 便携版：`BattDock-v<版本号>-Windows-x64-Portable.zip`
   - 校验文件：`SHA256SUMS.txt`
   - 软件内摘要：`update-summary.json`
   - 旧版迁移桥接包（仅供 `v2.2.0` 旧版平滑升级）：`VGNMouseBattery-v<版本号>-win64-UpgradeBridge.zip`
3. **两套更新说明规范**：
   - **`update-summary.json`**：3–5 条面向普通用户的简明中文条目（每条尽量 `<= 25` 字，零 Markdown/源码名/提交号/HTML 标签），重大提醒写入 `important_notice`。
   - **GitHub Release 正文**：清爽纯文本排版，严禁使用 `•`、`###`/`####`、`-`/`*`、`**`、反引号及顶部的 `<!-- BATTDOCK_SUMMARY_START -->` HTML 注释，统一使用简洁中文小节标题、自然数字编号与干净段落。
4. **发布门禁**：每次正式发布前必须逐项核对 `RELEASE_CHECKLIST.md`，完成全量单元测试、隐私/敏感信息扫描（零本机路径、零密钥/Token、不提交参考 PNG 原图），采用 `Draft Release → 核验全部资产 → 正式发布为 Latest → 线上验证更新接口与直链 HTTP 200` 流程。
5. **安全边界与开源合规**：严禁修改项目目录外个人文件或系统核心设置；严禁从 GPL-3.0 或无 LICENSE 仓库复制代码，所有合规参考记录于 `THIRD_PARTY_LICENSES.md`。

---

## 八、测试版优先与正式发布审批规则（强制，优先于一切自主发布）

今后所有 **BattDock** 功能更新、UI 优化、Bug 修复及版本迭代，**必须严格执行「先交付测试版 → 用户实测并明确批准 → 执行正式发布」三阶段流程**（本规则永久取代此前「直接自主发布正式版」权限，优先级最高）：

### 1. 第一阶段：生成独立测试版（默认止步于此）
1. 完成代码修改、全量单元测试及必要的核心功能回归测试。
2. 构建**独立测试版**安装包或便携版（建议输出至 `release/test_builds/v<目标版本>-test.<序号>/`，例如 `BattDock-v2.7.7-test.1-Portable.zip` / `BattDock-v2.7.7-test.1-Setup.exe`），明确标注测试版本号与测试版身份。
3. 提供测试版文件路径及本次修改说明、分级验证结果，交由用户安装与实机测试。
4. **隔离要求**：测试版绝不覆盖当前稳定正式版资产目录（`release/assets_v<正式版>`），绝不修改正式版本号对外渠道，绝不进入正式版本的自动更新渠道（严禁推送为 GitHub `Latest` Release 或覆盖正式版 `update-summary.json`）。

### 2. 第二阶段：等待用户实测与明确批准
1. 等待用户在真实环境（含交互桌面、真实外设、Win10/Win11 或游戏场景）反馈功能、界面、兼容性与稳定性问题。
2. 根据反馈持续修复并重新生成测试版。
3. **用户未明确表示同意正式发布之前，严禁进入第三阶段正式发布流程。**

### 3. 第三阶段：经用户明确批准后的正式发布流程与标准命令规范
**仅在用户明确同意正式发布，且全部发布前置条件满足（自动化测试通过、构建成功、程序可正常启动、核心功能回归通过、配置与旧版升级兼容、资产完整无阻断问题）时**，才可执行：
- **版本号判定与同步**：核实当前分支为 `master`、工作区状态及线上最新正式 Release Tag，按语义化版本更新 `brand.py`、`version_info.txt`、`installer/BattDock.iss`、`CHANGELOG.md`、`PROGRESS.md`、`PROJECT_CONTEXT.md`、`README.md`、`README_EN.md`。
- **正式测试与构建**：运行 `powershell -NoProfile -ExecutionPolicy Bypass -File ./build_release.ps1`（自动跑通全量单元测试、PyInstaller 打包、Inno Setup 编译、ZIP 打包与 `SHA256SUMS.txt` 生成），生成 `release/assets_vX.Y.Z/update-summary.json` 与纯文本 `RELEASE_NOTES_vX.Y.Z.md`，完成编译版启动与 ZIP/SHA-256 验收。
- **受控提交与打标（严禁多行拼接、`Write-Host` 包装、`$(...)` 替换、`git -c` 及 `git add -A`/`.`，严禁纳入未跟踪参考 PNG）**：
  - 显式暂存已跟踪改动及经确认的新源码文件
  - `git commit -m "<类型>: <中文说明> (vX.Y.Z)"`
  - `git tag -a vX.Y.Z -m "BattDock vX.Y.Z"`
- **单条纯净快进推送**：
  - `git push origin refs/heads/master:refs/heads/master`
  - `git push origin refs/tags/vX.Y.Z:refs/tags/vX.Y.Z`
- **GitHub CLI（`gh`）四步标准发布（严格锁定 `--repo edwin99701/BattDock`，严禁 `--clobber`）**：
  1. 创建草稿：`gh release create vX.Y.Z --repo edwin99701/BattDock --draft --title "BattDock vX.Y.Z" --notes-file release/assets_vX.Y.Z/RELEASE_NOTES_vX.Y.Z.md`
  2. 逐文件上传 5 个发布资产（不带 `--clobber`）：`gh release upload vX.Y.Z --repo edwin99701/BattDock release/assets_vX.Y.Z/<资产文件名>`（依次上传 `BattDock-vX.Y.Z-Setup.exe`、`BattDock-vX.Y.Z-Windows-x64-Portable.zip`、`VGNMouseBattery-vX.Y.Z-win64-UpgradeBridge.zip`、`SHA256SUMS.txt`、`update-summary.json`）
  3. 核验草稿资产：`gh release view vX.Y.Z --repo edwin99701/BattDock --json tagName,isDraft,assets`
  4. 正式发布为 Latest：`gh release edit vX.Y.Z --repo edwin99701/BattDock --draft=false --latest`
- **严格禁止**：
  - 严禁将测试通过或构建成功等同于允许正式发布；
  - 严禁未经用户明确批准擅自创建正式 Tag、推送正式发布、创建正式 GitHub Release 或上传正式更新资产；
  - 严禁让未经用户实测的版本进入正式自动更新渠道；
  - 严禁强制覆盖远程分支（`--force`/`-f`/`--force-with-lease`）、使用 `--clobber` 覆盖历史 Release 附件、删除历史 Git Tag/Release/仓库、重写 Git 历史（`reset --hard`/`rebase`）、删除用户配置或泄露密钥/隐私。
- **异常熔断机制**：遇测试失败、构建失败、Git 冲突、远端与本地存在无法安全解决的分歧、更新兼容性风险、核心功能回归或 GitHub 认证/权限失效时，立即暂停并向用户说明，严禁跳过测试或掩盖错误。
- **发布后核验**：正式发布后核验 GitHub Release（`Latest` 与非草稿状态）、5 个附件及 SHA-256、新旧仓库 `releases/latest` API 与国内加速节点 HTTP 200、软件内 `updater.check_for_update()` 检测结果，核验通过后立即执行第九节本地测试产物清理，并统一使用中文汇报。

---

## 九、正式版发布后的本地测试文件清理规则（强制）

每次正式版本成功发布并通过线上核验后，必须执行一次**本地测试产物安全清理**，防止旧测试安装包、临时构建缓存与重复测试产物长期占用磁盘空间。

### 1. 允许自动清理的范围
仅限明确核实属于已失效测试流程且可重新生成的本地文件：
1. 以前生成的本地测试版安装包（Test Build Setup）与测试版便携包（Portable Test Build ZIP）；
2. 已废弃的本地测试版 EXE、ZIP 等重复测试构建产物；
3. `release/test_builds/` 等独立测试输出目录中已完成发布、不再需要的旧测试目录与临时测试文件；
4. 可重新生成的临时构建缓存与中间目录（如残留的 `build_tmp/`、`build_dist/`）；
5. 已确认不再需要的临时测试日志、调试输出与临时测试报告。

### 2. 严禁纳入自动清理的受保护内容
- 当前及历史正式版本的安装包、便携版与 Release 资产（`release/assets_v*`）；
- 正式版本源码、Git 提交记录、分支与 Tag；
- 历史备份与必要回滚目录（如 `archive/` 整目录不擅自删除）；
- `AGENTS.md`、`PROJECT_CONTEXT.md`、`PROGRESS.md`、`SUPPORTED_DEVICES.md`、`RELEASE_CHECKLIST.md`、`CHANGELOG.md` 等全部项目文档；
- 正式图标、品牌素材、设备图标及本地参考图片（`极简白色电脑图标组.png`、`黑底白色外设图标目录.png`）；
- 用户配置（`config.json`、`%LOCALAPPDATA%\BattDock\`）、设备数据及个人文件；
- 尚未完成的开发/测试所需文件、未提交的源码修改；
- **任何无法明确确认用途的文件或目录**；
- GitHub 远端历史测试版 Release 与资产（不纳入本地自动清理；确需删除须单独列出并征得用户确认）。

### 3. 安全执行流程与验收汇报
1. **先核验线上正式版**：确认 GitHub 正式 Release 已发布为 `Latest`、全部 5 个正式资产已上传、版本号一致且下载/更新接口正常。
2. **先扫描列清单、再逐项精准删除**：严禁使用不受限制的通配符批量删除；严禁仅因文件名含 `test`/`temp`/`debug` 就直接判定删除；删除前必须逐一核实实际路径与用途。
3. **清理后必须汇报**：汇报本次删除的测试文件数量、释放的本地磁盘空间、保留的正式版本及回滚文件，以及是否存在无法确认用途、需要人工处理的文件。
