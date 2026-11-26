"""BattDock 基于 GitHub Releases 的轻量在线检查更新、简明摘要解析与 Windows 安全原地升级模块。

核心修复与设计原则（v2.4.0）：
1. 零第三方依赖、不内置 GitHub Token、自动兼容系统代理；仅识别正式稳定版本（过滤 draft/prerelease）。
2. 两层更新说明：
   - 优先解析 Release 中的结构化简明摘要（`<!-- BATTDOCK_SUMMARY_START -->` 块或 `update-summary.json`）；
   - 对历史无摘要版本自动清洗 Markdown 符号、文件名与提交号，提取 3-5 条简短面向普通用户的中文条目。
3. 仅通过 HTTPS 下载并校验 SHA256SUMS.txt 与 ZIP 完整性（含防 Zip Slip 路径遍历检查）。
4. 彻底修复跨盘符覆盖失败 Bug：
   - 回滚备份目录建立在目标程序同盘同目录下（`._battdock_rollback_<pid>`），不再跨盘 `Move-Item` 到系统临时目录；
   - 仅替换更新包内包含的文件，绝不删除用户目录中的其他文件；失败时自动完整回滚；
   - 等待旧进程及子进程释放锁后替换、自动重启新版 `BattDock.exe`、确认新进程运行并清理全部临时文件。
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
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from urllib.parse import urlparse

from brand import (
    APP_EXE_NAME,
    APP_NAME,
    CN_GITHUB_MIRRORS,
    GITHUB_OWNER,
    GITHUB_REPO,
    GITHUB_REPO_URL,
    LATEST_DOWNLOAD_BASE,
    LATEST_RELEASE_API,
    LEGACY_EXE_NAME,
    LEGACY_RUN_VALUE_NAME,
    RELEASES_PAGE_URL,
    RUN_REG_PATH,
    RUN_VALUE_NAME,
)

SUMMARY_START_MARKER = "<!-- BATTDOCK_SUMMARY_START"
SUMMARY_END_MARKER = "BATTDOCK_SUMMARY_END -->"

UPDATE_SOURCE_AUTO = "auto"      # 自动优选：优先国内加速节点，失败自动切换备用节点并兜底 GitHub 直连
UPDATE_SOURCE_CN = "cn"          # 仅使用国内加速节点
UPDATE_SOURCE_GITHUB = "github"  # 始终直连 GitHub 官方
UPDATE_SOURCE_CUSTOM = "custom"  # 使用用户自定义的国内 HTTPS 加速前缀


def normalize_mirror_prefix(raw: str) -> str:
    """规范化用户自定义的加速前缀，仅允许合法 HTTPS 地址，保证以 '/' 结尾。"""
    s = (raw or "").strip()
    if not s:
        return ""
    if not s.lower().startswith("https://"):
        return ""
    parsed = urlparse(s)
    if not parsed.netloc:
        return ""
    return s if s.endswith("/") else (s + "/")


def build_candidate_urls(
    original_url: str,
    update_source: str = UPDATE_SOURCE_AUTO,
    custom_mirror: str = "",
) -> list[tuple[str, str]]:
    """按更新线路策略生成候选下载列表 [(展示名称, 完整HTTPS链接)]，严格校验 HTTPS。"""
    url = (original_url or "").strip()
    if not url.startswith("https://"):
        return []

    is_github_download = url.startswith("https://github.com/")
    src = (update_source or UPDATE_SOURCE_AUTO).strip().lower()
    candidates: list[tuple[str, str]] = []

    if src == UPDATE_SOURCE_GITHUB or not is_github_download:
        candidates.append(("GitHub 官方", url))
        return candidates

    if src == UPDATE_SOURCE_CUSTOM:
        prefix = normalize_mirror_prefix(custom_mirror)
        if prefix:
            host = urlparse(prefix).netloc or "自定义镜像"
            candidates.append((f"自定义加速（{host}）", f"{prefix}{url}"))
        for name, m_prefix in CN_GITHUB_MIRRORS:
            candidates.append((f"国内加速（{name}）", f"{m_prefix}{url}"))
        candidates.append(("GitHub 官方", url))
        return candidates

    for name, m_prefix in CN_GITHUB_MIRRORS:
        candidates.append((f"国内加速（{name}）", f"{m_prefix}{url}"))

    if src != UPDATE_SOURCE_CN:
        candidates.append(("GitHub 官方", url))
    return candidates


def rank_candidate_urls(
    candidates: list[tuple[str, str]],
    probe_timeout: float = 3.5,
) -> list[tuple[str, str]]:
    """对多个候选加速节点并发做轻量 HEAD 探测，将最快响应的健康节点排在前面。"""
    if len(candidates) <= 1:
        return list(candidates)

    def _probe(idx_item: tuple[int, tuple[str, str]]) -> tuple[int, float, tuple[str, str]]:
        idx, (label, target_url) = idx_item
        t0 = time.perf_counter()
        req = urllib.request.Request(
            target_url,
            method="HEAD",
            headers={"User-Agent": f"{APP_NAME}-Updater/1.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=probe_timeout) as resp:
                status = getattr(resp, "status", 200)
                if 200 <= status < 400:
                    return (0, time.perf_counter() - t0, (label, target_url))
        except Exception:
            pass
        return (1, 999.0 + idx, (label, target_url))

    results: list[tuple[int, float, tuple[str, str]]] = []
    with ThreadPoolExecutor(max_workers=min(5, len(candidates))) as pool:
        futs = [pool.submit(_probe, (i, item)) for i, item in enumerate(candidates)]
        for fut in as_completed(futs):
            try:
                results.append(fut.result())
            except Exception:
                pass
    if not results:
        return list(candidates)
    results.sort(key=lambda x: (x[0], x[1]))
    return [item for _, _, item in results]


@dataclass
class UpdateCheckResult:
    ok: bool
    current_version: str
    latest_version: str = ""
    has_update: bool = False
    release_url: str = RELEASES_PAGE_URL
    release_notes: str = ""
    summary_items: list[str] = field(default_factory=list)
    important_notice: str = ""
    asset_name: str = ""
    asset_url: str = ""
    asset_size: int = 0
    sha256_url: str = ""
    summary_url: str = ""
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
    """将版本号（如 'v2.4.0' 或 '2.1.0-beta1'）解析为可比较的整数元组。"""
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
    for a in zip_assets:
        name = str(a.get("name", "")).lower()
        if "battdock" in name and "portable" in name and "bridge" not in name:
            return a
    for a in zip_assets:
        name = str(a.get("name", "")).lower()
        if "battdock" in name and "bridge" not in name:
            return a
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


def select_summary_asset(assets: list[dict[str, Any]]) -> str:
    """查找 Release 中随附的机器可读简明更新摘要 update-summary.json 地址。"""
    for a in (assets or []):
        if not isinstance(a, dict):
            continue
        name = str(a.get("name", "")).lower()
        url = str(a.get("browser_download_url", ""))
        if name == "update-summary.json" and url.startswith("https://"):
            return url
    return ""


def _strip_markdown_and_tech_noise(line: str) -> str:
    """去除原始 Markdown 标记、HTML 标签、代码标识符与文件路径，输出自然中文短句。"""
    s = (line or "").strip()
    s = re.sub(r"<!--.*?-->", "", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = re.sub(r"`[^`]*`", "", s)
    s = re.sub(r"[*_~#>]+", "", s)
    s = re.sub(r"^\s*[-•·\d.、]+\s*", "", s)
    # 去除括号中纯英文文件/路径/哈希注释，如（updater.py）
    s = re.sub(r"[（(]\s*[A-Za-z0-9_./\\-]+\.(?:py|js|html|css|json|bat|ps1|exe|zip)\s*[）)]", "", s)
    s = re.sub(r"\s+", " ", s).strip(" ：:;-—。")
    return s


def extract_user_summary(body: str, max_items: int = 5) -> tuple[list[str], str]:
    """从 Release 正文中提取面向普通用户的简明摘要（3-5 条、无 Markdown、无技术路径）。

    优先级：
    1. 正文内嵌结构化 JSON 块（`<!-- BATTDOCK_SUMMARY_START {...} BATTDOCK_SUMMARY_END -->`）；
    2. 兼容历史 Release：从要点行中自动去噪提炼前 3-5 条用户可感知变更。
    """
    text = body or ""
    # 1. 优先解析结构化摘要块
    m = re.search(
        r"<!--\s*BATTDOCK_SUMMARY_START\s*(\{.*?\})\s*BATTDOCK_SUMMARY_END\s*-->",
        text,
        flags=re.DOTALL,
    )
    if m:
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict):
                raw_items = obj.get("summary") or obj.get("items") or []
                clean_items = [_strip_markdown_and_tech_noise(str(x)) for x in raw_items]
                clean_items = [x for x in clean_items if x][:max_items]
                notice = _strip_markdown_and_tech_noise(str(obj.get("important_notice") or ""))
                if clean_items:
                    return clean_items, notice
        except Exception:
            pass

    # 2. 兼容无结构化块的历史 Release：移除代码块后提取简明条目
    stripped = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    items: list[str] = []
    seen: set[str] = set()
    for raw_line in stripped.splitlines():
        line = raw_line.strip()
        if not line.startswith(("-", "*", "•")):
            continue
        cleaned = _strip_markdown_and_tech_noise(line)
        if not cleaned or len(cleaned) < 4:
            continue
        # 若为“标题：冗长解释”格式，仅取简明核心短语
        if "：" in cleaned and len(cleaned) > 26:
            head = cleaned.split("：", 1)[0].strip()
            if 4 <= len(head) <= 26:
                cleaned = head
        if len(cleaned) > 28:
            cleaned = cleaned[:26].rstrip("，,、；; ") + "…"
        key = cleaned.lower()
        if key not in seen:
            seen.add(key)
            items.append(cleaned)
        if len(items) >= max_items:
            break

    return items, ""


def fetch_remote_summary_json(
    summary_url: str,
    timeout: float = 6.0,
    update_source: str = UPDATE_SOURCE_AUTO,
    custom_mirror: str = "",
) -> tuple[list[str], str]:
    """若 Release 随附 update-summary.json，按加速线路拉取其中的结构化用户摘要与重要提示。"""
    candidates = build_candidate_urls(summary_url, update_source=update_source, custom_mirror=custom_mirror)
    for _label, url in candidates:
        req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}-Updater/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                obj = json.loads(resp.read().decode("utf-8", errors="replace"))
            if isinstance(obj, dict):
                raw_items = obj.get("summary") or []
                clean = [_strip_markdown_and_tech_noise(str(x)) for x in raw_items if str(x).strip()][:5]
                notice = _strip_markdown_and_tech_noise(str(obj.get("important_notice") or ""))
                if clean or notice:
                    return clean, notice
        except Exception:
            continue
    return [], ""


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


def verify_downloaded_sha256(
    file_path: Path,
    asset_name: str,
    sha256_url: str,
    timeout: float = 10.0,
    update_source: str = UPDATE_SOURCE_AUTO,
    custom_mirror: str = "",
) -> Optional[bool]:
    """如存在 SHA256SUMS.txt，则核对下载文件哈希（支持国内镜像回退读取校验文件）。返回 True=通过，False=不匹配，None=未提供。"""
    candidates = build_candidate_urls(sha256_url, update_source=update_source, custom_mirror=custom_mirror)
    manifest_text = ""
    for _label, url in candidates:
        req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}-Updater/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                txt = resp.read().decode("utf-8", errors="replace")
            if parse_sha256_manifest(txt):
                manifest_text = txt
                break
        except Exception:
            continue
    if not manifest_text:
        return None
    table = parse_sha256_manifest(manifest_text)
    expected = table.get(Path(asset_name or file_path.name).name.lower())
    if not expected:
        return None
    actual = compute_file_sha256(file_path)
    return actual == expected


def parse_github_release_payload(payload: dict[str, Any], current_version: str) -> UpdateCheckResult:
    """解析 GitHub Releases API JSON 负载（自动过滤 draft 与 prerelease，提取简明用户摘要）。"""
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
    summary_url = select_summary_asset(assets)
    summary_items, important_notice = extract_user_summary(body)
    has_upd = bool(latest) and is_newer_version(latest, cur)

    return UpdateCheckResult(
        ok=True,
        current_version=cur,
        latest_version=latest or cur,
        has_update=has_upd,
        release_url=html_url,
        release_notes=body[:1500],
        summary_items=summary_items,
        important_notice=important_notice,
        asset_name=str(asset.get("name", "")) if asset else "",
        asset_url=str(asset.get("browser_download_url", "")) if asset else "",
        asset_size=int(asset.get("size", 0) or 0) if asset else 0,
        sha256_url=sha256_url,
        summary_url=summary_url,
        published_at=published_at,
        error="",
    )


def _check_via_mirror_summary(
    cur: str,
    timeout: float,
    update_source: str,
    custom_mirror: str,
) -> Optional[UpdateCheckResult]:
    """纯国内加速通道检查更新：通过 releases/latest/download/update-summary.json 获取最新版本，免直连 api.github.com。"""
    latest_summary_url = f"{LATEST_DOWNLOAD_BASE}/update-summary.json"
    candidates = build_candidate_urls(
        latest_summary_url,
        update_source=update_source,
        custom_mirror=custom_mirror,
    )
    for _label, url in candidates:
        req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{cur or '2.6'}"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                obj = json.loads(resp.read().decode("utf-8", errors="replace"))
            if not isinstance(obj, dict):
                continue
            latest = normalize_version_str(str(obj.get("version") or ""))
            if not latest:
                continue
            raw_items = obj.get("summary") or []
            clean_items = [_strip_markdown_and_tech_noise(str(x)) for x in raw_items if str(x).strip()][:5]
            notice = _strip_markdown_and_tech_noise(str(obj.get("important_notice") or ""))
            asset_name = str(obj.get("asset_name") or f"{APP_NAME}-v{latest}-Windows-x64-Portable.zip").strip()
            asset_size = int(obj.get("asset_size") or 0)
            tag_base = f"{GITHUB_REPO_URL}/releases/download/v{latest}"
            return UpdateCheckResult(
                ok=True,
                current_version=cur,
                latest_version=latest,
                has_update=is_newer_version(latest, cur),
                release_url=f"{GITHUB_REPO_URL}/releases/tag/v{latest}",
                release_notes="\n".join(f"• {x}" for x in clean_items),
                summary_items=clean_items,
                important_notice=notice,
                asset_name=asset_name,
                asset_url=f"{tag_base}/{asset_name}",
                asset_size=asset_size,
                sha256_url=f"{tag_base}/SHA256SUMS.txt",
                summary_url=f"{tag_base}/update-summary.json",
                published_at=str(obj.get("published_at") or ""),
                error="",
            )
        except Exception:
            continue
    return None


def check_for_update(
    current_version: str,
    timeout: float = 10.0,
    update_source: str = UPDATE_SOURCE_AUTO,
    custom_mirror: str = "",
) -> UpdateCheckResult:
    """请求最新稳定版本信息：支持国内加速通道免直连检查与 GitHub API 双向容错。"""
    cur = normalize_version_str(current_version)
    src = (update_source or UPDATE_SOURCE_AUTO).strip().lower()

    if src in (UPDATE_SOURCE_CN, UPDATE_SOURCE_CUSTOM):
        mir_res = _check_via_mirror_summary(cur, min(timeout, 8.0), src, custom_mirror)
        if mir_res is not None:
            return mir_res
        if src == UPDATE_SOURCE_CN:
            return UpdateCheckResult(ok=False, current_version=cur, error="无法连接国内更新镜像，请稍后重试或切换下载线路。")

    req = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={
            "User-Agent": f"{APP_NAME}/{cur or '2.6'}",
            "Accept": "application/vnd.github+json",
        },
    )
    api_err: Optional[str] = None
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
            if not isinstance(data, dict):
                api_err = "更新接口返回数据格式异常。"
            else:
                res = parse_github_release_payload(data, cur)
                if res.ok and res.summary_url and (not res.summary_items or not res.important_notice):
                    ext_items, ext_notice = fetch_remote_summary_json(
                        res.summary_url,
                        timeout=6.0,
                        update_source=src,
                        custom_mirror=custom_mirror,
                    )
                    if ext_items:
                        res.summary_items = ext_items
                    if ext_notice and not res.important_notice:
                        res.important_notice = ext_notice
                return res
    except urllib.error.HTTPError as e:
        if e.code == 404:
            api_err = "GitHub 仓库尚未发布正式版本。"
        elif e.code == 403:
            api_err = "GitHub 接口请求频率受限，请稍后再试。"
        else:
            api_err = f"检查更新失败（HTTP {e.code}）。"
    except (urllib.error.URLError, TimeoutError, OSError):
        api_err = "无法连接 GitHub，请检查网络连接或代理设置。"
    except Exception as e:
        api_err = f"检查更新出错：{e}"

    if src == UPDATE_SOURCE_AUTO:
        mir_res = _check_via_mirror_summary(cur, min(timeout, 8.0), UPDATE_SOURCE_CN, custom_mirror)
        if mir_res is not None:
            return mir_res

    return UpdateCheckResult(ok=False, current_version=cur, error=api_err or "检查更新失败。")


def _download_single_url(
    url: str,
    part_path: Path,
    expected_size: int,
    on_progress: Optional[Callable[[int, int], None]],
    cancel_event: Optional[threading.Event],
    timeout: float,
) -> int:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"{APP_NAME}-Updater/1.0"},
    )
    downloaded = 0
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
    return downloaded


def download_update_asset(
    asset_url: str,
    dest_zip: Path,
    expected_size: int = 0,
    on_progress: Optional[Callable[[int, int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    timeout: float = 25.0,
    update_source: str = UPDATE_SOURCE_AUTO,
    custom_mirror: str = "",
    on_source_change: Optional[Callable[[str], None]] = None,
    probe_mirrors: bool = True,
) -> Path:
    """仅通过 HTTPS 流式下载 Release ZIP 压缩包，支持国内加速节点并发测速择优与失败自动切换。"""
    if not asset_url.startswith("https://"):
        raise ValueError("出于安全限制，仅允许通过 HTTPS 下载更新包")

    candidates = build_candidate_urls(asset_url, update_source=update_source, custom_mirror=custom_mirror)
    if not candidates:
        raise ValueError("未找到可用的 HTTPS 下载地址")
    if probe_mirrors and len(candidates) > 1:
        candidates = rank_candidate_urls(candidates, probe_timeout=3.5)

    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    part_path = dest_zip.with_suffix(".zip.part")
    last_error: Optional[Exception] = None

    for label, url in candidates:
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("更新下载已取消")
        if on_source_change:
            on_source_change(label)
        try:
            _download_single_url(
                url=url,
                part_path=part_path,
                expected_size=expected_size,
                on_progress=on_progress,
                cancel_event=cancel_event,
                timeout=timeout,
            )
            if dest_zip.exists():
                dest_zip.unlink()
            part_path.replace(dest_zip)
            return dest_zip
        except Exception as exc:
            try:
                if part_path.exists():
                    part_path.unlink()
            except OSError:
                pass
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("更新下载已取消") from exc
            last_error = exc
            continue

    raise RuntimeError(f"所有更新下载节点均不可用：{last_error}") from last_error


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


def build_windows_updater_script(
    staged_dir: Path,
    target_dir: Path,
    pid: int,
    exe_name: str = APP_EXE_NAME,
    work_root: Optional[Path] = None,
    relaunch_args: str = "",
) -> str:
    """生成同盘回滚、安全替换并自动重启新版 BattDock.exe 的 PowerShell 更新脚本。"""
    cleanup_root = work_root or staged_dir.parent

    def _ps_quote(p: Path) -> str:
        return "'" + str(p.resolve()).replace("'", "''") + "'"

    arg_line = (
        f"$newProc = Start-Process -FilePath $NewExe -ArgumentList '{relaunch_args}' -WorkingDirectory $TargetDir -PassThru"
        if relaunch_args
        else "$newProc = Start-Process -FilePath $NewExe -WorkingDirectory $TargetDir -PassThru"
    )

    return f"""$ErrorActionPreference = 'Stop'
$TargetPid = {int(pid)}
$StagedDir = {_ps_quote(staged_dir)}
$TargetDir = {_ps_quote(target_dir)}
$CleanupDir = {_ps_quote(cleanup_root)}
$ExeName = '{exe_name}'
$LegacyExeName = '{LEGACY_EXE_NAME}'
$LogFile = Join-Path $env:TEMP 'battdock_updater.log'
# 关键修复：回滚目录必须与 TargetDir 位于同一磁盘卷，彻底避免跨盘 Move-Item 抛出根路径不一致异常
$RollbackDir = Join-Path $TargetDir ('._battdock_rollback_' + $TargetPid)

function Write-Log([string]$msg) {{
    try {{
        Add-Content -Path $LogFile -Value ("[" + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + "] " + $msg) -Encoding UTF8
    }} catch {{}}
}}

Write-Log "开始应用 BattDock 更新：$StagedDir -> $TargetDir (等待 PID=$TargetPid 退出)"

# 1. 等待旧进程安全退出（最多 10 秒，超时则温和强制结束）
for ($i = 0; $i -lt 40; $i++) {{
    $proc = Get-Process -Id $TargetPid -ErrorAction SilentlyContinue
    if (-not $proc) {{ break }}
    Start-Sleep -Milliseconds 250
}}
$proc = Get-Process -Id $TargetPid -ErrorAction SilentlyContinue
if ($proc) {{
    try {{ Stop-Process -Id $TargetPid -Force -ErrorAction SilentlyContinue }} catch {{}}
    Start-Sleep -Milliseconds 500
}}
# 额外等待 WebView2 / CLR 文件句柄完全释放
Start-Sleep -Milliseconds 400

# 2. 在同盘建立回滚目录（仅移出本软件自身主程序与 _internal，绝不触碰用户目录中的其他无关文件）
if (Test-Path $RollbackDir) {{ Remove-Item -Path $RollbackDir -Recurse -Force -ErrorAction SilentlyContinue }}
New-Item -ItemType Directory -Path $RollbackDir -Force | Out-Null

$CurExe = Join-Path $TargetDir $ExeName
$CurInternal = Join-Path $TargetDir '_internal'
$BackedUp = $false

for ($try = 0; $try -lt 15; $try++) {{
    try {{
        if ((Test-Path $CurInternal) -and (-not (Test-Path (Join-Path $RollbackDir '_internal')))) {{
            Move-Item -Path $CurInternal -Destination (Join-Path $RollbackDir '_internal') -Force
        }}
        if ((Test-Path $CurExe) -and (-not (Test-Path (Join-Path $RollbackDir $ExeName)))) {{
            Move-Item -Path $CurExe -Destination (Join-Path $RollbackDir $ExeName) -Force
        }}
        $BackedUp = $true
        Write-Log "旧版文件已同盘移入回滚区（第 $($try + 1) 次尝试）"
        break
    }} catch {{
        Write-Log "等待文件锁释放（第 $($try + 1) 次）：$($_.Exception.Message)"
        Start-Sleep -Milliseconds 400
    }}
}}

# 3. 逐项复制新版程序文件（仅替换更新包包含的文件，失败自动完整回滚）
$Applied = $false
if ($BackedUp) {{
    for ($try = 0; $try -lt 10; $try++) {{
        try {{
            Get-ChildItem -Path $StagedDir -Force | ForEach-Object {{
                Copy-Item -Path $_.FullName -Destination $TargetDir -Recurse -Force
            }}
            if (Test-Path (Join-Path $TargetDir $ExeName)) {{
                $Applied = $true
                Write-Log "新版本文件替换成功（第 $($try + 1) 次尝试）"
                break
            }}
        }} catch {{
            Write-Log "复制新版文件重试（第 $($try + 1) 次）：$($_.Exception.Message)"
            Start-Sleep -Milliseconds 400
        }}
    }}
}}

if (-not $Applied) {{
    Write-Log "更新失败，正在自动回滚至原可用版本..."
    try {{
        $PartialInternal = Join-Path $TargetDir '_internal'
        if (Test-Path $PartialInternal) {{ Remove-Item -Path $PartialInternal -Recurse -Force -ErrorAction SilentlyContinue }}
        if (Test-Path (Join-Path $RollbackDir '_internal')) {{ Move-Item -Path (Join-Path $RollbackDir '_internal') -Destination $CurInternal -Force }}
        if (Test-Path (Join-Path $RollbackDir $ExeName)) {{ Move-Item -Path (Join-Path $RollbackDir $ExeName) -Destination $CurExe -Force }}
        Write-Log "已恢复旧版本"
    }} catch {{
        Write-Log "回滚时发生异常：$($_.Exception.Message)"
    }}
}} else {{
    # 清理旧版残留主程序与重复开机自启项
    $LegacyExe = Join-Path $TargetDir $LegacyExeName
    if (Test-Path $LegacyExe) {{ Remove-Item -Path $LegacyExe -Force -ErrorAction SilentlyContinue }}
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

# 4. 自动启动新版 BattDock.exe 并确认进程运行
$NewExe = Join-Path $TargetDir $ExeName
if (Test-Path $NewExe) {{
    Write-Log "正在启动新版本：$NewExe"
    {arg_line}
    Start-Sleep -Milliseconds 500
    if ($newProc -and (-not $newProc.HasExited)) {{
        Write-Log "新版本已正常运行 (PID=$($newProc.Id))"
    }}
}}

# 5. 清理本次更新产生的回滚缓存、下载临时目录与辅助脚本
try {{ if (Test-Path $RollbackDir) {{ Remove-Item -Path $RollbackDir -Recurse -Force -ErrorAction SilentlyContinue }} }} catch {{}}
try {{ if (Test-Path $CleanupDir) {{ Remove-Item -Path $CleanupDir -Recurse -Force -ErrorAction SilentlyContinue }} }} catch {{}}
try {{ Remove-Item -Path $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue }} catch {{}}
"""


def launch_windows_updater(
    staged_dir: Path,
    target_dir: Path,
    pid: int,
    exe_name: str = APP_EXE_NAME,
    work_root: Optional[Path] = None,
    relaunch_args: str = "",
) -> Path:
    """生成并启动隐藏 PowerShell 覆盖更新脚本（UTF-8 BOM，同盘回滚，兼容中文路径与任意盘符）。"""
    if sys.platform != "win32":
        raise RuntimeError("仅支持 Windows 平台执行原地自动更新")

    script_path = Path(tempfile.gettempdir()) / f"battdock_apply_update_{os.getpid()}.ps1"
    ps_script = build_windows_updater_script(
        staged_dir=staged_dir,
        target_dir=target_dir,
        pid=pid,
        exe_name=exe_name,
        work_root=work_root,
        relaunch_args=relaunch_args,
    )
    script_path.write_text(ps_script, encoding="utf-8-sig")

    # 注意：Windows 下 CREATE_NO_WINDOW 与 DETACHED_PROCESS 互斥，同时传入会导致 powershell.exe 启动即退出！
    # 使用 CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP + DEVNULL 可稳定隐藏运行并在父进程退出后存活。
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
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
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )
    return script_path
