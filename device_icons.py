"""BattDock 全局统一黑白实心设备类型图标资源库（单一真值来源）。

设计规范：
- 严格遵循项目参考图（极简白色电脑图标组）绘制为 24x24 纯黑白单色实心剪影 SVG：
  1. mouse：对称卵形实心剪影，含横向按键分界线、上部中缝、镂空槽与实心竖向胶囊滚轮；
  2. headset：厚实马蹄形头梁无缝融合左右微内倾实心圆角耳罩（earbuds 复用同款标准耳机图标）；
  3. keyboard：横向大圆角实心剪影，内部整齐镂空 3 行按键（顶行 5 键、中行 5 交错宽键、底行 3 键含长空格键）；
  4. other：匹配同套实心剪影风格的通用紧凑无线外设造型。
- 前端（主窗口、设备管理、支持设备清单）与原生 WinForms（悬浮窗、低电量提醒弹窗）均从本模块
  获取完全一致的几何造型；浅色主题渲染纯黑，深色主题渲染纯白，透明背景，零渐变/阴影/彩色。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw

from providers.base import KIND_EARBUDS, KIND_HEADSET, KIND_KEYBOARD, KIND_MOUSE, KIND_OTHER

# 统一设备类型归一化：每种设备仅保留一种标准图标（耳塞统一归类为标准耳机图标）
def canonical_device_icon_kind(kind: str) -> str:
    k = (kind or "").strip().lower()
    if k == KIND_MOUSE:
        return KIND_MOUSE
    if k in (KIND_HEADSET, KIND_EARBUDS, "headphones"):
        return KIND_HEADSET
    if k == KIND_KEYBOARD:
        return KIND_KEYBOARD
    return KIND_OTHER


# 24x24 统一纯实心剪影 SVG 路径（使用 currentColor，浅色黑、深色白，无 mask id 冲突）
SVG_ICONS: dict[str, str] = {
    # 实心鼠标：左按键 + 右按键（围绕滚轮切槽）+ 实心滚轮胶囊 + 卵形下掌托
    KIND_MOUSE: (
        '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">'
        '<path d="M11.35 2.05V4.25C10.5 4.45 9.95 5.18 9.95 6.08V7.92C9.95 8.82 10.5 9.55 11.35 9.75V10.15H6V8C6 4.78 8.35 2.26 11.35 2.05Z"/>'
        '<path d="M12.65 2.05C15.65 2.26 18 4.78 18 8V10.15H12.65V9.75C13.5 9.55 14.05 8.82 14.05 7.92V6.08C14.05 5.18 13.5 4.45 12.65 4.25V2.05Z"/>'
        '<rect x="11.0" y="5.1" width="2.0" height="3.8" rx="1.0"/>'
        '<path d="M6 11.45H18V15.35C18 19.12 15.38 22 12 22C8.62 22 6 19.12 6 15.35V11.45Z"/>'
        '</svg>'
    ),
    # 实心头戴式耳机：宽润 1:1 比例马蹄形头梁无缝融合左右约 9° 微内收厚实圆角耳罩
    KIND_HEADSET: (
        '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">'
        '<path d="M3.2 13.6C3.0 6.9 6.6 2.5 12 2.5C17.4 2.5 21.0 6.9 20.8 13.6H17.6C17.7 8.7 15.5 5.4 12 5.4C8.5 5.4 6.3 8.7 6.4 13.6H3.2Z"/>'
        '<rect x="2.2" y="12.1" width="5.3" height="9.0" rx="2.35" transform="rotate(-9 4.85 16.6)"/>'
        '<rect x="16.5" y="12.1" width="5.3" height="9.0" rx="2.35" transform="rotate(9 19.15 16.6)"/>'
        '</svg>'
    ),
    # 实心紧凑键盘：外框大圆角 + 3 行整齐镂空按键（evenodd，顶5/中5交错宽键/底3含长空格）
    KIND_KEYBOARD: (
        '<svg viewBox="0 0 24 24" fill="currentColor" fill-rule="evenodd" clip-rule="evenodd" aria-hidden="true">'
        '<path d="'
        'M4.0 5.0H20.0C21.38 5.0 22.5 6.12 22.5 7.5V16.5C22.5 17.88 21.38 19.0 20.0 19.0H4.0C2.62 19.0 1.5 17.88 1.5 16.5V7.5C1.5 6.12 2.62 5.0 4.0 5.0Z'
        ' M3.9 7.0H5.7C5.92 7.0 6.1 7.18 6.1 7.4V9.0C6.1 9.22 5.92 9.4 5.7 9.4H3.9C3.68 9.4 3.5 9.22 3.5 9.0V7.4C3.5 7.18 3.68 7.0 3.9 7.0Z'
        ' M7.5 7.0H9.3C9.52 7.0 9.7 7.18 9.7 7.4V9.0C9.7 9.22 9.52 9.4 9.3 9.4H7.5C7.28 9.4 7.1 9.22 7.1 9.0V7.4C7.1 7.18 7.28 7.0 7.5 7.0Z'
        ' M11.1 7.0H12.9C13.12 7.0 13.3 7.18 13.3 7.4V9.0C13.3 9.22 13.12 9.4 12.9 9.4H11.1C10.88 9.4 10.7 9.22 10.7 9.0V7.4C10.7 7.18 10.88 7.0 11.1 7.0Z'
        ' M14.7 7.0H16.5C16.72 7.0 16.9 7.18 16.9 7.4V9.0C16.9 9.22 16.72 9.4 16.5 9.4H14.7C14.48 9.4 14.3 9.22 14.3 9.0V7.4C14.3 7.18 14.48 7.0 14.7 7.0Z'
        ' M18.3 7.0H20.1C20.32 7.0 20.5 7.18 20.5 7.4V9.0C20.5 9.22 20.32 9.4 20.1 9.4H18.3C18.08 9.4 17.9 9.22 17.9 9.0V7.4C17.9 7.18 18.08 7.0 18.3 7.0Z'
        ' M3.9 10.8H6.45C6.67 10.8 6.85 10.98 6.85 11.2V12.8C6.85 13.02 6.67 13.2 6.45 13.2H3.9C3.68 13.2 3.5 13.02 3.5 12.8V11.2C3.5 10.98 3.68 10.8 3.9 10.8Z'
        ' M8.18 10.8H9.58C9.8 10.8 9.98 10.98 9.98 11.2V12.8C9.98 13.02 9.8 13.2 9.58 13.2H8.18C7.96 13.2 7.78 13.02 7.78 12.8V11.2C7.78 10.98 7.96 10.8 8.18 10.8Z'
        ' M11.3 10.8H12.7C12.92 10.8 13.1 10.98 13.1 11.2V12.8C13.1 13.02 12.92 13.2 12.7 13.2H11.3C11.08 13.2 10.9 13.02 10.9 12.8V11.2C10.9 10.98 11.08 10.8 11.3 10.8Z'
        ' M14.42 10.8H15.82C16.04 10.8 16.22 10.98 16.22 11.2V12.8C16.22 13.02 16.04 13.2 15.82 13.2H14.42C14.2 13.2 14.02 13.02 14.02 12.8V11.2C14.02 10.98 14.2 10.8 14.42 10.8Z'
        ' M17.55 10.8H20.1C20.32 10.8 20.5 10.98 20.5 11.2V12.8C20.5 13.02 20.32 13.2 20.1 13.2H17.55C17.33 13.2 17.15 13.02 17.15 12.8V11.2C17.15 10.98 17.33 10.8 17.55 10.8Z'
        ' M3.9 14.6H5.7C5.92 14.6 6.1 14.78 6.1 15.0V16.6C6.1 16.82 5.92 17.0 5.7 17.0H3.9C3.68 17.0 3.5 16.82 3.5 16.6V15.0C3.5 14.78 3.68 14.6 3.9 14.6Z'
        ' M7.5 14.6H16.5C16.72 14.6 16.9 14.78 16.9 15.0V16.6C16.9 16.82 16.72 17.0 16.5 17.0H7.5C7.28 17.0 7.1 16.82 7.1 16.6V15.0C7.1 14.78 7.28 14.6 7.5 14.6Z'
        ' M18.3 14.6H20.1C20.32 14.6 20.5 14.78 20.5 15.0V16.6C20.5 16.82 20.32 17.0 20.1 17.0H18.3C18.08 17.0 17.9 16.82 17.9 16.6V15.0C17.9 14.78 18.08 14.6 18.3 14.6Z'
        '"/>'
        '</svg>'
    ),
    # 通用其他无线外设（同套实心剪影风格：简洁圆角机身 + 顶部无线指示小孔）
    KIND_OTHER: (
        '<svg viewBox="0 0 24 24" fill="currentColor" fill-rule="evenodd" clip-rule="evenodd" aria-hidden="true">'
        '<path d="M5.5 6.5H18.5C19.88 6.5 21 7.62 21 9V15C21 16.38 19.88 17.5 18.5 17.5H5.5C4.12 17.5 3 16.38 3 15V9C3 7.62 4.12 6.5 5.5 6.5Z'
        ' M7.5 10.6C6.73 10.6 6.1 11.23 6.1 12C6.1 12.77 6.73 13.4 7.5 13.4C8.27 13.4 8.9 12.77 8.9 12C8.9 11.23 8.27 10.6 7.5 10.6Z'
        ' M11.4 11.0H17.2C17.64 11.0 18.0 11.36 18.0 11.8V12.2C18.0 12.64 17.64 13.0 17.2 13.0H11.4C10.96 13.0 10.6 12.64 10.6 12.2V11.8C10.6 11.36 10.96 11.0 11.4 11.0Z"/>'
        '</svg>'
    ),
}


def get_device_svg(kind: str, size: Optional[int] = None) -> str:
    """返回统一黑白实心设备 SVG（earbuds 自动复用 headset 标准图标）。"""
    canon = canonical_device_icon_kind(kind)
    svg = SVG_ICONS[canon]
    if size is not None:
        svg = svg.replace("<svg ", f'<svg width="{int(size)}" height="{int(size)}" ', 1)
    return svg


def get_device_icons_svg_map(size: int = 20) -> dict[str, str]:
    """返回供前端主窗口/设置窗口统一调用的设备图标字典。"""
    return {
        KIND_MOUSE: get_device_svg(KIND_MOUSE, size),
        KIND_HEADSET: get_device_svg(KIND_HEADSET, size),
        KIND_EARBUDS: get_device_svg(KIND_HEADSET, size),
        KIND_KEYBOARD: get_device_svg(KIND_KEYBOARD, size),
        KIND_OTHER: get_device_svg(KIND_OTHER, size),
    }


def export_svg_assets(out_dir: Path) -> list[Path]:
    """将统一 SVG 矢量图标导出到 assets/icons/，便于打包与文档引用。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, body in SVG_ICONS.items():
        full = body.replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1)
        p = out_dir / f"{name}.svg"
        p.write_text(full + "\n", encoding="utf-8")
        written.append(p)
    return written


def _rotated_rounded_rect_mask(
    canvas_size: int,
    x: float,
    y: float,
    w: float,
    h: float,
    r: float,
    angle_deg: float,
    scale: float,
) -> Image.Image:
    """绘制旋转圆角实心胶囊到高分辨率单通道 alpha 蒙版。"""
    cx = (x + w / 2.0) * scale
    cy = (y + h / 2.0) * scale
    pw = int(round(w * scale))
    ph = int(round(h * scale))
    pr = int(round(r * scale))
    pad = max(pw, ph)
    tmp = Image.new("L", (pw + pad * 2, ph + pad * 2), 0)
    td = ImageDraw.Draw(tmp)
    td.rounded_rectangle([pad, pad, pad + pw, pad + ph], radius=pr, fill=255)
    # PIL rotate 正角度为逆时针，SVG rotate 正角度为顺时针，取负号保持 100% 一致
    rot = tmp.rotate(-angle_deg, resample=Image.Resampling.BICUBIC, expand=False)
    out = Image.new("L", (canvas_size, canvas_size), 0)
    ox = int(round(cx - rot.width / 2.0))
    oy = int(round(cy - rot.height / 2.0))
    out.paste(rot, (ox, oy))
    return out


def render_device_icon_pil(
    kind: str,
    size: int = 24,
    is_dark: bool = False,
    color: Optional[tuple[int, int, int, int]] = None,
) -> Image.Image:
    """以 8x 超采样渲染与 SVG 完全同源的黑白实心设备图标（供悬浮窗、低电量弹窗等原生控件使用）。"""
    canon = canonical_device_icon_kind(kind)
    rgba = color or ((248, 250, 252, 255) if is_dark else (17, 24, 39, 255))

    # 统一在 24x24 逻辑坐标系上以 8 倍超采样绘制到单通道 alpha 蒙版，再着色并 LANCZOS 下采样
    ss = max(192, size * 8)
    s = ss / 24.0
    mask = Image.new("L", (ss, ss), 0)
    md = ImageDraw.Draw(mask)

    def _xy(px: float, py: float) -> tuple[float, float]:
        return (px * s, py * s)

    def _box(x0: float, y0: float, x1: float, y1: float) -> list[float]:
        return [x0 * s, y0 * s, x1 * s, y1 * s]

    if canon == KIND_MOUSE:
        # 1. 外轮廓：上圆半径 6，中段微直，下端饱满卵形底
        md.ellipse(_box(6.0, 2.0, 18.0, 14.0), fill=255)
        md.rectangle(_box(6.0, 8.0, 18.0, 15.2), fill=255)
        md.ellipse(_box(6.0, 8.4, 18.0, 22.0), fill=255)
        # 2. 切出横向分界线（y=10.15..11.45）
        md.rectangle(_box(5.0, 10.15, 19.0, 11.45), fill=0)
        # 3. 切出上部纵向中缝（x=11.35..12.65, y=1.5..10.2）
        md.rectangle(_box(11.35, 1.5, 12.65, 10.2), fill=0)
        # 4. 切出滚轮胶囊镂空槽（x=9.95..14.05, y=4.2..9.8）
        md.rounded_rectangle(_box(9.95, 4.2, 14.05, 9.8), radius=2.05 * s, fill=0)
        # 5. 回填中央实心滚轮胶囊（x=11.0..13.0, y=5.1..8.9）
        md.rounded_rectangle(_box(11.0, 5.1, 13.0, 8.9), radius=1.0 * s, fill=255)

    elif canon == KIND_HEADSET:
        # 1. 宽润 1:1 马蹄形头梁（外椭圆减去内椭圆，保留上半部至耳罩顶部无缝衔接）
        outer = Image.new("L", (ss, ss), 0)
        od = ImageDraw.Draw(outer)
        od.ellipse(_box(3.1, 2.5, 20.9, 22.3), fill=255)
        od.ellipse(_box(6.35, 5.4, 17.65, 19.5), fill=0)
        od.rectangle(_box(0.0, 13.6, 24.0, 24.0), fill=0)
        mask.paste(255, (0, 0), outer)
        # 2. 左右微内收纯实心厚圆角耳罩（左 -9°，右 +9°）
        left_cup = _rotated_rounded_rect_mask(ss, 2.2, 12.1, 5.3, 9.0, 2.35, -9.0, s)
        right_cup = _rotated_rounded_rect_mask(ss, 16.5, 12.1, 5.3, 9.0, 2.35, 9.0, s)
        mask.paste(255, (0, 0), left_cup)
        mask.paste(255, (0, 0), right_cup)

    elif canon == KIND_KEYBOARD:
        # 1. 外框大圆角实心矩形
        md.rounded_rectangle(_box(1.5, 5.0, 22.5, 19.0), radius=2.5 * s, fill=255)
        kr = 0.42 * s
        # 2. 顶行 5 个等宽正方形键
        for x0 in (3.5, 7.1, 10.7, 14.3, 17.9):
            md.rounded_rectangle(_box(x0, 7.0, x0 + 2.6, 9.4), radius=kr, fill=0)
        # 3. 中行 5 个交错变宽键（左宽 + 中三 + 右宽）
        for x0, x1 in ((3.5, 6.85), (7.78, 9.98), (10.9, 13.1), (14.02, 16.22), (17.15, 20.5)):
            md.rounded_rectangle(_box(x0, 10.8, x1, 13.2), radius=kr, fill=0)
        # 4. 底行 3 键（左键 + 长空格 + 右键）
        for x0, x1 in ((3.5, 6.1), (7.1, 16.9), (17.9, 20.5)):
            md.rounded_rectangle(_box(x0, 14.6, x1, 17.0), radius=kr, fill=0)

    else:
        md.rounded_rectangle(_box(3.0, 6.5, 21.0, 17.5), radius=2.5 * s, fill=255)
        md.ellipse(_box(6.1, 10.6, 8.9, 13.4), fill=0)
        md.rounded_rectangle(_box(10.6, 11.0, 18.0, 13.0), radius=0.9 * s, fill=0)

    out_mask = mask.resize((size, size), Image.Resampling.LANCZOS)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    solid = Image.new("RGBA", (size, size), rgba)
    img.paste(solid, (0, 0), out_mask)
    return img
