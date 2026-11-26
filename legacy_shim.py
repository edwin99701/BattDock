"""旧版 VGNMouseBattery.exe (v2.2.0) 一键自动升级至 BattDock.exe 的平滑迁移桥接启动器。

仅打包进面向旧版的升级兼容桥接包（VGNMouseBattery-vX.Y.Z-win64-UpgradeBridge.zip）：
1. v2.2.0 自动更新完成后会启动同目录下的 VGNMouseBattery.exe；
2. 本桥接程序自动将开机自启项从 VGNMouseBattery 迁移至 BattDock（避免残留重复自启项）；
3. 立即启动同目录下的 BattDock.exe（附带 --cleanup-legacy-exe 参数清理旧桥接文件）并退出。
"""

from __future__ import annotations

import subprocess
import sys
import winreg
from pathlib import Path

RUN_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
LEGACY_RUN_VALUE = "VGNMouseBattery"
NEW_RUN_VALUE = "BattDock"


def _migrate_autostart(new_exe: Path) -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_REG_PATH, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
            try:
                old_val, _ = winreg.QueryValueEx(key, LEGACY_RUN_VALUE)
            except FileNotFoundError:
                return
            is_bg = "--background" in str(old_val).lower()
            new_cmd = f'"{new_exe}" --background' if is_bg else f'"{new_exe}"'
            winreg.SetValueEx(key, NEW_RUN_VALUE, 0, winreg.REG_SZ, new_cmd)
            winreg.DeleteValue(key, LEGACY_RUN_VALUE)
    except OSError:
        pass


def main() -> None:
    app_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    battdock_exe = app_dir / "BattDock.exe"
    if not battdock_exe.is_file():
        return
    _migrate_autostart(battdock_exe)
    extra_args = [a for a in sys.argv[1:] if a]
    if "--cleanup-legacy-exe" not in extra_args:
        extra_args.append("--cleanup-legacy-exe")
    flags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
    subprocess.Popen(
        [str(battdock_exe), *extra_args],
        cwd=str(app_dir),
        creationflags=flags,
        close_fds=True,
    )


if __name__ == "__main__":
    main()
