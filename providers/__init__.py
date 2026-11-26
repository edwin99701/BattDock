"""多品牌无线外设协议适配器包与统一设备管理层导出。"""

from .base import (
    BatteryProvider,
    DeviceBattery,
    KIND_EARBUDS,
    KIND_HEADSET,
    KIND_KEYBOARD,
    KIND_MOUSE,
    KIND_OTHER,
    STATUS_PROTOCOL,
    STATUS_UNSUPPORTED,
    STATUS_VERIFIED,
    SubBattery,
)
from .bluetooth_provider import BluetoothBatteryProvider, parse_airpods_continuity
from .corsair_hid import CorsairHidProvider
from .extra_brands import ExtraBrandsProvider
from .hyperx_hid import HyperXHidProvider
from .logitech_hidpp import LogitechHidppProvider
from .manager import DeviceManager, sanitize_device_reading
from .razer_hid import RazerHidProvider
from .steelseries_hid import SteelSeriesHidProvider
from .vgn_provider import VgnCompxProvider
from .wireless_headsets import WirelessHeadsetsProvider
from .wireless_keyboards import WirelessKeyboardsProvider

__all__ = [
    "BatteryProvider",
    "DeviceBattery",
    "SubBattery",
    "DeviceManager",
    "sanitize_device_reading",
    "VgnCompxProvider",
    "LogitechHidppProvider",
    "RazerHidProvider",
    "SteelSeriesHidProvider",
    "CorsairHidProvider",
    "HyperXHidProvider",
    "ExtraBrandsProvider",
    "WirelessHeadsetsProvider",
    "WirelessKeyboardsProvider",
    "BluetoothBatteryProvider",
    "parse_airpods_continuity",
    "KIND_MOUSE",
    "KIND_HEADSET",
    "KIND_EARBUDS",
    "KIND_KEYBOARD",
    "KIND_OTHER",
    "STATUS_VERIFIED",
    "STATUS_PROTOCOL",
    "STATUS_UNSUPPORTED",
]
