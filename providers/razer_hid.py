"""Razer 雷蛇无线鼠标与键盘 HID 适配器（90 字节只读 Feature Report 协议）。

协议参考（公开 OpenRazer 规范与 MIT 参考项目 qu1ncky/BatteryTray）：
- 91 字节 Feature Report（Report ID 0x00 + 90 字节帧），CRC 为字节 3..88 的异或值存于字节 89。
- 电量查询：Class 0x07, Command 0x80 -> 返回字节 10 (arguments[1]) 为 0..255，按 0..100% 映射。
- 充电查询：Class 0x07, Command 0x84 -> 返回字节 10 (arguments[1]) 非 0 表示充电中。
- 仅在目标集合 feature_length == 91 时执行只读查询，绝不向未知设备盲发。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import hid

from .base import (
    BatteryProvider,
    DeviceBattery,
    KIND_KEYBOARD,
    KIND_MOUSE,
    STATUS_PROTOCOL,
    get_hid_report_lengths,
)

RAZER_VID = 0x1532
REPORT_LEN = 91


@dataclass(frozen=True)
class RazerModel:
    key: str
    name: str
    kind: str
    wireless: bool
    tid: int
    interface: int
    wait_ms: int
    query_charging: bool = True


# 主流雷蛇无线鼠标与无线键盘表（含接收器与有线 PID）
RAZER_MODELS: dict[int, RazerModel] = {
    0x007A: RazerModel("viper-ultimate", "Razer Viper Ultimate", KIND_MOUSE, False, 0xFF, 0, 60),
    0x007B: RazerModel("viper-ultimate", "Razer Viper Ultimate", KIND_MOUSE, True, 0xFF, 0, 60),
    0x007C: RazerModel("deathadder-v2-pro", "Razer DeathAdder V2 Pro", KIND_MOUSE, False, 0x3F, 0, 60),
    0x007D: RazerModel("deathadder-v2-pro", "Razer DeathAdder V2 Pro", KIND_MOUSE, True, 0x3F, 0, 60),
    0x0083: RazerModel("basilisk-x-hyperspeed", "Razer Basilisk X HyperSpeed", KIND_MOUSE, True, 0xFF, 0, 32, False),
    0x0086: RazerModel("basilisk-ultimate", "Razer Basilisk Ultimate", KIND_MOUSE, False, 0x1F, 0, 32),
    0x0088: RazerModel("basilisk-ultimate", "Razer Basilisk Ultimate", KIND_MOUSE, True, 0x1F, 0, 32),
    0x008F: RazerModel("naga-pro", "Razer Naga Pro", KIND_MOUSE, False, 0x1F, 0, 2),
    0x0090: RazerModel("naga-pro", "Razer Naga Pro", KIND_MOUSE, True, 0x1F, 0, 32),
    0x0094: RazerModel("orochi-v2", "Razer Orochi V2", KIND_MOUSE, True, 0x1F, 0, 120, False),
    0x0095: RazerModel("orochi-v2", "Razer Orochi V2", KIND_MOUSE, True, 0x1F, 0, 120, False),
    0x009E: RazerModel("viper-mini-se", "Razer Viper Mini SE", KIND_MOUSE, False, 0x1F, 0, 60),
    0x009F: RazerModel("viper-mini-se", "Razer Viper Mini SE", KIND_MOUSE, True, 0x1F, 0, 60),
    0x00A5: RazerModel("viper-v2-pro", "Razer Viper V2 Pro", KIND_MOUSE, False, 0x1F, 0, 32),
    0x00A6: RazerModel("viper-v2-pro", "Razer Viper V2 Pro", KIND_MOUSE, True, 0x1F, 0, 32),
    0x00A7: RazerModel("naga-v2-pro", "Razer Naga V2 Pro", KIND_MOUSE, False, 0x1F, 0, 32),
    0x00A8: RazerModel("naga-v2-pro", "Razer Naga V2 Pro", KIND_MOUSE, True, 0x1F, 0, 32),
    0x00AA: RazerModel("basilisk-v3-pro", "Razer Basilisk V3 Pro", KIND_MOUSE, False, 0x1F, 0, 32),
    0x00AB: RazerModel("basilisk-v3-pro", "Razer Basilisk V3 Pro", KIND_MOUSE, True, 0x1F, 0, 32),
    0x00AF: RazerModel("cobra-pro", "Razer Cobra Pro", KIND_MOUSE, False, 0x1F, 0, 32),
    0x00B0: RazerModel("cobra-pro", "Razer Cobra Pro", KIND_MOUSE, True, 0x1F, 0, 32),
    0x00B3: RazerModel("hyperpolling", "Razer HyperPolling 4K/8K Mouse", KIND_MOUSE, True, 0x1F, 0, 60),
    0x00B6: RazerModel("deathadder-v3-pro", "Razer DeathAdder V3 Pro", KIND_MOUSE, False, 0x1F, 0, 32),
    0x00B7: RazerModel("deathadder-v3-pro", "Razer DeathAdder V3 Pro", KIND_MOUSE, True, 0x1F, 0, 32),
    0x00C2: RazerModel("deathadder-v3-pro", "Razer DeathAdder V3 Pro", KIND_MOUSE, False, 0x1F, 0, 32),
    0x00C3: RazerModel("deathadder-v3-pro", "Razer DeathAdder V3 Pro", KIND_MOUSE, True, 0x1F, 0, 32),
    0x00B8: RazerModel("viper-v3-hyperspeed", "Razer Viper V3 HyperSpeed", KIND_MOUSE, True, 0x1F, 0, 60, False),
    0x00BE: RazerModel("deathadder-v4-pro", "Razer DeathAdder V4 Pro", KIND_MOUSE, False, 0x1F, 0, 32),
    0x00BF: RazerModel("deathadder-v4-pro", "Razer DeathAdder V4 Pro", KIND_MOUSE, True, 0x1F, 0, 32),
    0x00C0: RazerModel("viper-v3-pro", "Razer Viper V3 Pro", KIND_MOUSE, False, 0x1F, 0, 32),
    0x00C1: RazerModel("viper-v3-pro", "Razer Viper V3 Pro", KIND_MOUSE, True, 0x1F, 0, 60),
    0x00C4: RazerModel("deathadder-v3-hs", "Razer DeathAdder V3 HyperSpeed", KIND_MOUSE, False, 0x1F, 0, 32),
    0x00C5: RazerModel("deathadder-v3-hs", "Razer DeathAdder V3 HyperSpeed", KIND_MOUSE, True, 0x1F, 0, 32),
    0x00CC: RazerModel("basilisk-v3-pro-35k", "Razer Basilisk V3 Pro 35K", KIND_MOUSE, False, 0x1F, 0, 32),
    0x00CD: RazerModel("basilisk-v3-pro-35k", "Razer Basilisk V3 Pro 35K", KIND_MOUSE, True, 0x1F, 0, 32),
    0x00E2: RazerModel("basilisk-v4-pro", "Razer Basilisk V4 Pro", KIND_MOUSE, False, 0x1F, 3, 32),
    0x00E3: RazerModel("basilisk-v4-pro", "Razer Basilisk V4 Pro", KIND_MOUSE, True, 0x1F, 3, 32),
    0x00E5: RazerModel("viper-v4-pro", "Razer Viper V4 Pro", KIND_MOUSE, False, 0x1F, 3, 60),
    0x00E6: RazerModel("viper-v4-pro", "Razer Viper V4 Pro", KIND_MOUSE, True, 0x1F, 3, 60),
    0x0258: RazerModel("blackwidow-v3-mini", "Razer BlackWidow V3 Mini HyperSpeed", KIND_KEYBOARD, False, 0x1F, 3, 2),
    0x0271: RazerModel("blackwidow-v3-mini", "Razer BlackWidow V3 Mini HyperSpeed", KIND_KEYBOARD, True, 0x9F, 3, 6),
    0x025A: RazerModel("blackwidow-v3-pro", "Razer BlackWidow V3 Pro", KIND_KEYBOARD, False, 0x3F, 2, 2),
    0x025C: RazerModel("blackwidow-v3-pro", "Razer BlackWidow V3 Pro", KIND_KEYBOARD, True, 0x9F, 2, 6),
    0x0292: RazerModel("deathstalker-v2-pro", "Razer DeathStalker V2 Pro", KIND_KEYBOARD, False, 0x1F, 3, 2),
    0x0290: RazerModel("deathstalker-v2-pro", "Razer DeathStalker V2 Pro", KIND_KEYBOARD, True, 0x9F, 2, 6),
    0x0298: RazerModel("deathstalker-v2-pro-tkl", "Razer DeathStalker V2 Pro TKL", KIND_KEYBOARD, False, 0x1F, 3, 2),
    0x0296: RazerModel("deathstalker-v2-pro-tkl", "Razer DeathStalker V2 Pro TKL", KIND_KEYBOARD, True, 0x9F, 2, 6),
    0x02B9: RazerModel("blackwidow-v4-mini", "Razer BlackWidow V4 Mini HyperSpeed", KIND_KEYBOARD, False, 0x1F, 3, 2),
    0x02BA: RazerModel("blackwidow-v4-mini", "Razer BlackWidow V4 Mini HyperSpeed", KIND_KEYBOARD, True, 0x9F, 3, 6),
    0x02D7: RazerModel("blackwidow-v4-tkl", "Razer BlackWidow V4 TKL HyperSpeed", KIND_KEYBOARD, False, 0x1F, 3, 2),
    0x02D5: RazerModel("blackwidow-v4-tkl", "Razer BlackWidow V4 TKL HyperSpeed", KIND_KEYBOARD, True, 0x9F, 2, 6),
    0x02CD: RazerModel("joro", "Razer Joro", KIND_KEYBOARD, True, 0x1F, 3, 2),
    0x02CC: RazerModel("blackwidow-v4-low-profile", "Razer BlackWidow V4 Low-Profile HyperSpeed", KIND_KEYBOARD, False, 0x1F, 3, 2),
    0x02C9: RazerModel("blackwidow-v4-low-profile", "Razer BlackWidow V4 Low-Profile HyperSpeed", KIND_KEYBOARD, True, 0x9F, 2, 6),
    0x02D4: RazerModel("blackwidow-v4-low-profile-tkl", "Razer BlackWidow V4 Low-Profile TKL HyperSpeed", KIND_KEYBOARD, False, 0x1F, 3, 2),
    0x02D2: RazerModel("blackwidow-v4-low-profile-tkl", "Razer BlackWidow V4 Low-Profile TKL HyperSpeed", KIND_KEYBOARD, True, 0x9F, 2, 6),
    0x0277: RazerModel("pro-type-ultra", "Razer Pro Type Ultra", KIND_KEYBOARD, False, 0x1F, 2, 2),
    0x027B: RazerModel("pro-type-ultra", "Razer Pro Type Ultra", KIND_KEYBOARD, True, 0x9F, 2, 6),
    0x02C4: RazerModel("pro-type-ergo", "Razer Pro Type Ergo", KIND_KEYBOARD, False, 0x1F, 3, 2),
    0x02C2: RazerModel("pro-type-ergo", "Razer Pro Type Ergo", KIND_KEYBOARD, True, 0x9F, 2, 6),
}


def build_razer_request(tid: int, cmd_class: int, cmd_id: int) -> list[int]:
    """构造 91 字节 Razer Feature Report（含 Report ID 0x00 与 XOR 校验和）。"""
    req = [0] * REPORT_LEN
    req[2] = tid & 0xFF
    req[6] = 0x02  # data size
    req[7] = cmd_class & 0xFF
    req[8] = cmd_id & 0xFF
    crc = 0
    for b in req[3:89]:
        crc ^= b
    req[89] = crc
    return req


def parse_razer_reply(reply: list[int] | bytes, cmd_class: int, cmd_id: int) -> Optional[list[int]]:
    """校验 Razer 91 字节回包，返回 80 字节 arguments；休眠/超时/不匹配返回 None。"""
    if len(reply) < REPORT_LEN:
        return None
    if reply[7] != cmd_class or reply[8] != cmd_id:
        return None
    if reply[1] not in (0x02, 0x01):  # 0x02 ok, 0x01 busy-but-valid
        return None
    return list(reply[9:89])


def raw_razer_level_to_percent(raw_byte: int) -> Optional[int]:
    """将 0..255 原始电量转换为 1..100%，0 视为休眠无效读数。"""
    pct = int(round(raw_byte * 100.0 / 255.0))
    if pct <= 0:
        return None
    return min(100, pct)


class RazerHidProvider(BatteryProvider):
    name = "razer_hid"
    brand = "Razer"

    def __init__(self) -> None:
        self._cache: dict[str, DeviceBattery] = {}

    def _send_cmd(self, dev: hid.device, model: RazerModel, cmd_class: int, cmd_id: int) -> Optional[list[int]]:
        req = build_razer_request(model.tid, cmd_class, cmd_id)
        for attempt in range(3):
            if attempt > 0:
                time.sleep(0.015)
            try:
                if dev.send_feature_report(req) < REPORT_LEN:
                    return None
                time.sleep(max(0.005, model.wait_ms / 1000.0))
                reply = dev.get_feature_report(0, REPORT_LEN)
            except OSError:
                return None
            args = parse_razer_reply(reply, cmd_class, cmd_id)
            if args is not None:
                return args
        return None

    def poll(self, hid_snapshot: list[dict]) -> list[DeviceBattery]:
        by_pid: dict[int, list[dict]] = {}
        for d in hid_snapshot:
            if d.get("vendor_id") != RAZER_VID:
                continue
            pid = d.get("product_id", 0)
            if pid in RAZER_MODELS:
                by_pid.setdefault(pid, []).append(d)

        out: list[DeviceBattery] = []
        for pid, colls in by_pid.items():
            model = RAZER_MODELS[pid]
            dev_id = f"razer:{model.key}"
            found_pct: Optional[int] = None
            charging = False

            for c in colls:
                if max(0, int(c.get("interface_number", 0))) != model.interface:
                    continue
                path = c.get("path")
                if not path:
                    continue
                _, _, feat_len = get_hid_report_lengths(path)
                if feat_len != REPORT_LEN:
                    continue
                dev = hid.device()
                try:
                    dev.open_path(path)
                    args = self._send_cmd(dev, model, 0x07, 0x80)
                    if args is not None and len(args) >= 2:
                        pct = raw_razer_level_to_percent(args[1])
                        if pct is not None:
                            found_pct = pct
                            if model.query_charging:
                                c_args = self._send_cmd(dev, model, 0x07, 0x84)
                                charging = bool(c_args and len(c_args) >= 2 and c_args[1] != 0)
                            break
                except OSError:
                    continue
                finally:
                    try:
                        dev.close()
                    except Exception:
                        pass

            if found_pct is not None:
                is_full = charging and found_pct >= 100
                item = DeviceBattery(
                    device_id=dev_id,
                    name=model.name,
                    brand="Razer",
                    kind=model.kind,
                    connection_mode="有线" if (not model.wireless or charging) else "2.4G",
                    vid=RAZER_VID,
                    pid=pid,
                    connected=True,
                    online=True,
                    percent=found_pct,
                    charging=charging and not is_full,
                    full=is_full,
                    support_status=STATUS_PROTOCOL,
                    provider_name=self.name,
                )
                self._cache[dev_id] = item
                out.append(item)
            else:
                prev = self._cache.get(dev_id)
                out.append(
                    DeviceBattery(
                        device_id=dev_id,
                        name=model.name,
                        brand="Razer",
                        kind=model.kind,
                        connection_mode="休眠" if model.wireless else "有线",
                        vid=RAZER_VID,
                        pid=pid,
                        connected=True,
                        online=False,
                        asleep=True,
                        percent=prev.percent if prev else None,
                        support_status=STATUS_PROTOCOL,
                        status_detail="休眠中",
                        provider_name=self.name,
                        timestamp=prev.timestamp if prev else time.time(),
                    )
                )
        return out
