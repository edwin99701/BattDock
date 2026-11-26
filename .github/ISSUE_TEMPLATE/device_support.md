---
name: 设备适配申请
about: 反馈您希望 BattDock 支持的新无线鼠标、耳机或键盘型号
title: "[Device] "
labels: enhancement
---

## 设备信息
- **品牌与官方完整型号**：例如 `Logitech G Pro 2 Lightspeed`
- **设备类型**：鼠标 / 耳机 / 分体式耳塞 / 键盘
- **连接方式**：2.4GHz 接收器 / 蓝牙 / USB 有线
- **操作系统**：例如 `Windows 11` / `Windows 10 22H2`

## 脱敏诊断片段
请在 BattDock「设置 → 关于软件」中点击「导出诊断」，找到对应设备的 `vid`、`pid`、`usage_page`、`usage` 字段粘贴到下方：

```json
{
  "vid": "0x....",
  "pid": "0x....",
  "product_string": "..."
}
```

> **隐私提醒**：上传前请再次确认已移除任何个人目录路径、系统用户名或设备序列号，切勿公开敏感隐私信息。
