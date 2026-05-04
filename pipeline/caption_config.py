"""
CaptionConfig — 字幕渲染参数集中管理

提供 YAML 文件读写，减少 CLI 参数数量。
GUI 写入 config/caption.yaml，main.py 通过 --caption-config 加载。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class CaptionConfig:
    """字幕渲染全部参数，支持 YAML 序列化。"""

    font: str = ""
    """字体路径或系统字体名（空 = 默认 Minecraft 字体）"""

    font_size: int = 0
    """字号 px（0 = 自动根据视频宽度计算）"""

    font_color: str = "white"
    """字体颜色（CSS 颜色名或 #rrggbb）"""

    stroke_width: float = 0.0
    """描边宽度（0 = 使用默认值）"""

    stroke_color: str = "black"
    """描边颜色"""

    bg_color: str = "rgba(0,0,0,128)"
    """背景色 RGBA 字符串"""

    alignment: str = "center"
    """对齐方式: center | left | right"""

    position: str = "bottom"
    """字幕位置: bottom | top"""

    max_lines: int = 2
    """字幕最大行数，超出时缩小字号或触发拆分"""

    max_font_size: int = 0
    """最大字号 px（0 = 自动根据视频高度计算）"""

    font_size_factor: float = 0.030
    """自动字号系数（相对于视频宽度）"""

    width_ratio: float = 0.85
    """字幕文本框宽度占视频宽度的比例"""

    enable_subtitle_optimization: bool = True
    """是否启用字幕拆分优化"""

    def __post_init__(self) -> None:
        if self.alignment not in ("center", "left", "right"):
            raise ValueError(f"alignment 仅支持 center/left/right，当前: {self.alignment}")
        if self.position not in ("bottom", "top"):
            raise ValueError(f"position 仅支持 bottom/top，当前: {self.position}")
        if not 1 <= self.max_lines <= 10:
            raise ValueError(f"max_lines 应在 [1, 10] 范围内，当前: {self.max_lines}")
        if self.max_font_size < 0:
            raise ValueError(f"max_font_size 不能为负数，当前: {self.max_font_size}")
        if not 0.01 <= self.font_size_factor <= 0.10:
            raise ValueError(f"font_size_factor 应在 [0.01, 0.10] 范围内，当前: {self.font_size_factor}")
        if not 0.50 <= self.width_ratio <= 1.0:
            raise ValueError(f"width_ratio 应在 [0.50, 1.0] 范围内，当前: {self.width_ratio}")

    # ── YAML I/O ────────────────────────────────────────────

    @classmethod
    def from_yaml(cls, path: str) -> "CaptionConfig":
        import yaml

        if not os.path.exists(path):
            raise FileNotFoundError(f"配置文件不存在: {path}")

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        caption_data = data.get("caption", data)
        return cls(**caption_data)

    def to_yaml(self, path: str) -> None:
        import yaml

        data = {"caption": asdict(self)}
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

    # ── TTSConfig 覆盖 ──────────────────────────────────────

    def to_tts_overrides(self) -> dict:
        """返回 TTSConfig 兼容的 caption_* 参数字典。

        仅包含非默认值字段，用于 TTSConfig.apply_caption_overrides()。
        """
        overrides: dict = {}
        if self.font:
            overrides["caption_font"] = self.font
        if self.font_size > 0:
            overrides["caption_font_size"] = self.font_size
        if self.font_color and self.font_color != "white":
            overrides["caption_font_color"] = self.font_color
        if self.stroke_width > 0:
            overrides["caption_stroke_width"] = self.stroke_width
        if self.stroke_color and self.stroke_color != "black":
            overrides["caption_stroke_color"] = self.stroke_color
        if self.bg_color and self.bg_color != "rgba(0,0,0,128)":
            overrides["caption_bg_color"] = self.bg_color
        if self.alignment and self.alignment != "center":
            overrides["caption_alignment"] = self.alignment
        if self.position and self.position != "bottom":
            overrides["caption_position"] = self.position
        if self.max_lines != 2:
            overrides["caption_max_lines"] = self.max_lines
        if self.max_font_size > 0:
            overrides["caption_max_font_size"] = self.max_font_size
        if abs(self.font_size_factor - 0.030) > 1e-6:
            overrides["caption_font_size_factor"] = self.font_size_factor
        if abs(self.width_ratio - 0.85) > 1e-6:
            overrides["caption_width_ratio"] = self.width_ratio
        overrides["enable_subtitle_optimization"] = self.enable_subtitle_optimization
        return overrides


def create_default_caption_config(path: str = "config/caption.yaml") -> CaptionConfig:
    """创建默认字幕配置并写入 YAML 文件。"""
    cfg = CaptionConfig()
    cfg.to_yaml(path)
    return cfg
