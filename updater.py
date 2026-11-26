"""基于 GitHub Releases 的轻量在线检查更新与 Windows 免安装一键覆盖更新模块。

设计原则：
1. 零第三方依赖，仅使用 Python 标准库（兼容 Win10/11 与 PyInstaller 打包）。
2. 自动兼容系统代理；网络异常、超时或离线时静默降级，绝不影响主程序监控。
3. 下载后校验 ZIP 完整性并防路径遍历（Zip Slip），仅在校验通过后执行覆盖更新。
4. 通过独立隐藏 PowerShell 辅助脚本（UTF-8 BOM，完美支持中文安装目录）在主进程退出后
   安全替换 `_internal/` 与 `VGNMouseBattery.exe`，保留 `卸载程序.bat` 与用户配置并自动重启。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Optional

GITHUB_OWNER = "edwin99701"
GITHUB_REPO = "wireless-peripheral-battery-monitor"
GITHUB_REPO_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
RELEASES_PAGE_URL = f"{GITHUB_REPO_URL}/releases"
LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"


@dataclass
class UpdateCheckResult:
    ok: bool
    current_version: str
    latest_version: str = ""
    has_update: bool = False
    release_url: str = RELEASES_PAGE_URL
    release_notes: str = ""
    asset_name: str = ""
    asset_url: str = ""
    asset_size: int = 0
    published_at: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_version_str(raw: str) -> str:
    """规范化版本字符串，去除前导 v/V 与首尾空白。"""
    s = (raw or "").strip()
    if s.lower().startswith("v"):
        s = s[1:].strip()
    return s


def parse_version(raw: str) -> tuple[int, ...]:
    """将版本号（如 'v2.2.0' 或 '2.1.0-beta1'）解析为可比较的整数元组。"""
    clean = normalize_version_str(raw)
    if not clean:
        return (0,)
    # 截取主版本段（丢弃 -rc1 / +build 等后缀）
    core = re.split(r"[-+]", clean, maxsplit=1)[0]
    nums = [int(m) for m in re.findall(r"\d+", core)]
    return tuple(nums) if nums else (0,)


def is_newer_version(latest: str, current: str) -> bool:
    """判断 latest 是否严格高于 current。"""
    a = list(parse_version(latest))
    b = list(parse_version(current))
    max_len = max(len(a), len(b))
    a.extend([0] * (max_len - len(a)))
    b.extend([0] * (max_len - len(b)))
    return tuple(a) > tuple(b)


def select_release_asset(assets: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """从 GitHub Release assets 中挑选最合适的 Windows 免安装 ZIP 包。"""
    zip_assets = [
        a for a in (assets or [])
        if isinstance(a, dict)
        and str(a.get("name", "")).lower().endswith(".zip")
        and str(a.get("browser_download_url", "")).startswith(("https://", "http://"))
    ]
    if not zip_assets:
        return None
    for a in zip_assets:
        name = str(a.get("name", "")).lower()
        if "win64" in name or "vgnmousebattery" in name:
            return a
    return zip_assets[0]


def parse_github_release_payload(payload: dict[str, Any], current_version: str) -> UpdateCheckResult:
    """解析 GitHub Releases API JSON 负载为 UpdateCheckResult（纯函数，便于单元测试）。"""
    cur = normalize_version_str(current_version)
    tag = str(payload.get("tag_name") or payload.get("name") or "").strip()
    latest = normalize_version_str(tag)
    html_url = str(payload.get("html_url") or RELEASES_PAGE_URL).strip() or RELEASES_PAGE_URL
    body = str(payload.get("body") or "").strip()
    published_at = str(payload.get("published_at") or "").strip()
    asset = select_release_asset(payload.get("assets") or [])
    has_upd = bool(latest) and is_newer_version(latest, cur)

    return UpdateCheckResult(
        ok=True,
        current_version=cur,
        latest_version=latest or cur,
        has_update=has_upd,
        release_url=html_url,
        release_notes=body[:1500],
        asset_name=str(asset.get("name", "")) if asset else "",
        asset_url=str(asset.get("browser_download_url", "")) if asset else "",
        asset_size=int(asset.get("size", 0) or 0) if asset else 0,
        published_at=published_at,
        error="",
    )


def check_for_update(current_version: str, timeout: float = 10.0) -> UpdateCheckResult:
    """请求 GitHub Releases 最新版本信息，网络失败时返回友好中文提示。"""
    cur = normalize_version_str(current_version)
    req = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={
            "User-Agent": f"WirelessPeripheralBatteryMonitor/{cur or '2.0'}",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
            if not isinstance(data, dict):
                return UpdateCheckResult(ok=False, current_version=cur, error="更新接口返回数据格式异常。")
            return parse_github_release_payload(data, cur)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return UpdateCheckResult(ok=False, current_version=cur, error="GitHub 仓库尚未发布正式版本。")
        if e.code == 403:
            return UpdateCheckResult(ok=False, current_version=cur, error="GitHub 接口请求频率受限，请稍后再试。")
        return UpdateCheckResult(ok=False, current_version=cur, error=f"检查更新失败（HTTP {e.code}）。")
    except (urllib.error.URLError, TimeoutError, OSError):
        return UpdateCheckResult(ok=False, current_version=cur, error="无法连接 GitHub，请检查网络连接或代理设置。")
    except Exception as e:
        return UpdateCheckResult(ok=False, current_version=cur, error=f"检查更新出错：{e}")


def download_update_asset(
    asset_url: str,
    dest_zip: Path,
    expected_size: int = 0,
    on_progress: Optional[Callable[[int, int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    timeout: float = 30.0,
) -> Path:
    """流式下载 Release ZIP 压缩包并持续回调进度。"""
    if not asset_url.startswith(("https://", "http://")):
        raise ValueError("无效的下载地址")

    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    part_path = dest_zip.with_suffix(".zip.part")
    req = urllib.request.Request(
        asset_url,
        headers={"User-Agent": "WirelessPeripheralBatteryMonitor-Updater/1.0"},
    )
    downloaded = 0
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, part_path.open("wb") as f:
            total_hdr = resp.headers.get("Content-Length")
            total = int(total_hdr) if (total_hdr and total_hdr.isdigit()) else int(expected_size or 0)
            if on_progress:
                on_progress(0, total)
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise RuntimeError("更新下载已取消")
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if on_progress:
                    on_progress(downloaded, total)
        if downloaded <= 0:
            raise RuntimeError("下载的更新包为空")
        if dest_zip.exists():
            dest_zip.unlink()
        part_path.replace(dest_zip)
        return dest_zip
    except Exception:
        try:
            if part_path.exists():
                part_path.unlink()
        except OSError:
            pass
        raise


def extract_and_verify_update(
    zip_path: Path,
    extract_dir: Path,
    exe_name: str = "VGNMouseBattery.exe",
) -> Path:
    """校验 ZIP 完整性与路径安全性（防 Zip Slip），解压并返回包含主程序的根目录。"""
    if extract_dir.exists():
        shutil.rmtree(extract_dir, ignore_errors=True)
    extract_dir.mkdir(parents=True, exist_ok=True)
    root_resolved = extract_dir.resolve()

    with zipfile.ZipFile(zip_path, "r") as zf:
        bad_member = zf.testzip()
        if bad_member is not None:
            raise ValueError(f"更新压缩包损坏：{bad_member}")
        for info in zf.infolist():
            dest = (extract_dir / info.filename).resolve()
            if root_resolved != dest and root_resolved not in dest.parents:
                raise ValueError(f"检测到不安全的压缩包路径：{info.filename}")
        zf.extractall(extract_dir)

    # 定位主程序所在目录（兼容顶层直接打包或嵌套单层文件夹）
    direct_exe = extract_dir / exe_name
    if direct_exe.is_file():
        return extract_dir
    for candidate in extract_dir.rglob(exe_name):
        if candidate.is_file():
            return candidate.parent
    raise FileNotFoundError(f"更新包中未找到主程序 {exe_name}")


def launch_windows_updater(
    staged_dir: Path,
    target_dir: Path,
    pid: int,
    exe_name: str = "VGNMouseBattery.exe",
    work_root: Optional[Path] = None,
) -> Path:
    """生成并启动隐藏 PowerShell 覆盖更新脚本（UTF-8 BOM，兼容中文路径），主进程退出后自动替换并重启。"""
    if sys.platform != "win32":
        raise RuntimeError("仅支持 Windows 平台执行原地自动更新")

    cleanup_root = work_root or staged_dir.parent
    script_path = Path(tempfile.gettempdir()) / f"vgn_apply_update_{os.getpid()}.ps1"

    def _ps_quote(p: Path) -> str:
        return "'" + str(p.resolve()).replace("'", "''") + "'"

    ps_script = f"""$ErrorActionPreference = 'Stop'
$TargetPid = {int(pid)}
$StagedDir = {_ps_quote(staged_dir)}
$TargetDir = {_ps_quote(target_dir)}
$CleanupDir = {_ps_quote(cleanup_root)}
$ExeName = '{exe_name}'
$LogFile = Join-Path $env:TEMP 'vgn_updater.log'

function Write-Log([string]$msg) {{
    try {{
        Add-Content -Path $LogFile -Value ("[" + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + "] " + $msg) -Encoding UTF8
    }} catch {{}}
}}

Write-Log "开始应用更新：$StagedDir -> $TargetDir (等待 PID=$TargetPid 退出)"

# 1. 等待旧进程退出（最多 12 秒，超时则强制结束）
for ($i = 0; $i -lt 48; $i++) {{
    $proc = Get-Process -Id $TargetPid -ErrorAction SilentlyContinue
    if (-not $proc) {{ break }}
    Start-Sleep -Milliseconds 250
}}
$proc = Get-Process -Id $TargetPid -ErrorAction SilentlyContinue
if ($proc) {{
    try {{ Stop-Process -Id $TargetPid -Force -ErrorAction SilentlyContinue }} catch {{}}
    Start-Sleep -Milliseconds 600
}}

# 2. 备份现有卸载脚本（如新版未包含则保留）
$UninstSrc = Join-Path $TargetDir '卸载程序.bat'
$UninstBak = Join-Path $env:TEMP ('vgn_uninstall_upd_' + $TargetPid + '.bat')
$HasUninstBak = $false
if (Test-Path $UninstSrc) {{
    try {{
        Copy-Item $UninstSrc $UninstBak -Force
        $HasUninstBak = $true
    }} catch {{}}
}}

# 3. 清理旧 _internal 目录并复制新版本文件（带重试以避开杀软短暂占用）
$OldInternal = Join-Path $TargetDir '_internal'
for ($try = 0; $try -lt 10; $try++) {{
    try {{
        if (Test-Path $OldInternal) {{
            Remove-Item -Path $OldInternal -Recurse -Force
        }}
        Get-ChildItem -Path $StagedDir -Force | ForEach-Object {{
            Copy-Item -Path $_.FullName -Destination $TargetDir -Recurse -Force
        }}
        Write-Log "文件替换成功（尝试第 $($try + 1) 次）"
        break
    }} catch {{
        Write-Log "替换遇阻（第 $($try + 1) 次）：$($_.Exception.Message)"
        Start-Sleep -Milliseconds 500
    }}
}}

if ($HasUninstBak -and (-not (Test-Path $UninstSrc))) {{
    try {{ Move-Item $UninstBak $UninstSrc -Force }} catch {{}}
}} elseif (Test-Path $UninstBak) {{
    Remove-Item $UninstBak -Force -ErrorAction SilentlyContinue
}}

# 4. 启动新版主程序
$NewExe = Join-Path $TargetDir $ExeName
if (Test-Path $NewExe) {{
    Write-Log "正在启动新版本：$NewExe"
    Start-Process -FilePath $NewExe -WorkingDirectory $TargetDir
}}

# 5. 清理临时目录与脚本自身
try {{
    if (Test-Path $CleanupDir) {{ Remove-Item -Path $CleanupDir -Recurse -Force -ErrorAction SilentlyContinue }}
}} catch {{}}
try {{ Remove-Item -Path $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue }} catch {{}}
"""
    # 使用 utf-8-sig（带 BOM）确保 Windows PowerShell 5.1 正确解析中文路径与中文注释
    script_path.write_text(ps_script, encoding="utf-8-sig")

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-File",
            str(script_path),
        ],
        creationflags=flags,
        close_fds=True,
    )
    return script_path
