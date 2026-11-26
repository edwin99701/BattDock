# 开源协议参考与第三方许可证声明（THIRD_PARTY_LICENSES）

本项目的架构设计与多品牌协议适配严格遵守开源许可证合规要求。在参考任何第三方开源项目前均已核查其 LICENSE 文件。

---

## 一、开源协议参考仓库核查记录

| 参考仓库 | 许可证 | 使用方式与合规说明 |
| :--- | :--- | :--- |
| [`qu1ncky/BatteryTray`](https://github.com/qu1ncky/BatteryTray) | **MIT License** | 参考了其公开整理的 Logitech HID++、Razer、SteelSeries、Corsair、HyperX、ASUS ROG、Sony INZONE、MCHOSE 等只读 HID 协议字段与报文规范，使用 Python 独立编写本项目的 `providers/` 适配器模块。 |
| [`JKWTCN/BatteryMonitor`](https://github.com/JKWTCN/BatteryMonitor) | **MIT License** | 参考了其公开整理的 ASUS ROG 鼠标型号表、MCHOSE `0x11` Feature Report XOR-0xFF 格式及 Apple AirPods Continuity BLE 广播字段解析规范，使用 Python 独立实现。 |
| [`Sapd/HeadsetControl`](https://github.com/Sapd/HeadsetControl) | **GPL-3.0**（强传染性 Copyleft） | **未复制或移植任何代码**。因 GPL-3.0 许可证兼容性限制，本项目仅参考了行业公开硬件通讯报文格式说明，全部实现为独立干净室 Python 代码。 |
| [`Fan4Metal/mouse_tray`](https://github.com/Fan4Metal/mouse_tray) | **无 LICENSE 文件** | **未复制或移植任何代码**（按开源版权规范，无明确许可证仓库视为保留全部权利，不得直接复用源码）。 |
| [`Capi005/batteryonpc`](https://github.com/Capi005/batteryonpc) | **无 LICENSE 文件** | **未复制或移植任何代码**。 |
| `krisgfx9/Wireless-Device-Battery-Monitor` | 仓库不可访问（HTTP 404） | 核查时仓库不存在，未引用。 |

### MIT 参考项目版权声明

以下 MIT 协议项目为本项目整理硬件只读报文格式提供了重要参考，特此保留其 MIT 许可证声明：

- **BatteryTray** (`qu1ncky/BatteryTray`) — Licensed under the MIT License.
- **BatteryMonitor** (`JKWTCN/BatteryMonitor`) — Licensed under the MIT License.

```text
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
```

---

## 二、本项目使用的 Python 第三方运行库许可证

| 依赖包 | 用途 | 许可证 |
| :--- | :--- | :--- |
| `hidapi` | 跨平台 USB HID 设备读写通信 | BSD-3-Clause / GPL-3.0 / HIDAPI Original（本项目按 BSD-3-Clause 使用） |
| `pywebview` | 基于 Edge WebView2 的桌面轻量窗口 | BSD-3-Clause |
| `pystray` | Windows 系统托盘图标与右键菜单 | LGPL-3.0（动态依赖使用） |
| `Pillow` | 矢量高清透明电池托盘图标与 ICO 渲染 | MIT-CMU（HPND） |
| `pythonnet` / `clr-loader` | WinForms 原生宿主与极速无边框置顶迷你弹窗 | MIT License |
| `PyInstaller` | Windows 独立可执行程序打包（仅构建期使用） | GPL-2.0 with Bootloader Exception（允许打包任意许可证应用） |
