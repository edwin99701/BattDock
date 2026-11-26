# 更新日志（CHANGELOG）

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

### 保留与兼容
- **VGN Dragonfly F2 Pro Max（`3554:FB3E`）零破坏兼容**：保留 `vgn_battery.py` 原有协议实现并在本机真实硬件上完成回归验证。
- 保留 Windows 11 原生 Acrylic 毛玻璃主窗口、开机 `--background` 静默驻留托盘、固定/解锁位置切换、托盘右键「测试低电量弹窗」及原生 WinForms 5 秒不抢焦点最高置顶提醒弹窗。

---

## v1.x（历史阶段 — VGN 单设备版）
- 完成 VGN Dragonfly F2 Pro Max 17 字节 HID 协议逆向验证与实时电量/电压监控。
- 实现 Windows 11 原生 DWM Acrylic 液态玻璃主窗口与透明矢量电池托盘图标。
- 实现右下角固定定位、开机 `--background` 静默启动、WinForms 5 秒不抢焦点最高置顶低电量迷你弹窗及独立 PyInstaller 打包与卸载脚本。
