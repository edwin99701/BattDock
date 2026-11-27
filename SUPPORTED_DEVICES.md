# 支持设备清单与验证状态说明（SUPPORTED_DEVICES）

本清单是 **BattDock** 面向开发者与用户的权威设备兼容性记录。所有设备均严格按以下**四级验证状态**分类记录，**绝不因代码中存在适配器或通过模拟报文测试，就将其标记为已通过实体设备验证**：

> 说明：软件内「设置 → 关于软件 → 支持设备清单」面向普通用户保持简洁中性展示，不直接显示测试状态标签；真实测试状态统一维护于本文件、底层适配器元数据及脱敏诊断报告中。

| 状态分级 | 定义与判定标准 |
| :--- | :--- |
| **1. 已通过实体设备验证** | 已接入真实物理外设完成完整只读查询、电量/充电/休眠状态变化与回归验收 |
| **2. 已实现协议但缺少实体设备验证** | 已依据公开只读协议完成独立 Python 实现并通过模拟报文单元测试，待对应实体设备实测晋升 |
| **3. 已知协议但尚未实现** | 已知存在公开或半公开协议方向，但缺少真机诊断报文验证安全只读边界或缺少可选运行环境，尚未正式实现 |
| **4. 暂不支持** | 因无公开协议、纯音频无 HID 通道、仅闭源内核驱动通信或硬件条件限制，当前明确不支持 |

---

## 一、已通过实体设备验证

| 品牌 | 官方标准名称 | 设备型号 / VID:PID | 设备类型 | 支持的连接方式 | 电量读取协议 | 当前适配状态 | 实体设备验证状态 | 已知限制 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **VGN** | **VGN Dragonfly F2 Pro Max** | `3554:FB3E`（2.4G）<br>`3554:FB3D`（有线） | 无线鼠标 | 2.4GHz 无线连接<br>USB 有线连接 | CompX / VGN 17 字节会话报文（`Interface 1`, `0xFF02:0x0002`, Report ID `0x08`, `sum % 256 == 0x55`） | 已完成（`vgn_battery.py`） | **已通过实体设备验证** | 固件原生按 `5%` 步进上报 `Byte[6]`，BattDock 原样透传不插值伪造；休眠时返回 `—` |

---

## 二、已实现协议但缺少实体设备验证（均已通过模拟报文单元测试）

### 1. VGN / VXE / ATK / MCHOSE / LAMZU / CompX 方案

| 品牌 | 官方标准名称 / 代表型号 | 设备类型 | 支持的连接方式 | 电量读取协议 | 当前适配状态 | 实体设备验证状态 | 已知限制 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **VGN / VXE / ATK** | F2 Master+、F1 Pro / MOBA、Dragonfly 4K、VXE R1 Pro Max / SE+、ATK F1 / X1 系列（VID `0x3554` / `0x373B`） | 无线鼠标 | 2.4GHz / USB 有线 | CompX `0xFF02:0x0002` 17 字节协议（`vgn_provider.py`） | 协议已实现 | 缺少实体设备验证 | 需对应型号固件遵循标准 CompX 报告格式 |
| **VGN / VXE / ATK** | VGN V98 Pro / V2 / V3、S99、N75 Pro / V2、V87 V2、V108、VXE75 / V2、VXE V87、ATK V75X / Z87（VID `0x258A` / `0x391D` / `0x320F` / `0x373B`） | 无线键盘 | 2.4GHz / USB 有线 | CompX BY / Evision 键盘只读协议（`wireless_keyboards.py`） | 协议已实现 | 缺少实体设备验证 | 内置 180 秒在线节流以防频繁唤醒休眠键盘 |
| **VGN** | VGN OMNISOUND（VID `0x372E`） | 无线耳机 | 2.4GHz | 专用 HID 无线耳机只读协议（`wireless_headsets.py`） | 协议已实现 | 缺少实体设备验证 | 待真机确认各固件版本字节偏移 |
| **MCHOSE（迈从）** | A5 / G3 / A7 / L7 / K7 鼠标；G75 / G87 / G98 / K87 / K87 V3 / K99 / X75 / Z75 / GX87 / KX75 / UT98 键盘；X9 / V9 Pro / V9 Pro 2 耳机（VID `0x35A4` / `0x248A` / `0x3554` / `0x41E4` / `0x3837` / `0x291D`） | 鼠 / 键 / 耳机 | 2.4GHz / USB 有线 | 鼠标 `0x11` Feature Report XOR-0xFF；键盘 CompX BY / K87 V3；耳机多集合自适应与受控通用探测（严格排除 `0x01` 鼠键输入集合） | 协议已实现 | 缺少实体设备验证 | 不同批次 PID 差异大，如未命中请导出脱敏诊断报告 |
| **LAMZU / Zaopin / Scyrox** | 采用标准 CompX `0xFF02:0x0002` 的无线鼠标（VID `0x3554` / `0x373B`） | 无线鼠标 | 2.4GHz / USB 有线 | CompX 17 字节协议（`vgn_provider.py`） | 协议已实现 | 缺少实体设备验证 | 仅覆盖标准 CompX 方案型号 |

### 2. AULA / AJAZZ / Attack Shark / CHERRY / EPOMAKER / EWEADN / Redragon / Alienware / 荣元 / URX 无线键盘

| 品牌 / 方案 | 官方标准名称 / 代表型号 | 设备类型 | 支持的连接方式 | 电量读取协议 | 当前适配状态 | 实体设备验证状态 | 已知限制 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **AULA / Redragon 等** | AULA F75 / F75 Max、Redragon Horus Pro / V2（VID `0x3554` / `0x05AC` / `0x41E4`） | 无线键盘 | 2.4GHz | CompX BY `0x13` 20 字节只读协议（`wireless_keyboards.py`） | 协议已实现 | 缺少实体设备验证 | 内置 180 秒低打扰节流 |
| **Attack Shark / EWEADN / AJAZZ / AULA / EPOMAKER** | Attack Shark X85、EWEADN X87、AJAZZ AK820 Pro / MAX、AULA F87 Pro V2 / F99 MAX、EPOMAKER EA75（VID `0x0C45` / `0x05AC`） | 无线键盘 | 2.4GHz | SONiX 33 字节协议（共享 `05AC:024F` 时严格限定 Interface 3，隔离 QMK/VIA Interface 1） | 协议已实现 | 缺少实体设备验证 | 依赖接收器暴露 Interface 3 |
| **CHERRY / AJAZZ** | CHERRY MX 3.0S / MX 2.0S / MX 2.0S WL Pro / PIXIU 75、AJAZZ AK992（VID `0x046A` / `0x320F`） | 无线键盘 | 2.4GHz / USB 有线 | Evision `0x04 / 0x1A` 协议 | 协议已实现 | 缺少实体设备验证 | 仅支持 2.4G/有线 HID 模式 |
| **Semico / Alienware / 荣元 / URX** | Attack Shark X98、AJAZZ AK820 Max Plus、Alienware Pro Wireless Keyboard；荣元 2.4G 平台（Attack Shark / Akko / Royuan / MSI / Trust 等 80+ PID）；URX Core75（`36B0:3002`） | 无线键盘 | 2.4GHz / USB 有线 | Semico / Alienware / 荣元 `Feature 0xF7` / URX VIA `0xFF60:0x0061`（严格匹配产品名） | 协议已实现 | 缺少实体设备验证 | 荣元多 PID 固件可能存在差异 |

### 3. Logitech / ASTRO（参考：[logitechg.com](https://www.logitechg.com/)）

| 品牌 | 官方标准名称 / 代表型号 | 设备类型 | 支持的连接方式 | 电量读取协议 | 当前适配状态 | 实体设备验证状态 | 已知限制 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Logitech** | G Pro 2 Lightspeed、G Pro X Superlight 2 / 1、G502 / G304 / G305 / G903、MX Master / MX Anywhere / MX Keys / MX Mechanical（VID `0x046D`） | 鼠标 / 键盘 | 2.4GHz（槽位 1–6）/ USB 有线 | HID++ 2.0（`0x1004` UnifiedBattery、`0x1000`、`0x1001`、`0x1F20` + `0x0005` 名称查询） | 协议已实现 | 缺少实体设备验证 | G Pro 2 Lightspeed 与 G Pro X Superlight 2 独立精确映射 |
| **Logitech / ASTRO** | G533 / G535 / G633 / G635 / G733 / G933 / G935 / G Pro Wireless / G Pro X Wireless / G Pro X 2 & 3 Lightspeed / G522；ASTRO A50 Gen 4/5 / A50 X / A20 X（VID `0x046D` / `0x9886`） | 无线耳机 | 2.4GHz / USB 有线 | Logitech G Headset HID & Centurion 协议（`logitech_hidpp.py`、`wireless_headsets.py`） | 协议已实现 | 缺少实体设备验证 | 蓝牙模式走 Windows 蓝牙适配器 |

### 4. Razer（参考：[razer.com](https://www.razer.com/)）

| 品牌 | 官方标准名称 / 代表型号 | 设备类型 | 支持的连接方式 | 电量读取协议 | 当前适配状态 | 实体设备验证状态 | 已知限制 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Razer** | Viper V3 Pro / V2 Pro / Ultimate、DeathAdder V3 Pro / V2 Pro / V3 HyperSpeed、Basilisk V3 Pro / Ultimate、Orochi V2、Naga Pro、Cobra Pro（VID `0x1532`） | 无线鼠标 | 2.4GHz / USB 有线 | Razer 91 字节 Feature Report（`0x07/0x80`, `0x07/0x84`, XOR CRC，`razer_hid.py`） | 协议已实现 | 缺少实体设备验证 | 严格校验 `feature_length == 91`，`raw=1` 保底 `1%` |
| **Razer** | BlackWidow V3 Pro / V3 Mini / V4 Mini / V4 TKL / V4 Low-Profile / TKL HyperSpeed、DeathStalker V2 Pro / TKL、Pro Type Ultra / Ergo、Joro（VID `0x1532`） | 无线键盘 | 2.4GHz / USB 有线 | Razer 91 字节 Feature Report（`razer_hid.py`） | 协议已实现 | 缺少实体设备验证 | 部分老固件电量步进受硬件限制 |
| **Razer** | BlackShark V2 Pro (2020/2023) / V2 HyperSpeed / V3 / V3 X HyperSpeed、Kraken V4 / V4 Pro / Kitty V3 Pro、Barracuda Pro（VID `0x1532`） | 无线耳机 | 2.4GHz / USB 有线 | Razer Audio HID 协议（`wireless_headsets.py`） | 协议已实现 | 缺少实体设备验证 | BlackShark V3 内置 5 分钟防断连节流 |

### 5. SteelSeries / Corsair / HyperX / ASUS ROG / Sony

| 品牌 | 官方标准名称 / 代表型号 | 设备类型 | 支持的连接方式 | 电量读取协议 | 当前适配状态 | 实体设备验证状态 | 已知限制 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **SteelSeries** | Aerox 3 / 5 / 9 / 3 Gen 2、Prime / Mini、Rival 3 / 650 鼠标；Arctis 1 / 7 / 7+ / 9 / Pro、Arctis Nova 3P / 5 / 7（15 PID）/ Pro / Pro Omni / Elite、GameBuds（VID `0x1038`） | 鼠标 / 耳机 / 耳塞 | 2.4GHz / USB 有线 | SteelSeries HID 协议（`steelseries_hid.py`） | 协议已实现 | 缺少实体设备验证 | 蓝牙模式依赖 Windows 蓝牙接口 |
| **Corsair** | Dark Core / Harpoon / Katar / M75 / Sabre / Scimitar 鼠标；K57 / K65 Plus / K70 Pro Mini / K70 Core TKL / K100 Air / MAKR 75 键盘；Void / Pro / Elite / v2、HS70 / Pro、Virtuoso / SE / XT / MAX、HS80 / MAX 耳机（VID `0x1B1C`） | 鼠 / 键 / 耳机 | 2.4GHz / USB 有线 | SLIPSTREAM Bragi (`0xFF42:0x0001`，千分比标准四舍五入) & Void/HS70 协议（`corsair_hid.py`） | 协议已实现 | 缺少实体设备验证 | 需接收器处于 SLIPSTREAM/HID 模式 |
| **HyperX** | Cloud Alpha / Alpha 2 / II (HP & Kingston) / III / III S / II Core / Flight / Flight S / Stinger 2 / Stinger Core (DTS) 耳机；Pulsefire Haste / Haste 2 / 2 Core / 2 Mini / Dart 鼠标（VID `0x03F0` / `0x0951`） | 耳机 / 鼠标 | 2.4GHz / USB 有线 | HyperX HID 协议（Stinger Core 采用电压分段线性插值，`hyperx_hid.py`） | 协议已实现 | 缺少实体设备验证 | 电压插值存在轻微小幅波动属正常现象 |
| **ASUS ROG / TUF** | ROG Chakram / Gladius / Keris / Harpe Ace / Spatha X / Pugio II / Strix Impact II / Carry、TUF M4、ROG Azoth / Falchion / Strix Scope II 96、Omni (`0x1ACE`) / SpeedNova 8K (`0x1AD0`)；ROG Pelta / Delta II / Cetra SpeedNova（左/右/盒）/ Cetra Open / Strix Go 2.4（VID `0x0B05`） | 鼠 / 键 / 耳机 / 耳塞 | 2.4GHz / USB 有线 | ASUS ROG HID 协议（Strix Go 2.4 电压分段线性插值，`extra_brands.py`） | 协议已实现 | 缺少实体设备验证 | Armoury Crate 同时占用时可能影响响应 |
| **Sony** | INZONE H5 (`0x0EBF`)、INZONE H9 II (`0x0FA8`)、INZONE Buds (`0x0EC2`，左/右/盒)、PULSE 3D (`0x0D5E`)（VID `0x054C`） | 耳机 / 耳塞 | 2.4GHz | INZONE HID（`extra_brands.py`）；PULSE 3D 常驻只读异步监听 `0xB0` 报告（`wireless_headsets.py`） | 协议已实现 | 缺少实体设备验证 | PULSE 3D 依赖被动报文上报，已实现休眠/插拔/退出完整释放句柄 |

### 6. JBL / EPOS / Audeze / AKG / Skullcandy / Alienware / Poly / Jabra / Fractal / 水月雨 / FIFINE / Lenovo 无线耳机

| 品牌 | 官方标准名称 / 代表型号 | 设备类型 | 支持的连接方式 | 电量读取协议 | 当前适配状态 | 实体设备验证状态 | 已知限制 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **JBL / EPOS / Audeze / AKG / Skullcandy / FIFINE / Lenovo** | JBL Quantum 350/360/520/520X/610/650/650X/810/850/910/950/950X、EPOS H3PRO Hybrid、Audeze Maxwell（含有线 `0x4B1A`）/ Maxwell 2、AKG N9 Hybrid、Skullcandy PLYR / Crusher PLYR 720、FIFINE HT6、Lenovo Wireless VoIP | 无线耳机 | 2.4GHz / USB 有线 | 专用只读 HID & Airoha RACE 控制管道 `HidD_GetInputReport(0x07)`（`wireless_headsets.py`） | 协议已实现 | 缺少实体设备验证 | 需固件未加密对应 HID 集合 |
| **Alienware / Poly / Jabra / Fractal / 水月雨** | Alienware AW920H (`413C:A515`)、Poly Voyager BT600 (`047F:02EE/02F7`)、Jabra Link 380 / 390 / Evolve2 65 Flex / Evolve3 75 (`0B0E`)、Fractal Design Scape (`36BC`)、MOONDROP 水月雨 GM01 Pro (`35D8:0133`) | 无线耳机 | 2.4GHz / USB 有线 | 专用只读 HID（Poly BT600 含 Hello ACK 握手与标准四舍五入，`wireless_headsets.py`） | 协议已实现 | 缺少实体设备验证 | 依赖对应接收器 HID 接口 |

### 7. Apple / 标准蓝牙外设（iKF、漫步者、Keychron 等）与标准 USB HID 通用设备

| 品牌 / 类别 | 官方标准名称 / 代表型号 | 设备类型 | 支持的连接方式 | 电量读取协议 | 当前适配状态 | 实体设备验证状态 | 已知限制 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Apple Magic Keyboard** | Apple Magic Keyboard（含数字小键盘 / Touch ID 多代款） | 无线键盘 | 蓝牙连接 | 只读 `HidD_GetInputReport(0x90)`（`wireless_keyboards.py`） | 协议已实现 | 缺少实体设备验证 | 零写操作，不占用键盘输入通道 |
| **标准蓝牙外设（MAC 跨节点聚合）** | iKF（King / Solo / V11 蓝牙模式）、漫步者 Edifier / HECATE、水月雨、Bose、Sennheiser、Marshall、Soundcore、Shokz、Sony WH-1000XM5 等耳机；Keychron / NuPhy / Royal Kludge / Akko / DAREU / MelGeek / Lofree / HHKB / NIZ 等蓝牙键盘 | 耳机 / 键盘 / 鼠标 | 蓝牙连接（HFP / BLE GATT `0x180F`） | Windows SetupAPI `DEVPKEY_Device_BatteryLevel` 按 12 位 MAC 跨节点聚合（兼容 4 字节 `UINT32`，`bluetooth_provider.py`） | 协议已实现 | 缺少实体设备验证 | 依赖本机蓝牙适配器与 Windows 上报电量属性；本机无蓝牙硬件 |
| **标准 USB HID 通用电池兜底** | 任意在 HID 描述符中公开标准 `Battery Strength (0x06:0x20)` 特征报告的无线外设 | 鼠 / 键 / 耳机 | 2.4GHz / USB 有线 | 零写操作只读 `HidD_GetFeature`（`standard_hid.py`），自动跳过专用适配器已认领 `(vid, pid)` 与蓝牙 HID | 协议已实现 | 缺少实体设备验证 | 仅对遵循标准 USB HID 电池规范的固件有效，内置 120s 节流 |

---

## 三、已知协议但尚未实现（或需额外运行环境）

| 品牌 / 设备类型 | 已知协议方向 | 当前状态 | 未实现 / 待补齐原因 |
| :--- | :--- | :--- | :--- |
| **雷柏（Rapoo）多代 2.4G 鼠标** | 各代 2.4G 接收器存在私有 HID 报告格式（`vgn_provider.py` 目前仅做安全识别，不盲发写入） | 已知协议方向，尚未实现完整电量读取 | 各代固件报告偏移与命令字差异大，遵循「禁止盲写」红线，需收集真实设备脱敏诊断报文确认安全只读命令后再实现 |
| **Apple AirPods / Beats 实时 BLE 广播被动监听** | Apple Continuity BLE `0x004C / 0x07` 广播报文（左/右/盒独立电量解析器已在 `bluetooth_provider.py` 实现并通过单测） | 报文解析已实现；实时 WinRT BLE 被动扫描未内置打包 | 需在具备蓝牙适配器的 Windows 机器上评估并集成可选 WinRT BLE 依赖（`winrt-Windows.Devices.Bluetooth.Advertisement`、`winrt-Windows.Storage.Streams`）并做真机验证 |

---

## 四、暂不支持（明确边界）

| 设备 / 场景 | 暂不支持原因 | 建议替代方案 |
| :--- | :--- | :--- |
| **部分纯 USB Audio 型 2.4G 接收器**（如部分 iKF 2.4G 接收器 / Megawin `0E6A:0110`） | 仅向系统暴露标准 USB Audio 音频接口，未公开 HID 电量报告通道（也未暴露标准 `0x06:0x20`） | 推荐切换至**蓝牙模式**读取电量，或导出脱敏 `diagnostics_*.json` 提交 Issue 协助核查 |
| **仅通过闭源内核驱动通信、不暴露标准 HID 集合的极少数外设** | BattDock 坚持免装第三方驱动、不注入系统服务与内核驱动的安全原则 | 暂无法免驱支持 |
| **无蓝牙适配器的电脑读取纯蓝牙外设 / AirPods** | 缺乏物理蓝牙硬件与 Windows 蓝牙服务 | 软件自动静默跳过且零报错，不影响 USB 2.4G 外设监控 |
| **无线充电底座或有线供电但不回报百分比的固件** | 设备固件本身不提供真实百分比数值 | 仅展示「充电中」或 `—`，绝不伪造 `0%` 或虚假估算电量 |

---

## 如何协助补充或实测验证设备？

打开 BattDock「**设置 → 关于软件 → 导出诊断**」（或点击「**复制诊断**」/ 系统托盘右键「**导出设备诊断报告**」），生成不含个人路径与序列号的脱敏 `diagnostics_*.json`（仅含 `VID/PID`、`Usage Page/Usage` 与原始硬件名），通过 [设备适配申请模板](./.github/ISSUE_TEMPLATE/device_support.md) 提交 Issue 即可协助完善只读适配或完成实体设备验证晋升。
