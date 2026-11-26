# 支持设备清单与验证状态说明（SUPPORTED_DEVICES）

本清单严格区分以下三类兼容状态，**绝不将未经真机实测的设备标注为已真机验证**：

| 状态标识 | 含义 |
| :--- | :--- |
| **已真实设备验证** | 已在本机真实物理外设上完成完整读写与状态回归测试 |
| **协议已实现待实测** | 已依据公开硬件协议完成独立只读实现并通过模拟报文单元测试，待对应真机接入验证 |
| **暂不支持** | 因缺少公开协议、使用加密私有通道或当前环境限制，暂不支持读取真实电量 |

---

## 一、已真实设备验证

| 品牌 | 型号 | VID / PID | 连接方式 | 协议通道 | 验证状态 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **VGN** | **VGN Dragonfly F2 Pro Max** | `0x3554` / `0xFB3E`（2.4G）、`0xFB3D`（有线） | 2.4G 接收器 / 有线 | Interface 1, Usage Page `0xFF02`, Usage `0x0002`, 17 字节会话报文（`0x04`） | **已真实设备验证** |

---

## 二、协议已实现待实测（已通过单元测试）

### 1. VGN / VXE / ATK / 迈从 / 雷柏 / CompX 方案
| 品牌 | 覆盖型号示例 | VID | 连接方式 | 验证状态 |
| :--- | :--- | :--- | :--- | :--- |
| VGN / VXE / ATK | F2 Master+、F1 Pro / MOBA、Dragonfly 4K、VXE R1 Pro Max / SE+、ATK F1 / X1 系列 | `0x3554` / `0x373B` | 2.4G / 有线 | 协议已实现待实测 |
| MCHOSE 迈从 | A5 / G3 / A7 / L7 / K7 等支持 Feature Report `0x11` (XOR 0xFF) 型号 | `0x35A4` / `0x248A` | 2.4G / 有线 | 协议已实现待实测 |
| LAMZU / Zaopin / Scyrox | 采用标准 CompX `0xFF02:0x0002` 17 字节协议的型号 | `0x3554` / `0x373B` | 2.4G / 有线 | 协议已实现待实测 |

### 2. Logitech 罗技（官网参考：[logitechg.com](https://www.logitechg.com/)）
| 类型 | 覆盖型号 / 协议 | VID | 连接方式 | 验证状态 |
| :--- | :--- | :--- | :--- | :--- |
| 鼠标 / 键盘 | 支持 HID++ 2.0 电池特性（`0x1004` UnifiedBattery、`0x1000` BatteryStatus、`0x1001` BatteryVoltage、`0x1F20` ADC）的 **Logitech G Pro 2 Lightspeed**、**Logitech G Pro X Superlight 2**、Logitech G Pro X Superlight、G502 / G304 / G305 / G903、MX Master / MX Anywhere / MX Keys 等（注：G Pro 2 Lightspeed 与 G Pro X Superlight 2 为不同型号，底层独立映射） | `0x046D` | 2.4GHz 无线连接（Unifying / Bolt / Lightspeed 接收器槽位 1–6）/ USB 有线连接 | 协议已实现待实测 |
| 无线耳机 | Logitech G533、G535、G633、G635、G733、G933、G935、G Pro Wireless Headset、G Pro X Wireless、G Pro X 2 Lightspeed | `0x046D` | 2.4GHz 无线连接 | 协议已实现待实测 |

### 3. Razer 雷蛇（官网参考：[razer.com](https://www.razer.com/)）
| 类型 | 覆盖型号示例 | VID | 连接方式 | 验证状态 |
| :--- | :--- | :--- | :--- | :--- |
| 无线鼠标 / 键盘 | Razer Viper V3 Pro / V2 Pro / Ultimate、DeathAdder V3 Pro / V2 Pro / V3 HyperSpeed、Basilisk V3 Pro / Ultimate、Orochi V2、Naga Pro、BlackWidow V3 Pro、DeathStalker V2 Pro（需支持 91 字节 Feature Report） | `0x1532` | 2.4GHz 无线连接 / USB 有线连接 | 协议已实现待实测 |

### 4. SteelSeries 赛睿
| 类型 | 覆盖型号示例 | VID | 连接方式 | 验证状态 |
| :--- | :--- | :--- | :--- | :--- |
| 无线鼠标 | Aerox 3 / 5 / 9 Wireless、Aerox 3 Gen 2、Prime Wireless / Mini、Rival 3 / 650 Wireless | `0x1038` | 2.4G / 有线 | 协议已实现待实测 |
| 无线耳机 / 耳塞 | Arctis 7 / 7+ / 9、Arctis Nova 5 / Nova 7 / Nova Pro Wireless、Arctis GameBuds | `0x1038` | 2.4G 接收器 / 基站 | 协议已实现待实测 |

### 5. Corsair 海盗船
| 类型 | 覆盖型号示例 | VID | 连接方式 | 验证状态 |
| :--- | :--- | :--- | :--- | :--- |
| 无线鼠标 / 键盘 | 支持 SLIPSTREAM Bragi 协议（Usage Page `0xFF42`）的 Dark Core、Harpoon、Katar、M75、Sabre、K57/K65/K70 Wireless 等 | `0x1B1C` | SLIPSTREAM 2.4G / 有线 | 协议已实现待实测 |
| 无线耳机 | Void RGB / Pro / Elite Wireless、HS70 / HS70 Pro Wireless、Virtuoso / HS80 系列（Bragi） | `0x1B1C` | 2.4G USB 接收器 | 协议已实现待实测 |

### 6. HyperX
| 类型 | 覆盖型号示例 | VID | 连接方式 | 验证状态 |
| :--- | :--- | :--- | :--- | :--- |
| 无线耳机 | Cloud Alpha Wireless、Cloud II Wireless（HP）、Cloud III Wireless、Cloud II Core Wireless、Cloud Stinger 2 Wireless | `0x03F0` / `0x0951` | 2.4G USB 接收器 | 协议已实现待实测 |
| 无线鼠标 | Pulsefire Haste 2 / 2 Core / 2 Mini Wireless、Pulsefire Haste Wireless、Pulsefire Dart | `0x03F0` / `0x0951` | 2.4G / 有线 | 协议已实现待实测 |

### 7. ASUS ROG / TUF
| 类型 | 覆盖型号示例 | VID | 连接方式 | 验证状态 |
| :--- | :--- | :--- | :--- | :--- |
| 无线鼠标 / 键盘 | ROG Chakram / Chakram X、Gladius II / III / III AimPoint、Keris Wireless / AimPoint / II Ace / II Origin、Harpe Ace / Mini / Extreme / II Ace、Spatha X、Pugio II、Strix Impact II、Strix Carry、TUF M4、ROG Azoth / Falchion / Strix Scope II 96 及 ROG Omni (`0x1ACE`) / SpeedNova 8K (`0x1AD0`) 接收器 | `0x0B05` | 2.4G / Omni 接收器 / 有线 | 协议已实现待实测 |
| 无线耳机 / 耳塞 | ROG Pelta、ROG Delta II、ROG Cetra True Wireless SpeedNova（含 L/R/盒独立电量）、ROG Cetra Open、ROG Strix Go 2.4 | `0x0B05` | 2.4G USB 接收器 | 协议已实现待实测 |

### 8. Sony 索尼
| 类型 | 覆盖型号示例 | VID | 连接方式 | 验证状态 |
| :--- | :--- | :--- | :--- | :--- |
| 无线耳机 / 耳塞 | Sony INZONE H5 (`0x0EBF`)、INZONE H9 II (`0x0FA8`)、INZONE Buds (`0x0EC2`，含左/右/盒独立电量) | `0x054C` | 2.4G USB 接收器 | 协议已实现待实测 |

### 9. Apple AirPods / Beats 与标准蓝牙设备
| 类型 | 覆盖型号 / 服务 | 连接方式 | 说明 | 验证状态 |
| :--- | :--- | :--- | :--- | :--- |
| Apple AirPods / Beats | AirPods 1/2/3/4/4 ANC、AirPods Pro 1/2/2 USB-C/3、AirPods Max / USB-C / 2、Beats 全系 | 蓝牙 BLE Continuity 广播（`0x004C / 0x07`） | 解析器已实现左/右/盒独立电量与充电位；运行时依赖本机蓝牙适配器及可选 WinRT BLE 监听 | 协议已实现待实测 |
| 标准蓝牙外设 | 支持 Windows Bluetooth Battery Service（GATT `0x180F`）或 HFP 电量上报的任意蓝牙鼠标、耳机、键盘 | 经典蓝牙 / BLE | 通过 Windows SetupAPI 只读读取 `DEVPKEY_Device_BatteryLevel`；无蓝牙适配器时静默跳过 | 协议已实现待实测 |

---

## 三、暂不支持（明确说明）

| 设备 / 场景 | 暂不支持原因 |
| :--- | :--- |
| **部分采用非标准加密私有协议的雷柏（Rapoo）旧款 2.4G 鼠标** | 各代固件报告格式差异大，在未取得确切安全只读协议前禁止盲发写入报文，仅做安全识别提示 |
| **无蓝牙适配器的台式机使用纯蓝牙 / AirPods 监听** | 依赖系统蓝牙无线电硬件（如本测试机无蓝牙适配器），软件会安全降级并忽略，不影响 USB 2.4G 设备监控 |
| **仅通过官方闭源内核驱动通信、不暴露标准 HID 集合的极少数设备** | 本工具坚持不安装第三方驱动、不注入系统服务的安全原则 |
| **无线充电底座或仅显示有线供电但固件不回报百分比的设备** | 仅展示真实状态（如「充电中」或「未知 / 未响应」），绝不伪造电量数字 |

---

## 如何协助补充新设备？

点击软件主界面底部「**导出诊断**」（或托盘右键「**导出设备诊断报告**」），即可生成不含隐私信息的 `diagnostics_*.json` 文件，其中包含设备 `VID/PID`、`Usage Page/Usage` 与接口集合信息，可据此快速为新型号添加安全只读适配器。
