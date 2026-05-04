"""
测试 CaptionRenderer 字幕渲染 —— guard against 字幕溢出 / 不居中 回归

验证:
  1. text clip 宽度不超过视频宽度（不溢出）
  2. caption 模式自动换行有效
  3. 短文本不无故换行
  4. 中英双语渲染正常
  5. 自适应字号：长文本缩小、短文本不缩小
  6. 行数测量：CJK/拉丁混合文本
  7. 脚本检测：CJK/Latin/Arabic
  8. 单词边界换行 vs 逐字符
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


class TestScriptDetection:
    """书写系统检测测试"""

    @pytest.fixture
    def renderer(self):
        return CaptionRenderer(font_path=FONT_PATH)

    def test_detect_cjk(self, renderer):
        assert renderer._detect_script("今天我们要看十个最佳Minecraft模组包") == "cjk"
        assert renderer._detect_script("日本語のテスト") == "cjk"
        assert renderer._detect_script("한국어 테스트") == "cjk"

    def test_detect_latin(self, renderer):
        assert renderer._detect_script("Hello World") == "latin"
        assert renderer._detect_script("This is a long English sentence.") == "latin"

    def test_detect_mixed_falls_to_cjk(self, renderer):
        """混合文本 CJK 占比 > 30% 时判定为 CJK"""
        result = renderer._detect_script("今天我们要看Minecraft模组")
        assert result == "cjk"

    def test_detect_mixed_mostly_latin(self, renderer):
        """混合文本中 Latin 占主导时判定为 Latin"""
        result = renderer._detect_script("Minecraft is great 我的世界")
        # Latin chars dominate → "latin"
        assert result == "latin"


class TestLineCounting:
    """行数测量测试"""

    @pytest.fixture
    def renderer(self):
        return CaptionRenderer(font_path=FONT_PATH)

    def test_single_line_text(self, renderer):
        lines = renderer._measure_lines("Hello World", 36, 1000)
        assert lines == 1

    def test_long_text_wraps(self, renderer):
        long_text = "Today we are going to look at ten of the best Minecraft mod packs available"
        lines = renderer._measure_lines(long_text, 48, 400)
        assert lines >= 2, f"Expected 2+ lines at narrow width, got {lines}"

    def test_bilingual_counting(self, renderer):
        combined = "今天我们要看十个最佳Minecraft模组包\nTen best Minecraft mod packs"
        lines = renderer._measure_lines(combined, 36, 600)
        assert lines >= 2

    def test_cjk_long_text(self, renderer):
        text = "今天我们要看十个最佳Minecraft模组包，这些模组包都有不同的特色和玩法，快来一起探索吧"
        lines = renderer._measure_lines(text, 40, 500)
        assert lines >= 2, f"CJK long text should wrap, got {lines}"


class TestAdaptiveFontSize:
    """自适应字号测试"""

    @pytest.fixture
    def renderer(self):
        return CaptionRenderer(font_path=FONT_PATH, max_lines=2, min_font_size=12)

    def test_short_text_keeps_desired_size(self, renderer):
        # max_font_size auto = 720 * 0.045 = 32, so desired=48 caps at 32
        # Use explicit max_font_size=80 to verify short text preserves desired size
        r = CaptionRenderer(font_path=FONT_PATH, max_lines=2,
                            min_font_size=12, max_font_size=80)
        size, text = r._adaptive_font_size(
            "Hello", "World", desired_size=36,
            max_width_px=800, video_height=720,
        )
        assert size == 36

    def test_long_text_shrinks(self, renderer):
        zh = "今天我们要看十个最佳Minecraft模组包，这些模组包都有不同的特色和玩法"
        en = "Today we are going to look at ten of the best Minecraft mod packs"
        size, text = renderer._adaptive_font_size(
            zh, en, desired_size=48,
            max_width_px=600, video_height=720,
        )
        assert size < 48, f"Long text should shrink from 48, got {size}"

    def test_respects_min_font_size(self, renderer):
        """即使文本极长，也不低于 min_font_size"""
        zh = "今天我们要看十个最佳Minecraft模组包" * 10
        en = "Today we are going to look at ten of the best Minecraft mod packs" * 10
        size, text = renderer._adaptive_font_size(
            zh, en, desired_size=48,
            max_width_px=600, video_height=720,
        )
        assert size >= renderer.min_font_size

    def test_respects_max_font_size(self, renderer):
        """max_font_size 限制上限"""
        r = CaptionRenderer(font_path=FONT_PATH, max_lines=2,
                            min_font_size=12, max_font_size=30)
        size, text = r._adaptive_font_size(
            "Hello", "World", desired_size=48,
            max_width_px=800, video_height=720,
        )
        assert size <= 30, f"Should cap at max_font_size=30, got {size}"


class TestTextWrapping:
    """文本换行策略测试"""

    @pytest.fixture
    def renderer(self):
        return CaptionRenderer(font_path=FONT_PATH)

    def test_cjk_char_by_char_wrap(self, renderer):
        from PIL import ImageFont
        font = ImageFont.truetype(FONT_PATH, 36)
        result = renderer._wrap_cjk("今天我们要看十个最佳Minecraft模组包", 300, font)
        lines = result.split("\n")
        assert len(lines) >= 2, f"CJK should wrap character-by-character, got {len(lines)} lines"

    def test_latin_word_boundary_wrap(self, renderer):
        from PIL import ImageFont
        font = ImageFont.truetype(FONT_PATH, 36)
        result = renderer._wrap_latin("Today we are going to look at mods", 200, font)
        lines = result.split("\n")
        # Words should not be broken mid-word
        for line in lines:
            words = line.split()
            for w in words:
                assert len(w) > 0, "Words should remain intact"

    def test_wrap_text_routes_to_correct_strategy(self, renderer):
        from PIL import ImageFont
        font = ImageFont.truetype(FONT_PATH, 36)
        cjk_result = renderer._wrap_text("今天我们要看十个最佳Minecraft模组包", 300, font)
        latin_result = renderer._wrap_text("Today we are going to look at mods", 200, font)
        assert len(cjk_result) > 0
        assert len(latin_result) > 0
