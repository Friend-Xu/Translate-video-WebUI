"""
测试 SubtitleOptimizer 字幕拆分优化

验证:
  1. 短字幕不触发拆分
  2. 超长文本拆分为多段
  3. 双语按比例对齐切分
  4. 每段行数 <= max_lines
  5. 拆分后总时长等于原始时长
  6. 边界情况：零时长、空文本、极短字幕
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "pipeline"))

import pytest
from pipeline.tts_caption import CaptionRenderer

FONT_PATH = os.path.join(PROJECT_ROOT, "models", "font", "Minecraft_font",
                         "5_Minecraft_AE_zh_en.ttf")
_font_available = os.path.isfile(FONT_PATH)


@pytest.fixture
def capturer():
    if not _font_available:
        pytest.skip("Font file not available in CI")
    return CaptionRenderer(
        font_path=FONT_PATH,
        max_lines=2,
        min_font_size=12,
        font_size_factor=0.030,
        caption_width_ratio=0.85,
    )


@pytest.fixture
def video_width():
    return 1280


class TestOptimize:
    """SubtitleOptimizer.optimize 核心测试"""

    def test_short_subtitles_pass_through(self, capturer, video_width):
        """短字幕不拆分，原样返回"""
        from pipeline.subtitle_optimizer import optimize
        subs_target = [(0, 3000, "Hello World")]
        subs_source = [(0, 3000, "Hello World")]

        groups = optimize(subs_target, subs_source, capturer, video_width)

        assert len(groups) == 1
        assert len(groups[0]) == 1
        rel_start, rel_end, t_text, s_text = groups[0][0]
        assert t_text == "Hello World"
        assert rel_start == 0
        assert rel_end == 3000

    def test_long_text_gets_split(self, capturer, video_width):
        """超长字幕拆分为多段"""
        from pipeline.subtitle_optimizer import optimize
        long_zh = "今天我们要看十个最佳Minecraft模组包，这些模组包都有不同的特色和玩法" * 3
        long_en = "Today we are going to look at ten of the best Minecraft mod packs, each with different features" * 3
        subs_target = [(0, 5000, long_zh)]
        subs_source = [(0, 5000, long_en)]

        groups = optimize(subs_target, subs_source, capturer, video_width)

        assert len(groups) == 1
        assert len(groups[0]) >= 2, f"Expected split into 2+ segments, got {len(groups[0])}"

    def test_each_segment_within_max_lines(self, capturer, video_width):
        """拆分后每个子段都不超过 max_lines"""
        from pipeline.subtitle_optimizer import optimize
        max_width = int(video_width * capturer.caption_width_ratio)

        long_zh = "今天我们要看十个最佳Minecraft模组包，这些模组包都有不同的特色和玩法" * 3
        long_en = "Today we are going to look at ten of the best Minecraft mod packs, each with different features" * 3
        subs_target = [(0, 5000, long_zh)]
        subs_source = [(0, 5000, long_en)]

        groups = optimize(subs_target, subs_source, capturer, video_width)

        for group in groups:
            for _, _, t_text, s_text in group:
                combined = f"{t_text}\n{s_text}" if s_text else t_text
                lines = capturer._measure_lines(
                    combined, capturer.min_font_size, max_width,
                )
                assert lines <= capturer.max_lines, (
                    f"Segment should fit within {capturer.max_lines} lines, got {lines}"
                )

    def test_total_duration_preserved(self, capturer, video_width):
        """拆分后各段时长之和等于原始时长"""
        from pipeline.subtitle_optimizer import optimize

        long_zh = "今天我们要看十个最佳Minecraft模组包，这些模组包都有不同的特色和玩法" * 3
        long_en = "Today we are going to look at ten of the best Minecraft mod packs" * 3
        subs_target = [(1000, 6000, long_zh)]
        subs_source = [(1000, 6000, long_en)]

        groups = optimize(subs_target, subs_source, capturer, video_width)

        for i, group in enumerate(groups):
            total = sum(end - start for start, end, _, _ in group)
            original = subs_target[i][1] - subs_target[i][0]
            assert total == original, (
                f"Total duration {total}ms != original {original}ms"
            )

    def test_bilingual_alignment(self, capturer, video_width):
        """双语拆分后中英文都非空"""
        from pipeline.subtitle_optimizer import optimize

        zh = "今天我们要看十个最佳Minecraft模组包，这些模组包都有不同的特色和玩法，快来一起探索吧"
        en = "Today we look at ten best Minecraft mod packs, each with different features, come explore"
        subs_target = [(0, 4000, zh)]
        subs_source = [(0, 4000, en)]

        groups = optimize(subs_target, subs_source, capturer, video_width)

        for group in groups:
            for _, _, t_text, s_text in group:
                assert len(t_text) > 0
                if s_text:
                    assert len(s_text) > 0

    def test_multiple_entries(self, capturer):
        """多个字幕条目混合处理 — 用窄宽度强制拆分"""
        from pipeline.subtitle_optimizer import optimize
        narrow_width = 640

        long_zh = "今天我们要看十个最佳Minecraft模组包，这些模组包都有不同的特色和玩法" * 3
        long_en = "Today we are going to look at ten of the best Minecraft mod packs" * 3
        subs_target = [
            (0, 2000, "Hello"),
            (2000, 7000, long_zh),
            (7000, 10000, "Goodbye"),
        ]
        subs_source = [
            (0, 2000, "Hello"),
            (2000, 7000, long_en),
            (7000, 10000, "Goodbye"),
        ]

        groups = optimize(subs_target, subs_source, capturer, narrow_width)

        assert len(groups) == 3
        assert len(groups[0]) == 1, "Short entry should not split"
        assert len(groups[1]) >= 2, "Long entry should split"
        assert len(groups[2]) == 1, "Short entry should not split"


class TestEdgeCases:
    """边界情况测试"""

    @pytest.fixture
    def capturer(self):
        if not _font_available:
            pytest.skip("Font file not available in CI")
        return CaptionRenderer(
            font_path=FONT_PATH,
            max_lines=2,
            min_font_size=12,
        )

    @pytest.fixture
    def video_width(self):
        return 1280

    def test_zero_duration(self, capturer, video_width):
        from pipeline.subtitle_optimizer import optimize
        groups = optimize(
            [(0, 0, "test")], [(0, 0, "test")], capturer, video_width,
        )
        assert len(groups) == 1
        assert len(groups[0]) == 1

    def test_empty_text(self, capturer, video_width):
        from pipeline.subtitle_optimizer import optimize
        groups = optimize(
            [(0, 3000, "")], [(0, 3000, "")], capturer, video_width,
        )
        assert len(groups) == 1

    def test_missing_source(self, capturer, video_width):
        """源语言字幕缺失时应正常工作"""
        from pipeline.subtitle_optimizer import optimize
        long_zh = "今天我们要看十个最佳Minecraft模组包" * 3
        groups = optimize(
            [(0, 5000, long_zh)], [], capturer, video_width,
        )
        assert len(groups) == 1
        assert len(groups[0]) >= 1


class TestScriptDetection:
    """SubtitleOptimizer 书写系统检测"""

    def test_detect_cjk(self):
        from pipeline.subtitle_optimizer import _detect_script
        assert _detect_script("今天我们要看十个最佳Minecraft模组包") == "cjk"

    def test_detect_latin(self):
        from pipeline.subtitle_optimizer import _detect_script
        assert _detect_script("Hello World! This is English.") == "latin"

    def test_detect_arabic(self):
        from pipeline.subtitle_optimizer import _detect_script
        assert _detect_script("مرحبا بالعالم") == "arabic"


class TestFindBreakpoint:
    """断句点查找测试"""

    def test_cjk_period_break(self):
        from pipeline.subtitle_optimizer import _find_breakpoint, _CJK_STOPS
        text = "今天我们要看十个最佳Minecraft模组包。这些模组包都有不同的特色。"
        pos = _find_breakpoint(text, 0.5, _CJK_STOPS, "cjk")
        assert pos > 0
        assert text[pos - 1] == "。"

    def test_latin_comma_break(self):
        from pipeline.subtitle_optimizer import _find_breakpoint, _LATIN_STOPS
        text = "Hello world, this is a test, more text here."
        pos = _find_breakpoint(text, 0.5, _LATIN_STOPS, "latin")
        assert pos > 0

    def test_fallback_forced_split(self):
        """无标点文本强制按位置切分"""
        from pipeline.subtitle_optimizer import _find_breakpoint, _LATIN_STOPS
        text = "abcdefghijklmnopqrstuvwxyz" * 4
        pos = _find_breakpoint(text, 0.5, _LATIN_STOPS, "latin")
        assert pos > 0
        assert pos < len(text)
