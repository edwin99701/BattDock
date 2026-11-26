"""多品牌无线外设协议解析器与统一设备管理层自动化单元测试。"""

from __future__ import annotations

import sys
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

        # Strix Go 2.4: 3850 mV -> 75%
        sg = [0xFF, 0x1B] + [0] * 9 + [0x0A, 0x0F]
        self.assertEqual(parse_asus_strix_go(sg), (True, 75, False, 3850))

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


if __name__ == "__main__":
    unittest.main()
