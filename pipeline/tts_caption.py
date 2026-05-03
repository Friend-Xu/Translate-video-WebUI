"""
字幕渲染器 — CaptionRenderer

从原 `SrtTxtToAudio.set_caption()`、`split_text_to_lines()`、`reserve_2_num()` 提取。
行为与原版完全一致。
"""

from __future__ import annotations

import os
from typing import Optional


class CaptionRenderer:
    """字幕渲染器：在视频上叠加中英双层字幕。

    从原 `SrtTxtToAudio` 的 set_caption/split_text_to_lines/reserve_2_num 原样提取。

    用法:
        renderer = CaptionRenderer(
            font_path="./Model/font/Minecraft_font/5_Minecraft_AE_zh_en.ttf",
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
            caption_width_ratio: 字幕文本框宽度占视频宽度的比例（默认 85%，左右各 7.5% 留白）
        """
        self.font_path = font_path
        self.font_size = font_size
        self.font_color = font_color
        self.stroke_color = stroke_color
        self.stroke_width = stroke_width
        self.bg_color = bg_color
        self.font_size_factor = font_size_factor
        self.bottom_margin_ratio = bottom_margin_ratio
        self.caption_width_ratio = caption_width_ratio

    def split_text_to_lines(self, text: str, max_width_px: int) -> str:
        """按像素宽度换行。从原版原样提取。

        Args:
            text: 要换行的文本
            max_width_px: 最大像素宽度

        Returns:
            换行后文本，行间用 \\n 隔开
        """
        from PIL import ImageFont

        font_size = self._get_font_size(max_width_px)
        font = ImageFont.truetype(self.font_path, font_size)
        lines = []
        current_line = ""

        for char in text:
            test_line = current_line + char
            line_width = font.getlength(test_line)
            if line_width > max_width_px:
                lines.append(current_line)
                current_line = char
            else:
                current_line = test_line

        if current_line:
            lines.append(current_line)

        return "\n".join(lines)

    def _get_font_size(self, video_width: int) -> int:
        """获取字体大小。优先使用指定值，否则自动计算。"""
        if self.font_size is not None:
            return self.font_size
        return int(video_width * self.font_size_factor)

    def render(self, video, duration: float, text_zh: str, text_eng: str):
        """在视频上叠加中英字幕（底部居中，带可配置边距）。

        Args:
            video: 视频剪辑 (VideoFileClip)
            duration: 字幕持续时长（秒）
            text_zh: 中文字幕
            text_eng: 英文字幕

        Returns:
            CompositeVideoClip 叠加字幕后的视频
        """
        from moviepy import TextClip, ColorClip, CompositeVideoClip

        width, height = video.size
        font_size = self._get_font_size(width)
        bottom_margin = int(height * self.bottom_margin_ratio)
        max_width = int(width * self.caption_width_ratio)

        subtitles = TextClip(
            text=f"{text_zh}\n{text_eng}",
            font=self.font_path,
            font_size=font_size,
            color=self.font_color,
            stroke_color=self.stroke_color,
            stroke_width=self.stroke_width,
            method="caption",
            size=(max_width, None),
            text_align="center",
        )

        # 水平居中（caption 框宽度 = max_width，clip center 对齐 frame center）
        # 垂直距底部 bottom_margin 像素
        sub_w, sub_h = subtitles.size
        y = height - sub_h - bottom_margin
        position = ("center", y)

        subtitles = subtitles.with_duration(duration).with_position(position)

        bg_clip = (
            ColorClip(size=subtitles.size, color=self.bg_color)
            .with_duration(subtitles.duration)
            .with_position(position)
        )

        return CompositeVideoClip([video, bg_clip, subtitles])

    @staticmethod
    def reserve_2_num(duration: float) -> float:
        """保留原版的时长修正值。

        原版: `return duration - 0.06`
        用于防止 moviepy 音频合并时出现重复音频帧。
        """
        return duration - 0.06
