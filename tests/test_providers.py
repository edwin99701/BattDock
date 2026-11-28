"""多品牌无线外设协议解析器与统一设备管理层自动化单元测试。"""

from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from providers import (
    BatteryProvider,
    BluetoothBatteryProvider,
    DeviceBattery,
    DeviceManager,
    KIND_EARBUDS,
    KIND_HEADSET,
    KIND_KEYBOARD,
    KIND_MOUSE,
    STATUS_PROTOCOL,
    STATUS_VERIFIED,
    parse_airpods_continuity,
    sanitize_device_reading,
)
from providers.corsair_hid import parse_bragi_property, parse_corsair_void_reply
from providers.extra_brands import (
    build_sony_inzone_request,
    parse_asus_cetra_speednova,
    parse_asus_keyboard_reply,
    parse_asus_mouse_reply,
    parse_asus_omni_pairs,
    parse_asus_rog_headset_cc,
    parse_asus_strix_go,
    parse_sony_inzone_buds,
    parse_sony_inzone_h5,
)
from providers.hyperx_hid import (
    parse_hyperx_alpha_battery,
    parse_hyperx_cloud2_hp,
    parse_hyperx_ngenuity2_heartbeat,
    parse_hyperx_universal_battery,
)
from providers.logitech_hidpp import G533_CURVE, parse_hidpp_battery, parse_logitech_headset_voltage
from providers.razer_hid import build_razer_request, parse_razer_reply, raw_razer_level_to_percent
from providers.steelseries_hid import parse_steelseries_headset, parse_steelseries_mouse
from providers.vgn_provider import parse_mchose_feature_reply
from vgn_battery import _is_valid_battery_reply, _make_frame


class TestVgnAndCompx(unittest.TestCase):
    def test_vgn_checksum_and_packet(self) -> None:
        pkt = _make_frame(0x04)
        self.assertEqual(len(pkt), 17)
        self.assertEqual(pkt[0], 0x08)
        self.assertEqual(pkt[1], 0x04)
        self.assertEqual(sum(pkt) & 0xFF, 0x55)

        reply = [0x08, 0x04, 0, 0, 0, 0, 86, 0x00, 0x0F, 0xA0] + [0] * 6
        reply.append((0x55 - sum(reply)) % 256)
        self.assertTrue(_is_valid_battery_reply(reply))

    def test_mchose_xor_feature_reply(self) -> None:
        # decoded: [0x06, vid_lo=0xA4, vid_hi=0x35, pid_lo=0x01, pid_hi=0x10, 0,0,0,0,0, pct=78, chg=1]
        plain = [0x06, 0xA4, 0x35, 0x01, 0x10, 0, 0, 0, 0, 0, 78, 1]
        raw = [0x11] + [b ^ 0xFF for b in plain]
        res = parse_mchose_feature_reply(raw)
        self.assertEqual(res, (0x35A4, 0x1001, 78, True))


class TestLogitechHidpp(unittest.TestCase):
    def test_unified_battery_1004(self) -> None:
        self.assertEqual(parse_hidpp_battery(0x1004, [82, 0x08, 0x00]), (True, 82, False, False, None))
        self.assertEqual(parse_hidpp_battery(0x1004, [100, 0x08, 0x03]), (True, 100, False, True, None))
        self.assertEqual(parse_hidpp_battery(0x1004, [45, 0x04, 0x01]), (True, 45, True, False, None))

    def test_battery_status_1000(self) -> None:
        self.assertEqual(parse_hidpp_battery(0x1000, [64, 50, 0x00]), (True, 64, False, False, None))

    def test_battery_voltage_1001(self) -> None:
        # 3950 mV -> 0x0F6E, flags 0x80 (powered/charging)
        online, pct, chg, full, mv = parse_hidpp_battery(0x1001, [0x0F, 0x6E, 0x80])
        self.assertTrue(online)
        self.assertTrue(chg)
        self.assertFalse(full)
        self.assertEqual(mv, 3950)
        self.assertIsNotNone(pct)

    def test_adc_1f20_inactive(self) -> None:
        self.assertEqual(parse_hidpp_battery(0x1F20, [0x00, 0x00, 0x00]), (False, None, False, False, None))

    def test_g533_headset_voltage(self) -> None:
        # 3850 mV = 0x0F0A -> 50% on G533_CURVE, state 0x01 (discharging)
        reply = [0x11, 0xFF, 0x07, 0x01, 0x0F, 0x0A, 0x01] + [0] * 13
        online, pct, chg, mv = parse_logitech_headset_voltage(reply, G533_CURVE)
        self.assertTrue(online)
        self.assertEqual(pct, 50)
        self.assertFalse(chg)
        self.assertEqual(mv, 3850)


class TestRazerHid(unittest.TestCase):
    def test_request_crc_and_reply(self) -> None:
        req = build_razer_request(0x3F, 0x07, 0x80)
        self.assertEqual(len(req), 91)
        crc = 0
        for b in req[3:89]:
            crc ^= b
        self.assertEqual(req[89], crc)

        reply = list(req)
        reply[1] = 0x02
        reply[10] = 204  # 204/255 ≈ 80%
        args = parse_razer_reply(reply, 0x07, 0x80)
        self.assertIsNotNone(args)
        self.assertEqual(raw_razer_level_to_percent(args[1]), 80)
        # 0 视为休眠而非 0%
        self.assertIsNone(raw_razer_level_to_percent(0))


class TestSteelSeriesHid(unittest.TestCase):
    def test_mice_parsers(self) -> None:
        # Aerox: (b & 0x7F - 1) * 5 -> 17-1=16 -> 80%, bit7=1 charging
        self.assertEqual(parse_steelseries_mouse([0x00, 0xD2, 0x80 | 17], "aerox", 0xD2), (80, True, False))
        # Aerox Gen 2: status=1 charging, level=63
        self.assertEqual(parse_steelseries_mouse([0x92, 0x01, 63], "aerox_gen2", 0x92), (63, True, False))
        # Rival: level=45, charging=1
        self.assertEqual(parse_steelseries_mouse([45, 0, 1], "rival", 0xAA), (45, True, False))

    def test_headset_parsers(self) -> None:
        self.assertEqual(parse_steelseries_headset("nova5", [0xB0, 0x01, 0x00, 72, 0x01]), (True, 72, True))
        self.assertEqual(parse_steelseries_headset("nova5", [0xB0, 0x02, 0x00, 0, 0]), (False, None, False))
        # GameBuds: left out-of-case 65%, right in-case 0% -> min=65%
        self.assertEqual(parse_steelseries_headset("gamebuds", [0xB0, 0, 0, 0x03, 0x02, 65, 0]), (True, 65, False))


class TestCorsairAndHyperX(unittest.TestCase):
    def test_corsair_bragi_and_void(self) -> None:
        # 850 (0x0352) -> 85.0%
        self.assertEqual(parse_bragi_property([0x01, 0x02, 0x00, 0x52, 0x03, 0x00, 0x00], 0x01), 850)
        self.assertEqual(parse_corsair_void_reply([0x64, 0x00, 0x4B, 0x00, 0x04]), (True, 75, True))
        self.assertEqual(parse_corsair_void_reply([0x64, 0x00, 0x00, 0x00, 0x00]), (False, None, False))

    def test_hyperx_parsers(self) -> None:
        self.assertEqual(parse_hyperx_alpha_battery([0x21, 0xBB, 0x0B, 92]), 92)
        self.assertEqual(parse_hyperx_cloud2_hp([0x06, 0xFF, 0xBB, 0x02, 0, 0, 0, 66]), 66)
        self.assertEqual(parse_hyperx_universal_battery([0x51, 0x02, 88, 1]), (88, True, False))
        self.assertEqual(parse_hyperx_ngenuity2_heartbeat([0x00, 0x51, 0, 0, 0, 54, 2]), (54, False, True))


class TestAsusAndSony(unittest.TestCase):
    def test_asus_mouse_percent_and_sleep(self) -> None:
        # Harpe II Ace on SpeedNova (report ID 0x03): 0x35 = 53%
        frame = [0x03, 0x12, 0x07, 0x00, 0x00, 0x35, 0x02, 0x14, 0xFD, 0x0E, 0x00, 0x00]
        online, asleep, pct, chg, _ = parse_asus_mouse_reply(frame, report_id=0x03)
        self.assertTrue(online)
        self.assertFalse(asleep)
        self.assertEqual(pct, 53)
        self.assertFalse(chg)

        # FF AA 表示休眠，禁止伪造 0%
        online2, asleep2, pct2, _, _ = parse_asus_mouse_reply([0x03, 0xFF, 0xAA, 0, 0], report_id=0x03)
        self.assertFalse(online2)
        self.assertTrue(asleep2)
        self.assertIsNone(pct2)

        # 老款四档鼠标：3 * 25 = 75%
        q_frame = [0x12, 0x07, 0x00, 0x00, 0x03, 0, 0, 0, 0, 0x01]
        self.assertEqual(parse_asus_mouse_reply(q_frame, report_id=0x00, multiplier=25)[:4], (True, False, 75, True))

    def test_asus_keyboard_and_omni_pairs(self) -> None:
        kb = [0x02, 0x12, 0x01, 0x00, 0x00, 0x00, 0x42, 0x02, 0x01, 0x01, 0x14, 0x42]
        self.assertEqual(parse_asus_keyboard_reply(kb, report_id=0x02, level_offset=10)[:4], (True, False, 66, True))

        pairs_raw = [0x01, 0xA0, 0x00, 0x02, 0x00, 0x65, 0x1B, 0x03, 0x00, 0x06, 0x1B, 0x02, 0x00, 0x00, 0x00]
        self.assertEqual(parse_asus_omni_pairs(pairs_raw), [(0x1B65, 0x03), (0x1B06, 0x02)])

    def test_asus_headsets(self) -> None:
        self.assertEqual(
            parse_asus_rog_headset_cc([0xCC, 0x12, 0x07, 0, 0, 0, 84], [0xCC, 0x12, 0x08, 0, 0, 1, 0]),
            (True, 84, True),
        )
        ok, pct, chg, sub = parse_asus_cetra_speednova(
            [0xCC, 0x12, 0x07, 0, 0, 0, 70, 85, 95],
            [0xCC, 0x12, 0x08, 0, 0, 0x01, 0],
        )
        self.assertTrue(ok)
        self.assertEqual(pct, 70)
        self.assertTrue(chg)
        self.assertEqual((sub.left_percent, sub.right_percent, sub.case_percent), (70, 85, 95))

        # Strix Go 2.4: 3850 mV -> 分段线性插值 79% (3800=75%, 4100=100%)
        sg = [0xFF, 0x1B] + [0] * 9 + [0x0A, 0x0F]
        self.assertEqual(parse_asus_strix_go(sg), (True, 79, False, 3850))

    def test_sony_inzone_h5_and_buds(self) -> None:
        req = build_sony_inzone_request()
        self.assertEqual(len(req), 64)
        self.assertEqual(req[13], sum(req[6:13]) & 0xFF)

        h5_reply = [0x02, 16, 0x04, 0xFF, 0, 0, 0x96, 0xC3, 0x10, 0x04, 0x10, 0x02, 0x00, 0x01, 68, 0]
        self.assertEqual(parse_sony_inzone_h5(h5_reply), (True, 68, True))

        # Buds: left=75%, right=82%, case=100%
        buds_reply = [0x02, 20, 0x04, 0xFF, 0, 0, 0x96, 0xC3, 0x10, 0x04, 0xA0, 0x02, 0x00, 1, 75, 1, 82, 1, 100, 0]
        ok, main_pct, _chg, sub = parse_sony_inzone_buds(buds_reply)
        self.assertTrue(ok)
        self.assertEqual(main_pct, 75)
        self.assertEqual((sub.left_percent, sub.right_percent, sub.case_percent), (75, 82, 100))


class TestAppleAirPodsAndBluetooth(unittest.TestCase):
    def _make_airpods_packet(
        self,
        model_id: int,
        left_nib: int,
        right_nib: int,
        case_nib: int,
        status_nib: int,
        flip: bool = False,
    ) -> bytes:
        buf = bytearray(27)
        buf[0] = 0x07
        buf[3] = model_id & 0xFF
        buf[4] = (model_id >> 8) & 0xFF
        buf[6] = ((left_nib & 0x0F) << 4) | (right_nib & 0x0F)
        buf[7] = ((status_nib & 0x0F) << 4) | (case_nib & 0x0F)
        buf[10] = 0x02 if flip else 0x00
        return bytes(buf)

    def test_airpods_pro2_standard_and_flipped(self) -> None:
        # 未翻转: L=80%, R=90%, Case=60%, L+Case 充电 (status_nib = 0x01 | 0x04 = 5)
        pkt = self._make_airpods_packet(0x2014, 8, 9, 6, 0x05, flip=False)
        dev = parse_airpods_continuity(pkt, address=0xAABBCCDDEEFF)
        self.assertIsNotNone(dev)
        self.assertEqual(dev.brand, "Apple")
        self.assertEqual(dev.kind, KIND_EARBUDS)
        self.assertEqual(dev.percent, 60)  # 取三路最低值
        self.assertEqual(dev.sub_batteries.left_percent, 80)
        self.assertTrue(dev.sub_batteries.left_charging)
        self.assertEqual(dev.sub_batteries.right_percent, 90)
        self.assertFalse(dev.sub_batteries.right_charging)
        self.assertEqual(dev.sub_batteries.case_percent, 60)
        self.assertTrue(dev.sub_batteries.case_charging)

        # 翻转位开启: buf[6] 高位变为右耳、低位变为左耳
        pkt_flip = self._make_airpods_packet(0x2024, 3, 7, 15, 0x02, flip=True)
        dev_f = parse_airpods_continuity(pkt_flip, address=0x112233445566)
        self.assertEqual(dev_f.sub_batteries.left_percent, 70)
        self.assertTrue(dev_f.sub_batteries.left_charging)
        self.assertEqual(dev_f.sub_batteries.right_percent, 30)
        self.assertIsNone(dev_f.sub_batteries.case_percent)  # nibble=15 -> 未知
        self.assertEqual(dev_f.percent, 30)

    def test_airpods_max_plus5_offset(self) -> None:
        pkt = self._make_airpods_packet(0x200A, 7, 15, 15, 0x00, flip=False)
        dev = parse_airpods_continuity(pkt, address=0x123456)
        self.assertEqual(dev.kind, KIND_HEADSET)
        self.assertEqual(dev.percent, 75)  # 7*10 + 5

    def test_bluetooth_provider_graceful_and_ingest(self) -> None:
        bt = BluetoothBatteryProvider()
        pkt = self._make_airpods_packet(0x2014, 9, 8, 10, 0x00)
        bt.ingest_airpods_advertisement(0xCAFEBABE0001, pkt)
        devs = bt.poll([])
        self.assertTrue(any(d.device_id == "airpods:cafebabe0001" and d.percent == 80 for d in devs))


class _DummyProvider(BatteryProvider):
    name = "dummy"
    brand = "Dummy"

    def __init__(self, items: list[DeviceBattery], fail: bool = False) -> None:
        self._items = items
        self._fail = fail

    def poll(self, _hid_snapshot: list[dict]) -> list[DeviceBattery]:
        if self._fail:
            raise RuntimeError("simulated provider crash")
        return list(self._items)


class TestDeviceManager(unittest.TestCase):
    def test_dedup_isolation_and_no_fake_zero(self) -> None:
        d_offline_zero = DeviceBattery(
            device_id="test:mouse1",
            name="Mock Mouse",
            brand="Mock",
            kind=KIND_MOUSE,
            connected=True,
            online=False,
            asleep=False,
            percent=0,  # 必须被纠正为 None
        )
        d_online = DeviceBattery(
            device_id="test:mouse2",
            name="Online Mouse",
            brand="VGN",
            kind=KIND_MOUSE,
            connected=True,
            online=True,
            percent=100,
            charging=True,
            support_status=STATUS_VERIFIED,
        )
        d_online_dup_offline = DeviceBattery(
            device_id="test:mouse2",
            name="Online Mouse",
            brand="VGN",
            kind=KIND_MOUSE,
            connected=True,
            online=False,
            percent=None,
            support_status=STATUS_PROTOCOL,
        )

        mgr = DeviceManager(
            providers=[
                _DummyProvider([d_offline_zero, d_online_dup_offline]),
                _DummyProvider([], fail=True),
                _DummyProvider([d_online]),
            ]
        )
        res = mgr.poll(hid_snapshot=[])
        self.assertEqual(len(res), 2)
        # 已验证在线设备排第一，且满电自动置 full=True
        self.assertEqual(res[0].device_id, "test:mouse2")
        self.assertTrue(res[0].online)
        self.assertTrue(res[0].full)
        # 离线设备的 0% 已被清理为 None
        self.assertEqual(res[1].device_id, "test:mouse1")
        self.assertIsNone(res[1].percent)

        diag = mgr.export_diagnostics(hid_snapshot=[])
        self.assertEqual(len(diag["detected_devices"]), 2)
        self.assertIn("simulated provider crash", diag["providers"][1]["error"])


class TestTieredAlertStateMachine(unittest.TestCase):
    def test_three_tier_hysteresis_and_per_device_isolation(self) -> None:
        from app_config import AppConfig, get_device_tiers, set_device_tiers
        from mouse_battery_app import evaluate_tiered_alerts

        cfg = AppConfig()
        # 默认三级档位 [30, 20, 10]
        self.assertEqual(get_device_tiers(cfg, "dev:a"), [30, 20, 10])
        # 设备 B 单独关闭 30%，仅保留 [20, 10]
        set_device_tiers(cfg, "dev:b", [20, 10])
        self.assertEqual(get_device_tiers(cfg, "dev:b"), [20, 10])

        alerted: dict[str, set[int]] = {}
        dev_a = DeviceBattery("dev:a", "Mouse A", "VGN", KIND_MOUSE, online=True, percent=28)
        dev_b = DeviceBattery("dev:b", "Headset B", "Sony", KIND_HEADSET, online=True, percent=28)

        # 28% 时只有 A 触发 30% 档，B 不触发
        fired1 = evaluate_tiered_alerts([dev_a, dev_b], cfg, alerted)
        self.assertEqual([(d.device_id, t) for d, t in fired1], [("dev:a", 30)])

        # 同电量重复轮询绝不重复弹窗
        self.assertEqual(evaluate_tiered_alerts([dev_a, dev_b], cfg, alerted), [])

        # 降至 18%：A 触发 20% 档，B 首次触发 20% 档
        dev_a.percent = 18
        dev_b.percent = 18
        fired2 = evaluate_tiered_alerts([dev_a, dev_b], cfg, alerted)
        self.assertEqual(sorted((d.device_id, t) for d, t in fired2), [("dev:a", 20), ("dev:b", 20)])

        # A 插线充电重置冷却，拔线后回到 15% 应只弹一次最紧急档（20%），不连弹 30%+20%
        dev_a.charging = True
        self.assertEqual(evaluate_tiered_alerts([dev_a], cfg, alerted), [])
        dev_a.charging = False
        dev_a.percent = 15
        fired3 = evaluate_tiered_alerts([dev_a], cfg, alerted)
        self.assertEqual([(d.device_id, t) for d, t in fired3], [("dev:a", 20)])

        # 休眠/离线设备绝不触发误报
        dev_a.asleep = True
        dev_a.percent = 5
        self.assertEqual(evaluate_tiered_alerts([dev_a], cfg, alerted), [])

    def test_custom_thresholds_repeat_cooldown_and_device_pause(self) -> None:
        from app_config import AppConfig, set_device_pref
        from mouse_battery_app import evaluate_tiered_alerts

        cfg = AppConfig()
        cfg.custom_alerts_enabled = True
        cfg.custom_thresholds = [25, 15]
        cfg.repeat_alert_enabled = True
        cfg.repeat_interval_min = 10

        dev = DeviceBattery("dev:r", "Test Headset", "SteelSeries", KIND_HEADSET, online=True, percent=24)
        alerted: dict[str, set[int]] = {}
        last_ts: dict[str, float] = {}

        # t=1000 首次低于 25%（且低于 30%），取最紧急的 25%
        fired1 = evaluate_tiered_alerts([dev], cfg, alerted, last_ts, now_ts=1000.0)
        self.assertEqual([(d.device_id, t) for d, t in fired1], [("dev:r", 25)])

        # t=1300（仅过 5 分钟 < 10 分钟）不重复触发
        self.assertEqual(evaluate_tiered_alerts([dev], cfg, alerted, last_ts, now_ts=1300.0), [])

        # t=1605（超过 10 分钟）触发重复提醒
        fired2 = evaluate_tiered_alerts([dev], cfg, alerted, last_ts, now_ts=1605.0)
        self.assertEqual([(d.device_id, t) for d, t in fired2], [("dev:r", 25)])

        # 单设备暂停监控后，不再触发提醒
        set_device_pref(cfg, "dev:r", {"monitor_enabled": False})
        self.assertEqual(evaluate_tiered_alerts([dev], cfg, alerted, last_ts, now_ts=3000.0), [])

    def test_window_centering_and_work_area_clamping(self) -> None:
        from mouse_battery_app import _compute_centered_rect

        # 1. 1920x1040（扣除 40px 任务栏）主窗口居中
        work = (0, 0, 1920, 1040)
        x, y, w, h = _compute_centered_rect(work, 760, 480)
        self.assertEqual((x, y, w, h), (580, 280, 760, 480))

        # 2. 设置窗口以主窗口为基准居中
        sx, sy, sw, sh = _compute_centered_rect(work, 840, 742, anchor_rect=(580, 280, 760, 480))
        self.assertEqual((sx, sy, sw, sh), (540, 149, 840, 742))

        # 3. 副屏负坐标 + 主窗口靠近边缘时，设置窗口必须钳制在工作区内不得越界
        left_mon = (-1920, 0, 0, 1040)
        cx, cy, cw, ch = _compute_centered_rect(left_mon, 840, 742, anchor_rect=(-1910, 800, 760, 480))
        self.assertGreaterEqual(cx, -1920)
        self.assertLessEqual(cx + cw, 0)
        self.assertGreaterEqual(cy, 0)
        self.assertLessEqual(cy + ch, 1040)

        # 4. 超高 DPI / 小屏工作区高度小于窗口高度时自动收缩不遮挡任务栏
        small_work = (0, 0, 1280, 680)
        ux, uy, uw, uh = _compute_centered_rect(small_work, 840, 742)
        self.assertEqual((ux, uy, uw, uh), (220, 0, 840, 680))


class TestUpdater(unittest.TestCase):
    def test_version_compare(self):
        from updater import is_newer_version, parse_version

        self.assertEqual(parse_version("v2.3.0"), (2, 3, 0))
        self.assertTrue(is_newer_version("v2.3.0", "2.2.0"))
        self.assertTrue(is_newer_version("2.10.0", "2.3.0"))
        self.assertFalse(is_newer_version("v2.3.0", "2.3.0"))
        self.assertFalse(is_newer_version("2.2.9", "2.3.0"))
        self.assertFalse(is_newer_version("2.3", "2.3.0"))

    def test_release_payload_stable_only_and_asset_selection(self):
        from updater import parse_github_release_payload, parse_sha256_manifest

        payload = {
            "tag_name": "v2.4.0",
            "draft": False,
            "prerelease": False,
            "html_url": "https://github.com/edwin99701/BattDock/releases/tag/v2.4.0",
            "body": "## 更新内容\n- 新增设备支持",
            "published_at": "2026-11-26T04:00:00Z",
            "assets": [
                {"name": "SHA256SUMS.txt", "browser_download_url": "https://example.com/SHA256SUMS.txt", "size": 120},
                {"name": "VGNMouseBattery-v2.4.0-win64-UpgradeBridge.zip", "browser_download_url": "https://example.com/bridge.zip", "size": 38000000},
                {"name": "BattDock-v2.4.0-Windows-x64-Portable.zip", "browser_download_url": "https://example.com/BattDock.zip", "size": 37000000},
            ],
        }
        res = parse_github_release_payload(payload, "2.3.0")
        self.assertTrue(res.ok)
        self.assertTrue(res.has_update)
        self.assertEqual(res.latest_version, "2.4.0")
        # BattDock 优先选择官方便携包，不误选旧版桥接包
        self.assertEqual(res.asset_name, "BattDock-v2.4.0-Windows-x64-Portable.zip")
        self.assertEqual(res.sha256_url, "https://example.com/SHA256SUMS.txt")

        # 预发布版与草稿不得误判为正式更新
        pre = dict(payload, prerelease=True)
        self.assertFalse(parse_github_release_payload(pre, "2.3.0").has_update)
        draft = dict(payload, draft=True)
        self.assertFalse(parse_github_release_payload(draft, "2.3.0").has_update)

        manifest = parse_sha256_manifest("a" * 64 + "  BattDock-v2.4.0-Windows-x64-Portable.zip\n")
        self.assertEqual(manifest.get("battdock-v2.4.0-windows-x64-portable.zip"), "a" * 64)

    def test_extract_and_verify_zip_security(self):
        import tempfile
        import zipfile
        from updater import extract_and_verify_update

        with tempfile.TemporaryDirectory() as tmp:
            tpath = Path(tmp)
            # 1. 合法嵌套目录 ZIP（默认校验 BattDock.exe）
            good_zip = tpath / "good.zip"
            with zipfile.ZipFile(good_zip, "w") as zf:
                zf.writestr("BattDock/BattDock.exe", b"MZ-test")
                zf.writestr("BattDock/_internal/dummy.txt", b"ok")
            staged = extract_and_verify_update(good_zip, tpath / "out_good")
            self.assertTrue((staged / "BattDock.exe").is_file())

            # 2. 路径遍历攻击包必须被拦截
            evil_zip = tpath / "evil.zip"
            with zipfile.ZipFile(evil_zip, "w") as zf:
                zf.writestr("../escape.txt", b"bad")
            with self.assertRaises(ValueError):
                extract_and_verify_update(evil_zip, tpath / "out_evil")

            # 3. 缺少主程序 EXE 的包必须报错
            missing_zip = tpath / "missing.zip"
            with zipfile.ZipFile(missing_zip, "w") as zf:
                zf.writestr("readme.txt", b"hello")
            with self.assertRaises(FileNotFoundError):
                extract_and_verify_update(missing_zip, tpath / "out_missing")


class TestBrandAndDeviceNaming(unittest.TestCase):
    def test_official_device_names_and_model_distinction(self):
        from providers.device_naming import (
            format_connection_mode_cn,
            format_device_subtitle,
            normalize_device_display_name,
        )

        # 严格区分 Logitech G Pro 2 Lightspeed 与 Logitech G Pro X Superlight 2
        self.assertEqual(normalize_device_display_name("PRO 2 LIGHTSPEED", brand="Logitech"), "Logitech G Pro 2 Lightspeed")
        self.assertEqual(normalize_device_display_name("PRO X SUPERLIGHT 2", brand="Logitech"), "Logitech G Pro X Superlight 2")
        self.assertNotEqual(
            normalize_device_display_name("PRO 2 LIGHTSPEED", vid=0x046D, pid=0xC0A4, brand="Logitech"),
            normalize_device_display_name("PRO X SUPERLIGHT 2", vid=0x046D, pid=0xC09B, brand="Logitech"),
        )
        self.assertEqual(normalize_device_display_name("RAZER VIPER V3 PRO", brand="Razer"), "Razer Viper V3 Pro")
        self.assertEqual(normalize_device_display_name("RAZER DEATHADDER V3 PRO", brand="Razer"), "Razer DeathAdder V3 Pro")
        self.assertEqual(normalize_device_display_name("RAZER VIPER V3 HYPERSPEED", brand="Razer"), "Razer Viper V3 HyperSpeed")
        self.assertEqual(normalize_device_display_name("WH-1000XM5", brand="Sony"), "Sony WH-1000XM5")
        self.assertEqual(normalize_device_display_name("VGN DRAGONFLY F2 PRO MAX", vid=0x3554, pid=0xFB3E, brand="VGN"), "VGN Dragonfly F2 Pro Max")
        # 保留合理缩写与未知型号不编造
        self.assertEqual(normalize_device_display_name("JBL Quantum 910"), "JBL Quantum 910")
        self.assertEqual(normalize_device_display_name("ASUS ROG Azoth"), "ASUS ROG Azoth")

        # 连接方式与副标题规范（不展示品牌技术词、正常连接不写已连接、未知连接留空）
        self.assertEqual(format_connection_mode_cn("LIGHTSPEED"), "2.4GHz 无线连接")
        self.assertEqual(format_connection_mode_cn("HyperSpeed"), "2.4GHz 无线连接")
        self.assertEqual(format_connection_mode_cn("Bluetooth"), "蓝牙连接")
        self.assertEqual(format_connection_mode_cn("USB Wired"), "USB 有线连接")
        self.assertEqual(format_connection_mode_cn("wireless"), "无线连接")
        self.assertEqual(format_connection_mode_cn(""), "")
        self.assertEqual(format_device_subtitle("2.4G", True, True, False, False, False, 82), "2.4GHz 无线连接")
        self.assertEqual(format_device_subtitle("2.4G", True, False, True, False, False, None), "2.4GHz 无线连接 · 休眠中")
        self.assertEqual(format_device_subtitle("Bluetooth", True, True, False, True, False, 65), "蓝牙连接 · 充电中")
        self.assertEqual(format_device_subtitle("USB Wired", True, True, False, True, True, 100), "USB 有线连接 · 已充满")
        self.assertEqual(format_device_subtitle("Bluetooth", False, False, False, False, False, None), "蓝牙连接 · 未连接")

    def test_legacy_config_migration_preserves_settings(self):
        import json
        import tempfile
        from app_config import migrate_legacy_config

        with tempfile.TemporaryDirectory() as tmp:
            tpath = Path(tmp)
            legacy_cfg = tpath / "VGNMouseBattery" / "config.json"
            new_cfg = tpath / "BattDock" / "config.json"
            legacy_cfg.parent.mkdir(parents=True)
            legacy_cfg.write_text(json.dumps({"theme": "dark", "poll_interval_sec": 15}), encoding="utf-8")

            self.assertTrue(migrate_legacy_config(target_path=new_cfg, legacy_path=legacy_cfg))
            self.assertTrue(new_cfg.exists())
            self.assertEqual(json.loads(new_cfg.read_text(encoding="utf-8"))["theme"], "dark")
            # 二次调用不覆盖已存在的新配置
            self.assertFalse(migrate_legacy_config(target_path=new_cfg, legacy_path=legacy_cfg))

    def test_v240_icons_compact_labels_summary_and_same_volume_updater(self):
        from device_icons import canonical_device_icon_kind, get_device_icons_svg_map, render_device_icon_pil
        from providers.base import DeviceBattery, KIND_EARBUDS, KIND_HEADSET, KIND_KEYBOARD, KIND_MOUSE
        from providers.device_naming import resolve_compact_device_label
        from updater import build_windows_updater_script, extract_user_summary

        # 1. 全局设备图标统一性（earbuds 复用 headset；浅色黑、深色白）
        self.assertEqual(canonical_device_icon_kind(KIND_EARBUDS), KIND_HEADSET)
        svg_map = get_device_icons_svg_map(20)
        self.assertEqual(svg_map[KIND_EARBUDS], svg_map[KIND_HEADSET])
        for k in (KIND_MOUSE, KIND_HEADSET, KIND_KEYBOARD):
            im_l = render_device_icon_pil(k, 24, is_dark=False)
            im_d = render_device_icon_pil(k, 24, is_dark=True)
            self.assertEqual(im_l.size, (24, 24))
            self.assertNotEqual(im_l.tobytes(), im_d.tobytes())

        # 2. 悬浮窗品牌精简与同品牌多设备自动区分
        d_vgn = DeviceBattery("vgn:1", "VGN Dragonfly F2 Pro Max", "VGN", KIND_MOUSE)
        d_logi1 = DeviceBattery("logi:1", "Logitech G Pro 2 Lightspeed", "Logitech", KIND_MOUSE)
        d_logi2 = DeviceBattery("logi:2", "Logitech G Pro X Superlight 2", "Logitech", KIND_MOUSE)
        d_unknown = DeviceBattery("unk:1", "Wireless Mouse X1", "", KIND_MOUSE)
        self.assertEqual(resolve_compact_device_label(d_vgn, [d_vgn, d_logi1]), "VGN")
        self.assertEqual(resolve_compact_device_label(d_vgn, [d_vgn], custom_label="主力鼠标"), "主力鼠标")
        # 同品牌双鼠标自动补充型号区分
        self.assertEqual(resolve_compact_device_label(d_logi1, [d_logi1, d_logi2]), "Logitech G Pro 2 Lightspeed")
        self.assertEqual(resolve_compact_device_label(d_logi2, [d_logi1, d_logi2]), "Logitech G Pro X Superlight 2")
        # 未知品牌不编造
        self.assertEqual(resolve_compact_device_label(d_unknown, [d_unknown]), "Wireless Mouse X1")

        # 3. 简明摘要提取（结构化块 + Markdown 清洗降级，不含 Markdown 符号或源码文件名）
        structured = '正文\n<!-- BATTDOCK_SUMMARY_START {"summary":["统一设备图标","修复Win10圆角"],"important_notice":"请重启生效"} BATTDOCK_SUMMARY_END -->'
        items, notice = extract_user_summary(structured)
        self.assertEqual(items, ["统一设备图标", "修复Win10圆角"])
        self.assertEqual(notice, "请重启生效")

        raw_md = "## 更新\n- **修复自动更新（updater.py）**：解决 `Move-Item` 跨盘失败\n- 优化悬浮窗与提醒弹窗"
        fb_items, _ = extract_user_summary(raw_md)
        self.assertTrue(len(fb_items) >= 2)
        for it in fb_items:
            self.assertNotIn("**", it)
            self.assertNotIn("`", it)
            self.assertNotIn("updater.py", it)

        # 4. 更新脚本必须将回滚目录置于 TargetDir 同盘（杜绝跨盘 Move-Item 失败）
        ps = build_windows_updater_script(Path(r"C:\Temp\stage"), Path(r"E:\Apps\BattDock"), pid=12345)
        self.assertIn("Join-Path $TargetDir ('._battdock_rollback_' + $TargetPid)", ps)
        self.assertNotIn("Join-Path $env:TEMP ('battdock_rollback_'", ps)

    def test_v250_alert_device_names_reorder_and_ui_invariants(self):
        import os
        from floating_widget import is_windows_11
        from providers.base import DeviceBattery, KIND_HEADSET, KIND_KEYBOARD, KIND_MOUSE
        from providers.device_naming import format_alert_device_name, resolve_compact_device_label

        # 1. 低电量提醒设备名：优先自定义名 > 完整标准型号名；超长仅删冗余修饰词，绝不退化为纯品牌名
        d_vgn = DeviceBattery("vgn:1", "VGN Dragonfly F2 Pro Max", "VGN", KIND_MOUSE)
        d_ss = DeviceBattery("ss:1", "SteelSeries Arctis Nova 7", "SteelSeries", KIND_HEADSET)
        d_long = DeviceBattery(
            "logi:long",
            "Logitech G Pro X Superlight 2 DEX Wireless Gaming Mouse",
            "Logitech",
            KIND_MOUSE,
        )
        self.assertEqual(format_alert_device_name(d_vgn), ("VGN Dragonfly F2 Pro Max", "VGN Dragonfly F2 Pro Max"))
        self.assertEqual(format_alert_device_name(d_vgn, alias="我的主力鼠"), ("我的主力鼠", "我的主力鼠"))
        self.assertEqual(format_alert_device_name(d_ss), ("SteelSeries Arctis Nova 7", "SteelSeries Arctis Nova 7"))
        short_long, full_long = format_alert_device_name(d_long)
        self.assertEqual(full_long, "Logitech G Pro X Superlight 2 DEX Wireless Gaming Mouse")
        self.assertEqual(short_long, "Logitech G Pro X Superlight 2 DEX")
        self.assertNotEqual(short_long, "Logitech")

        # 2. 悬浮窗依旧保持默认仅品牌名规则（不受提醒弹窗完整名称规则影响）
        self.assertEqual(resolve_compact_device_label(d_vgn, [d_vgn, d_ss]), "VGN")
        self.assertEqual(resolve_compact_device_label(d_ss, [d_vgn, d_ss]), "SteelSeries")

        # 3. Windows 10 圆角模式强制开关校验
        old_env = os.environ.get("BATTDOCK_FORCE_WIN10_ROUND")
        try:
            os.environ["BATTDOCK_FORCE_WIN10_ROUND"] = "1"
            self.assertFalse(is_windows_11())
        finally:
            if old_env is None:
                os.environ.pop("BATTDOCK_FORCE_WIN10_ROUND", None)
            else:
                os.environ["BATTDOCK_FORCE_WIN10_ROUND"] = old_env

        # 4. 设置页 HTML 结构不变量：无标题栏齿轮图标、无底层协议名暴露、无逗号分隔阈值输入框、保留左侧导航图标
        settings_html = (Path(__file__).resolve().parent.parent / "ui" / "settings.html").read_text(encoding="utf-8")
        self.assertNotIn("协议：", settings_html)
        self.assertNotIn("用逗号分隔百分比", settings_html)
        self.assertIn("dev-drag-handle", settings_html)
        self.assertIn("reorder_devices", settings_html)
        titlebar_block = settings_html.split('id="titlebar"', 1)[1].split("</div>", 2)[0]
        self.assertNotIn("M19.4 15", titlebar_block)  # 标题栏“设置”左侧无齿轮 SVG
        self.assertIn("返回主窗口", titlebar_block)  # 保留返回箭头
        self.assertIn('data-sec="general"', settings_html)  # 保留左侧导航栏

        # 5. Windows 10 防 1px 白色直角外框回归校验
        app_py = (Path(__file__).resolve().parent.parent / "mouse_battery_app.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(app_py.count("shadow=is_windows_11()"), 2)
        flt_py = (Path(__file__).resolve().parent.parent / "floating_widget.py").read_text(encoding="utf-8")
        self.assertIn("DWMNCRP_DISABLED", flt_py)
        self.assertIn("DwmExtendFrameIntoClientArea", flt_py)


class TestV252StabilityAndLifecycle(unittest.TestCase):
    def test_device_manager_caches_hid_snapshot_and_records_diagnostics(self):
        from unittest.mock import patch
        from brand import APP_VERSION

        fake_hid = [
            {
                "vendor_id": 0x3554,
                "product_id": 0xFB3E,
                "usage_page": 0xFF02,
                "usage": 0x0002,
                "interface_number": 1,
                "path": b"fake-path",
                "product_string": "VGN DragonFly F2 Pro Max",
            }
        ]
        dummy_dev = DeviceBattery("vgn:3554:fb3e", "VGN Dragonfly F2 Pro Max", "VGN", KIND_MOUSE, online=True, percent=88)
        mgr = DeviceManager(providers=[_DummyProvider([dummy_dev])])

        with patch("providers.manager.hid.enumerate", return_value=fake_hid) as mock_enum:
            # 1. 首轮启动扫描必须枚举一次
            r1 = mgr.poll(reason="startup")
            self.assertEqual(len(r1), 1)
            self.assertEqual(mock_enum.call_count, 1)

            # 2. 常规周期轮询必须复用缓存，不再重复触发 hid.enumerate(0, 0)
            r2 = mgr.poll(reason="scheduled")
            self.assertEqual(len(r2), 1)
            self.assertEqual(mock_enum.call_count, 1)

            # 3. 硬件插拔标记脏位后，下轮才重新扫描
            mgr.mark_hid_dirty("device_change")
            mgr.poll(reason="scheduled")
            self.assertEqual(mock_enum.call_count, 2)

            # 4. 手动刷新强制重新扫描
            mgr.poll(reason="manual_refresh", force_rescan=True, force_query=True)
            self.assertEqual(mock_enum.call_count, 3)

            diag = mgr.export_diagnostics(hid_snapshot=fake_hid, active_monitor_tasks=4)
            self.assertEqual(diag["app_version"], APP_VERSION)
            pd = diag["poll_diagnostics"]
            self.assertEqual(pd["total_polls"], 5)
            self.assertEqual(pd["total_full_hid_scans"], 3)
            self.assertEqual(pd["recent_polls"][-1]["active_monitor_tasks"], 4)
            self.assertEqual(pd["recent_polls"][1]["scan_reason"], "cached")
            self.assertFalse(pd["recent_polls"][1]["hid_scanned"])

    def test_vgn_reader_reuses_snapshot_and_applies_sleep_backoff(self):
        from unittest.mock import patch
        from vgn_battery import VgnBatteryReader

        snap = [
            {
                "vendor_id": 0x3554,
                "product_id": 0xFB3E,
                "usage_page": 0xFF02,
                "usage": 0x0002,
                "path": b"vgn-fake-path",
                "product_string": "VGN DragonFly F2 Pro Max",
            }
        ]
        reader = VgnBatteryReader()
        query_calls = []

        def fake_query(path, max_attempts=2):
            query_calls.append((path, max_attempts))
            return None, {
                "ok": False,
                "duration_ms": 10.0,
                "timeouts": 1,
                "retries": max(0, max_attempts - 1),
                "io_error": False,
                "skipped_backoff": False,
            }

        with patch("vgn_battery.hid.enumerate") as mock_enum, patch.object(reader, "_query_once", side_effect=fake_query):
            # 连续 3 次无应答进入休眠态，且全程不调用 hid.enumerate
            for _ in range(3):
                res = reader.read(hid_snapshot=snap, force=False)
            self.assertEqual(mock_enum.call_count, 0)
            self.assertTrue(res.asleep)
            self.assertEqual(len(query_calls), 3)

            # 第 4 次常规轮询在退避窗口内应直接跳过 HID 访问，不反复唤醒休眠鼠标
            res_backoff = reader.read(hid_snapshot=snap, force=False)
            self.assertTrue(res_backoff.asleep)
            self.assertEqual(len(query_calls), 3)
            self.assertTrue(reader.get_last_query_stats()["skipped_backoff"])

            # 手动强制刷新或唤醒必须穿透退避立即查询
            reader.read(hid_snapshot=snap, force=True)
            self.assertEqual(len(query_calls), 4)

    def test_window_lifecycle_closing_recovery_and_ui_reset_invariants(self):
        from unittest.mock import MagicMock, patch
        from mouse_battery_app import MouseBatteryApp

        app = MouseBatteryApp(start_hidden=False)
        app.cfg.close_to_tray = True
        app._hide_main_window = MagicMock()
        app.quit_app = MagicMock()

        # 1. 开启最小化至托盘：任务栏右键关闭 / Alt+F4 必须取消原生销毁并隐藏窗口
        self.assertFalse(app._on_main_window_closing())
        app._hide_main_window.assert_called_once()
        app.quit_app.assert_not_called()

        # 2. 关闭最小化至托盘：任务栏关闭 / Alt+F4 必须触发完整退出
        app.cfg.close_to_tray = False
        app._hide_main_window.reset_mock()
        with patch("mouse_battery_app.threading.Thread") as mock_thr:
            self.assertFalse(app._on_main_window_closing())
            mock_thr.assert_called_once()
            self.assertEqual(mock_thr.call_args.kwargs.get("target"), app.quit_app)

        # 3. 正式退出或系统关机时允许原生窗口关闭
        app._quitting = True
        self.assertTrue(app._on_main_window_closing())
        self.assertTrue(app._on_settings_window_closing())

        # 4. 若主窗口已失效/销毁，show_main_window 必须触发安全重建而非继续操作死句柄
        app._quitting = False
        app.window = None
        app.hwnd = 0
        app._recreate_main_window = MagicMock(return_value=True)
        app.show_main_window()
        app._recreate_main_window.assert_called_once()

        # 5. 前端交互状态重置与防残留不变量校验
        root = Path(__file__).resolve().parent.parent
        idx_html = (root / "ui" / "index.html").read_text(encoding="utf-8")
        set_html = (root / "ui" / "settings.html").read_text(encoding="utf-8")
        common_css = (root / "ui" / "common.css").read_text(encoding="utf-8")
        self.assertIn("function resetInteractionState", idx_html)
        self.assertIn("ui-await-pointer", idx_html)
        self.assertIn("function resetInteractionState", set_html)
        self.assertIn(":root.ui-await-pointer .win-btn.close:hover", common_css)

    def test_taskbar_click_toggle_style_and_lifecycle_invariants(self):
        import ctypes
        from ctypes import wintypes
        from unittest.mock import MagicMock, patch
        import floating_widget
        import mouse_battery_app as mba
        from mouse_battery_app import MouseBatteryApp, _ensure_taskbar_toggle_style

        # 1. 真实 WinForms 无边框窗口 Win32 样式与 SC_MINIMIZE / SC_RESTORE 验收
        if sys.platform == "win32":
            import clr
            clr.AddReference("System.Windows.Forms")
            clr.AddReference("System.Drawing")
            import System.Windows.Forms as WinForms
            from System.Drawing import Point, Size

            user32 = ctypes.windll.user32
            GWL_STYLE = -16
            WS_MINIMIZEBOX = 0x00020000
            WS_SYSMENU = 0x00080000
            WS_CAPTION = 0x00C00000
            WS_THICKFRAME = 0x00040000
            WS_BORDER = 0x00800000
            WM_SYSCOMMAND = 0x0112
            SC_MINIMIZE = 0xF020
            SC_RESTORE = 0xF120

            form = WinForms.Form()
            try:
                form.Text = "BattDock Taskbar Toggle Test"
                form.Size = Size(760, 480)
                form.StartPosition = WinForms.FormStartPosition.Manual
                form.Location = Point(-2200, -2200)
                form.Opacity = 0.0
                form.FormBorderStyle = getattr(WinForms.FormBorderStyle, "None")
                form.Show()
                WinForms.Application.DoEvents()

                hwnd = int(form.Handle.ToInt64())
                init_style = int(user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_STYLE)) & 0xFFFFFFFF
                self.assertEqual(init_style & WS_MINIMIZEBOX, 0)

                # 补齐任务栏点击切换所需原生样式位（且幂等、不引入边框/标题栏）
                self.assertTrue(_ensure_taskbar_toggle_style(hwnd))
                self.assertTrue(_ensure_taskbar_toggle_style(hwnd))
                style = int(user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_STYLE)) & 0xFFFFFFFF
                self.assertTrue(bool(style & WS_MINIMIZEBOX))
                self.assertTrue(bool(style & WS_SYSMENU))
                self.assertFalse(bool(style & WS_CAPTION))
                self.assertFalse(bool(style & WS_THICKFRAME))
                self.assertFalse(bool(style & WS_BORDER))

                wrect, crect = wintypes.RECT(), wintypes.RECT()
                user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(wrect))
                user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(crect))
                self.assertEqual(wrect.right - wrect.left, crect.right - crect.left)
                self.assertEqual(wrect.bottom - wrect.top, crect.bottom - crect.top)

                # 模拟任务栏点击前台窗口触发 SC_MINIMIZE -> 最小化且 Win10 圆角逻辑跳过假尺寸
                user32.SendMessageW(wintypes.HWND(hwnd), WM_SYSCOMMAND, SC_MINIMIZE, 0)
                WinForms.Application.DoEvents()
                self.assertTrue(bool(user32.IsIconic(wintypes.HWND(hwnd))))
                self.assertEqual(
                    floating_widget.apply_window_rounded_corners(hwnd, radius_dip=10, force_region=True),
                    "minimized_skip",
                )

                # 模拟再次点击任务栏图标触发 SC_RESTORE -> 恢复且保持样式与无边框尺寸
                user32.SendMessageW(wintypes.HWND(hwnd), WM_SYSCOMMAND, SC_RESTORE, 0)
                WinForms.Application.DoEvents()
                self.assertFalse(bool(user32.IsIconic(wintypes.HWND(hwnd))))
                restored_style = int(user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_STYLE)) & 0xFFFFFFFF
                self.assertTrue(bool(restored_style & WS_MINIMIZEBOX))
                self.assertTrue(bool(restored_style & WS_SYSMENU))

                # 模拟隐藏至托盘再重新显示后样式不丢失
                form.Hide()
                WinForms.Application.DoEvents()
                form.Show()
                WinForms.Application.DoEvents()
                reshown_style = int(user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_STYLE)) & 0xFFFFFFFF
                self.assertTrue(bool(reshown_style & WS_MINIMIZEBOX))
                self.assertTrue(bool(reshown_style & WS_SYSMENU))
            finally:
                form.Close()
                form.Dispose()

        # 2. 应用层事件绑定与最小化/恢复不中断监控、不重复创建窗口验收
        app = MouseBatteryApp(start_hidden=False)
        app.window = MagicMock()
        app.hwnd = 123456
        app._drag_state["main"] = ((0, 0), (0, 0), (760, 480))
        app.quit_app = MagicMock()
        app._reset_window_interaction_state = MagicMock()
        app._push_state_to_ui = MagicMock()
        app._recreate_main_window = MagicMock()

        with patch.object(mba, "_is_window_alive", return_value=True):
            app._on_main_window_minimized()
            self.assertNotIn("main", app._drag_state)
            self.assertFalse(app._stop_event.is_set())
            app.quit_app.assert_not_called()
            app._recreate_main_window.assert_not_called()
            app._reset_window_interaction_state.assert_called_once_with(app.window, hiding=False)

            app._reset_window_interaction_state.reset_mock()
            with patch.object(mba, "_apply_window_chrome") as mock_chrome, \
                 patch.object(mba.ctypes.windll.user32, "IsIconic", return_value=0), \
                 patch.object(mba.ctypes.windll.user32, "IsZoomed", return_value=0), \
                 patch.object(mba.threading, "Thread") as mock_thr:
                app._on_main_window_restored()
                mock_chrome.assert_called_once()
                self.assertFalse(app._main_maximized)
                self.assertFalse(app._stop_event.is_set())
                app.quit_app.assert_not_called()
                app._recreate_main_window.assert_not_called()
                mock_thr.assert_called_once()
                self.assertEqual(mock_thr.call_args.kwargs.get("target"), app._push_state_to_ui)

        # 3. 组合场景：最小化状态下被关闭至托盘后，从托盘唤出必须 SW_RESTORE + 居中显现
        app._center_main_hwnd = MagicMock()
        with patch.object(mba, "_is_window_alive", return_value=True), \
             patch.object(app, "_find_hwnd_for", return_value=123456), \
             patch.object(mba, "_apply_window_chrome") as mock_chrome, \
             patch.object(mba, "_set_form_visibility") as mock_vis, \
             patch.object(mba, "_bring_hwnd_to_foreground") as mock_fg, \
             patch.object(mba.ctypes.windll.user32, "IsWindowVisible", return_value=0), \
             patch.object(mba.ctypes.windll.user32, "IsIconic", return_value=1), \
             patch.object(mba.ctypes.windll.user32, "IsZoomed", return_value=0), \
             patch.object(mba.ctypes.windll.user32, "ShowWindow") as mock_show:
            app.show_main_window()
            mock_show.assert_called_once()
            self.assertEqual(mock_show.call_args.args[1], 9)  # SW_RESTORE
            app._center_main_hwnd.assert_called_once()
            mock_chrome.assert_called_once()
            mock_vis.assert_called_once()
            mock_fg.assert_called_once()
            app._recreate_main_window.assert_not_called()

        # 4. 组合场景：窗口处于后台但仍可见时唤出，必须置前而非最小化
        with patch.object(mba, "_is_window_alive", return_value=True), \
             patch.object(app, "_find_hwnd_for", return_value=123456), \
             patch.object(mba, "_apply_window_chrome") as mock_chrome, \
             patch.object(mba, "_bring_hwnd_to_foreground") as mock_fg, \
             patch.object(mba.ctypes.windll.user32, "IsWindowVisible", return_value=1), \
             patch.object(mba.ctypes.windll.user32, "IsIconic", return_value=0), \
             patch.object(mba.ctypes.windll.user32, "ShowWindow") as mock_show:
            app.show_main_window()
            mock_show.assert_not_called()
            mock_chrome.assert_called_once()
            mock_fg.assert_called_once()

        # 5. 校验 _attach_main_window_events 完整挂载 5 个生命周期事件及准确回调
        class _FakeEvent:
            def __init__(self):
                self.handlers = []

            def __iadd__(self, fn):
                self.handlers.append(fn)
                return self

        fake_events = MagicMock()
        ev_map = {}
        for ev_name in ("closing", "closed", "minimized", "restored", "maximized", "loaded"):
            ev = _FakeEvent()
            setattr(fake_events, ev_name, ev)
            ev_map[ev_name] = ev
        fake_win = MagicMock()
        fake_win.events = fake_events
        app._attach_main_window_events(fake_win, is_recreate=False)
        self.assertIn(app._on_main_window_closing, ev_map["closing"].handlers)
        self.assertIn(app._on_main_window_closed, ev_map["closed"].handlers)
        self.assertIn(app._on_main_window_minimized, ev_map["minimized"].handlers)
        self.assertIn(app._on_main_window_restored, ev_map["restored"].handlers)
        self.assertIn(app._on_main_window_restored, ev_map["maximized"].handlers)


class TestV260WirelessHeadsetsAndKeyboards(unittest.TestCase):
    def test_wireless_keyboards_parsers_and_qmk_safety(self):
        from providers.base import KIND_KEYBOARD
        from providers.wireless_keyboards import (
            WirelessKeyboardsProvider,
            build_compx_kb_request,
            build_evision_request,
            build_mchose_k87_v3_request,
            build_sonix_battery_request,
            parse_alienware_kb_reply,
            parse_apple_magic_keyboard_report,
            parse_compx_kb_battery,
            parse_compx_kb_model,
            parse_evision_reply,
            parse_mchose_k87_v3_reply,
            parse_semico_reply,
            parse_sonix_battery_reply,
            parse_sonix_info_reply,
        )

        # 1. CompX BY 键盘 0x13 / 0x4A & 0x05
        req = build_compx_kb_request(0x4A)
        self.assertEqual(len(req), 20)
        self.assertEqual(req[0], 0x13)
        self.assertEqual(req[19], sum(req[:19]) & 0xFF)
        rep = [0x13, 0x4A, 0x01, 0x00, 0x00, 82, 0x10] + [0x00] * 13
        self.assertEqual(parse_compx_kb_battery(rep), (82, True))
        self.assertIsNone(parse_compx_kb_battery([0x13, 0x4A, 0x01, 0x00] + [0x00] * 16))
        mrep = [0x13, 0x05, 0x01, 0x00, 0x00, 0x03, 0x00, 0x00, 0x00, 0x01, 0x15] + [0x00] * 9
        self.assertEqual(parse_compx_kb_model(mrep), ("MCHOSE G75 Pro", "MCHOSE"))

        # 2. SONiX 键盘 20 01 与 55 10 两种回包格式
        sreq = build_sonix_battery_request()
        self.assertEqual(len(sreq), 33)
        self.assertEqual(sreq[32], sum(sreq[:32]) & 0xFF)
        self.assertEqual(parse_sonix_battery_reply([0x00, 0x20, 0x01, 0x00, 76]), 76)
        self.assertEqual(parse_sonix_battery_reply([0x20, 0x01, 0x00, 65]), 65)
        info_rep = [0x00, 0x55, 0x10] + [0x00] * 23 + [91] + [0x00] * 6
        self.assertEqual(parse_sonix_info_reply(info_rep), 91)

        # 共享 05AC:024F 的 Interface 1（QMK/VIA）必须被严格忽略，绝不打开
        prov = WirelessKeyboardsProvider()
        qmk_snap = [{
            "vendor_id": 0x05AC,
            "product_id": 0x024F,
            "usage_page": 0xFF60,
            "usage": 0x0061,
            "interface_number": 1,
            "path": b"fake-qmk-via",
            "product_string": "QMK Keyboard",
        }]
        self.assertEqual(prov._poll_sonix_keyboards(qmk_snap, 100.0, False), [])

        # 3. Evision 键盘（CHERRY / VGN / ATK）
        ev_req, ev_tag = build_evision_request("vgn", 1, 64)
        self.assertEqual(ev_req[0], 0x04)
        self.assertEqual(ev_req[3], 0x1A)
        ev_ok = [0x04, ev_tag & 0xFF, (ev_tag >> 8) & 0xFF, 0x1A, 0x06, 0x00, 0x00, 0x00, 73, 0x01] + [0x00] * 54
        self.assertEqual(parse_evision_reply(ev_ok, "vgn", ev_tag), (True, 73, True))
        ev_sleep = [0x04, ev_tag & 0xFF, (ev_tag >> 8) & 0xFF, 0xFF] + [0x00] * 60
        self.assertEqual(parse_evision_reply(ev_sleep, "vgn", ev_tag), (False, None, False))

        # 4. Semico / MCHOSE K87 V3 / Alienware / Apple Magic Keyboard
        self.assertEqual(parse_semico_reply([0x00, 0xAA, 0x55, 0xCC, 0x33, 0x0E, 64, 0x01]), (True, 64))
        self.assertEqual(parse_semico_reply([0xAA, 0x55, 0xCC, 0x33, 0x0E, 0, 0x00]), (False, None))

        k87_req = build_mchose_k87_v3_request()
        self.assertEqual(k87_req[0], 0x4D)
        data = [0x37, 0x38, 0x23, 0x20] + [0x00] * 6 + [1, 1, 88] + [0x00] * 7
        frame = [0x4D, 0x01, 0x01, len(data), 0x00, 0x09, 0x00, 0x00] + data
        crc = 0
        for b in frame[2:]:
            crc ^= b
        frame.append(crc)
        self.assertEqual(parse_mchose_k87_v3_reply(frame), (True, 88, True))

        self.assertEqual(parse_alienware_kb_reply([0x00, 0x0E, 0xA1, 55, 0x04]), (55, True))
        self.assertEqual(parse_apple_magic_keyboard_report([0x90, 0x02, 85]), (85, True, False))
        self.assertEqual(parse_apple_magic_keyboard_report([0x90, 0x02, 100]), (100, False, True))

        # 5. 键盘 180 秒低打扰节流与手动刷新穿透
        cached_dev = DeviceBattery("kb-compx:3554:fa09", "AULA F75", "AULA", KIND_KEYBOARD, online=True, percent=80)
        prov._remember(cached_dev, 1000.0)
        self.assertIsNotNone(prov._get_throttled("kb-compx:3554:fa09", 1050.0, False))
        self.assertIsNone(prov._get_throttled("kb-compx:3554:fa09", 1050.0, True))
        self.assertIsNone(prov._get_throttled("kb-compx:3554:fa09", 1200.0, False))

    def test_wireless_headsets_parsers(self):
        from providers.wireless_headsets import (
            build_centurion_frame,
            build_epos_request,
            build_razer_bridge_frame,
            build_razer_report02_frame,
            build_razer_v3x_request,
            epos_crc8,
            parse_astro_a50_gen4_battery,
            parse_astro_a50_gen5_reply,
            parse_centurion_battery,
            parse_centurion_payload,
            parse_cmedia_5565_reply,
            parse_epos_reply,
            parse_jbl_info_reply,
            parse_mchose_v9_pro_2_reply,
            parse_race_battery_reply,
            parse_razer_bridge_value,
            parse_razer_report02_answer,
            parse_razer_v2_pro_2020_reply,
            parse_razer_v3x_reply,
        )

        # 1. Razer Report 02 / Feature 07 / Feature FF / Bridge
        r02 = build_razer_report02_frame(0x80, 0x21, 3)
        rep02 = list(r02)
        rep02[1] = 0x02
        rep02[6] = 0x05
        rep02[11] = 0x01
        rep02[12] = 0x01
        rep02[13] = 74
        x = 0
        for b in rep02[1:62]:
            x ^= b
        rep02[62] = x
        self.assertEqual(parse_razer_report02_answer(rep02, r02), 74)

        v3x_req = build_razer_v3x_request(0x05, 0x80)
        v3x_rep = list(v3x_req)
        v3x_rep[1] = 0x02
        v3x_rep[10] = 63
        xc = 0
        for b in v3x_rep[3:61]:
            xc ^= b
        v3x_rep[62] = xc
        self.assertEqual(parse_razer_v3x_reply(v3x_rep, v3x_req), 63)

        v2p = [0xFF, 0x0F, 0x05, 0xFE, 0x12, 0x04, 0x1F, 0x08, 0x05, 0x00, 0x00, 0x03, 0x01, 0x00, 88]
        self.assertEqual(parse_razer_v2_pro_2020_reply(v2p), (True, 88, False, False))

        br_req = build_razer_bridge_frame(0x02, 0x08, [0x03, 0x21, 0x00, 0x00])
        self.assertEqual(br_req[0], 0x02)
        br_rep = [0x02, 0x80, 0x50, 0x49] + [0x00] * 8 + [0x21, 0x01, 0x01, 67] + [0x00] * 48
        self.assertEqual(parse_razer_bridge_value(br_rep, 0x02, 0x21), 67)

        # 2. Logitech Centurion & ASTRO A50 Gen 4/5
        cframe = build_centurion_frame((0x51,), [0x04, 0x06, 85, 0x00, 0x01])
        cpl = parse_centurion_payload((0x51,), cframe)
        self.assertEqual(cpl, [0x04, 0x06, 85, 0x00, 0x01])
        self.assertEqual(parse_centurion_battery(cpl[2:]), (85, True, False))
        self.assertEqual(parse_astro_a50_gen5_reply([0x02, 0x0C, 0x03, 0x00, 0x06, 0x0C, 90, 0x00, 0x01]), (90, True))
        self.assertEqual(parse_astro_a50_gen4_battery([0x02, 0x02, 0x01, 0x80 | 72]), (72, True))

        # 3. JBL Quantum FF12 / EPOS H3PRO / Airoha RACE / C-Media 55 65 / MCHOSE V9 Pro 2
        jbl = [0x86, 0x00, 0xDD, 0x01, 0x00, 0x01, 0, 0, 0, 0, 0x00, 0x0D, 0x00, 0x01, 0x00, 0x80 | 55]
        self.assertEqual(parse_jbl_info_reply(jbl), (55, True))

        ep_req = build_epos_request(0x0005, 0x12, 0x03)
        self.assertEqual(len(ep_req), 107)
        ep_pl = [0x12, 0x00, 0x03, 0x00, 77, 0x00]
        ep_rep = [0x01, 0xEB, 0xFE, 0x01, 0x00, 0x04, 0x00, 0x04, 0x00, len(ep_pl), 0x00, epos_crc8(ep_pl), 0x00] + ep_pl
        self.assertEqual(parse_epos_reply(ep_rep, 0x0005, 0x12, 0x03), [77])

        race_rep = [0x07, 9, 0x00, 0x05, 0x5D, 0x04, 0x00, 0xD6, 0x0C, 0x00, 0x00, 94]
        self.assertEqual(parse_race_battery_reply(race_rep), 94)

        self.assertEqual(parse_cmedia_5565_reply([0x55, 0x65, 80, 0x02]), (True, 80, False, False))
        self.assertEqual(parse_cmedia_5565_reply([0x55, 0x65, 50, 0x00], allow_zero_charge=True), (True, 50, True, False))
        self.assertEqual(parse_cmedia_5565_reply([0x55, 0x65, 50, 0x1A]), (False, None, False, False))

        mc_notify = [0x55, 0xAA, 0x01, 0x01, 0x03, 0x00, 0x04, 0x22, 0x01, 0x40, 0x65] + [0x00] * 53
        self.assertEqual(parse_mchose_v9_pro_2_reply(mc_notify), (True, 64, False))

    def test_upgraded_brand_providers_and_manager_registration(self):
        from providers.corsair_hid import CORSAIR_PERIPHERALS, parse_bragi_headset_reply
        from providers.hyperx_hid import (
            parse_hyperx_cloud3s_reply,
            parse_hyperx_cloud_flight_voltage,
            parse_hyperx_stinger_core_battery,
        )
        from providers.razer_hid import RAZER_MODELS
        from providers.steelseries_hid import HEADSET_MODELS, parse_steelseries_headset

        # Corsair Bragi 耳机（Virtuoso/HS80/wireless_v2）与新增键盘 PID
        self.assertEqual(parse_bragi_headset_reply([0x01, 0x01, 0x02, 0x00, 0x69, 0x03, 0x00, 0x00], 0x09), 873)
        self.assertIsNone(parse_bragi_headset_reply([0x01, 0x00, 0x02, 0x00, 0x69, 0x03, 0x00, 0x00], 0x09))
        self.assertIn(0x2B02, CORSAIR_PERIPHERALS)  # K70 Core TKL Wireless
        self.assertIn(0x2B04, CORSAIR_PERIPHERALS)  # MAKR 75

        # SteelSeries Arctis 1 / Nova Elite / Nova Pro Omni
        self.assertEqual(parse_steelseries_headset("arctis1", [0x06, 0x12, 0x03, 66]), (True, 66, False))
        elite_rep = [0x01, 0xB0, 0, 0, 0x04, 0x01, 48, 0, 0, 0, 0, 0, 0, 0, 0x08, 0x08]
        self.assertEqual(parse_steelseries_headset("nova_omni", elite_rep), (True, 48, False))
        self.assertIn(0x1290, HEADSET_MODELS)  # Arctis Pro Wireless

        # HyperX Cloud III S / Cloud Flight / Cloud Stinger Core
        self.assertEqual(parse_hyperx_cloud3s_reply([0x0C, 0x02, 0x03, 0x01, 0x00, 0x06, 39], 0x06), 39)
        self.assertEqual(parse_hyperx_cloud_flight_voltage([0x21, 0xFF, 0x05, 0x0F, 0xA0]), (True, 100, False))
        self.assertEqual(
            parse_hyperx_stinger_core_battery([0xFF, 0x12, 0x05, 0xFE, 0x0C, 0x04, 0x1F, 0x0B, 0x01, 0x03, 0x05, 0x7F, 0x0F]),
            (81, False, False),
        )

        # Razer 新增无线键盘型号
        self.assertIn(0x02BA, RAZER_MODELS)  # BlackWidow V4 Mini HyperSpeed
        self.assertIn(0x02D5, RAZER_MODELS)  # BlackWidow V4 TKL HyperSpeed
        self.assertIn(0x027B, RAZER_MODELS)  # Pro Type Ultra

        # DeviceManager 默认已注册全部无线耳机与无线键盘适配器
        mgr = DeviceManager()
        names = [p.name for p in mgr.providers]
        self.assertIn("wireless_headsets", names)
        self.assertIn("wireless_keyboards", names)

    def test_v261_cn_mirror_update_sources_and_failover(self):
        import tempfile
        from unittest.mock import patch
        import updater

        # 1. 前缀规范化与 HTTPS 安全约束
        self.assertEqual(updater.normalize_mirror_prefix("https://gh-proxy.org"), "https://gh-proxy.org/")
        self.assertEqual(updater.normalize_mirror_prefix("https://ghfast.top/"), "https://ghfast.top/")
        self.assertEqual(updater.normalize_mirror_prefix("http://insecure.example/"), "")
        self.assertEqual(updater.normalize_mirror_prefix("not-a-url"), "")

        raw_url = "https://github.com/edwin99701/BattDock/releases/download/v2.6.0/BattDock-v2.6.0-Windows-x64-Portable.zip"

        # 2. 四种线路策略生成的候选列表顺序与兜底
        auto_list = updater.build_candidate_urls(raw_url, "auto")
        self.assertTrue(auto_list[0][0].startswith("国内加速"))
        self.assertEqual(auto_list[-1], ("GitHub 官方", raw_url))

        cn_list = updater.build_candidate_urls(raw_url, "cn")
        self.assertTrue(all(lbl.startswith("国内加速") for lbl, _ in cn_list))
        self.assertTrue(all(u.startswith("https://") for _, u in cn_list))

        gh_list = updater.build_candidate_urls(raw_url, "github")
        self.assertEqual(gh_list, [("GitHub 官方", raw_url)])

        custom_list = updater.build_candidate_urls(raw_url, "custom", "https://mirror.example.cn")
        self.assertEqual(custom_list[0][1], f"https://mirror.example.cn/{raw_url}")
        self.assertEqual(custom_list[-1], ("GitHub 官方", raw_url))

        # 3. 节点故障自动切换验证：首节点失败自动切到第二节点并成功落盘
        tried_urls = []

        def fake_single(url, part_path, expected_size, on_progress, cancel_event, timeout):
            tried_urls.append(url)
            if len(tried_urls) == 1:
                raise OSError("simulated mirror timeout")
            part_path.write_bytes(b"PK\x03\x04fake-zip-payload")
            return 20

        with tempfile.TemporaryDirectory() as td, patch.object(updater, "_download_single_url", side_effect=fake_single):
            dest = Path(td) / "update.zip"
            sources_seen = []
            out = updater.download_update_asset(
                asset_url=raw_url,
                dest_zip=dest,
                update_source="auto",
                probe_mirrors=False,
                on_source_change=sources_seen.append,
            )
            self.assertEqual(out, dest)
            self.assertEqual(len(tried_urls), 2)
            self.assertEqual(len(sources_seen), 2)
            self.assertTrue(dest.exists())

        # 4. api.github.com 不可达时自动回退国内加速 update-summary.json 检查更新
        fake_summary = b'{"version":"2.6.1","summary":["\xe5\x9b\xbd\xe5\x86\x85\xe5\x8a\xa0\xe9\x80\x9f\xe4\xb8\x8b\xe8\xbd\xbd"],"asset_name":"BattDock-v2.6.1-Windows-x64-Portable.zip","asset_size":37000000}'

        class _FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return fake_summary

        def fake_urlopen(req, timeout=10.0):
            if "api.github.com" in req.full_url:
                raise OSError("api blocked")
            return _FakeResp()

        with patch("updater.urllib.request.urlopen", side_effect=fake_urlopen):
            res = updater.check_for_update("2.6.0", update_source="auto")
            self.assertTrue(res.ok)
            self.assertTrue(res.has_update)
            self.assertEqual(res.latest_version, "2.6.1")
            self.assertEqual(res.summary_items, ["国内加速下载"])
            self.assertEqual(res.asset_size, 37000000)

    def test_v270_ikf_bluetooth_aggregation_standard_hid_and_new_brands(self):
        from providers.base import KIND_HEADSET, KIND_KEYBOARD
        from providers.bluetooth_provider import aggregate_bluetooth_pnp_nodes, parse_bluetooth_address
        from providers.device_naming import canonical_brand_name, normalize_device_display_name
        from providers.manager import DeviceManager
        from providers.standard_hid import infer_standard_hid_brand_and_kind, scale_hid_battery_value
        from providers.wireless_headsets import (
            parse_alienware_aw920h_reply,
            parse_fractal_scape_reply,
            parse_jabra_gn_battery,
            parse_moondrop_gm01_reply,
            parse_poly_bt600_reply,
            parse_sony_pulse3d_report,
        )
        from providers.wireless_keyboards import parse_rongyuan_status, parse_urx_via_battery

        # 1. iKF 蓝牙耳机按 MAC 聚合主节点名与 HFP 子节点电量（彻底解决漏识别）
        self.assertEqual(
            parse_bluetooth_address(r"BTHENUM\{0000111E-0000-1000-8000-00805F9B34FB}_VID&00010094_PID&0001\7&1234&0&AABBCCDDEEFF_C00000000"),
            "AABBCCDDEEFF",
        )
        raw_nodes = [
            {
                "instance_id": r"BTHENUM\DEV_AABBCCDDEEFF\7&1234&0&BLUETOOTHDEVICE_AABBCCDDEEFF",
                "name": "iKF-King",
                "battery": None,
                "is_connected": True,
            },
            {
                "instance_id": r"BTHENUM\{0000111E-0000-1000-8000-00805F9B34FB}_LOCALMFG&0002\7&1234&0&AABBCCDDEEFF_C00000000",
                "name": "Microsoft Bluetooth Hands-Free Profile Audio Device",
                "battery": 85,
                "is_connected": False,
            },
            # BLE Keychron 无线键盘（名称在根节点，电量在 Battery Service 0x180F 子节点）
            {
                "instance_id": r"BTHLE\DEV_112233445566\8&ABCD&0&112233445566",
                "name": "Keychron K2 Pro",
                "battery": None,
                "is_connected": True,
            },
            {
                "instance_id": r"BTHLEDEVICE\{0000180F-0000-1000-8000-00805F9B34FB}_DEV_VID&0205AC_PID&024F_REV&0001_112233445566\9&1111&0&001E",
                "name": "Battery Service",
                "battery": 64,
                "is_connected": None,
            },
            # 离线蓝牙设备应过滤，绝不显示虚假电量
            {
                "instance_id": r"BTHENUM\DEV_FFEEDDCCBBAA\7&9999&0&BLUETOOTHDEVICE_FFEEDDCCBBAA",
                "name": "iKF-Solo",
                "battery": 50,
                "is_connected": False,
            },
        ]
        bt_devs = aggregate_bluetooth_pnp_nodes(raw_nodes)
        self.assertEqual(len(bt_devs), 2)
        by_id = {d.device_id: d for d in bt_devs}
        ikf = by_id["bt:aabbccddeeff"]
        self.assertEqual(ikf.name, "iKF-King")
        self.assertEqual(ikf.brand, "iKF")
        self.assertEqual(ikf.kind, KIND_HEADSET)
        self.assertEqual(ikf.percent, 85)
        self.assertEqual(canonical_brand_name(ikf.brand, ikf.name), "iKF")
        self.assertEqual(normalize_device_display_name(ikf.name, brand=ikf.brand), "iKF-King")

        kc = by_id["bt:112233445566"]
        self.assertEqual(kc.brand, "Keychron")
        self.assertEqual(kc.kind, KIND_KEYBOARD)
        self.assertEqual(kc.percent, 64)

        # 2. 标准 USB HID Battery Strength (0x06:0x20) 缩放与品牌推断
        self.assertEqual(scale_hid_battery_value(75, 0, 100), 75)
        self.assertEqual(scale_hid_battery_value(3, 0, 4), 75)
        self.assertIsNone(scale_hid_battery_value(0, 0, 100))
        self.assertEqual(infer_standard_hid_brand_and_kind("iKF-V11 Pro 2.4G"), ("iKF", KIND_HEADSET))
        self.assertEqual(infer_standard_hid_brand_and_kind("NuPhy Air75 V2"), ("NuPhy", KIND_KEYBOARD))

        # 3. 新增耳机协议解析器验证
        aw = [0x07, 0xC0, 0x0A, 0x09, 0x00, 0x01, 78, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
        xor_v = 0
        for b in aw[3:13]:
            xor_v ^= b
        aw[13] = xor_v
        self.assertEqual(parse_alienware_aw920h_reply(aw), (True, 78, True))

        poly = [0x07, 0x01, 0x01, 0x10, 0x00, 0x02, 0x00, 0x00, 0x03, 0x0A, 0x1A, 4, 6, 1]
        self.assertEqual(parse_poly_bt600_reply(poly), (80, True))

        jabra = [0x05, 0x00, 0x01, 0x07, (3 << 6) | 8, 0x12, 0x02, 0x01, 92]
        self.assertEqual(parse_jabra_gn_battery(jabra, expected_from=0x01, seq=0x07), (92, True))

        scape = [0x02, 0xF1, 0x21] + [0x00] * 12 + [66] + [0x00] * 7 + [1]
        self.assertEqual(parse_fractal_scape_reply(scape), (66, True))

        moondrop = [0x4B, 0x80, 0x27, 0x06, 0x00, 0x00, 0x00, 0x00, 0x01, 88]
        self.assertEqual(parse_moondrop_gm01_reply(moondrop), 88)

        self.assertEqual(parse_sony_pulse3d_report([0xB0, 0, 0, 70, 0x08, 0, 0, 0]), (True, 70, False))
        self.assertEqual(parse_sony_pulse3d_report([0xB0, 0, 0, 0x80, 0x08, 0, 0, 0]), (True, None, True))

        # 4. 新增无线键盘协议解析器验证（荣元 2.4G + URX Core75）
        ry = parse_rongyuan_status([0x00, 0x01, 82, 0x00, 0x00, 0x01, 0x01])
        self.assertIsNotNone(ry)
        self.assertTrue(ry["kb_online"])
        self.assertEqual(ry["kb_percent"], 82)
        self.assertFalse(ry["mouse_online"])
        self.assertIsNone(ry["mouse_percent"])

        self.assertEqual(parse_urx_via_battery([0x08, 0x00, 0x07, 91]), 91)
        self.assertEqual(parse_urx_via_battery([0x00, 0x08, 0x00, 0x07, 45]), 45)

        # 5. DeviceManager 已注册 StandardHidBatteryProvider（共 11 个适配器）
        mgr = DeviceManager()
        names = [p.name for p in mgr.providers]
        self.assertIn("standard_hid", names)
        self.assertEqual(len(names), 11)

    def test_v271_precision_mchose_guardrails_pulse3d_stdhid_and_ui(self):
        import json
        import tempfile
        from unittest.mock import MagicMock, patch
        import app_config
        import updater
        from providers.base import (
            BatteryProvider,
            KIND_HEADSET,
            KIND_MOUSE,
            build_hid_output_report,
            map_range,
            round_half_up,
        )
        from providers.corsair_hid import corsair_tenths_to_percent
        from providers.extra_brands import parse_asus_strix_go
        from providers.hyperx_hid import parse_hyperx_stinger_core_battery
        from providers.manager import DeviceManager
        from providers.razer_hid import raw_razer_level_to_percent
        from providers.standard_hid import StandardHidBatteryProvider, scale_hid_battery_value
        from providers.wireless_headsets import (
            AIROHA_RACE_HEADSETS,
            WirelessHeadsetsProvider,
            collect_hid_mouse_keyboard_vps,
            is_safe_mchose_headset_candidate,
            parse_mchose_v9_pro_2_reply,
            parse_poly_bt600_reply,
        )

        # 1. 全适配器取整/保底/插值精度校验
        self.assertEqual(round_half_up(12.5), 13)
        self.assertEqual(map_range(1, 0, 8), 13)
        self.assertEqual(map_range(5, 0, 8), 63)
        self.assertEqual(corsair_tenths_to_percent(859), 86)
        self.assertEqual(corsair_tenths_to_percent(855), 86)
        self.assertEqual(corsair_tenths_to_percent(1), 1)
        self.assertIsNone(corsair_tenths_to_percent(0))
        self.assertEqual(raw_razer_level_to_percent(1), 1)
        self.assertIsNone(raw_razer_level_to_percent(0))
        self.assertEqual(scale_hid_battery_value(1, 0, 255), 1)
        self.assertIsNone(scale_hid_battery_value(0, 0, 255))
        # Poly BT600: 4 档中第 2 档应四舍五入为 67%（非地板除 66%）
        poly_4 = [0x07, 0x01, 0x01, 0x10, 0x00, 0x02, 0x00, 0x00, 0x03, 0x0A, 0x1A, 2, 4, 0]
        self.assertEqual(parse_poly_bt600_reply(poly_4), (67, False))
        # HyperX Stinger Core: 3999 mV 位于 (3954,80)..(4042,90)，四舍五入得 85%
        stinger_3999 = [0xFF, 0x12, 0x05, 0, 0, 0, 0, 0, 0, 0x03, 0, 3999 & 0xFF, 3999 >> 8]
        self.assertEqual(parse_hyperx_stinger_core_battery(stinger_3999), (85, False, False))
        # ASUS ROG Strix Go 2.4: 3950 mV 位于 (3800,75)..(4100,100) 中点 -> 88%
        strix_3950 = [0xFF, 0x1B, 0, 0, 0, 0, 0, 0, 0, 0x00, 0, 3950 & 0xFF, 3950 >> 8]
        self.assertEqual(parse_asus_strix_go(strix_3950), (True, 88, False, 3950))

        # 2. output_report_id 补 0x00 与迈从耳机安全护栏（严禁触碰 0x01 鼠键输入集合）
        self.assertEqual(build_hid_output_report([0x55, 0x65, 0x01], 65, 0)[:4], [0x00, 0x55, 0x65, 0x01])
        self.assertEqual(len(build_hid_output_report([0x55, 0x65, 0x01], 65, 0)), 65)
        self.assertEqual(build_hid_output_report([0x55, 0x65, 0x01], 64, 0x55)[:3], [0x55, 0x65, 0x01])
        # Audeze Maxwell 有线 PID 0x4B1A 已支持
        self.assertIn((0x3329, 0x4B1A), AIROHA_RACE_HEADSETS)
        self.assertTrue(AIROHA_RACE_HEADSETS[(0x3329, 0x4B1A)][3])
        # 兼容前导 0x00 的迈从 MC 协议包
        mc_body = [0x55, 0xAA, 0x01, 0x01, 0x03, 0x00, 0x01, 0x0B, 0x01, 72]
        xor_v = 0
        for b in mc_body[3:]:
            xor_v ^= b
        self.assertEqual(parse_mchose_v9_pro_2_reply([0x00] + mc_body + [xor_v]), (True, 72, False))

        fake_snap = [
            # 某迈从鼠标暴露了标准鼠标集合 0x01:0x02 与厂商集合 0xFF00 -> 整机严禁被耳机探测触碰
            {"vendor_id": 0x3837, "product_id": 0x9001, "usage_page": 0x0001, "usage": 0x0002, "product_string": "MCHOSE Mouse"},
            {"vendor_id": 0x3837, "product_id": 0x9001, "usage_page": 0xFF00, "usage": 0x0001, "product_string": "MCHOSE Mouse"},
            # 某迈从无线耳机仅暴露音频 + 两个 Vendor 集合（0xFF01 无应答 + 0xFF90 有效）
            {"vendor_id": 0x3837, "product_id": 0x6099, "usage_page": 0x000C, "usage": 0x0001, "product_string": "MCHOSE S9 Pro"},
            {"vendor_id": 0x3837, "product_id": 0x6099, "usage_page": 0xFF01, "usage": 0x0001, "path": b"mchose-bad", "interface_number": 2, "product_string": "MCHOSE S9 Pro"},
            {"vendor_id": 0x3837, "product_id": 0x6099, "usage_page": 0xFF90, "usage": 0x0001, "path": b"mchose-ok", "interface_number": 3, "product_string": "MCHOSE S9 Pro"},
        ]
        mk_vps = collect_hid_mouse_keyboard_vps(fake_snap)
        self.assertIn((0x3837, 0x9001), mk_vps)
        self.assertFalse(is_safe_mchose_headset_candidate(fake_snap[0], mk_vps))
        self.assertFalse(is_safe_mchose_headset_candidate(fake_snap[1], mk_vps))
        self.assertFalse(is_safe_mchose_headset_candidate(fake_snap[2], mk_vps))
        self.assertTrue(is_safe_mchose_headset_candidate(fake_snap[4], mk_vps))

        # 多集合不锁死 + 空包过滤模拟：第 1 个 Vendor 集合返回空包，第 2 个集合返回 85%
        class _FakeMchoseHid:
            def __init__(self):
                self.path = b""
                self.reads = []

            def open_path(self, p):
                self.path = p

            def write(self, data):
                if self.path == b"mchose-ok" and 0x55 in data and 0x65 in data:
                    self.reads = [[0x00] * 64, [0x00, 0x55, 0x65, 85, 0x02] + [0x00] * 59]
                else:
                    self.reads = [[0x00] * 64]
                return len(data)

            def read(self, _n, _t=0):
                return self.reads.pop(0) if self.reads else []

            def close(self):
                pass

        wh_provider = WirelessHeadsetsProvider()
        with patch("providers.wireless_headsets.hid.device", side_effect=_FakeMchoseHid), \
             patch("providers.wireless_headsets.get_hid_report_lengths", return_value=(65, 65, 0)), \
             patch("providers.wireless_headsets.get_hid_output_report_id", return_value=0):
            found_hs = wh_provider.poll(fake_snap)
        self.assertEqual(len(found_hs), 1)
        self.assertEqual(found_hs[0].brand, "MCHOSE")
        self.assertTrue(found_hs[0].online)
        self.assertEqual(found_hs[0].percent, 85)

        # 3. Sony PULSE 3D 常驻只读句柄：持续读取 + 异常/休眠唤醒/拔出/退出彻底释放
        pulse_handles = []

        class _FakePulseHid:
            def __init__(self):
                self.closed = False
                self.raise_on_read = False
                self.queue = [[0xB0, 0, 0, 77, 0x08, 0, 0, 0]]
                pulse_handles.append(self)

            def open_path(self, _p):
                pass

            def set_nonblocking(self, _v):
                pass

            def read(self, _n):
                if self.raise_on_read:
                    raise OSError("disconnected")
                return self.queue.pop(0) if self.queue else []

            def close(self):
                self.closed = True

        pulse_snap = [{
            "vendor_id": 0x054C,
            "product_id": 0x0D5E,
            "usage_page": 0xFF01,
            "usage": 0x0020,
            "path": b"pulse3d-path",
        }]
        wh_p3 = WirelessHeadsetsProvider()
        with patch("providers.wireless_headsets.hid.device", side_effect=_FakePulseHid):
            res1 = wh_p3.poll(pulse_snap)
            self.assertEqual(len(res1), 1)
            self.assertEqual(res1[0].percent, 77)
            self.assertEqual(len(pulse_handles), 1)
            self.assertFalse(pulse_handles[0].closed)  # 保持常驻
            # 休眠唤醒释放句柄
            wh_p3.on_power_resume()
            self.assertTrue(pulse_handles[0].closed)
            # 再次轮询自动重建，遇到 OSError 立即释放
            wh_p3.poll(pulse_snap)
            self.assertEqual(len(pulse_handles), 2)
            pulse_handles[1].raise_on_read = True
            wh_p3.poll(pulse_snap)
            self.assertTrue(pulse_handles[1].closed)
            # 再次重建后拔出设备立即释放
            wh_p3.poll(pulse_snap)
            self.assertEqual(len(pulse_handles), 3)
            self.assertEqual(wh_p3.poll([]), [])
            self.assertTrue(pulse_handles[2].closed)
            # 退出 stop() 释放
            wh_p3.poll(pulse_snap)
            self.assertEqual(len(pulse_handles), 4)
            wh_p3.stop()
            self.assertTrue(pulse_handles[3].closed)

        # 4. standard_hid 放宽 VID 后，严格跳过专用适配器已在线与已登记休眠占位的 (vid, pid)
        class _MockDedicated(BatteryProvider):
            name = "mock_dedicated"
            brand = "Dedicated"

            def poll(self, _snap):
                return [
                    DeviceBattery("ded:online", "Logitech G Pro", "Logitech", KIND_MOUSE, vid=0x046D, pid=0xC547, connected=True, online=True, asleep=False, percent=90),
                    DeviceBattery("ded:asleep", "VGN Dragonfly F2 Pro Max", "VGN", KIND_MOUSE, vid=0x3554, pid=0xFB3E, connected=True, online=False, asleep=True, percent=None),
                ]

        std_snap = [
            {"vendor_id": 0x046D, "product_id": 0xC547, "path": b"p1", "product_string": "Logitech G Pro"},
            {"vendor_id": 0x3554, "product_id": 0xFB3E, "path": b"p2", "product_string": "VGN F2 Pro Max"},
            {"vendor_id": 0x046D, "product_id": 0x9999, "path": b"p3", "product_string": "Logitech Office Mouse"},
        ]
        mgr2 = DeviceManager(providers=[_MockDedicated(), StandardHidBatteryProvider()])
        with patch("providers.standard_hid.get_hid_report_lengths", return_value=(0, 0, 8)), \
             patch("providers.standard_hid.read_standard_hid_battery_strength", return_value=82):
            merged = mgr2.poll(std_snap, force_query=True)
        ids = {d.device_id for d in merged}
        self.assertEqual(ids, {"ded:online", "ded:asleep", "stdhid:046d:9999"})

        # 5. 老配置残留线路规范化、国内优先+GitHub静默回退、关于页精简与托盘勾选同步校验
        with tempfile.TemporaryDirectory() as td:
            old_cfg_file = Path(td) / "config.json"
            old_cfg_file.write_text(
                json.dumps({"update_source": "github", "update_custom_mirror": "https://dead.example/"}),
                encoding="utf-8",
            )
            with patch.object(app_config, "CONFIG_PATH", old_cfg_file), \
                 patch.object(app_config, "LEGACY_CONFIG_PATH", old_cfg_file):
                loaded = app_config.load_config()
            self.assertEqual(loaded.update_source, "auto")
            self.assertEqual(loaded.update_custom_mirror, "")

        # 国内镜像全失败时静默回退 GitHub API
        called_urls = []

        class _FakeGhResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps({
                    "tag_name": "v2.7.2",
                    "draft": False,
                    "prerelease": False,
                    "html_url": "https://github.com/edwin99701/BattDock/releases/tag/v2.7.2",
                    "body": "• 静默回退测试",
                    "assets": [{
                        "name": "BattDock-v2.7.2-Windows-x64-Portable.zip",
                        "browser_download_url": "https://github.com/edwin99701/BattDock/releases/download/v2.7.2/BattDock-v2.7.2-Windows-x64-Portable.zip",
                        "size": 123456,
                    }],
                }).encode("utf-8")

        def _fake_fallback_open(req, timeout=10.0):
            called_urls.append(req.full_url)
            if "api.github.com" not in req.full_url:
                raise OSError("cn mirror down")
            return _FakeGhResp()

        with patch("updater.urllib.request.urlopen", side_effect=_fake_fallback_open):
            fb_res = updater.check_for_update("2.7.1", update_source="auto")
        self.assertTrue(fb_res.ok)
        self.assertEqual(fb_res.latest_version, "2.7.2")
        self.assertTrue(any("api.github.com" in u for u in called_urls))
        self.assertFalse("api.github.com" in called_urls[0])  # 国内高速通道优先

        # 关于页与托盘结构不变量
        root = Path(__file__).resolve().parent.parent
        set_html = (root / "ui" / "settings.html").read_text(encoding="utf-8")
        self.assertNotIn("更新下载线路", set_html)
        self.assertNotIn("cs-updSource", set_html)
        self.assertNotIn("inp-customMirror", set_html)
        self.assertNotIn("checkedSuffix", set_html)
        self.assertIn("项目主页", set_html)
        self.assertIn("doCopyDiag", set_html)
        self.assertIn("复制诊断", set_html)

        app_src = (root / "mouse_battery_app.py").read_text(encoding="utf-8")
        idx_open = app_src.index('f"打开 {APP_NAME}"')
        idx_flt = app_src.index('"显示桌面悬浮窗"')
        idx_set = app_src.index('"设置", action=lambda: self.open_settings_window')
        self.assertLess(idx_open, idx_flt)
        self.assertLess(idx_flt, idx_set)
        self.assertIn("checked=self._is_floating_enabled", app_src)
        self.assertIn("self._refresh_tray_menu()", app_src)


class TestCoreTrayLifecycleRegression(unittest.TestCase):
    """核心受保护功能回归测试：动态系统托盘电池图标生命周期、失败自愈、并发安全与窗口解耦。"""

    def test_dynamic_battery_hicon_creation_and_cleanup(self):
        from floating_widget import draw_battery_icon
        from tray_icon import destroy_hicon_safe, pil_image_to_hicon

        cases = [
            (85, False, True),   # 正常绿色
            (25, False, True),   # 一级偏低黄色
            (15, False, True),   # 二级不足橙色
            (8, False, True),    # 三级紧急红色
            (60, True, True),    # 充电中闪电
            (None, False, False),  # 休眠/未连接灰色
        ]
        for pct, chg, conn in cases:
            img = draw_battery_icon(size=64, percent=pct, charging=chg, connected=conn)
            self.assertEqual(img.size, (64, 64))
            self.assertEqual(img.mode, "RGBA")
            if sys.platform == "win32":
                hicon = pil_image_to_hicon(img)
                self.assertGreater(hicon, 0, f"HICON creation failed for {(pct, chg, conn)}")
                destroy_hicon_safe(hicon)

    def test_tray_add_retry_modify_self_heal_and_sync_delete_on_stop(self):
        from floating_widget import draw_battery_icon
        from tray_icon import NIM_ADD, NIM_DELETE, NIM_MODIFY, TrayIconController, TrayMenuEntry

        calls: list[tuple[int, int]] = []
        created_icons: list[int] = []
        destroyed_icons: list[int] = []
        next_h = [100]
        # 模拟更新重启瞬间前 2 次 NIM_ADD 失败，第 3 次成功；之后模拟 1 次 NIM_MODIFY 失败触发自愈补注册
        add_results = [False, False, True, True]
        modify_results = [True, False]

        def fake_notify(code: int, nid) -> bool:
            hicon_val = int(getattr(nid, "hIcon", 0) or 0) if not isinstance(nid, dict) else int(nid.get("hIcon", 0))
            calls.append((code, hicon_val))
            if code == NIM_ADD:
                return add_results.pop(0) if add_results else True
            if code == NIM_MODIFY:
                return modify_results.pop(0) if modify_results else True
            return True

        def fake_factory(_img) -> int:
            next_h[0] += 1
            created_icons.append(next_h[0])
            return next_h[0]

        def fake_destroy(h: int) -> None:
            destroyed_icons.append(h)

        tray = TrayIconController(
            name="BattDock",
            initial_icon=draw_battery_icon(size=64, percent=None, charging=False, connected=False),
            title="BattDock",
            menu_entries=[TrayMenuEntry("打开 BattDock", action=lambda: None, default=True)],
            _notify_api=fake_notify,
            _icon_factory=fake_factory,
            _icon_destroyer=fake_destroy,
        )
        self.assertEqual(tray.TRAY_UID, 0)  # 保持与既有 Win11 NotifyIconSettings IsPromoted=1 兼容

        # 手动驱动注册重试与更新自愈（不依赖真实桌面 Explorer）
        with tray._lock:
            tray._hwnd = 99999
            tray._running = True
            self.assertFalse(tray._register_icon_locked(is_reregister=False))
            self.assertFalse(tray.get_health_snapshot()["registered"])
            self.assertFalse(tray._register_icon_locked(is_reregister=True))
            self.assertTrue(tray._register_icon_locked(is_reregister=True))
            self.assertTrue(tray.get_health_snapshot()["registered"])
            self.assertTrue(tray.get_health_snapshot()["visible"])

        # 电量变化更新成功 -> 创建新 HICON 后安全销毁旧 HICON
        self.assertTrue(tray.set_icon(draw_battery_icon(size=64, percent=75, charging=False, connected=True)))
        self.assertEqual(len(destroyed_icons), 1)
        self.assertEqual(destroyed_icons[0], created_icons[0])

        # 模拟 Explorer 静默重启导致 NIM_MODIFY 返回 False -> 自动回退 NIM_ADD 自愈注册
        self.assertTrue(tray.set_icon(draw_battery_icon(size=64, percent=20, charging=False, connected=True)))
        snap = tray.get_health_snapshot()
        self.assertTrue(snap["registered"])
        self.assertTrue(snap["visible"])
        self.assertGreaterEqual(snap["modify_failures"], 1)
        self.assertGreaterEqual(snap["reregister_count"], 2)

        # 退出 stop() 必须同步发出 NIM_DELETE 并释放当前 HICON
        tray.stop(join_timeout=0.2)
        self.assertEqual(calls[-1][0], NIM_DELETE)
        self.assertFalse(tray.get_health_snapshot()["registered"])
        self.assertFalse(tray.get_health_snapshot()["visible"])
        self.assertEqual(set(destroyed_icons), set(created_icons))

    def test_tray_survives_window_lifecycle_pause_resume_and_concurrent_updates(self):
        import concurrent.futures
        from unittest.mock import MagicMock, patch
        import mouse_battery_app as mba
        from mouse_battery_app import MouseBatteryApp
        from providers.base import DeviceBattery, KIND_MOUSE

        app = MouseBatteryApp(start_hidden=False)
        fake_tray = MagicMock()
        fake_tray.set_icon.return_value = True
        fake_tray.set_title.return_value = True
        fake_tray.ensure_visible.return_value = True
        fake_tray.get_health_snapshot.return_value = {
            "running": True,
            "registered": True,
            "visible": True,
            "hwnd_valid": True,
            "icon_handle_valid": True,
            "uid": 0,
            "add_attempts": 1,
            "add_failures": 0,
            "modify_failures": 0,
            "reregister_count": 0,
            "last_error": "",
        }
        app._tray = fake_tray
        app.window = MagicMock()
        app.hwnd = 234567
        app.cfg.close_to_tray = True
        app._push_state_to_ui = MagicMock()
        app._sync_floating_widget = MagicMock()
        app._reset_window_interaction_state = MagicMock()

        # 1. 主窗口关闭至托盘、最小化、恢复、唤出均不得销毁或重建托盘
        with patch.object(mba, "_is_window_alive", return_value=True), \
             patch.object(mba, "_set_form_visibility"), \
             patch.object(mba, "_apply_window_chrome"), \
             patch.object(mba, "_bring_hwnd_to_foreground"), \
             patch.object(mba.ctypes.windll.user32, "IsIconic", return_value=0), \
             patch.object(mba.ctypes.windll.user32, "IsZoomed", return_value=0), \
             patch.object(mba.ctypes.windll.user32, "IsWindowVisible", return_value=1), \
             patch.object(app, "_find_hwnd_for", return_value=234567):
            self.assertFalse(app._on_main_window_closing())
            app._on_main_window_minimized()
            app._on_main_window_restored()
            app.show_main_window()
            # 再次调用 _start_tray 必须幂等复用现有托盘，绝不重复创建
            app._start_tray()

        self.assertIs(app._tray, fake_tray)
        fake_tray.stop.assert_not_called()

        # 2. 暂停与恢复后台电量监控不得销毁托盘
        with patch.object(mba, "save_config"):
            app.update_settings({"auto_monitor": False})
            app.update_settings({"auto_monitor": True})
        self.assertIs(app._tray, fake_tray)
        fake_tray.stop.assert_not_called()

        # 3. 并发电量更新与失败保留重试：若 set_icon 返回 False，不得推进 _last_tray_icon_key
        app.devices = [
            DeviceBattery(
                device_id="vgn:test",
                name="VGN Dragonfly F2 Pro Max",
                brand="VGN",
                kind=KIND_MOUSE,
                percent=60,
                charging=False,
                connected=True,
                online=True,
                connection_mode="2.4GHz",
            )
        ]
        fake_tray.set_icon.return_value = False
        prev_key = app._last_tray_icon_key
        app._update_tray_visual()
        self.assertEqual(app._last_tray_icon_key, prev_key)
        self.assertNotEqual((app._last_tray_icon_key or (None,))[0], 60)

        fake_tray.set_icon.return_value = True
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            futs = [ex.submit(app._update_tray_visual) for _ in range(12)]
            for f in futs:
                f.result()
        self.assertIsNotNone(app._last_tray_icon_key)
        self.assertEqual(app._last_tray_icon_key[0], 60)

        # 4. 诊断报告包含托盘健康快照
        with patch.object(app, "_copy_text_to_clipboard", return_value=True):
            diag = app.copy_diagnostics()
        self.assertIn('"tray"', diag["text"])
        self.assertIn('"registered": true', diag["text"])

        # 5. 仅在完整退出 quit_app() 时注销并清理托盘
        app.floating_widget = MagicMock()
        app.manager = MagicMock()
        with patch.object(mba, "_is_window_alive", return_value=False):
            app.quit_app()
        fake_tray.stop.assert_called_once()
        self.assertIsNone(app._tray)


class TestWin10GameFocusAndWhiteScreenRegression(unittest.TestCase):
    """Windows 10/11 游戏全屏防抢焦点、防 Alt+Tab 残留、防白屏与隐藏窗零打扰回归测试。"""

    def test_non_activating_layered_style_survives_alpha_transitions_and_preserves_foreground(self):
        import ctypes
        from ctypes import wintypes
        import floating_widget as fw

        if sys.platform != "win32":
            self.skipTest("仅在 Windows 上验证 WinForms/Win32 扩展样式")

        import clr
        clr.AddReference("System.Windows.Forms")
        clr.AddReference("System.Drawing")
        import System.Windows.Forms as WinForms
        from System.Drawing import Color, Point, Size

        user32 = ctypes.windll.user32
        GWL_EXSTYLE = -20
        fg_before = int(user32.GetForegroundWindow() or 0)

        form = WinForms.Form()
        try:
            form.FormBorderStyle = getattr(WinForms.FormBorderStyle, "None")
            form.ShowInTaskbar = False
            form.StartPosition = WinForms.FormStartPosition.Manual
            form.BackColor = Color.FromArgb(26, 30, 39)
            form.Size = Size(260, 56)
            form.Location = Point(24, 24)
            hwnd = int(form.Handle.ToInt64())

            ex_init = fw.apply_non_activating_tool_style(hwnd, layered=True)
            self.assertTrue(bool(ex_init & fw.WS_EX_NOACTIVATE))
            self.assertTrue(bool(ex_init & fw.WS_EX_TOOLWINDOW))
            self.assertTrue(bool(ex_init & fw.WS_EX_LAYERED))
            self.assertFalse(bool(ex_init & fw.WS_EX_APPWINDOW))

            # 模拟淡入 -> 100% 不透明 -> 淡出全过程：绝不能像 Form.Opacity 那样抹除 NOACTIVATE/TOOLWINDOW
            for alpha in (0.0, 0.45, 1.0, 0.92, 0.0):
                self.assertTrue(fw.set_layered_window_alpha(hwnd, alpha))
                if alpha == 0.0:
                    user32.ShowWindow(wintypes.HWND(hwnd), fw.SW_SHOWNOACTIVATE)
                    fw.set_window_topmost_noactivate(hwnd, True, x=24, y=24, w=260, h=56, show=True)
                WinForms.Application.DoEvents()
                ex_now = int(user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE)) & 0xFFFFFFFF
                self.assertTrue(bool(ex_now & fw.WS_EX_NOACTIVATE), f"alpha={alpha} 丢失 WS_EX_NOACTIVATE")
                self.assertTrue(bool(ex_now & fw.WS_EX_TOOLWINDOW), f"alpha={alpha} 丢失 WS_EX_TOOLWINDOW")
                self.assertTrue(bool(ex_now & fw.WS_EX_LAYERED), f"alpha={alpha} 丢失 WS_EX_LAYERED")
                self.assertEqual(int(user32.GetForegroundWindow() or 0), fg_before)
        finally:
            form.Dispose()

    def test_exclusive_fullscreen_detection_and_game_safe_deferral(self):
        from unittest.mock import MagicMock, patch
        import floating_widget as fw
        import mouse_battery_app as mba
        from app_config import AppConfig, FloatingWidgetConfig

        # 1. 仅 QUNS_RUNNING_D3D_FULL_SCREEN (3) 判为独占全屏，普通窗口与无边框/忙碌态不误判
        with patch.object(fw, "query_user_notification_state", return_value=fw.QUNS_RUNNING_D3D_FULL_SCREEN):
            self.assertTrue(fw.is_exclusive_fullscreen_active())
        for non_excl in (fw.QUNS_BUSY, fw.QUNS_ACCEPTS_NOTIFICATIONS, fw.QUNS_NOT_PRESENT, 0):
            with patch.object(fw, "query_user_notification_state", return_value=non_excl):
                self.assertFalse(fw.is_exclusive_fullscreen_active())

        # 2. 独占全屏期间悬浮窗仅静默隐藏，绝不改动 fcfg.enabled 也不销毁配置
        widget = fw.DesktopFloatingWidget(
            get_native_host=lambda: None,
            get_work_area=lambda: (0, 0, 1920, 1080),
            get_dpi_scale=lambda: 1.0,
            on_position_saved=lambda _x, _y: None,
            on_double_click=lambda: None,
        )
        fcfg = FloatingWidgetConfig(enabled=True, topmost=True, opacity=92)
        with patch.object(fw, "is_exclusive_fullscreen_active", return_value=True), \
             patch.object(widget, "_hide_for_fullscreen") as mock_hide, \
             patch.object(widget, "close") as mock_close:
            widget.sync(fcfg, None, "VGN", "dark")
        mock_hide.assert_called_once()
        mock_close.assert_not_called()
        self.assertTrue(fcfg.enabled)

        # 3. 独占全屏且仅启用迷你弹窗时暂缓低电量评估（不消耗档位），退出全屏后立刻补发提醒
        app = object.__new__(mba.MouseBatteryApp)
        app.cfg = AppConfig(popup_alert_enabled=True, windows_notify_enabled=False, sound_enabled=False)
        app._alerted_tiers = {}
        app._last_alert_ts = {}
        low_dev = DeviceBattery(
            device_id="vgn:low",
            name="VGN Dragonfly F2 Pro Max",
            brand="VGN",
            kind=KIND_MOUSE,
            percent=15,
            charging=False,
            connected=True,
            online=True,
            connection_mode="2.4GHz",
        )
        with patch.object(mba, "is_exclusive_fullscreen_active", return_value=True), \
             patch.object(app, "_dispatch_alert") as mock_dispatch:
            app._check_low_batteries([low_dev])
        mock_dispatch.assert_not_called()
        self.assertEqual(app._alerted_tiers, {})

        with patch.object(mba, "is_exclusive_fullscreen_active", return_value=False), \
             patch.object(app, "_dispatch_alert") as mock_dispatch:
            app._check_low_batteries([low_dev])
        mock_dispatch.assert_called_once()
        self.assertIn("vgn:low", app._alerted_tiers)

        # 4. 手动测试低电量弹窗即使在独占全屏标志下也照常允许触发（遵循用户主动操作）
        app._tray = None
        with patch.object(mba, "is_exclusive_fullscreen_active", return_value=True), \
             patch("mouse_battery_app.threading.Thread") as mock_thread:
            app._dispatch_alert("VGN", 15, KIND_MOUSE, is_test=True, device_id="vgn:low", full_device_name="VGN Dragonfly F2 Pro Max")
        mock_thread.assert_called_once()

    def test_hidden_windows_skip_background_js_eval_and_rgn_redraw(self):
        import threading
        from unittest.mock import MagicMock, patch
        import mouse_battery_app as mba
        from app_config import AppConfig

        app = object.__new__(mba.MouseBatteryApp)
        app.cfg = AppConfig()
        app.devices = []
        app._last_poll_ts = 0.0
        app._main_maximized = False
        app._settings_maximized = False
        app._update_lock = threading.Lock()
        app._update_state = {"status": "idle"}
        app.window = MagicMock()
        app.settings_window = MagicMock()
        app.hwnd = 1001
        app.settings_hwnd = 1002

        # 隐藏态：后台轮询 _push_state_to_ui(force=False) 不应向隐藏的 WebView2 注入 JS
        with patch.object(mba, "_is_window_alive", return_value=True), \
             patch.object(app, "_is_ui_window_visible", return_value=False), \
             patch.object(mba, "_safe_eval_js") as mock_eval:
            app._push_state_to_ui(force=False)
        mock_eval.assert_not_called()

        # 显式 force=True（如唤出主窗口/打开设置页前预同步）仍正常推送状态
        with patch.object(mba, "_is_window_alive", return_value=True), \
             patch.object(app, "_is_ui_window_visible", return_value=False), \
             patch.object(app, "_build_state_dict", return_value={"ok": True}), \
             patch.object(mba, "_safe_eval_js") as mock_eval:
            app._push_state_to_ui(force=True)
        self.assertEqual(mock_eval.call_count, 2)

    def test_alert_window_independent_topmost_without_promoting_other_windows_or_focus(self):
        import ctypes
        from ctypes import wintypes
        import floating_widget as fw

        if sys.platform != "win32":
            self.skipTest("仅在 Windows 上验证提醒窗口独立置顶层级")

        import clr
        clr.AddReference("System.Windows.Forms")
        clr.AddReference("System.Drawing")
        import System.Windows.Forms as WinForms
        from System.Drawing import Color, Point, Size

        user32 = ctypes.windll.user32
        GWL_EXSTYLE = -20
        fg_before = int(user32.GetForegroundWindow() or 0)

        main_f = WinForms.Form()
        settings_f = WinForms.Form()
        float_f = WinForms.Form()
        alert_f = WinForms.Form()
        try:
            for f, sz, pt in (
                (main_f, (360, 240), (60, 60)),
                (settings_f, (360, 240), (90, 90)),
                (float_f, (180, 50), (120, 120)),
                (alert_f, (280, 56), (150, 150)),
            ):
                f.FormBorderStyle = getattr(WinForms.FormBorderStyle, "None")
                f.ShowInTaskbar = False
                f.StartPosition = WinForms.FormStartPosition.Manual
                f.BackColor = Color.FromArgb(26, 30, 39)
                f.Size = Size(*sz)
                f.Location = Point(*pt)

            alert_f.Owner = None
            h_main = int(main_f.Handle.ToInt64())
            h_set = int(settings_f.Handle.ToInt64())
            h_flt = int(float_f.Handle.ToInt64())
            h_alert = int(alert_f.Handle.ToInt64())

            for h in (h_main, h_set, h_flt):
                fw.apply_non_activating_tool_style(h, layered=True)
                fw.set_layered_window_alpha(h, 0.9)
                user32.ShowWindow(wintypes.HWND(h), fw.SW_SHOWNOACTIVATE)

            # 仅对提醒窗口设置独立最高置顶
            fw.apply_non_activating_tool_style(h_alert, layered=True)
            fw.set_layered_window_alpha(h_alert, 1.0)
            user32.ShowWindow(wintypes.HWND(h_alert), fw.SW_SHOWNOACTIVATE)
            self.assertTrue(fw.set_window_topmost_noactivate(h_alert, True, x=150, y=150, w=280, h=56, show=True))
            WinForms.Application.DoEvents()

            ex_alert = int(user32.GetWindowLongW(wintypes.HWND(h_alert), GWL_EXSTYLE)) & 0xFFFFFFFF
            ex_main = int(user32.GetWindowLongW(wintypes.HWND(h_main), GWL_EXSTYLE)) & 0xFFFFFFFF
            ex_set = int(user32.GetWindowLongW(wintypes.HWND(h_set), GWL_EXSTYLE)) & 0xFFFFFFFF
            ex_flt = int(user32.GetWindowLongW(wintypes.HWND(h_flt), GWL_EXSTYLE)) & 0xFFFFFFFF

            # 提醒窗口独立 TopMost + 不抢焦点 + 不进 Alt+Tab
            self.assertTrue(bool(ex_alert & fw.WS_EX_TOPMOST))
            self.assertTrue(bool(ex_alert & fw.WS_EX_NOACTIVATE))
            self.assertTrue(bool(ex_alert & fw.WS_EX_TOOLWINDOW))
            self.assertIsNone(alert_f.Owner)
            # 主窗口、设置窗口、非置顶悬浮窗绝不被连带置顶
            self.assertFalse(bool(ex_main & fw.WS_EX_TOPMOST))
            self.assertFalse(bool(ex_set & fw.WS_EX_TOPMOST))
            self.assertFalse(bool(ex_flt & fw.WS_EX_TOPMOST))
            # 前台窗口焦点纹丝不动
            self.assertEqual(int(user32.GetForegroundWindow() or 0), fg_before)

            # 提醒关闭前降级释放置顶状态
            self.assertTrue(fw.set_window_topmost_noactivate(h_alert, False, show=False))
            user32.ShowWindow(wintypes.HWND(h_alert), fw.SW_HIDE)
            WinForms.Application.DoEvents()
            ex_after = int(user32.GetWindowLongW(wintypes.HWND(h_alert), GWL_EXSTYLE)) & 0xFFFFFFFF
            self.assertFalse(bool(ex_after & fw.WS_EX_TOPMOST))
            self.assertEqual(int(user32.GetForegroundWindow() or 0), fg_before)
        finally:
            for f in (alert_f, float_f, settings_f, main_f):
                try:
                    f.Dispose()
                except Exception:
                    pass


class TestV275BatteryAccuracyChargingAndFonts(unittest.TestCase):
    """v2.7.5 电量真实性、充电快速检测、异常跳变复核、跨品牌缓存与全局字体回归测试。"""

    @staticmethod
    def _vgn_reply(pct: int, charging: bool = False, mv: int = 3920) -> list[int]:
        frame = [0x08, 0x04, 0x00, 0x00, 0x00, 0x00, pct & 0xFF, 1 if charging else 0, (mv >> 8) & 0xFF, mv & 0xFF] + [0] * 6
        frame.append((0x55 - sum(frame)) % 256)
        return frame

    def test_vgn_17b_vs_compx_20b_isolation_and_exact_vid_pid(self) -> None:
        from unittest.mock import patch
        from providers.vgn_provider import VgnCompxProvider

        # 20B CompX 键盘 (3554:FA09) 排在 17B VGN 鼠标 (3554:FB3D 有线 + 3554:FB3E 2.4G) 前面
        snap = [
            {
                "vendor_id": 0x3554,
                "product_id": 0xFA09,
                "usage_page": 0xFF02,
                "usage": 0x0002,
                "interface_number": 1,
                "path": b"kb-20b-path",
                "product_string": "AULA F75 2.4G Receiver",
            },
            {
                "vendor_id": 0x3554,
                "product_id": 0xFB3E,
                "usage_page": 0xFF02,
                "usage": 0x0002,
                "interface_number": 1,
                "path": b"vgn-24g-path",
                "product_string": "VGN DragonFly F2 Pro Max",
            },
            {
                "vendor_id": 0x3554,
                "product_id": 0xFB3D,
                "usage_page": 0xFF02,
                "usage": 0x0002,
                "interface_number": 1,
                "path": b"vgn-wired-path",
                "product_string": "VGN DragonFly F2 Pro Max",
            },
        ]

        def fake_lengths(path: bytes) -> tuple[int, int, int]:
            if path == b"kb-20b-path":
                return (20, 20, 0)
            return (17, 17, 0)

        prov = VgnCompxProvider()
        queried_paths: list[bytes] = []

        def fake_query(path: bytes, max_attempts: int = 2):
            queried_paths.append(path)
            return self._vgn_reply(80, charging=True, mv=4100), {
                "ok": True, "duration_ms": 12.0, "timeouts": 0, "retries": 0, "io_error": False, "skipped_backoff": False
            }

        with patch("vgn_battery._safe_report_lengths", side_effect=fake_lengths), \
                patch.object(prov._vgn_reader, "_query_once", side_effect=fake_query):
            devs = prov.poll(snap, force=True)

        # 20B 键盘被严格隔离；优先有线 FB3D 且使用其自身 VID/PID，不取快照首个匹配项
        self.assertEqual(queried_paths, [b"vgn-wired-path"])
        self.assertEqual(len(devs), 1)
        self.assertEqual(devs[0].vid, 0x3554)
        self.assertEqual(devs[0].pid, 0xFB3D)
        self.assertEqual(devs[0].device_id, "vgn:3554:fb3d")
        self.assertEqual(devs[0].percent, 80)
        self.assertTrue(devs[0].charging)
        self.assertFalse(devs[0].from_cache)
        self.assertFalse(devs[0].stale)

    def test_vgn_unplug_clears_cache_and_failures_never_fake_online_or_flip_charging(self) -> None:
        from unittest.mock import patch
        from vgn_battery import VgnBatteryReader

        snap_mouse_a = [{
            "vendor_id": 0x3554, "product_id": 0xFB3E, "usage_page": 0xFF02, "usage": 0x0002,
            "interface_number": 1, "path": b"mouse-a", "product_string": "VGN DragonFly F2 Pro Max",
        }]
        reader = VgnBatteryReader()

        ok_stats = {"ok": True, "duration_ms": 8.0, "timeouts": 0, "retries": 0, "io_error": False, "skipped_backoff": False}
        fail_stats = {"ok": False, "duration_ms": 15.0, "timeouts": 1, "retries": 1, "io_error": False, "skipped_backoff": False}

        with patch("vgn_battery._safe_report_lengths", return_value=(17, 17, 0)):
            # 1. 首次成功读取 60% 充电中
            with patch.object(reader, "_query_once", return_value=(self._vgn_reply(60, charging=True, mv=4050), ok_stats)):
                r1 = reader.read(hid_snapshot=snap_mouse_a, force=True)
            self.assertTrue(r1.online)
            self.assertTrue(r1.charging)
            self.assertEqual(r1.percent, 60)
            self.assertFalse(r1.stale)
            ok_ts = r1.last_success_ts
            self.assertIsNotNone(ok_ts)

            # 2. 连续 2 次读取失败：绝不伪装在线、不伪造 timestamp、不错误翻转充电状态
            time.sleep(0.02)
            with patch.object(reader, "_query_once", return_value=(None, fail_stats)):
                r_fail1 = reader.read(hid_snapshot=snap_mouse_a, force=True)
                r_fail2 = reader.read(hid_snapshot=snap_mouse_a, force=True)
            for rf in (r_fail1, r_fail2):
                self.assertFalse(rf.online)
                self.assertFalse(rf.asleep)
                self.assertTrue(rf.from_cache)
                self.assertTrue(rf.stale)
                self.assertTrue(rf.charging)  # 读取失败不能错误把充电态切为 False
                self.assertEqual(rf.timestamp, ok_ts)
                self.assertEqual(rf.last_success_ts, ok_ts)

            # 3. 拔出设备：彻底清理 _last_valid 与状态表
            r_unplug = reader.read(hid_snapshot=[], force=False)
            self.assertFalse(r_unplug.connected)
            self.assertIsNone(reader._last_valid)
            self.assertEqual(len(reader._device_states), 0)

            # 4. 重新插入设备若首轮失败：绝不返回拔出前的旧 60%
            with patch.object(reader, "_query_once", return_value=(None, fail_stats)):
                r_replug_fail = reader.read(hid_snapshot=snap_mouse_a, force=True)
            self.assertIsNone(r_replug_fail.percent)
            self.assertFalse(r_replug_fail.online)
            self.assertTrue(r_replug_fail.stale)

    def test_vgn_multi_device_no_crosstalk(self) -> None:
        from unittest.mock import patch
        from providers.vgn_provider import VgnCompxProvider

        snap_two = [
            {
                "vendor_id": 0x3554, "product_id": 0xFB3E, "usage_page": 0xFF02, "usage": 0x0002,
                "interface_number": 1, "path": b"f2-path", "product_string": "VGN DragonFly F2 Pro Max",
            },
            {
                "vendor_id": 0x3554, "product_id": 0xF58A, "usage_page": 0xFF02, "usage": 0x0002,
                "interface_number": 1, "path": b"r1-path", "product_string": "VXE R1 Pro Max",
            },
        ]
        prov = VgnCompxProvider()
        ok_stats = {"ok": True, "duration_ms": 5.0, "timeouts": 0, "retries": 0, "io_error": False, "skipped_backoff": False}

        def fake_query(path: bytes, max_attempts: int = 2):
            if path == b"f2-path":
                return self._vgn_reply(85, charging=False, mv=4020), ok_stats
            return self._vgn_reply(35, charging=True, mv=3790), ok_stats

        with patch("vgn_battery._safe_report_lengths", return_value=(17, 17, 0)), \
                patch.object(prov._vgn_reader, "_query_once", side_effect=fake_query):
            devs = prov.poll(snap_two, force=True)

        by_id = {d.device_id: d for d in devs}
        self.assertEqual(len(by_id), 2)
        self.assertEqual(by_id["vgn:3554:fb3e"].percent, 85)
        self.assertFalse(by_id["vgn:3554:fb3e"].charging)
        self.assertEqual(by_id["vgn:3554:f58a"].percent, 35)
        self.assertTrue(by_id["vgn:3554:f58a"].charging)

    def test_vgn_50_to_75_jump_confirmation_and_transient_spike_rejection(self) -> None:
        from unittest.mock import patch
        from vgn_battery import VgnBatteryReader

        snap = [{
            "vendor_id": 0x3554, "product_id": 0xFB3E, "usage_page": 0xFF02, "usage": 0x0002,
            "interface_number": 1, "path": b"vgn-jump", "product_string": "VGN DragonFly F2 Pro Max",
        }]
        ok_stats = {"ok": True, "duration_ms": 6.0, "timeouts": 0, "retries": 0, "io_error": False, "skipped_backoff": False}

        # 场景 A：50% -> 75% 且复核连续返回 75% -> 接受真实 75%，绝不人为压成 50%/55%
        reader_a = VgnBatteryReader()
        seq_a = iter([
            (self._vgn_reply(50, charging=False, mv=3810), ok_stats),
            (self._vgn_reply(75, charging=True, mv=4010), ok_stats),   # 首次跳变
            (self._vgn_reply(75, charging=True, mv=4012), ok_stats),   # 复核确认
        ])
        with patch("vgn_battery._safe_report_lengths", return_value=(17, 17, 0)), \
                patch("vgn_battery.time.sleep"), \
                patch.object(reader_a, "_query_once", side_effect=lambda *a, **kw: next(seq_a)):
            r1 = reader_a.read(snap, force=True)
            r2 = reader_a.read(snap, force=True)
        self.assertEqual(r1.percent, 50)
        self.assertEqual(r2.percent, 75)
        self.assertTrue(r2.online)
        self.assertTrue(r2.charging)
        self.assertTrue(r2.diagnostic["anomaly_detected"])
        self.assertEqual(r2.diagnostic["anomaly_resolution"], "confirmed_hardware_reading")
        self.assertEqual(r2.diagnostic["percentage_delta"], 25)
        self.assertEqual(r2.diagnostic["charging_transition"], "started_charging")
        self.assertGreaterEqual(len(r2.diagnostic["confirmation_reads"]), 1)

        # 场景 B：50% -> 单次异常 75% -> 复核回到 50% -> 拒绝异常值覆盖，保持 50%
        reader_b = VgnBatteryReader()
        seq_b = iter([
            (self._vgn_reply(50, charging=False, mv=3810), ok_stats),
            (self._vgn_reply(75, charging=True, mv=4010), ok_stats),   # 瞬时异常帧
            (self._vgn_reply(50, charging=True, mv=3820), ok_stats),   # 复核 1 回落
            (self._vgn_reply(50, charging=True, mv=3820), ok_stats),   # 复核 2 稳定
        ])
        with patch("vgn_battery._safe_report_lengths", return_value=(17, 17, 0)), \
                patch("vgn_battery.time.sleep"), \
                patch.object(reader_b, "_query_once", side_effect=lambda *a, **kw: next(seq_b)):
            reader_b.read(snap, force=True)
            r_spike = reader_b.read(snap, force=True)
        self.assertEqual(r_spike.percent, 50)
        self.assertTrue(r_spike.charging)  # 充电状态正常更新且不人为提高电量
        self.assertTrue(r_spike.diagnostic["anomaly_detected"])
        self.assertEqual(r_spike.diagnostic["anomaly_resolution"], "rejected_transient_spike")

        # 场景 C：50% 未充 -> 50% 充电中：充电状态变化不人为提高电量
        reader_c = VgnBatteryReader()
        seq_c = iter([
            (self._vgn_reply(50, charging=False, mv=3810), ok_stats),
            (self._vgn_reply(50, charging=True, mv=3980), ok_stats),
        ])
        with patch("vgn_battery._safe_report_lengths", return_value=(17, 17, 0)), \
                patch.object(reader_c, "_query_once", side_effect=lambda *a, **kw: next(seq_c)):
            reader_c.read(snap, force=True)
            r_chg = reader_c.read(snap, force=True)
        self.assertEqual(r_chg.percent, 50)
        self.assertTrue(r_chg.charging)
        self.assertEqual(r_chg.diagnostic["percentage_delta"], 0)
        self.assertEqual(r_chg.diagnostic["charging_transition"], "started_charging")
        self.assertFalse(r_chg.diagnostic["anomaly_detected"])

    def test_all_adapters_cache_fallback_never_forges_timestamp_and_clears_on_unplug(self) -> None:
        from providers.base import make_cached_device
        from providers.razer_hid import RazerHidProvider
        from providers.steelseries_hid import SteelSeriesHidProvider
        from providers.corsair_hid import CorsairHidProvider
        from providers.hyperx_hid import HyperXHidProvider
        from providers.extra_brands import ExtraBrandsProvider
        from providers.standard_hid import StandardHidBatteryProvider

        old_ts = 1700000123.0
        base_dev = DeviceBattery(
            device_id="razer:viper-v3-pro", name="Razer Viper V3 Pro", brand="Razer",
            kind=KIND_MOUSE, vid=0x1532, pid=0x00C1, connected=True, online=True,
            percent=68, charging=True, timestamp=old_ts, last_success_ts=old_ts,
        )
        fb = make_cached_device(base_dev, asleep=True, status_detail="休眠中", now_ts=old_ts + 3600.0)
        self.assertEqual(fb.timestamp, old_ts)
        self.assertEqual(fb.last_success_ts, old_ts)
        self.assertTrue(fb.from_cache)
        self.assertTrue(fb.stale)
        self.assertFalse(fb.online)
        self.assertTrue(fb.charging)  # 保留原充电态不误翻转

        # 各品牌适配器均支持热插拔清理内部缓存
        for cls in (RazerHidProvider, SteelSeriesHidProvider, CorsairHidProvider, HyperXHidProvider, ExtraBrandsProvider):
            p = cls()
            p._cache["dummy"] = base_dev
            p.on_device_change()
            self.assertEqual(len(p._cache), 0)

        # StandardHid 120s 节流期内对已拔出设备立即过滤
        std = StandardHidBatteryProvider()
        std._cached = [
            DeviceBattery("stdhid:1234:5678", "Test HID", "Wireless", KIND_MOUSE, vid=0x1234, pid=0x5678, online=True, percent=70, timestamp=old_ts, last_success_ts=old_ts)
        ]
        std._last_poll_mono = time.monotonic()
        self.assertEqual(std.poll(hid_snapshot=[], force=False), [])
        # 在场设备命中节流时保留原 last_success_ts，不伪造 timestamp
        in_snap = [{"vendor_id": 0x1234, "product_id": 0x5678, "path": b"std-p"}]
        throttled = std.poll(hid_snapshot=in_snap, force=False)
        self.assertEqual(len(throttled), 1)
        self.assertTrue(throttled[0].from_cache)
        self.assertEqual(throttled[0].timestamp, old_ts)
        self.assertEqual(throttled[0].last_success_ts, old_ts)

    def test_protocol_accuracy_razer_logitech_steelseries_sony_bluetooth(self) -> None:
        from providers.razer_hid import build_razer_request, parse_razer_reply
        from providers.logitech_hidpp import parse_hidpp_battery
        from providers.steelseries_hid import parse_steelseries_headset, parse_steelseries_gamebuds_sub
        from providers.extra_brands import parse_sony_inzone_buds
        from providers.bluetooth_provider import aggregate_bluetooth_pnp_nodes

        # 1. Razer 拒绝 0x01 BUSY、错 TID 和坏 CRC
        req = build_razer_request(0x1F, 0x07, 0x80)
        busy = list(req)
        busy[1] = 0x01
        self.assertIsNone(parse_razer_reply(busy, 0x07, 0x80, expected_tid=0x1F, verify_crc=True))
        bad_tid = list(req)
        bad_tid[1] = 0x02
        bad_tid[2] = 0x3F
        self.assertIsNone(parse_razer_reply(bad_tid, 0x07, 0x80, expected_tid=0x1F, verify_crc=True))
        bad_crc = list(req)
        bad_crc[1] = 0x02
        bad_crc[10] = 200  # 未重算 CRC
        self.assertIsNone(parse_razer_reply(bad_crc, 0x07, 0x80, expected_tid=0x1F, verify_crc=True))
        good = list(bad_crc)
        crc = 0
        for b in good[3:89]:
            crc ^= b
        good[89] = crc
        self.assertIsNotNone(parse_razer_reply(good, 0x07, 0x80, expected_tid=0x1F, verify_crc=True))

        # 2. Logitech 0x1001 干电池 (1500mV / 3000mV) 绝不误套锂电曲线算成 0%
        _, pct_1aa, _, _, mv_1aa = parse_hidpp_battery(0x1001, [0x05, 0xDC, 0x00])  # 1500mV
        self.assertIsNone(pct_1aa)
        self.assertEqual(mv_1aa, 1500)
        _, pct_2aa, _, _, mv_2aa = parse_hidpp_battery(0x1001, [0x0B, 0xB8, 0x00])  # 3000mV
        self.assertIsNone(pct_2aa)
        self.assertEqual(mv_2aa, 3000)

        # 3. SteelSeries 拒绝越界杂包 (0xFF 不硬截断为 100%) + GameBuds SubBattery
        self.assertIsNone(parse_steelseries_headset("arctis1", [0x06, 0x12, 0x00, 0xFF]))
        self.assertIsNone(parse_steelseries_headset("nova5", [0xB0, 0x01, 0x00, 0xFF, 0x00]))
        self.assertIsNone(parse_steelseries_headset("arctis7p", [0xB0, 0x00, 0x09, 0x00]))
        sub_gb = parse_steelseries_gamebuds_sub([0xB0, 0, 0, 0x03, 0x03, 65, 80])
        self.assertIsNotNone(sub_gb)
        self.assertEqual((sub_gb.left_percent, sub_gb.right_percent), (65, 80))

        # 4. Sony INZONE Buds 单耳离线 (state=0, lvl=0) 返回 None，不误报 0%
        buds_one_off = [0x02, 20, 0x04, 0xFF, 0, 0, 0x96, 0xC3, 0x10, 0x04, 0xA0, 0x02, 0x00, 0, 0, 1, 78, 1, 90, 0]
        ok, main_pct, _, sub = parse_sony_inzone_buds(buds_one_off)
        self.assertTrue(ok)
        self.assertEqual(main_pct, 78)
        self.assertIsNone(sub.left_percent)
        self.assertEqual(sub.right_percent, 78)

        # 5. 蓝牙根节点明确断开 (root_connected=False) 不被滞后子节点误判在线
        bt_nodes = [
            {"instance_id": "BTHENUM\\DEV_AABBCCDDEEFF\\8&1", "name": "iKF King", "battery": None, "is_connected": False},
            {"instance_id": "BTHENUM\\{0000111E-0000-1000-8000-00805F9B34FB}\\8&1&AABBCCDDEEFF_C00000000", "name": "Hands-Free", "battery": 70, "is_connected": True},
        ]
        self.assertEqual(aggregate_bluetooth_pnp_nodes(bt_nodes), [])

    def test_bluetooth_mac_redacted_in_diagnostics_export(self) -> None:
        bt_dev = DeviceBattery(
            device_id="bt:aabbccddeeff",
            name="iKF King",
            brand="iKF",
            kind=KIND_HEADSET,
            connection_mode="蓝牙",
            connected=True,
            online=True,
            percent=80,
        )
        air_dev = DeviceBattery(
            device_id="airpods:112233445566",
            name="AirPods Pro (第 2 代)",
            brand="Apple",
            kind=KIND_EARBUDS,
            connection_mode="蓝牙 BLE",
            connected=True,
            online=True,
            percent=90,
        )
        mgr = DeviceManager(providers=[_DummyProvider([bt_dev, air_dev])])
        diag = mgr.export_diagnostics(hid_snapshot=[])
        serialized = json.dumps(diag, ensure_ascii=False)
        self.assertNotIn("aabbccddeeff", serialized.lower())
        self.assertNotIn("112233445566", serialized.lower())
        self.assertIn("bt:anon_", serialized)
        self.assertIn("airpods:anon_", serialized)

    def test_stale_and_cached_data_blocked_from_alerts_and_live_ui(self) -> None:
        from app_config import AppConfig
        from mouse_battery_app import MouseBatteryApp, evaluate_tiered_alerts

        cfg = AppConfig()
        stale_dev = DeviceBattery(
            device_id="vgn:3554:fb3e", name="VGN Dragonfly F2 Pro Max", brand="VGN",
            kind=KIND_MOUSE, connected=True, online=False, asleep=False,
            percent=8, charging=False, from_cache=True, stale=True, last_success_ts=1700000000.0,
        )
        cached_online = DeviceBattery(
            device_id="kb-compx:3554:fa09", name="AULA F75", brand="AULA",
            kind=KIND_KEYBOARD, connected=True, online=True, asleep=False,
            percent=10, charging=False, from_cache=True, stale=False, last_success_ts=1700000000.0,
        )
        # 过期数据与缓存数据绝不触发低电量提醒
        self.assertEqual(evaluate_tiered_alerts([stale_dev, cached_online], cfg, {}), [])

        # 主窗口序列化：过期数据 live_percent 必须为 None，alert_level 为 offline
        app = MouseBatteryApp(start_hidden=True)
        app.devices = [stale_dev]
        serialized = app._sorted_devices()
        self.assertEqual(len(serialized), 1)
        self.assertIsNone(serialized[0]["live_percent"])
        self.assertEqual(serialized[0]["alert_level"], "offline")

    def test_charging_fast_response_tray_sync_pending_merge_and_monotonic_guard(self) -> None:
        from unittest.mock import MagicMock
        from mouse_battery_app import MouseBatteryApp

        app = MouseBatteryApp(start_hidden=True)
        app.cfg.poll_interval_sec = 25
        tray_mock = MagicMock()
        tray_mock.set_icon.return_value = True
        app._tray = tray_mock
        app._sync_floating_widget = MagicMock()
        app._push_state_to_ui = MagicMock()
        app._check_low_batteries = MagicMock()

        # 1. 无线放电 50% -> 插入充电线 50% 充电中 -> 立即刷新托盘并进入 10s 充电自适应周期
        d_dis = DeviceBattery("vgn:3554:fb3e", "VGN Dragonfly F2 Pro Max", "VGN", KIND_MOUSE, connected=True, online=True, percent=50, charging=False)
        d_chg = DeviceBattery("vgn:3554:fb3e", "VGN Dragonfly F2 Pro Max", "VGN", KIND_MOUSE, connected=True, online=True, percent=50, charging=True)
        app.manager = DeviceManager(providers=[_DummyProvider([d_dis])])
        self.assertTrue(app._poll_once(reason="startup", force_rescan=True, force_query=True))
        self.assertEqual(app._compute_next_poll_interval(), 25)  # 常规放电保持 25s，绝不降成 1s
        self.assertEqual(tray_mock.set_icon.call_count, 1)

        app.manager.providers = [_DummyProvider([d_chg])]
        self.assertTrue(app._poll_once(reason="device_change", force_rescan=True, force_query=True))
        self.assertEqual(tray_mock.set_icon.call_count, 2)  # 充电切换立即更新托盘图标
        self.assertEqual(app._compute_next_poll_interval(), 10)  # 充电期间自适应 10s
        diag = app.manager.get_poll_diagnostics()
        self.assertTrue(diag["last_tray_sync"]["charging"])
        self.assertEqual(diag["battery_transitions"][-1]["charging_transition"], "started_charging")

        # 2. 并发高优先级请求在锁忙时合并为单一 _pending_poll，绝不丢弃也不产生请求堆积
        app._poll_lock.acquire()
        try:
            self.assertFalse(app._poll_once(reason="device_change", force_rescan=True, force_query=True))
            self.assertFalse(app._poll_once(reason="wakeup", force_rescan=False, force_query=True))
            self.assertIsNotNone(app._pending_poll)
            self.assertEqual(app._pending_poll, ("device_change", True, True))
        finally:
            app._pending_poll = None
            app._poll_lock.release()

        # 3. 单调 poll_seq 防旧结果覆盖新结果
        app._last_applied_poll_seq = 999
        app.manager.providers = [_DummyProvider([d_dis])]
        self.assertFalse(app._poll_once(reason="scheduled"))
        self.assertTrue(app.devices[0].charging)  # 旧序号不得覆盖已应用的充电状态

    def test_long_run_consistency_and_global_font_standards(self) -> None:
        from unittest.mock import patch
        from floating_widget import resolve_winforms_font_family
        from vgn_battery import VgnBatteryReader

        # 1. 连续 60 轮交替（正常/丢包/休眠/唤醒/拔插/充电）数据一致性无崩溃无伪造 timestamp
        snap = [{
            "vendor_id": 0x3554, "product_id": 0xFB3E, "usage_page": 0xFF02, "usage": 0x0002,
            "interface_number": 1, "path": b"vgn-long", "product_string": "VGN DragonFly F2 Pro Max",
        }]
        ok_stats = {"ok": True, "duration_ms": 4.0, "timeouts": 0, "retries": 0, "io_error": False, "skipped_backoff": False}
        fail_stats = {"ok": False, "duration_ms": 8.0, "timeouts": 1, "retries": 0, "io_error": False, "skipped_backoff": False}
        reader = VgnBatteryReader()

        with patch("vgn_battery._safe_report_lengths", return_value=(17, 17, 0)), patch("vgn_battery.time.sleep"):
            last_ok_ts = None
            for i in range(60):
                if i % 15 == 10:
                    # 模拟拔出
                    r = reader.read([], force=False)
                    self.assertFalse(r.connected)
                    last_ok_ts = None
                elif i % 5 in (2, 3):
                    # 模拟偶发失败
                    with patch.object(reader, "_query_once", return_value=(None, fail_stats)):
                        r = reader.read(snap, force=True)
                    self.assertFalse(r.online)
                    if last_ok_ts is not None:
                        self.assertEqual(r.timestamp, last_ok_ts)
                else:
                    pct = 70 if (i % 15 < 7) else 75
                    chg = i % 15 >= 7
                    with patch.object(reader, "_query_once", return_value=(self._vgn_reply(pct, charging=chg), ok_stats)):
                        r = reader.read(snap, force=True)
                    self.assertTrue(r.online)
                    self.assertFalse(r.stale)
                    last_ok_ts = r.last_success_ts

        # 2. 全局字体栈与 tabular-nums 规范校验
        root = Path(__file__).resolve().parent.parent
        common_css = (root / "ui" / "common.css").read_text(encoding="utf-8")
        index_html = (root / "ui" / "index.html").read_text(encoding="utf-8")
        settings_html = (root / "ui" / "settings.html").read_text(encoding="utf-8")

        self.assertIn('Inter, "Segoe UI Variable", "Noto Sans SC", "Microsoft YaHei UI"', common_css)
        self.assertIn('"Cascadia Code", "JetBrains Mono", Consolas, monospace', common_css)
        self.assertIn("tabular-nums", index_html)
        self.assertIn("var(--font-mono)", settings_html)
        self.assertTrue(len(resolve_winforms_font_family(numeric=False)) > 0)
        self.assertTrue(len(resolve_winforms_font_family(numeric=True)) > 0)


class TestV276TrayIconAndHoverPopup(unittest.TestCase):
    """v2.7.6 系统托盘极简动态图标、悬停紧凑电量浮层、定位兼容与防干扰回归门禁。"""

    def test_charging_keeps_battery_outline_and_fill_on_each_native_grid(self):
        from floating_widget import draw_battery_icon

        for size in (16, 20, 24, 28, 32):
            for light_bg in (False, True):
                with self.subTest(size=size, light=light_bg):
                    normal = draw_battery_icon(size, 75, light_bg=light_bg)
                    charging = draw_battery_icon(size, 75, charging=True, light_bg=light_bg)
                    self.assertEqual(normal.getbbox(), charging.getbbox())
                    outline = normal.getpixel((0, size // 2))
                    normal_pixels = [normal.getpixel((x, y)) for y in range(size) for x in range(size)]
                    charging_pixels = [charging.getpixel((x, y)) for y in range(size) for x in range(size)]
                    self.assertTrue(all(after == outline for before, after in zip(normal_pixels, charging_pixels) if before == outline))
                    def green_count(pixels):
                        return sum(g > max(r, b) + 40 and a >= 128 for r, g, b, a in pixels)

                    self.assertGreaterEqual(green_count(charging_pixels), green_count(normal_pixels) * 0.45)
                    mid = size // 2
                    window = [(x, y) for y in range(mid - 2, mid + 2) for x in range(mid - 3, mid + 2)]
                    self.assertTrue(any(max(charging.getpixel(pt)[:3]) < 40 and charging.getpixel(pt)[3] > 220 for pt in window))
                    self.assertTrue(any(min(charging.getpixel(pt)[:3]) > 170 and charging.getpixel(pt)[3] > 155 for pt in window))

    def test_tray_fill_tracks_percent_on_each_grid_with_or_without_charging(self):
        from floating_widget import draw_battery_icon

        def filled_span(icon):
            size = icon.width
            return sum(
                a / 255
                for x in range(size)
                if (r := icon.getpixel((x, size // 2)))[1] > max(r[0], r[2]) + 55
                and (a := r[3]) > 0
            )

        for size in (16, 20, 24, 28, 32):
            baseline = filled_span(draw_battery_icon(size, 100, low_t1=0, low_t2=0, low_t3=0))
            for pct in (10, 25, 50, 75, 90, 100):
                with self.subTest(size=size, pct=pct):
                    plain = draw_battery_icon(size, pct, low_t1=0, low_t2=0, low_t3=0)
                    self.assertAlmostEqual(filled_span(plain), baseline * pct / 100, delta=0.85)
            charging = [filled_span(draw_battery_icon(size, pct, charging=True)) for pct in (10, 25, 50, 75, 90, 100)]
            self.assertGreater(charging[-1], charging[3])
            self.assertGreater(charging[3], charging[2])
            self.assertGreater(charging[2], charging[0])

    def test_hover_status_height_only_when_needed_in_single_and_mixed_rows(self):
        from dataclasses import replace
        from providers.base import DeviceBattery, KIND_MOUSE
        from tray_hover_popup import build_tray_hover_rows, compute_popup_logical_size

        normal = DeviceBattery(device_id="vgn", name="VGN Dragonfly F2 Pro Max", brand="VGN",
                               kind=KIND_MOUSE, percent=65, connected=True, online=True)
        charging = replace(normal, device_id="charge", name="Logitech G Pro X Superlight 2", brand="Logitech", charging=True, percent=25)
        expired = replace(normal, device_id="expired", name="Razer Viper V3 Pro", brand="Razer", stale=True)
        rows = build_tray_hover_rows([normal, charging, expired])
        self.assertEqual(rows[0].name, normal.name)
        self.assertEqual([r.status_text for r in rows], ["", "充电中", "数据过期"])
        self.assertEqual([r.value_text for r in rows], ["65%", "25%", "—"])
        default_height = compute_popup_logical_size(rows[:1])[1]
        charging_height = compute_popup_logical_size(rows[1:2])[1]
        self.assertGreater(charging_height, default_height)
        normal_pair = compute_popup_logical_size(rows[:1] * 2)[1]
        self.assertEqual(compute_popup_logical_size(rows[:2])[1] - normal_pair, charging_height - default_height)
        # 滚动到两个特殊状态之后，普通行占满可见区域，浮层高度随窗口内容收紧。
        long_rows = rows + rows[:1] * 7
        self.assertGreater(compute_popup_logical_size(long_rows)[1],
                           compute_popup_logical_size(long_rows, scroll_offset=3)[1])

    @unittest.skipUnless(sys.platform == "win32", "需要 Windows GDI")
    def test_hicon_edges_composite_correctly_with_native_drawiconex(self):
        import ctypes
        from ctypes import wintypes

        from PIL import Image
        from tray_icon import _BITMAPV5HEADER, _gdi32, destroy_hicon_safe, pil_image_to_hicon

        gdi = ctypes.WinDLL("gdi32")
        user = ctypes.WinDLL("user32")
        gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
        gdi.CreateCompatibleDC.restype = wintypes.HDC
        gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        gdi.SelectObject.restype = wintypes.HGDIOBJ
        gdi.DeleteDC.argtypes = [wintypes.HDC]
        user.DrawIconEx.argtypes = [
            wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.HICON,
            ctypes.c_int, ctypes.c_int, wintypes.UINT, wintypes.HBRUSH, wintypes.UINT,
        ]
        info = _BITMAPV5HEADER()
        info.bV5Size, info.bV5Width, info.bV5Height = ctypes.sizeof(info), 16, -16
        info.bV5Planes, info.bV5BitCount = 1, 32
        bits = ctypes.c_void_p()
        dc = gdi.CreateCompatibleDC(None)
        bitmap = _gdi32.CreateDIBSection(dc, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
        self.assertTrue(bitmap and bits.value)
        previous = gdi.SelectObject(dc, bitmap)
        icon = pil_image_to_hicon(Image.new("RGBA", (16, 16), (200, 100, 50, 128)))
        try:
            self.assertTrue(icon)
            for background in (0, 120):
                ctypes.memmove(bits.value, bytes((background, background, background, 255)) * 256, 1024)
                self.assertTrue(user.DrawIconEx(dc, 0, 0, icon, 16, 16, 0, None, 3))
                bgr = ctypes.string_at(bits.value, 3)
                for actual, source in zip(bgr, (50, 100, 200)):
                    self.assertAlmostEqual(actual, (source + background) / 2, delta=1)
        finally:
            destroy_hicon_safe(icon)
            gdi.SelectObject(dc, previous)
            _gdi32.DeleteObject(bitmap)
            gdi.DeleteDC(dc)

    def test_hover_shows_brand_model_and_explicit_charging_state(self):
        from providers.base import DeviceBattery, KIND_HEADSET
        from tray_hover_popup import build_tray_hover_rows

        dev = DeviceBattery(
            device_id="headset", name="SteelSeries Arctis Nova 7", brand="SteelSeries",
            kind=KIND_HEADSET, percent=83, connected=True, online=True, charging=True,
        )
        row, = build_tray_hover_rows([dev])
        self.assertEqual((row.name, row.status_text, row.value_text), ("SteelSeries Arctis Nova 7", "充电中", "83%"))
        dev.charging = False
        row, = build_tray_hover_rows([dev])
        self.assertEqual((row.status_text, row.value_text), ("", "83%"))
        dev.full, dev.percent = True, 100
        row, = build_tray_hover_rows([dev])
        self.assertEqual((row.status_text, row.value_text), ("已充满", "100%"))
        dev.name, dev.brand = "AirPods Pro 2", "Apple"
        row, = build_tray_hover_rows([dev])
        self.assertEqual(row.name, "Apple AirPods Pro 2")

    @unittest.skipUnless(sys.platform == "win32", "需要 Windows 显示器 API")
    def test_hover_monitor_query_preserves_shared_point_signature(self):
        import ctypes
        from ctypes import wintypes

        from tray_hover_popup import _query_monitor_metrics_for_point

        monitor, work_area, scale = _query_monitor_metrics_for_point((0, 0))
        self.assertGreater(monitor[2] - monitor[0], 0)
        self.assertGreater(work_area[3] - work_area[1], 0)
        self.assertGreaterEqual(scale, 1.0)
        self.assertTrue(ctypes.windll.user32.MonitorFromPoint(wintypes.POINT(0, 0), 2))

    def test_minimal_tray_battery_icon_sizes_states_and_taskbar_themes(self):
        from floating_widget import draw_battery_icon
        from tray_icon import destroy_hicon_safe, pil_image_to_hicon

        sizes = (16, 20, 24, 28, 32, 64)
        states = [
            (85, False, True, False),   # 正常绿色
            (25, False, True, False),   # 一级黄
            (15, False, True, False),   # 二级橙
            (8, False, True, False),    # 三级红
            (65, True, True, False),    # 充电中（带闪电）
            (100, True, True, True),    # 已充满（真实 full 状态）
            (None, False, True, False), # 休眠/未知灰态
            (None, False, False, False),# 离线灰态
        ]
        for sz in sizes:
            for light_bg in (False, True):
                for pct, chg, conn, full in states:
                    img = draw_battery_icon(
                        size=sz,
                        percent=pct,
                        charging=chg,
                        connected=conn,
                        light_bg=light_bg,
                        full=full,
                    )
                    self.assertEqual(img.size, (sz, sz))
                    self.assertEqual(img.mode, "RGBA")
                    # 必须含透明背景（非实心不透明方块）且含满画布高占比前景像素
                    alpha = img.getchannel("A")
                    lo, hi = alpha.getextrema()
                    self.assertEqual(lo, 0)
                    self.assertGreaterEqual(hi, 230)
                    bbox = alpha.getbbox()
                    self.assertIsNotNone(bbox)
                    bw = bbox[2] - bbox[0]
                    bh = bbox[3] - bbox[1]
                    # 横向细框电池充分利用画布宽度，高度与参考图约为画布的一半。
                    self.assertGreaterEqual(bw, int(sz * 0.90), f"width too small at {sz}px: {bw}")
                    self.assertEqual(bh, round(sz * 0.50), f"height at {sz}px: {bh}")
                    if sys.platform == "win32" and sz in (16, 20, 24, 28, 32):
                        hicon = pil_image_to_hicon(img)
                        self.assertGreater(hicon, 0)
                        destroy_hicon_safe(hicon)

        # 浅色任务栏与深色任务栏外框颜色应存在明确区分
        dark_img = draw_battery_icon(size=32, percent=80, charging=False, connected=True, light_bg=False)
        light_img = draw_battery_icon(size=32, percent=80, charging=False, connected=True, light_bg=True)
        self.assertNotEqual(dark_img.tobytes(), light_img.tobytes())

        # 实心填充像素面积应随真实电量单调递增（40% < 70% < 100%）
        def _count_green(im):
            raw = im.tobytes()
            return sum(
                1 for i in range(0, len(raw), 4)
                if raw[i + 3] > 200 and raw[i + 1] > raw[i] + 40 and raw[i + 1] > raw[i + 2] + 30
            )

        g40 = _count_green(draw_battery_icon(size=24, percent=40, charging=False, connected=True))
        g70 = _count_green(draw_battery_icon(size=24, percent=70, charging=False, connected=True))
        g100 = _count_green(draw_battery_icon(size=24, percent=100, charging=False, connected=True))
        self.assertGreater(g40, 0)
        self.assertGreater(g70, g40)
        self.assertGreater(g100, g70)

        # 充电中与非充电同电量应存在闪电像素差异，且闪电不得遮挡过多绿色填充区
        chg_img = draw_battery_icon(size=24, percent=75, charging=True, connected=True, full=False)
        norm_img = draw_battery_icon(size=24, percent=75, charging=False, connected=True, full=False)
        self.assertNotEqual(chg_img.tobytes(), norm_img.tobytes())
        self.assertGreater(_count_green(chg_img), _count_green(norm_img) * 0.55)

        full_chg = draw_battery_icon(size=32, percent=100, charging=True, connected=True, full=True)
        full_only = draw_battery_icon(size=32, percent=100, charging=False, connected=True, full=True)
        self.assertEqual(full_chg.tobytes(), full_only.tobytes())

    def test_tray_hover_device_name_simplification_and_duplicate_disambiguation(self):
        from providers.base import DeviceBattery, KIND_HEADSET, KIND_KEYBOARD, KIND_MOUSE
        from providers.device_naming import resolve_tray_hover_device_names

        devs = [
            DeviceBattery(device_id="m1", name="VGN Dragonfly F2 Pro Max", brand="VGN", kind=KIND_MOUSE, percent=75, charging=True, connected=True, online=True, connection_mode="2.4GHz"),
            DeviceBattery(device_id="h1", name="SteelSeries Arctis Nova 7", brand="SteelSeries", kind=KIND_HEADSET, percent=82, connected=True, online=True, connection_mode="2.4GHz"),
            DeviceBattery(device_id="k1", name="ATK68", brand="ATK", kind=KIND_KEYBOARD, percent=20, connected=True, online=True, connection_mode="2.4GHz"),
        ]
        names = resolve_tray_hover_device_names(devs)
        self.assertEqual(names, ["VGN F2 Pro Max", "Arctis Nova 7", "ATK68"])

        # 自定义名称优先级最高
        aliased = resolve_tray_hover_device_names(devs, aliases={"m1": "主力鼠标"})
        self.assertEqual(aliased[0], "主力鼠标")

        # 同品牌同型号不同连接方式自动区分
        dup_conn = [
            DeviceBattery(device_id="d1", name="VGN Dragonfly F2 Pro Max", brand="VGN", kind=KIND_MOUSE, percent=75, connected=True, online=True, connection_mode="2.4GHz"),
            DeviceBattery(device_id="d2", name="VGN Dragonfly F2 Pro Max", brand="VGN", kind=KIND_MOUSE, percent=90, connected=True, online=True, connection_mode="Wired"),
        ]
        dup_names = resolve_tray_hover_device_names(dup_conn)
        self.assertEqual(len(set(dup_names)), 2)
        self.assertIn("2.4G", dup_names[0])
        self.assertIn("有线", dup_names[1])

        # 完全相同的双设备以序号 #1 / #2 稳定区分
        dup_same = [
            DeviceBattery(device_id="s1", name="VGN Dragonfly F2 Pro Max", brand="VGN", kind=KIND_MOUSE, percent=75, connected=True, online=True, connection_mode="2.4GHz"),
            DeviceBattery(device_id="s2", name="VGN Dragonfly F2 Pro Max", brand="VGN", kind=KIND_MOUSE, percent=60, connected=True, online=True, connection_mode="2.4GHz"),
        ]
        same_names = resolve_tray_hover_device_names(dup_same)
        self.assertEqual(len(set(same_names)), 2)
        self.assertTrue(same_names[0].endswith("#1"))
        self.assertTrue(same_names[1].endswith("#2"))

    def test_tray_hover_rows_no_fake_cached_percent_and_size_bounds(self):
        from providers.base import DeviceBattery, KIND_HEADSET, KIND_KEYBOARD, KIND_MOUSE
        from tray_hover_popup import (
            POPUP_MAX_VISIBLE_ROWS,
            POPUP_MAX_WIDTH_DIP,
            POPUP_MIN_WIDTH_DIP,
            build_tray_hover_rows,
            compute_popup_logical_size,
            render_hover_popup_pil,
        )

        devs = [
            DeviceBattery(device_id="d1", name="VGN Dragonfly F2 Pro Max", brand="VGN", kind=KIND_MOUSE, percent=75, charging=True, connected=True, online=True, connection_mode="2.4GHz"),
            DeviceBattery(device_id="d2", name="SteelSeries Arctis Nova 7", brand="SteelSeries", kind=KIND_HEADSET, percent=82, connected=True, online=True, connection_mode="2.4GHz"),
            DeviceBattery(device_id="d3", name="ATK68", brand="ATK", kind=KIND_KEYBOARD, percent=20, connected=True, online=True, connection_mode="2.4GHz"),
            # 过期缓存数据不得伪装实时电量
            DeviceBattery(device_id="d4", name="Logitech G Pro X Superlight 2", brand="Logitech", kind=KIND_MOUSE, percent=64, connected=True, online=False, stale=True, from_cache=True),
            # 休眠状态显示灰态休眠
            DeviceBattery(device_id="d5", name="Razer Viper V3 Pro", brand="Razer", kind=KIND_MOUSE, percent=None, connected=True, online=False, asleep=True),
            # 隐藏设备不应展示
            DeviceBattery(device_id="d_hid", name="Hidden Mouse", brand="VGN", kind=KIND_MOUSE, percent=50, connected=True, online=True),
        ]
        rows = build_tray_hover_rows(devs, hidden_ids={"d_hid"})
        self.assertEqual(len(rows), 5)
        self.assertEqual((rows[0].name, rows[0].value_text, rows[0].show_bolt, rows[0].alert_level), ("VGN Dragonfly F2 Pro Max", "75%", True, "charging"))
        self.assertEqual((rows[1].name, rows[1].value_text, rows[1].show_bolt, rows[1].alert_level), ("SteelSeries Arctis Nova 7", "82%", False, "normal"))
        self.assertEqual((rows[2].name, rows[2].value_text, rows[2].show_bolt, rows[2].alert_level), ("ATK68", "20%", False, "tier2"))
        self.assertEqual((rows[3].value_text, rows[3].alert_level, rows[3].percent), ("—", "stale", None))
        self.assertEqual((rows[4].value_text, rows[4].alert_level, rows[4].percent), ("—", "sleep", None))

        w_dip, h_dip, vis, scrollable = compute_popup_logical_size(rows)
        self.assertGreaterEqual(w_dip, POPUP_MIN_WIDTH_DIP)
        self.assertLessEqual(w_dip, POPUP_MAX_WIDTH_DIP)
        self.assertEqual(vis, 5)
        self.assertFalse(scrollable)

        # 超多设备（8 台）自动限高并启用滚动
        many = [
            DeviceBattery(device_id=f"x{i}", name=f"Device {i}", brand="VGN", kind=KIND_MOUSE, percent=90 - i * 8, connected=True, online=True)
            for i in range(8)
        ]
        many_rows = build_tray_hover_rows(many)
        mw, mh, mvis, mscroll = compute_popup_logical_size(many_rows)
        self.assertEqual(mvis, POPUP_MAX_VISIBLE_ROWS)
        self.assertTrue(mscroll)
        self.assertGreaterEqual(mw, POPUP_MIN_WIDTH_DIP)
        self.assertLessEqual(mw, POPUP_MAX_WIDTH_DIP)

        # 多 DPI 离屏渲染验证无报错且比例准确
        for sc in (1.0, 1.25, 1.5, 1.75, 2.0):
            im = render_hover_popup_pil(rows[:3], is_dark=(sc > 1.3), scale=sc)
            self.assertGreater(im.width, 200)
            self.assertGreater(im.height, 80)

    def test_tray_hover_state_machine_delays_and_no_flicker_on_passover(self):
        from tray_hover_popup import TrayHoverStateMachine

        sm = TrayHoverStateMachine(show_delay_sec=0.30, hide_delay_sec=0.20)
        icon = (1700, 1044, 1724, 1076)
        popup = (1600, 920, 1840, 1036)

        # 1. 快速划过托盘图标（< 300ms 移开）不得闪烁弹出
        sm.on_tray_move(10.00, (1712, 1060), icon)
        self.assertEqual(sm.state, "pending_show")
        self.assertIsNone(sm.tick(10.12, (1500, 900)))
        self.assertEqual(sm.state, "idle")

        # 2. 持续悬停 >= 300ms 后弹出
        sm.on_tray_move(20.00, (1712, 1060), icon)
        self.assertIsNone(sm.tick(20.20, (1712, 1060)))
        self.assertEqual(sm.state, "pending_show")
        self.assertEqual(sm.tick(20.32, (1712, 1060)), "show")
        self.assertEqual(sm.state, "visible")

        # 3. 移动到浮层本体上保持可见
        self.assertIsNone(sm.tick(20.60, (1712, 980), popup_rect=popup))
        self.assertEqual(sm.state, "visible")

        # 4. 离开后 120ms 内返回取消隐藏
        self.assertIsNone(sm.tick(21.00, (1200, 500), popup_rect=popup))
        self.assertEqual(sm.state, "pending_hide")
        self.assertIsNone(sm.tick(21.12, (1712, 980), popup_rect=popup))
        self.assertEqual(sm.state, "visible")

        # 5. 离开 >= 200ms 自动收起
        self.assertIsNone(sm.tick(22.00, (1200, 500), popup_rect=popup))
        self.assertEqual(sm.state, "pending_hide")
        self.assertIsNone(sm.tick(22.15, (1200, 500), popup_rect=popup))
        self.assertEqual(sm.tick(22.22, (1200, 500), popup_rect=popup), "hide")
        self.assertEqual(sm.state, "idle")

        # 6. force_hide 立即终止显示
        sm.on_tray_move(30.00, (1712, 1060), icon)
        sm.tick(30.35, (1712, 1060))
        self.assertTrue(sm.force_hide())
        self.assertEqual(sm.state, "idle")

    def test_tray_hover_positioning_win10_four_edges_autohide_overflow_multimonitor_dpi(self):
        from tray_hover_popup import compute_hover_popup_rect

        pw, ph = 260, 120

        # 1. 底部任务栏（Win10/11 标准）
        x, y = compute_hover_popup_rect(
            icon_rect=(1780, 1044, 1804, 1076),
            cursor_pos=(1792, 1060),
            popup_size=(pw, ph),
            monitor_rect=(0, 0, 1920, 1080),
            work_area=(0, 0, 1920, 1040),
            scale=1.0,
        )
        self.assertGreaterEqual(x, 8)
        self.assertLessEqual(x + pw, 1920 - 8)
        self.assertLessEqual(y + ph, 1040)

        # 2. Win10 顶部任务栏
        x, y = compute_hover_popup_rect(
            icon_rect=(1780, 4, 1804, 36),
            cursor_pos=(1792, 20),
            popup_size=(pw, ph),
            monitor_rect=(0, 0, 1920, 1080),
            work_area=(0, 40, 1920, 1080),
            scale=1.0,
        )
        self.assertGreaterEqual(y, 40)
        self.assertLessEqual(x + pw, 1920 - 8)

        # 3. Win10 左侧任务栏
        x, y = compute_hover_popup_rect(
            icon_rect=(16, 960, 48, 984),
            cursor_pos=(30, 972),
            popup_size=(pw, ph),
            monitor_rect=(0, 0, 1920, 1080),
            work_area=(62, 0, 1920, 1080),
            scale=1.0,
        )
        self.assertGreaterEqual(x, 62)
        self.assertLessEqual(y + ph, 1080 - 8)

        # 4. Win10 右侧任务栏
        x, y = compute_hover_popup_rect(
            icon_rect=(1872, 960, 1904, 984),
            cursor_pos=(1888, 972),
            popup_size=(pw, ph),
            monitor_rect=(0, 0, 1920, 1080),
            work_area=(0, 0, 1858, 1080),
            scale=1.0,
        )
        self.assertLessEqual(x + pw, 1858)
        self.assertLessEqual(y + ph, 1080 - 8)

        # 5. 任务栏自动隐藏（work_area == monitor_rect）
        x, y = compute_hover_popup_rect(
            icon_rect=(1780, 1048, 1804, 1078),
            cursor_pos=(1792, 1060),
            popup_size=(pw, ph),
            monitor_rect=(0, 0, 1920, 1080),
            work_area=(0, 0, 1920, 1080),
            scale=1.25,
        )
        self.assertLess(y + ph, 1048)
        self.assertLessEqual(x + pw, 1920 - 8)

        # 6. 托盘折叠区（overflow_rect）+ 负坐标副屏 + 150% DPI
        ox, oy = compute_hover_popup_rect(
            icon_rect=None,  # 模拟折叠区 Shell_NotifyIconGetRect 不可用，走光标安全回退
            cursor_pos=(-220, 920),
            popup_size=(360, 160),
            monitor_rect=(-1920, 0, 0, 1080),
            work_area=(-1920, 0, 0, 1040),
            scale=1.5,
            overflow_rect=(-280, 860, -140, 1000),
        )
        self.assertGreaterEqual(ox, -1920 + 10)
        self.assertLessEqual(ox + 360, -280)
        self.assertGreaterEqual(oy, 10)
        self.assertLessEqual(oy + 160, 1040 - 10)

    def test_tray_hover_toggle_tooltip_suppression_and_no_extra_polling(self):
        from unittest.mock import MagicMock, patch
        import mouse_battery_app as mba
        from mouse_battery_app import MouseBatteryApp
        from providers.base import DeviceBattery, KIND_MOUSE

        app = MouseBatteryApp(start_hidden=False)
        self.assertTrue(app.cfg.tray_hover_popup_enabled)

        fake_tray = MagicMock()
        fake_tray.set_icon.return_value = True
        fake_tray.set_title.return_value = True
        fake_tray.ensure_visible.return_value = True
        fake_tray.is_menu_open.return_value = False
        app._tray = fake_tray
        app._push_state_to_ui = MagicMock()
        app._sync_floating_widget = MagicMock()
        app.devices = [
            DeviceBattery(
                device_id="vgn:1",
                name="VGN Dragonfly F2 Pro Max",
                brand="VGN",
                kind=KIND_MOUSE,
                percent=75,
                charging=True,
                connected=True,
                online=True,
                connection_mode="2.4GHz",
            )
        ]

        # 开启悬停浮层时，原生 szTip 置空防重复弹窗
        app._update_tray_visual()
        fake_tray.set_title.assert_called_with("")

        # 关闭「悬停显示设备电量」后，立即隐藏浮层并恢复普通系统托盘提示文本
        app.tray_hover_popup.hide = MagicMock()
        with patch.object(mba, "save_config"):
            app.update_settings({"tray_hover_popup_enabled": False})
        self.assertFalse(app.cfg.tray_hover_popup_enabled)
        app.tray_hover_popup.hide.assert_called()
        restored_title = fake_tray.set_title.call_args[0][0]
        self.assertIn("VGN Dragonfly F2 Pro Max", restored_title)
        self.assertIn("75%", restored_title)

        # 悬停浮层构建行仅复用已有 self.devices，不触发 manager.poll()
        app.manager.poll = MagicMock()
        rows = app._build_tray_hover_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].name, "VGN Dragonfly F2 Pro Max")
        app.manager.poll.assert_not_called()

        # 设置页外观设置含「悬停显示设备电量」开关及规范说明文字
        settings_html = (Path(__file__).resolve().parent.parent / "ui" / "settings.html").read_text(encoding="utf-8")
        self.assertIn("悬停显示设备电量", settings_html)
        self.assertIn("鼠标停留在系统托盘图标上时，快速查看已连接设备的电量。", settings_html)
        self.assertIn("tray_hover_popup_enabled", settings_html)

    def test_v277_unified_floating_widget_multi_device_snap_and_popup_specs(self):
        from app_config import FloatingWidgetConfig
        from floating_widget import (
            FLOATING_RADIUS_DIP,
            FloatingDeviceItem,
            compute_floating_logical_size,
            render_floating_widget_pil,
            snap_floating_position,
        )
        from mouse_battery_app import MouseBatteryApp
        from providers.base import DeviceBattery, KIND_HEADSET, KIND_KEYBOARD, KIND_MOUSE
        from tray_hover_popup import (
            FADE_IN_MS,
            FADE_OUT_MS,
            POPUP_MIN_WIDTH_DIP,
            POPUP_RADIUS_DIP,
            POPUP_ROW_HEIGHT_DIP,
            POPUP_SINGLE_MAX_WIDTH_DIP,
            POPUP_STATUS_HEIGHT_DIP,
            build_tray_hover_rows,
            compute_popup_logical_size,
        )

        # 1. 悬停浮层与悬浮窗圆角及动画参数统一规范校验
        self.assertEqual(POPUP_RADIUS_DIP, FLOATING_RADIUS_DIP)
        self.assertGreaterEqual(POPUP_RADIUS_DIP, 10)
        self.assertEqual(POPUP_ROW_HEIGHT_DIP, 32)
        self.assertLessEqual(POPUP_ROW_HEIGHT_DIP + POPUP_STATUS_HEIGHT_DIP, 48)
        self.assertGreaterEqual(FADE_IN_MS, 120)
        self.assertLessEqual(FADE_IN_MS, 160)
        self.assertGreaterEqual(FADE_OUT_MS, 100)
        self.assertLessEqual(FADE_OUT_MS, 140)

        devs = [
            DeviceBattery(device_id="m1", name="VGN Dragonfly F2 Pro Max", brand="VGN", kind=KIND_MOUSE, percent=95, charging=True, connected=True, online=True, connection_mode="2.4GHz"),
            DeviceBattery(device_id="h1", name="Logitech G Pro X 2 Lightspeed", brand="Logitech", kind=KIND_HEADSET, percent=82, connected=True, online=True, connection_mode="2.4GHz"),
            DeviceBattery(device_id="k1", name="ATK68", brand="ATK", kind=KIND_KEYBOARD, percent=24, connected=True, online=True, connection_mode="2.4GHz"),
        ]

        # 单设备悬停浮层宽度落在 230~270 DIP
        single_rows = build_tray_hover_rows([devs[0]])
        sw, sh, svis, sscroll = compute_popup_logical_size(single_rows)
        self.assertEqual(svis, 1)
        self.assertFalse(sscroll)
        self.assertGreaterEqual(sw, POPUP_MIN_WIDTH_DIP)
        self.assertLessEqual(sw, POPUP_SINGLE_MAX_WIDTH_DIP)

        # 2. 桌面悬浮窗单设备与多设备条目构建与高度自适应
        app = MouseBatteryApp(start_hidden=False)
        app.devices = devs
        items_all = app._build_floating_device_items(FloatingWidgetConfig(enabled=True, device_id="auto"))
        self.assertEqual(len(items_all), 3)
        self.assertEqual(items_all[0].label, "VGN F2 Pro Max")
        self.assertTrue(items_all[0].show_bolt)
        self.assertEqual(items_all[2].value_text, "24%")

        items_lowest = app._build_floating_device_items(FloatingWidgetConfig(enabled=True, device_id="lowest"))
        self.assertEqual(len(items_lowest), 1)
        self.assertEqual(items_lowest[0].device_id, "k1")

        items_pinned = app._build_floating_device_items(FloatingWidgetConfig(enabled=True, device_id="m1", custom_label="主力鼠标"))
        self.assertEqual(len(items_pinned), 1)
        self.assertEqual(items_pinned[0].label, "主力鼠标")

        w1, h1, _ = compute_floating_logical_size("medium", [items_all[0]])
        w3, h3, _ = compute_floating_logical_size("medium", items_all)
        self.assertGreater(h3, h1 * 2)
        self.assertGreaterEqual(w1, 220)

        # 3. 悬浮窗拖拽磁性吸附逻辑校验
        sx, sy = snap_floating_position(10, 12, 240, 64, (0, 0, 1920, 1040), scale=1.0)
        self.assertEqual((sx, sy), (16, 16))
        rx, ry = snap_floating_position(1670, 965, 240, 64, (0, 0, 1920, 1040), scale=1.0)
        self.assertEqual((rx, ry), (1920 - 240 - 16, 1040 - 64 - 16))

        # 4. 离屏渲染支持单/多设备与 100%/150% DPI
        for sc in (1.0, 1.5):
            for dark in (False, True):
                im_s = render_floating_widget_pil([items_all[0]], size_key="medium", is_dark=dark, scale=sc)
                im_m = render_floating_widget_pil(items_all, size_key="medium", is_dark=dark, scale=sc)
                self.assertGreater(im_m.height, im_s.height * 2)


if __name__ == "__main__":
    unittest.main()
