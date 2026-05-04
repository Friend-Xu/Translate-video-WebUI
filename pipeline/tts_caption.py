"""
字幕渲染器 — CaptionRenderer

从原 `SrtTxtToAudio.set_caption()`、`split_text_to_lines()`、`reserve_2_num()` 提取。
行为与原版完全一致。
"""

from __future__ import annotations

import os
import re
from typing import Optional, Union


def _parse_rgba(rgba_str: str) -> tuple[int, int, int, int]:
    """Parse 'rgba(R,G,B,A)' or 'R,G,B,A' to (R, G, B, A) tuple."""
    m = re.match(r'rgba?\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)', rgba_str)
    if m:
        return (int(m[1]), int(m[2]), int(m[3]), int(m[4]))
    parts = [p.strip() for p in rgba_str.replace('(', '').replace(')', '').split(',')]
    if len(parts) >= 4:
        return (int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))
    return (0, 0, 0, 128)


class CaptionRenderer:
    """字幕渲染器：在视频上叠加中英双层字幕。

    从原 `SrtTxtToAudio` 的 set_caption/split_text_to_lines/reserve_2_num 原样提取。

    用法:
        renderer = CaptionRenderer(
            font_path="./models/font/Minecraft_font/5_Minecraft_AE_zh_en.ttf",
        )
        composite_clip = renderer.render(video, duration, "中文", "English")
    """

    def __init__(
        self,
        font_path: str = "./models/font/Minecraft_font/5_Minecraft_AE_zh_en.ttf",
        font_size: Optional[int] = None,
        font_color: str = "white",
        stroke_color: str = "black",
        stroke_width: float = 0.5,
        bg_color: tuple = (0, 0, 0, 128),
        font_size_factor: float = 0.030,
        bottom_margin_ratio: float = 0.03,
        caption_width_ratio: float = 0.85,
        max_lines: int = 2,
        max_font_size: Optional[int] = None,
        max_font_size_ratio: float = 0.045,
        min_font_size: int = 12,
        alignment: str = "center",
        position: str = "bottom",
    ):
        """
        Args:
            font_path: 字体文件路径
            font_size: 字体大小。为 None 时根据视频宽度自动计算
            font_color: 字体颜色
            stroke_color: 描边颜色
            stroke_width: 描边宽度
            bg_color: 半透明背景色 (R, G, B, Alpha)
            font_size_factor: 自动计算字号时的缩放系数（默认 3%）
            bottom_margin_ratio: 字幕底部边距占视频高度的比例（默认 3%）
            caption_width_ratio: 字幕文本框宽度占视频宽度的比例（默认 85%）
            max_lines: 字幕最大行数。超出时先缩小字号，仍超出返回 min 字号由上层决策
            max_font_size: 最大字号。None 时自动 = 视频高度 * max_font_size_ratio
            max_font_size_ratio: max_font_size 为 None 时的自动计算比例（默认 4.5%）
            min_font_size: 最小字号。缩到此值仍超行数时不截断，保留原文由 SubtitleOptimizer 拆分
            alignment: 对齐方式 center | left | right
            position: 位置 bottom | top
        """
        self.font_path = font_path
        self.font_size = font_size
        self.font_color = font_color
        self.stroke_color = stroke_color
        self.stroke_width = stroke_width
        self.bg_color = _parse_rgba(bg_color) if isinstance(bg_color, str) else bg_color
        self.font_size_factor = font_size_factor
        self.bottom_margin_ratio = bottom_margin_ratio
        self.caption_width_ratio = caption_width_ratio
        self.max_lines = max_lines
        self.max_font_size = max_font_size
        self.max_font_size_ratio = max_font_size_ratio
        self.min_font_size = min_font_size
        self.alignment = alignment
        self.position = position

    def split_text_to_lines(self, text: str, max_width_px: int, font_size: int) -> str:
        """按像素宽度换行，自动适配书写系统。

        - CJK 文本（中日韩）：逐字符换行
        - Latin/Cyrillic 文本：按单词边界换行

        Args:
            text: 要换行的文本
            max_width_px: 最大像素宽度
            font_size: 测量字号

        Returns:
            换行后文本，行间用 \\n 隔开
        """
        from PIL import ImageFont

        font = ImageFont.truetype(self.font_path, font_size)
        return self._wrap_text(text, max_width_px, font)

    def _detect_script(self, text: str) -> str:
        """检测文本主导书写系统: cjk | latin | arabic | mixed"""
        cjk_ranges = [
            (0x4E00, 0x9FFF), (0x3400, 0x4DBF),  # CJK Unified
            (0x3040, 0x30FF), (0x31F0, 0x31FF),   # Hiragana, Katakana
            (0xAC00, 0xD7AF), (0x1100, 0x11FF),   # Hangul
        ]
        latin_ranges = [
            (0x0020, 0x024F), (0x1E00, 0x1EFF),   # Latin
            (0x0400, 0x04FF),                       # Cyrillic
        ]
        arabic_ranges = [
            (0x0600, 0x06FF), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF),
        ]

        cjk_count = sum(1 for ch in text if any(lo <= ord(ch) <= hi for lo, hi in cjk_ranges))
        latin_count = sum(1 for ch in text if any(lo <= ord(ch) <= hi for lo, hi in latin_ranges))
        arabic_count = sum(1 for ch in text if any(lo <= ord(ch) <= hi for lo, hi in arabic_ranges))
        total = max(cjk_count + latin_count + arabic_count, 1)

        if cjk_count / total > 0.3:
            return "cjk"
        if arabic_count / total > 0.3:
            return "arabic"
        if latin_count / total > 0:
            return "latin"
        return "cjk"  # default for unknown

    def _wrap_text(self, text: str, max_width_px: int, font) -> str:
        script = self._detect_script(text)

        if script == "latin":
            return self._wrap_latin(text, max_width_px, font)
        elif script == "arabic":
            return self._wrap_latin(text, max_width_px, font)  # space-based wrapping works for Arabic too
        else:
            return self._wrap_cjk(text, max_width_px, font)

    def _wrap_cjk(self, text: str, max_width_px: int, font) -> str:
        lines = []
        current_line = ""
        for char in text:
            test_line = current_line + char
            if font.getlength(test_line) > max_width_px:
                if current_line:
                    lines.append(current_line)
                current_line = char
            else:
                current_line = test_line
        if current_line:
            lines.append(current_line)
        return "\n".join(lines)

    def _wrap_latin(self, text: str, max_width_px: int, font) -> str:
        lines = []
        current_line = ""
        for word in text.split():
            if not word:
                continue
            separator = " " if current_line else ""
            test_line = current_line + separator + word
            if font.getlength(test_line) <= max_width_px:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                    current_line = ""
                if font.getlength(word) <= max_width_px:
                    current_line = word
                else:
                    partial = ""
                    for char in word:
                        if font.getlength(partial + char) > max_width_px:
                            if partial:
                                lines.append(partial)
                            partial = char
                        else:
                            partial += char
                    current_line = partial
        if current_line:
            lines.append(current_line)
        return "\n".join(lines)

    def _measure_lines(self, text: str, font_size: int, max_width_px: int) -> int:
        """快速测量文本在给定字号和宽度下会产生多少行。"""
        from PIL import ImageFont
        font = ImageFont.truetype(self.font_path, font_size)
        total_lines = 0
        for paragraph in text.split("\n"):
            if not paragraph:
                total_lines += 1
                continue
            wrapped = self._wrap_text(paragraph, max_width_px, font)
            total_lines += max(1, len(wrapped.split("\n")))
        return total_lines

    def _compute_max_font_size(self, video_height: int) -> int:
        """计算最大允许字号。"""
        if self.max_font_size is not None and self.max_font_size > 0:
            return self.max_font_size
        return int(video_height * self.max_font_size_ratio)

    def _adaptive_font_size(
        self,
        text_zh: str,
        text_eng: str,
        desired_size: int,
        max_width_px: int,
        video_height: int,
    ) -> tuple[int, str]:
        """二分搜索最大字号使文本不超过 max_lines。

        Returns:
            (font_size, display_text) — 不在此层截断，保留原文
        """
        max_fs = min(desired_size, self._compute_max_font_size(video_height))
        min_fs = self.min_font_size
        combined = f"{text_zh}\n{text_eng}" if text_eng else text_zh

        if self._measure_lines(combined, max_fs, max_width_px) <= self.max_lines:
            return max_fs, combined

        best_size = min_fs
        lo, hi = min_fs, max_fs
        while lo <= hi:
            mid = (lo + hi) // 2
            if mid < min_fs:
                break
            if self._measure_lines(combined, mid, max_width_px) <= self.max_lines:
                best_size = mid
                lo = mid + 1
            else:
                hi = mid - 1

        return best_size, combined

    def _get_font_size(self, video_width: int) -> int:
        """获取字体大小。优先使用指定值，否则自动计算。"""
        if self.font_size is not None:
            return self.font_size
        return int(video_width * self.font_size_factor)

    def render_overlay(self, video, duration: float, text_zh: str, text_eng: str):
        """渲染字幕叠加层（不含视频，用于多段分组）。

        Returns: (bg_clip, subtitles_clip) 两个独立的 MoviePy clip
        """
        from moviepy import TextClip, ColorClip

        width, height = video.size
        max_width = int(width * self.caption_width_ratio)
        margin = int(height * self.bottom_margin_ratio)
        desired_size = self._get_font_size(width)
        font_size, display_text = self._adaptive_font_size(
            text_zh, text_eng, desired_size, max_width, height
        )

        subtitles = TextClip(
            text=display_text,
            font=self.font_path,
            font_size=font_size,
            color=self.font_color,
            stroke_color=self.stroke_color,
            stroke_width=self.stroke_width,
            method="caption",
            size=(max_width, None),
            text_align=self.alignment,
        )

        sub_w, sub_h = subtitles.size
        if self.alignment == "left":
            x = int(width * (1.0 - self.caption_width_ratio) / 2)
        elif self.alignment == "right":
            x = width - sub_w - int(width * (1.0 - self.caption_width_ratio) / 2)
        else:
            x = "center"

        if self.position == "top":
            y = max(0, margin)
        else:
            y = max(0, height - sub_h - margin)

        pos = (x, y)
        subtitles = subtitles.with_duration(duration).with_position(pos)
        bg_clip = (
            ColorClip(size=subtitles.size, color=self.bg_color)
            .with_duration(subtitles.duration)
            .with_position(pos)
        )
        return bg_clip, subtitles

    def render(self, video, duration: float, text_zh: str, text_eng: str):
        """在视频上叠加中英字幕，含自适应字号和溢出保护。"""
        from moviepy import CompositeVideoClip

        bg_clip, subtitles = self.render_overlay(video, duration, text_zh, text_eng)
        return CompositeVideoClip([video, bg_clip, subtitles])

    @staticmethod
    def reserve_2_num(duration: float) -> float:
        """保留原版的时长修正值。

        原版: `return duration - 0.06`
        用于防止 moviepy 音频合并时出现重复音频帧。
        """
        return duration - 0.06
