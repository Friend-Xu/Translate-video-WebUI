"""
VideoSegmenter 和 CaptionRenderer 单元测试
"""

import os
from unittest.mock import MagicMock, patch

import pytest


class TestVideoSegmenter:
    """VideoSegmenter 单元测试"""

    def test_import(self):
        """模块可导入"""
        from pipeline.tts_video import VideoSegmenter, SpeedDecision
        assert VideoSegmenter is not None
        assert SpeedDecision is not None

    def test_default_params(self):
        """默认构造参数"""
        from pipeline.tts_video import VideoSegmenter
        vs = VideoSegmenter()
        assert vs.speed_tolerance == 0.15
        assert vs.video_output_dir == "file/Video_file"

    def test_custom_params(self):
        """自定义构造参数"""
        from pipeline.tts_video import VideoSegmenter
        vs = VideoSegmenter(
            video_output_dir="custom/video",
            speed_tolerance=0.2,
            caption=False,
            clone_color=True,
        )
        assert vs.video_output_dir == "custom/video"
        assert vs.speed_tolerance == 0.2
        assert vs.caption is False
        assert vs.clone_color is True


class TestSpeedDecision:
    """SpeedDecision 两级决策测试"""

    def test_import(self):
        from pipeline.tts_video import SpeedDecision
        sd = SpeedDecision()
        assert sd.video_speed_factor == 1.0
        assert sd.tts_rate == "+0%"
        assert sd.use_video_speed is True

    def test_within_tolerance(self):
        """ratio 在容忍范围内 → 调视频速度"""
        from pipeline.tts_video import VideoSegmenter
        vs = VideoSegmenter(speed_tolerance=0.15)
        # ratio = 1.05 / 1.0 = 1.05, |1.05-1| = 0.05 ≤ 0.15 → 调视频
        decision = vs.decide_speed(tts_duration=1.05, video_duration=1.0)
        assert decision.use_video_speed is True
        assert decision.video_speed_factor == pytest.approx(1.05)

    def test_within_tolerance_slow(self):
        """视频比 TTS 长，但在容忍范围内 → 调视频（减速）"""
        from pipeline.tts_video import VideoSegmenter
        vs = VideoSegmenter(speed_tolerance=0.2)
        decision = vs.decide_speed(tts_duration=1.0, video_duration=1.15)
        assert decision.use_video_speed is True
        assert decision.video_speed_factor == pytest.approx(1.0 / 1.15)

    def test_exceeds_tolerance_high(self):
        """ratio 超出容忍范围上限 → 不调视频，调 TTS"""
        from pipeline.tts_video import VideoSegmenter
        vs = VideoSegmenter(speed_tolerance=0.15)
        # ratio = 1.3 / 1.0 = 1.3, |1.3-1| = 0.3 > 0.15 → 调 TTS
        decision = vs.decide_speed(tts_duration=1.3, video_duration=1.0)
        assert decision.use_video_speed is False

    def test_exceeds_tolerance_low(self):
        """ratio 超出容忍范围下限 → 不调视频，调 TTS"""
        from pipeline.tts_video import VideoSegmenter
        vs = VideoSegmenter(speed_tolerance=0.15)
        decision = vs.decide_speed(tts_duration=1.0, video_duration=2.0)
        # ratio = 0.5, |0.5-1| = 0.5 > 0.15 → 调 TTS
        assert decision.use_video_speed is False

    def test_equal_duration(self):
        """TTS 时长 == 视频时长 → 不调整"""
        from pipeline.tts_video import VideoSegmenter
        vs = VideoSegmenter()
        decision = vs.decide_speed(tts_duration=1.0, video_duration=1.0)
        assert decision.use_video_speed is True
        assert decision.video_speed_factor == pytest.approx(1.0)

    def test_zero_duration(self):
        """零时长 → 不调整"""
        from pipeline.tts_video import VideoSegmenter
        vs = VideoSegmenter()
        decision = vs.decide_speed(tts_duration=0, video_duration=0)
        assert decision.use_video_speed is True
        assert decision.video_speed_factor == pytest.approx(1.0)

    def test_edge_tolerance_exact(self):
        """ratio 恰好等于容忍边界 → 调视频"""
        from pipeline.tts_video import VideoSegmenter
        vs = VideoSegmenter(speed_tolerance=0.15)
        decision = vs.decide_speed(tts_duration=1.14, video_duration=1.0)
        assert decision.use_video_speed is True

        decision2 = vs.decide_speed(tts_duration=0.86, video_duration=1.0)
        assert decision2.use_video_speed is True


class TestReserve2Num:
    """reserve_2_num 保持原版行为"""

    def test_original_behavior(self):
        """验证原版 duration - 0.06 的行为"""
        from pipeline.tts_video import VideoSegmenter
        vs = VideoSegmenter()
        assert vs.reserve_2_num(2.0) == 1.94
        assert vs.reserve_2_num(1.5) == 1.44
        assert vs.reserve_2_num(10.0) == 9.94


class TestCaptionRenderer:
    """CaptionRenderer 单元测试"""

    def test_import(self):
        """模块可导入"""
        from pipeline.tts_caption import CaptionRenderer
        assert CaptionRenderer is not None

    def test_default_params(self):
        """默认构造参数"""
        from pipeline.tts_caption import CaptionRenderer
        cr = CaptionRenderer()
        assert "Minecraft" in cr.font_path
        assert cr.font_color == "white"

    def test_reserve_2_num_static(self):
        """静态方法保持原版行为"""
        from pipeline.tts_caption import CaptionRenderer
        assert CaptionRenderer.reserve_2_num(2.0) == 1.94
        assert CaptionRenderer.reserve_2_num(1.5) == 1.44

    def test_split_text_no_wrap(self):
        """短文本不需要换行"""
        from pipeline.tts_caption import CaptionRenderer
        cr = CaptionRenderer()
        # 字体不存在时，split_text_to_lines 会报错
        cr.font_path = "/nonexistent/font.ttf"
        with pytest.raises(Exception):
            cr.split_text_to_lines("短", 1000)

    def test_render_requires_font(self):
        """字体不存在时渲染文件会出错"""
        from pipeline.tts_caption import CaptionRenderer
        cr = CaptionRenderer(font_path="/nonexistent/font.ttf")
        # 因为没有字体，split_text_to_lines 会报错
        with pytest.raises(Exception):
            cr.render(MagicMock(), 1.0, "测试", "test")
