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
            "html_url": "https://github.com/edwin99701/wireless-peripheral-battery-monitor/releases/tag/v2.4.0",
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

        raw_url = "https://github.com/edwin99701/wireless-peripheral-battery-monitor/releases/download/v2.6.0/BattDock-v2.6.0-Windows-x64-Portable.zip"

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
                    "html_url": "https://github.com/edwin99701/wireless-peripheral-battery-monitor/releases/tag/v2.7.2",
                    "body": "• 静默回退测试",
                    "assets": [{
                        "name": "BattDock-v2.7.2-Windows-x64-Portable.zip",
                        "browser_download_url": "https://github.com/edwin99701/wireless-peripheral-battery-monitor/releases/download/v2.7.2/BattDock-v2.7.2-Windows-x64-Portable.zip",
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
        idx_set = app_src.index('"设置", lambda _i, _m: self.open_settings_window')
        self.assertLess(idx_open, idx_flt)
        self.assertLess(idx_flt, idx_set)
        self.assertIn("checked=lambda _item: self._is_floating_enabled()", app_src)
        self.assertIn("self._refresh_tray_menu()", app_src)


if __name__ == "__main__":
    unittest.main()
