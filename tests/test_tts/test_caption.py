"""
测试 CaptionRenderer 字幕渲染 —— guard against 字幕溢出 / 不居中 回归

验证:
  1. text clip 宽度不超过视频宽度（不溢出）
  2. caption 模式自动换行有效
  3. 短文本不无故换行
  4. 中英双语渲染正常
"""
import os
import sys

# 确保能找到 pipeline 和根目录字体
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "pipeline"))

import pytest
from pipeline.tts_caption import CaptionRenderer


FONT_PATH = os.path.join(PROJECT_ROOT, "models", "font", "Minecraft_font",
                         "5_Minecraft_AE_zh_en.ttf")


@pytest.fixture
def renderer():
    return CaptionRenderer(font_path=FONT_PATH, caption_width_ratio=0.85)


class TestCaptionRenderer:
    """字幕渲染行为测试"""

    def test_text_clip_width_within_bounds(self, renderer):
        """文本 clip 宽度不应超过视频宽度，字幕框应居中留边距"""
        from moviepy import TextClip
        width = 1280
        max_width = int(width * renderer.caption_width_ratio)
        font_size = renderer._get_font_size(width)

        text = ("Today guys, we're going to be looking at 10 of the best "
                "Minecraft mod packs for 1.19 and of course 1.18 as well.")

        tc = TextClip(text=f"{text}\n{text}", font=renderer.font_path,
                      font_size=font_size, color="white",
                      stroke_color="black", stroke_width=1,
                      method="caption", size=(max_width, None),
                      text_align="center")

        assert tc.w <= max_width
        assert tc.w == max_width
        tc.close()

    def test_caption_not_overflow(self, renderer):
        """caption 模式生成的 clip 不超过视频宽度的 caption_width_ratio"""
        from moviepy import TextClip
        width = 1280
        max_width = int(width * renderer.caption_width_ratio)

        text = ("Today guys, we're going to be looking at 10 of the best "
                "Minecraft mod packs for 1.19 and of course 1.18 as well.")

        tc = TextClip(text=text, font=renderer.font_path,
                      font_size=renderer._get_font_size(width),
                      color="white", stroke_color="black", stroke_width=1,
                      method="caption", size=(max_width, None),
                      text_align="center")

        assert tc.w <= max_width
        tc.close()

    def test_caption_multiline_fits(self, renderer):
        """长文本自动换行后宽度统一"""
        from moviepy import TextClip
        width = 1280
        max_width = int(width * renderer.caption_width_ratio)

        text = ("Today guys, we're going to be looking at 10 of the best "
                "Minecraft mod packs for 1.19 and of course 1.18 as well. "
                "Make sure you watch all the way through!")

        tc = TextClip(text=text, font=renderer.font_path,
                      font_size=renderer._get_font_size(width),
                      color="white", stroke_color="black", stroke_width=1,
                      method="caption", size=(max_width, None),
                      text_align="center")

        assert tc.w == max_width
        assert tc.h > 50, f"长文本应有换行，高度只有 {tc.h}px"
        tc.close()

    def test_bilingual_caption(self, renderer):
        """中英双语字幕渲染不崩溃"""
        from moviepy import TextClip
        width = 1280
        max_width = int(width * renderer.caption_width_ratio)

        zh = "今天我们要看10个最佳Minecraft模组包"
        en = "Today we're looking at 10 best Minecraft mod packs"
        both = f"{zh}\n{en}"

        tc = TextClip(text=both, font=renderer.font_path,
                      font_size=renderer._get_font_size(width),
                      color="white", stroke_color="black", stroke_width=1,
                      method="caption", size=(max_width, None),
                      text_align="center")

        assert tc.w == max_width
        tc.close()

    def test_short_text_stays_single_line(self, renderer):
        """短文本仍保持单行（不无故换行）"""
        from moviepy import TextClip
        width = 1280
        max_width = int(width * renderer.caption_width_ratio)

        tc = TextClip(text="Hello World", font=renderer.font_path,
                      font_size=renderer._get_font_size(width),
                      color="white", method="caption",
                      size=(max_width, None), text_align="center")

        assert tc.w <= max_width
        assert tc.h < renderer._get_font_size(width) * 2
        tc.close()
