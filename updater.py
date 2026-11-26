"""BattDock 基于 GitHub Releases 的轻量在线检查更新与 Windows 安全原地升级模块。

设计原则：
1. 零第三方依赖，仅使用 Python 标准库（兼容 Win10/11 与 PyInstaller 打包），不要求 GitHub Token。
2. 默认仅识别稳定正式版（跳过 draft 与 prerelease），自动兼容系统代理，断网优雅降级。
3. 仅通过 HTTPS 下载，优先匹配 BattDock Windows 便携包，支持 SHA256SUMS.txt 完整性校验与防 Zip Slip 校验。
4. 通过独立隐藏 PowerShell 辅助脚本（UTF-8 BOM，完美支持中文路径）在主进程退出后安全覆盖升级：
   - 失败时自动回滚原有程序文件；
   - 不删除用户目录中的其他无关文件，保留个人配置（%LOCALAPPDATA%\\BattDock\\config.json）与卸载脚本；
   - 自动清理旧版 VGNMouseBattery.exe 及重复开机自启项，重启新版本 BattDock.exe。
"""

from __future__ import annotations

import hashlib
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

from brand import (
    APP_EXE_NAME,
    APP_NAME,
    GITHUB_OWNER,
    GITHUB_REPO,
    GITHUB_REPO_URL,
    LATEST_RELEASE_API,
    LEGACY_EXE_NAME,
    LEGACY_RUN_VALUE_NAME,
    RELEASES_PAGE_URL,
    RUN_REG_PATH,
    RUN_VALUE_NAME,
)


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
    sha256_url: str = ""
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
    """将版本号（如 'v2.3.0' 或 '2.1.0-beta1'）解析为可比较的整数元组。"""
    clean = normalize_version_str(raw)
    if not clean:
        return (0,)
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
    """从 GitHub Release assets 中挑选 BattDock 的 Windows 便携版 HTTPS ZIP 包（排除旧版桥接包）。"""
    zip_assets = [
        a for a in (assets or [])
        if isinstance(a, dict)
        and str(a.get("name", "")).lower().endswith(".zip")
        and str(a.get("browser_download_url", "")).startswith("https://")
    ]
    if not zip_assets:
        return None
    # 1. 最优先匹配官方 BattDock Windows 便携包
    for a in zip_assets:
        name = str(a.get("name", "")).lower()
        if "battdock" in name and "portable" in name and "bridge" not in name:
            return a
    # 2. 其次匹配任意 BattDock ZIP
    for a in zip_assets:
        name = str(a.get("name", "")).lower()
        if "battdock" in name and "bridge" not in name:
            return a
    # 3. 兼容历史命名
    for a in zip_assets:
        name = str(a.get("name", "")).lower()
        if "win64" in name or "windows" in name:
            return a
    return zip_assets[0]


def select_checksum_asset(assets: list[dict[str, Any]]) -> str:
    """查找 Release 中随附的 SHA256SUMS.txt 校验文件 HTTPS 地址。"""
    for a in (assets or []):
        if not isinstance(a, dict):
            continue
        name = str(a.get("name", "")).lower()
        url = str(a.get("browser_download_url", ""))
        if name in ("sha256sums.txt", "checksums.txt") and url.startswith("https://"):
            return url
    return ""


def parse_sha256_manifest(text: str) -> dict[str, str]:
    """解析标准 `sha256  filename` 校验清单，返回 {小写文件名: 小写64位hex}。"""
    result: dict[str, str] = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([0-9a-fA-F]{64})\s+\*?(.+)$", line)
        if m:
            digest = m.group(1).lower()
            fname = Path(m.group(2).strip()).name.lower()
            result[fname] = digest
    return result


def compute_file_sha256(file_path: Path) -> str:
    h = hashlib.sha256()
    with file_path.open("rb") as f:
        while True:
            chunk = f.read(131072)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest().lower()


def verify_downloaded_sha256(file_path: Path, asset_name: str, sha256_url: str, timeout: float = 10.0) -> Optional[bool]:
    """如存在 SHA256SUMS.txt，则核对下载文件哈希。返回 True=校验通过，False=哈希不匹配，None=未提供清单。"""
    if not sha256_url or not sha256_url.startswith("https://"):
        return None
    req = urllib.request.Request(sha256_url, headers={"User-Agent": f"{APP_NAME}-Updater/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            manifest_text = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None
    table = parse_sha256_manifest(manifest_text)
    expected = table.get(Path(asset_name or file_path.name).name.lower())
    if not expected:
        return None
    actual = compute_file_sha256(file_path)
    return actual == expected


def parse_github_release_payload(payload: dict[str, Any], current_version: str) -> UpdateCheckResult:
    """解析 GitHub Releases API JSON 负载（自动过滤 draft 与 prerelease）。"""
    cur = normalize_version_str(current_version)
    if payload.get("draft") or payload.get("prerelease"):
        return UpdateCheckResult(
            ok=True,
            current_version=cur,
            latest_version=cur,
            has_update=False,
            release_url=RELEASES_PAGE_URL,
            error="",
        )

    tag = str(payload.get("tag_name") or payload.get("name") or "").strip()
    latest = normalize_version_str(tag)
    html_url = str(payload.get("html_url") or RELEASES_PAGE_URL).strip() or RELEASES_PAGE_URL
    body = str(payload.get("body") or "").strip()
    published_at = str(payload.get("published_at") or "").strip()
    assets = payload.get("assets") or []
    asset = select_release_asset(assets)
    sha256_url = select_checksum_asset(assets)
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
        sha256_url=sha256_url,
        published_at=published_at,
        error="",
    )


def check_for_update(current_version: str, timeout: float = 10.0) -> UpdateCheckResult:
    """请求 GitHub Releases 最新稳定版本信息，网络失败时返回友好中文提示。"""
    cur = normalize_version_str(current_version)
    req = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={
            "User-Agent": f"{APP_NAME}/{cur or '2.3'}",
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
    """仅通过 HTTPS 流式下载 Release ZIP 压缩包并持续回调进度。"""
    if not asset_url.startswith("https://"):
        raise ValueError("出于安全限制，仅允许通过 HTTPS 下载更新包")

    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    part_path = dest_zip.with_suffix(".zip.part")
    req = urllib.request.Request(
        asset_url,
        headers={"User-Agent": f"{APP_NAME}-Updater/1.0"},
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
        if downloaded <= 0 or (expected_size > 0 and downloaded < int(expected_size * 0.9)):
            raise RuntimeError("更新包下载不完整，请重试")
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
    exe_name: str = APP_EXE_NAME,
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
    exe_name: str = APP_EXE_NAME,
    work_root: Optional[Path] = None,
) -> Path:
    """生成并启动隐藏 PowerShell 覆盖更新脚本（支持失败回滚、不误删无关文件、清理旧版残留并重启 BattDock）。"""
    if sys.platform != "win32":
        raise RuntimeError("仅支持 Windows 平台执行原地自动更新")

    cleanup_root = work_root or staged_dir.parent
    script_path = Path(tempfile.gettempdir()) / f"battdock_apply_update_{os.getpid()}.ps1"

    def _ps_quote(p: Path) -> str:
        return "'" + str(p.resolve()).replace("'", "''") + "'"

    ps_script = f"""$ErrorActionPreference = 'Stop'
$TargetPid = {int(pid)}
$StagedDir = {_ps_quote(staged_dir)}
$TargetDir = {_ps_quote(target_dir)}
$CleanupDir = {_ps_quote(cleanup_root)}
$ExeName = '{exe_name}'
$LegacyExeName = '{LEGACY_EXE_NAME}'
$LogFile = Join-Path $env:TEMP 'battdock_updater.log'
$RollbackDir = Join-Path $env:TEMP ('battdock_rollback_' + $TargetPid)

function Write-Log([string]$msg) {{
    try {{
        Add-Content -Path $LogFile -Value ("[" + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + "] " + $msg) -Encoding UTF8
    }} catch {{}}
}}

Write-Log "开始应用 BattDock 更新：$StagedDir -> $TargetDir (等待 PID=$TargetPid 退出)"

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

# 2. 为可替换核心文件建立临时回滚备份（仅备份程序自身与 _internal，绝不触碰用户目录中的其他无关文件）
New-Item -ItemType Directory -Path $RollbackDir -Force | Out-Null
$CurExe = Join-Path $TargetDir $ExeName
$CurInternal = Join-Path $TargetDir '_internal'
if (Test-Path $CurExe) {{ Copy-Item $CurExe (Join-Path $RollbackDir $ExeName) -Force }}
if (Test-Path $CurInternal) {{ Move-Item $CurInternal (Join-Path $RollbackDir '_internal') -Force }}

# 3. 复制新版程序文件（带重试，失败则自动回滚旧版本）
$Applied = $false
for ($try = 0; $try -lt 10; $try++) {{
    try {{
        Get-ChildItem -Path $StagedDir -Force | ForEach-Object {{
            Copy-Item -Path $_.FullName -Destination $TargetDir -Recurse -Force
        }}
        $Applied = $true
        Write-Log "文件替换成功（尝试第 $($try + 1) 次）"
        break
    }} catch {{
        Write-Log "替换遇阻（第 $($try + 1) 次）：$($_.Exception.Message)"
        Start-Sleep -Milliseconds 500
    }}
}}

if (-not $Applied) {{
    Write-Log "更新失败，正在回滚至旧版本..."
    try {{
        $FailedInternal = Join-Path $TargetDir '_internal'
        if (Test-Path $FailedInternal) {{ Remove-Item $FailedInternal -Recurse -Force -ErrorAction SilentlyContinue }}
        if (Test-Path (Join-Path $RollbackDir '_internal')) {{ Move-Item (Join-Path $RollbackDir '_internal') $CurInternal -Force }}
        if (Test-Path (Join-Path $RollbackDir $ExeName)) {{ Copy-Item (Join-Path $RollbackDir $ExeName) $CurExe -Force }}
    }} catch {{}}
}} else {{
    # 清理历史遗留的旧版主程序（若存在），避免新旧版本共存
    $LegacyExe = Join-Path $TargetDir $LegacyExeName
    if (Test-Path $LegacyExe) {{
        Remove-Item $LegacyExe -Force -ErrorAction SilentlyContinue
    }}
    # 同步检查注册表，防止残留旧版重复开机自启项
    try {{
        $RunKey = 'HKCU:\\{RUN_REG_PATH}'
        $oldRun = Get-ItemProperty -Path $RunKey -Name '{LEGACY_RUN_VALUE_NAME}' -ErrorAction SilentlyContinue
        if ($oldRun) {{
            $isBg = $oldRun.'{LEGACY_RUN_VALUE_NAME}' -like '*--background*'
            $newExePath = Join-Path $TargetDir $ExeName
            $cmd = if ($isBg) {{ '"' + $newExePath + '" --background' }} else {{ '"' + $newExePath + '"' }}
            Set-ItemProperty -Path $RunKey -Name '{RUN_VALUE_NAME}' -Value $cmd
            Remove-ItemProperty -Path $RunKey -Name '{LEGACY_RUN_VALUE_NAME}' -ErrorAction SilentlyContinue
        }}
    }} catch {{}}
}}

# 4. 启动新版 BattDock.exe
$NewExe = Join-Path $TargetDir $ExeName
if (Test-Path $NewExe) {{
    Write-Log "正在启动新版本：$NewExe"
    Start-Process -FilePath $NewExe -WorkingDirectory $TargetDir
}}

# 5. 清理临时目录、回滚缓存与脚本自身
try {{ if (Test-Path $RollbackDir) {{ Remove-Item -Path $RollbackDir -Recurse -Force -ErrorAction SilentlyContinue }} }} catch {{}}
try {{ if (Test-Path $CleanupDir) {{ Remove-Item -Path $CleanupDir -Recurse -Force -ErrorAction SilentlyContinue }} }} catch {{}}
try {{ Remove-Item -Path $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue }} catch {{}}
"""
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
