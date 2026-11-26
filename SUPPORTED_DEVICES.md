# 支持设备清单与验证状态说明（SUPPORTED_DEVICES）

本清单是 **BattDock** 面向开发者与用户的权威设备兼容性记录，严格区分以下三类兼容状态，**绝不将未经真机实测的设备标注为已真机验证**：

> 说明：软件内「设置 → 关于软件 → 支持设备清单」子页面面向普通用户保持简洁中性展示，不直接显示测试状态标签；真实测试状态统一保留于本文件、底层设备数据库及脱敏诊断报告中。

| 状态标识 | 含义 |
| :--- | :--- |
| **已真实设备验证** | 已在本机真实物理外设上完成完整只读查询与状态回归测试 |
| **协议已实现待实测** | 已依据公开硬件协议完成独立只读实现并通过模拟报文单元测试，待对应真机接入验证 |
| **暂不支持** | 因缺少公开协议、使用加密私有通道或当前硬件环境限制，暂不支持读取真实电量 |

---

## 一、已真实设备验证

| 品牌 | 标准显示型号 | VID / PID | 连接方式 | 协议通道 | 验证状态 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **VGN** | **VGN Dragonfly F2 Pro Max** | `0x3554` / `0xFB3E`（2.4G）、`0xFB3D`（有线） | 2.4GHz 无线连接 / USB 有线连接 | Interface 1, Usage Page `0xFF02`, Usage `0x0002`, 17 字节会话报文（`0x04`） | **已真实设备验证** |

---

## 二、协议已实现待实测（已通过单元测试）

### 1. VGN / VXE / ATK / MCHOSE / LAMZU / CompX 方案
| 品牌 | 覆盖型号示例 | VID | 连接方式 | 验证状态 |
| :--- | :--- | :--- | :--- | :--- |
| VGN / VXE / ATK 鼠标 | F2 Master+、F1 Pro / MOBA、Dragonfly 4K、VXE R1 Pro Max / SE+、ATK F1 / X1 系列 | `0x3554` / `0x373B` | 2.4GHz 无线连接 / USB 有线连接 | 协议已实现待实测 |
| VGN / VXE / ATK 无线键盘 | VGN V98 Pro / V98 Pro V2 / V98 Pro V3、S99、N75 Pro / N75 V2、V87 V2、V108、VXE75 / VXE75 V2、VXE V87、ATK V75X / Z87 | `0x258A` / `0x391D` / `0x320F` / `0x373B` | 2.4GHz 无线连接 / USB 有线连接 | 协议已实现待实测 |
| VGN 无线耳机 | VGN OMNISOUND | `0x372E` | 2.4GHz 无线连接 | 协议已实现待实测 |
| MCHOSE 鼠标 / 键盘 / 耳机 | A5 / G3 / A7 / L7 / K7 鼠标；G75 / G87 / G98 / K87 / K87 V3 / K99 / X75 / Z75 / GX87 / KX75 / UT98 键盘；MCHOSE X9 / V9 Pro / V9 Pro 2 耳机 | `0x35A4` / `0x248A` / `0x3554` / `0x41E4` / `0x3837` / `0x291D` | 2.4GHz 无线连接 / USB 有线连接 | 协议已实现待实测 |
| LAMZU / Zaopin / Scyrox | 采用标准 CompX `0xFF02:0x0002` 17 字节协议的型号 | `0x3554` / `0x373B` | 2.4GHz 无线连接 / USB 有线连接 | 协议已实现待实测 |

### 2. AULA / AJAZZ / Attack Shark / CHERRY / EPOMAKER / EWEADN / Redragon / Alienware 无线键盘
| 品牌 / 方案 | 覆盖型号示例 | VID | 连接方式 | 验证状态 |
| :--- | :--- | :--- | :--- | :--- |
| CompX BY（`0x13` 20B） | AULA F75 / F75 Max、Redragon Horus Pro / V2 及上述 MCHOSE / VGN 型号 | `0x3554` / `0x05AC` / `0x41E4` | 2.4GHz 无线连接 | 协议已实现待实测 |
| SONiX（33B，严格隔离 QMK/VIA） | Attack Shark X85、EWEADN X87、AJAZZ AK820 Pro / MAX、AULA F87 Pro V2 / F99 MAX、EPOMAKER EA75 | `0x0C45` / `0x05AC`（仅 Interface 3） | 2.4GHz 无线连接 | 协议已实现待实测 |
| Evision（`0x04 / 0x1A`） | CHERRY MX 3.0S Wireless / MX 2.0S Wireless / MX 2.0S WL Pro / PIXIU 75、AJAZZ AK992 及上述 ATK / VGN / VXE 型号 | `0x046A` / `0x320F` / `0x373B` | 2.4GHz 无线连接 / USB 有线连接 | 协议已实现待实测 |
| Semico / Alienware / 荣元 / URX | Attack Shark X98、AJAZZ AK820 Max Plus、Alienware Pro Wireless Gaming Keyboard；荣元（Rongyuan）2.4G 键盘接收器平台（覆盖 Attack Shark / Akko / Royuan / MSI / Trust 等 80+ PID）；URX Core75（VIA `0xFF60:0x0061`） | `0x1A2C` / `0x413C` / `0x36B0` / 荣元多 VID | 2.4GHz 无线连接 / USB 有线连接 | 协议已实现待实测 |

### 3. Logitech / ASTRO（官网参考：[logitechg.com](https://www.logitechg.com/)）
| 类型 | 覆盖型号 / 协议 | VID | 连接方式 | 验证状态 |
| :--- | :--- | :--- | :--- | :--- |
| 鼠标 / 键盘 | 支持 HID++ 2.0 电池特性（`0x1004` UnifiedBattery、`0x1000` BatteryStatus、`0x1001` BatteryVoltage、`0x1F20` ADC）的 **Logitech G Pro 2 Lightspeed**、**Logitech G Pro X Superlight 2**、Logitech G Pro X Superlight、G502 / G304 / G305 / G903、MX Master / MX Anywhere / MX Keys / MX Mechanical 等（注：G Pro 2 Lightspeed 与 G Pro X Superlight 2 为不同型号，底层独立精确映射） | `0x046D` | 2.4GHz 无线连接（接收器槽位 1–6）/ USB 有线连接 | 协议已实现待实测 |
| 无线耳机 | Logitech G533 Wireless、G535 Lightspeed、G633、G635、G733 Lightspeed、G933、G935、G Pro Wireless Headset、G Pro X Wireless、G Pro X 2 / G Pro X 3 Lightspeed（Centurion）、G522 Lightspeed；ASTRO A50 Gen 4 / A50 Gen 5 / A50 X / A20 X | `0x046D` / `0x9886` | 2.4GHz 无线连接 / USB 有线连接 | 协议已实现待实测 |

### 4. Razer（官网参考：[razer.com](https://www.razer.com/)）
| 类型 | 覆盖型号示例 | VID | 连接方式 | 验证状态 |
| :--- | :--- | :--- | :--- | :--- |
| 无线鼠标 | Razer Viper V3 Pro / V2 Pro / Ultimate、DeathAdder V3 Pro / V2 Pro / V3 HyperSpeed、Basilisk V3 Pro / Ultimate、Orochi V2、Naga Pro、Cobra Pro 等 | `0x1532` | 2.4GHz 无线连接 / USB 有线连接 | 协议已实现待实测 |
| 无线键盘 | Razer BlackWidow V3 Pro / V3 Mini / V4 Mini / V4 TKL / V4 Low-Profile / V4 Low-Profile TKL HyperSpeed、DeathStalker V2 Pro / V2 Pro TKL、Pro Type Ultra / Pro Type Ergo、Razer Joro（91 字节 Feature Report） | `0x1532` | 2.4GHz 无线连接 / USB 有线连接 | 协议已实现待实测 |
| 无线耳机 | Razer BlackShark V2 Pro (2020/2023) / V2 HyperSpeed / V3（内置 5 分钟防断连节流）/ V3 X HyperSpeed、Kraken V4 / V4 Pro / Kitty V3 Pro、Barracuda Pro | `0x1532` | 2.4GHz 无线连接 / USB 有线连接 | 协议已实现待实测 |

### 5. SteelSeries（官网参考：[steelseries.com](https://steelseries.com/)）
| 类型 | 覆盖型号示例 | VID | 连接方式 | 验证状态 |
| :--- | :--- | :--- | :--- | :--- |
| 无线鼠标 | SteelSeries Aerox 3 / 5 / 9 Wireless、Aerox 3 Gen 2、Prime Wireless / Mini、Rival 3 / 650 Wireless | `0x1038` | 2.4GHz 无线连接 / USB 有线连接 | 协议已实现待实测 |
| 无线耳机 / 耳塞 | SteelSeries Arctis 1 / 7 / 7+ / 9 / Pro Wireless、Arctis Nova 5 / Nova 3P / Nova 7（完整 15 PID）/ Nova Pro Wireless / Nova Pro Omni / Nova Elite、Arctis GameBuds | `0x1038` | 2.4GHz 无线连接 | 协议已实现待实测 |

### 6. Corsair（官网参考：[corsair.com](https://www.corsair.com/)）
| 类型 | 覆盖型号示例 | VID | 连接方式 | 验证状态 |
| :--- | :--- | :--- | :--- | :--- |
| 无线鼠标 / 键盘 | 支持 SLIPSTREAM Bragi 协议（Usage Page `0xFF42`）的 Dark Core、Harpoon、Katar、M75、Sabre、Scimitar、K57 / K65 Plus / K70 Pro Mini / K70 Core TKL / K100 Air / MAKR 75 等 | `0x1B1C` | 2.4GHz 无线连接 / USB 有线连接 | 协议已实现待实测 |
| 无线耳机 | Corsair Void RGB / Pro / Elite / Void v2、HS70 / HS70 Pro、Virtuoso RGB Wireless / SE / XT / MAX、HS80 RGB / HS80 MAX Wireless | `0x1B1C` | 2.4GHz 无线连接 / USB 有线连接 | 协议已实现待实测 |

### 7. HyperX（官网参考：[hyperx.com](https://hyperx.com/)）
| 类型 | 覆盖型号示例 | VID | 连接方式 | 验证状态 |
| :--- | :--- | :--- | :--- | :--- |
| 无线耳机 | HyperX Cloud Alpha / Cloud Alpha 2 Wireless、Cloud II Wireless（HP / Kingston）、Cloud III / Cloud III S Wireless、Cloud II Core Wireless、Cloud Flight / Flight S、Cloud Stinger 2 / Stinger Core Wireless (DTS) | `0x03F0` / `0x0951` | 2.4GHz 无线连接 | 协议已实现待实测 |
| 无线鼠标 | HyperX Pulsefire Haste 2 / 2 Core / 2 Mini Wireless、Pulsefire Haste Wireless、Pulsefire Dart | `0x03F0` / `0x0951` | 2.4GHz 无线连接 / USB 有线连接 | 协议已实现待实测 |

### 8. ASUS ROG / TUF（官网参考：[rog.asus.com](https://rog.asus.com/)）
| 类型 | 覆盖型号示例 | VID | 连接方式 | 验证状态 |
| :--- | :--- | :--- | :--- | :--- |
| 无线鼠标 / 键盘 | ROG Chakram / Chakram X、Gladius II / III / III AimPoint、Keris Wireless / AimPoint / II Ace / II Origin、Harpe Ace / Mini / Extreme / II Ace、Spatha X、Pugio II、Strix Impact II、Strix Carry、TUF M4、ROG Azoth / Falchion / Strix Scope II 96 及 ROG Omni（`0x1ACE`）/ SpeedNova 8K（`0x1AD0`）接收器 | `0x0B05` | 2.4GHz 无线连接 / USB 有线连接 | 协议已实现待实测 |
| 无线耳机 / 耳塞 | ROG Pelta、ROG Delta II、ROG Cetra True Wireless SpeedNova（含左/右/盒独立电量）、ROG Cetra Open、ROG Strix Go 2.4 | `0x0B05` | 2.4GHz 无线连接 | 协议已实现待实测 |

### 9. JBL / EPOS / Audeze / AKG / Skullcandy / FIFINE / Lenovo / Alienware / Poly / Jabra / Fractal Design / 水月雨 无线耳机
| 类型 | 覆盖型号示例 | VID | 连接方式 | 验证状态 |
| :--- | :--- | :--- | :--- | :--- |
| JBL Quantum | Quantum 350 / 360 / 520 / 520X / 610 / 650 / 650X / 810 / 850 / 910 / 950 / 950X Wireless | `0x0ECB` | 2.4GHz 无线连接 / USB 有线连接 | 协议已实现待实测 |
| Airoha RACE / EPOS / 其他 | Audeze Maxwell / Maxwell 2、EPOS H3PRO Hybrid、AKG N9 Hybrid、Skullcandy PLYR / Crusher PLYR 720、FIFINE HT6、Lenovo Wireless VoIP Headset | `0x3329` / `0x1395` / `0x0ECB` / `0x34F0` / `0x3142` / `0x17EF` | 2.4GHz 无线连接 / USB 有线连接 | 协议已实现待实测 |
| Alienware / Poly / Jabra / Fractal / 水月雨 | Alienware AW920H（`413C:A515`）、Poly Voyager BT600（`047F:02EE/02F7`）、Jabra Link 380 / Link 390 / Evolve2 65 Flex / Evolve3 75（`0B0E`）、Fractal Design Scape（`36BC`）、MOONDROP 水月雨 GM01 Pro（`35D8:0133`） | `0x413C` / `0x047F` / `0x0B0E` / `0x36BC` / `0x35D8` | 2.4GHz 无线连接 / USB 有线连接 | 协议已实现待实测 |

### 10. Sony（官网参考：[sony.com](https://www.sony.com/)）
| 类型 | 覆盖型号示例 | VID | 连接方式 | 验证状态 |
| :--- | :--- | :--- | :--- | :--- |
| 无线耳机 / 耳塞 | Sony INZONE H5（`0x0EBF`）、Sony INZONE H9 II（`0x0FA8`）、Sony INZONE Buds（`0x0EC2`，含左/右/盒独立电量）、Sony PULSE 3D（`0x0D5E`） | `0x054C` | 2.4GHz 无线连接 | 协议已实现待实测 |

### 11. iKF / 漫步者 / Keychron / NuPhy / Apple 与标准蓝牙及标准 USB HID 通用设备
| 类型 | 覆盖型号 / 服务 | 连接方式 | 说明 | 验证状态 |
| :--- | :--- | :--- | :--- | :--- |
| Apple AirPods / Beats | AirPods 1/2/3/4/4 ANC、AirPods Pro 1/2/2 USB-C/3、AirPods Max / USB-C / 2、Beats 全系 | 蓝牙连接（BLE Continuity `0x004C / 0x07`） | 解析器已实现左/右/盒独立电量与充电位；运行时依赖本机蓝牙适配器及可选 WinRT BLE 监听 | 协议已实现待实测 |
| Apple Magic Keyboard | Apple Magic Keyboard（含数字小键盘 / Touch ID 多代蓝牙款） | 蓝牙连接（只读 `HidD_GetInputReport(0x90)`） | 零写操作、不占用键盘输入通道 | 协议已实现待实测 |
| 标准蓝牙外设（MAC 跨节点聚合） | **iKF**（King / Solo / V11 等蓝牙模式）、漫步者 Edifier / HECATE、水月雨 MOONDROP、Bose、Sennheiser、Marshall、Soundcore、Shokz、Audio-Technica、Xiaomi / HUAWEI / OPPO / Samsung / Nothing；以及 **Keychron / NuPhy / Royal Kludge (RK) / Akko / DAREU / MelGeek / Lofree / WOBKEY / CIDOO / LEOBOG / HHKB / NIZ** 等蓝牙无线键盘 | 蓝牙连接（HFP / BLE GATT `0x180F`） | 按 12 位蓝牙 MAC 自动聚合主节点型号、在线状态与 HFP/BLE 子节点电量，彻底修复 Windows 蓝牙耳机漏识别 | 协议已实现待实测 |
| 标准 USB HID 通用电池（`0x06:0x20`） | 任何在 HID 报告描述符中暴露标准 Generic Device Controls `Battery Strength`（Usage Page `0x06`, Usage `0x20`）特征报告的 2.4G / 有线无线耳机、无线键盘或鼠标 | 2.4GHz 无线连接 / USB 有线连接 | 零写操作、仅只读 `HidD_GetFeature`，自动跳过专用品牌与蓝牙 HID，作为广谱兜底 | 协议已实现待实测 |

---

## 三、暂不支持（明确说明）

| 设备 / 场景 | 暂不支持原因 |
| :--- | :--- |
| **部分纯 USB 音频型 2.4G 接收器（如部分 iKF 2.4G 接收器 / Megawin `0E6A:0110` 等）** | 该类接收器仅向系统暴露标准 USB Audio 音频设备而未公开 HID 电量报告通道；如固件暴露标准 HID `0x06:0x20` 电量则会自动识别，否则建议切换至**蓝牙模式**读取电量，或导出脱敏 `diagnostics_*.json` 协助后续分析 |
| **部分采用非标准加密私有协议的雷柏（Rapoo）旧款 2.4G 鼠标** | 各代固件报告格式差异大，在未取得确切安全只读协议前禁止盲发写入报文，仅做安全识别 |
| **无蓝牙适配器的电脑使用纯蓝牙 / AirPods 监听** | 依赖系统蓝牙硬件，软件会安全降级并静默跳过，不影响 USB 2.4G 设备监控 |
| **仅通过官方闭源内核驱动通信、不暴露标准 HID 集合的极少数设备** | BattDock 坚持免装第三方驱动、不注入系统服务的安全原则 |
| **无线充电底座或有线供电但不回报百分比的固件** | 仅展示真实状态（如「充电中」或 `—`），绝不伪造 `0%` 或虚假电量 |

---

## 如何协助补充新设备？

打开 BattDock「**设置 → 关于软件 → 导出诊断**」（或系统托盘右键「**导出设备诊断报告**」），即可生成不含隐私信息的 `diagnostics_*.json`（含 `VID/PID`、`Usage Page/Usage` 与原始硬件名），提交至 GitHub Issue 后即可据此添加安全只读适配器。
