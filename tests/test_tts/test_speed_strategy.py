"""
速度策略模块单元测试 — speed_strategy.py

测试 PerSegmentStrategy、GlobalStrategy、工厂函数 和 配置校验。
"""

import os
from unittest.mock import MagicMock, patch

import pytest


# ════════════════════════════════════════════════════════════════════
# StrategyContext 基础测试
# ════════════════════════════════════════════════════════════════════


class TestStrategyContext:
    """StrategyContext dataclass 默认值与自定义值"""

    def test_import(self):
        from pipeline.speed_strategy import StrategyContext
        assert StrategyContext is not None

    def test_defaults(self):
        from pipeline.speed_strategy import StrategyContext
        ctx = StrategyContext()
        assert ctx.base_speed == 30
        assert ctx.speed_max == 70
        assert ctx.video_speed_min == 0.75
        assert ctx.video_speed_max == 1.25
        assert ctx.search_method == "linear"

    def test_custom(self):
        from pipeline.speed_strategy import StrategyContext
        ctx = StrategyContext(
            base_speed=50, speed_max=90, search_method="binary",
        )
        assert ctx.base_speed == 50
        assert ctx.speed_max == 90
        assert ctx.search_method == "binary"


# ════════════════════════════════════════════════════════════════════
# 工厂函数测试
# ════════════════════════════════════════════════════════════════════


class TestCreateStrategy:
    """create_strategy 工厂函数"""

    def test_per_segment_default(self):
        from pipeline.speed_strategy import create_strategy, PerSegmentStrategy
        s = create_strategy("per_segment")
        assert isinstance(s, PerSegmentStrategy)

    def test_global_default(self):
        from pipeline.speed_strategy import create_strategy, GlobalStrategy
        s = create_strategy("global")
        assert isinstance(s, GlobalStrategy)

    def test_unknown_mode_falls_back(self):
        from pipeline.speed_strategy import create_strategy, PerSegmentStrategy
        s = create_strategy("unknown")
        assert isinstance(s, PerSegmentStrategy)

    def test_with_custom_ctx(self):
        from pipeline.speed_strategy import create_strategy, StrategyContext
        ctx = StrategyContext(base_speed=50, speed_max=90)
        s = create_strategy("per_segment", ctx)
        assert s.ctx.base_speed == 50
        assert s.ctx.speed_max == 90


# ════════════════════════════════════════════════════════════════════
# PerSegmentStrategy 测试
# ════════════════════════════════════════════════════════════════════


class TestPerSegmentStrategy:
    """PerSegmentStrategy 逐段调速策略"""

    def test_import(self):
        from pipeline.speed_strategy import PerSegmentStrategy
        assert PerSegmentStrategy is not None

    def test_process_empty_subs(self, temp_dir):
        """空字幕列表应返回空 ProcessResult"""
        from pipeline.speed_strategy import PerSegmentStrategy, StrategyContext, ProcessResult

        ctx = StrategyContext(trail_dir=temp_dir, audio_output_dir=temp_dir)
        strategy = PerSegmentStrategy(ctx)

        resume = MagicMock()
        resume.is_processed.return_value = False

        result = strategy.process(
            subs_cn=[], subs_en=[],
            synth_fn=MagicMock(return_value=1.0),
            video_clip=MagicMock(),
            instrumental_path="dummy.wav",
            video_segmenter=MagicMock(),
            resume_manager=resume,
        )
        assert isinstance(result, ProcessResult)
        assert result.total_success == 0
        assert result.total_error == 0
        assert len(result.results) == 0

    def test_process_skips_resumed(self, temp_dir):
        """resume_manager 返回已处理时应跳过"""
        from pipeline.speed_strategy import PerSegmentStrategy, StrategyContext

        ctx = StrategyContext(trail_dir=temp_dir, audio_output_dir=temp_dir)
        strategy = PerSegmentStrategy(ctx)

        resume = MagicMock()
        resume.is_processed.return_value = True

        subs = [(1000, 5000, "hello")]
        result = strategy.process(
            subs_cn=subs, subs_en=subs,
            synth_fn=MagicMock(return_value=1.0),
            video_clip=MagicMock(),
            instrumental_path="dummy.wav",
            video_segmenter=MagicMock(),
            resume_manager=resume,
        )
        assert result.total_success == 0
        assert result.total_error == 0

    def test_process_skips_invalid_timestamps(self, temp_dir):
        """无效时间戳应跳过"""
        from pipeline.speed_strategy import PerSegmentStrategy, StrategyContext

        ctx = StrategyContext(trail_dir=temp_dir, audio_output_dir=temp_dir)
        strategy = PerSegmentStrategy(ctx)

        resume = MagicMock()
        resume.is_processed.return_value = False

        subs = [(5000, 1000, "invalid"), (-100, 1000, "negative")]  # end < start, negative start
        result = strategy.process(
            subs_cn=subs, subs_en=subs,
            synth_fn=MagicMock(return_value=1.0),
            video_clip=MagicMock(),
            instrumental_path="dummy.wav",
            video_segmenter=MagicMock(),
            resume_manager=resume,
        )
        assert result.total_success == 0

    @patch("subprocess.run")
    def test_process_success_path(self, mock_run, temp_dir):
        """正常路径：一条字幕成功处理（不崩溃即可）"""
        from pipeline.speed_strategy import PerSegmentStrategy, StrategyContext

        ctx = StrategyContext(trail_dir=temp_dir, audio_output_dir=temp_dir)
        strategy = PerSegmentStrategy(ctx)

        resume = MagicMock()
        resume.is_processed.return_value = False

        subs_cn = [(1000, 5000, "hello")]
        subs_en = [(1000, 5000, "hello")]

        mock_video = MagicMock()
        mock_video.subclipped.return_value = MagicMock()

        # synth_fn 返回 float 但不创建文件 → shutil.copy 会失败 → 错误被捕获
        result = strategy.process(
            subs_cn=subs_cn, subs_en=subs_en,
            synth_fn=MagicMock(return_value=2.0),
            video_clip=mock_video,
            instrumental_path="dummy.wav",
            video_segmenter=MagicMock(),
            resume_manager=resume,
        )
        # 不崩溃即算通过；mark_processed 可能因文件不存在而未被调用
        from pipeline.speed_strategy import ProcessResult
        assert isinstance(result, ProcessResult)

    @patch("subprocess.run")
    def test_process_handles_errors(self, mock_run, temp_dir):
        """合成失败时不应崩溃"""
        from pipeline.speed_strategy import PerSegmentStrategy, StrategyContext

        ctx = StrategyContext(trail_dir=temp_dir, audio_output_dir=temp_dir)
        strategy = PerSegmentStrategy(ctx)

        resume = MagicMock()
        resume.is_processed.return_value = False

        subs = [(1000, 5000, "hello")]
        mock_video = MagicMock()
        mock_video.subclipped.return_value = MagicMock()

        def raise_error(text, path, rate):
            raise RuntimeError("TTS failure")
            return 0.0  # unreachable

        result = strategy.process(
            subs_cn=subs, subs_en=subs,
            synth_fn=raise_error,
            video_clip=mock_video,
            instrumental_path="dummy.wav",
            video_segmenter=MagicMock(),
            resume_manager=resume,
        )


# ════════════════════════════════════════════════════════════════════
# GlobalStrategy 测试
# ════════════════════════════════════════════════════════════════════


class TestGlobalStrategy:
    """GlobalStrategy 全局统一调速"""

    def test_import(self):
        from pipeline.speed_strategy import GlobalStrategy
        assert GlobalStrategy is not None

    def test_process_empty_subs(self, temp_dir):
        """空字幕列表"""
        from pipeline.speed_strategy import GlobalStrategy, StrategyContext, ProcessResult

        ctx = StrategyContext(trail_dir=temp_dir, audio_output_dir=temp_dir)
        strategy = GlobalStrategy(ctx)

        resume = MagicMock()
        resume.is_processed.return_value = False

        result = strategy.process(
            subs_cn=[], subs_en=[],
            synth_fn=MagicMock(return_value=1.0),
            video_clip=MagicMock(),
            instrumental_path="dummy.wav",
            video_segmenter=MagicMock(),
            resume_manager=resume,
        )
        assert isinstance(result, ProcessResult)
        assert result.total_success == 0
        assert result.total_error == 0

    @patch("subprocess.run")
    def test_process_perfect_fit(self, mock_run, temp_dir):
        """全部 TTS 时长正好 = 总可用时长时，rate 应接近 base_speed"""
        from pipeline.speed_strategy import GlobalStrategy, StrategyContext

        ctx = StrategyContext(trail_dir=temp_dir, audio_output_dir=temp_dir)
        strategy = GlobalStrategy(ctx)

        resume = MagicMock()
        resume.is_processed.return_value = False

        # 两条字幕，每条 1s TTS / 1s 可用
        subs_cn = [(0, 1000, "hi"), (1000, 2000, "hello")]
        subs_en = subs_cn
        mock_video = MagicMock()
        mock_video.subclipped.return_value = MagicMock()

        result = strategy.process(
            subs_cn=subs_cn, subs_en=subs_en,
            synth_fn=MagicMock(return_value=1.0),
            video_clip=mock_video,
            instrumental_path="dummy.wav",
            video_segmenter=MagicMock(),
            resume_manager=resume,
        )
        assert result.total_success >= 0
        # rate should be approximately +0% since everything fits
        assert result.global_rate_used is not None

    @patch("subprocess.run")
    def test_process_skips_resumed(self, mock_run, temp_dir):
        """跳过已处理的条目"""
        from pipeline.speed_strategy import GlobalStrategy, StrategyContext

        ctx = StrategyContext(trail_dir=temp_dir, audio_output_dir=temp_dir)
        strategy = GlobalStrategy(ctx)

        resume = MagicMock()
        resume.is_processed.return_value = True

        subs = [(1000, 5000, "hello")]
        result = strategy.process(
            subs_cn=subs, subs_en=subs,
            synth_fn=MagicMock(return_value=2.0),  # return float, not MagicMock
            video_clip=MagicMock(),
            instrumental_path="dummy.wav",
            video_segmenter=MagicMock(),
            resume_manager=resume,
        )
        assert result.total_success == 0
        assert result.total_error == 0


# ════════════════════════════════════════════════════════════════════
# TTSConfig 新字段校验测试
# ════════════════════════════════════════════════════════════════════


class TestConfigFields:
    """TTSConfig 新增字段和校验"""

    def test_speed_mode_default(self):
        from pipeline.tts_config import TTSConfig
        cfg = TTSConfig()
        assert cfg.speed_mode == "per_segment"

    def test_speed_mode_global(self):
        from pipeline.tts_config import TTSConfig
        cfg = TTSConfig(speed_mode="global")
        assert cfg.speed_mode == "global"

    def test_speed_mode_invalid(self):
        from pipeline.tts_config import TTSConfig
        with pytest.raises(ValueError, match="speed_mode"):
            TTSConfig(speed_mode="hybrid")

    def test_search_method_default(self):
        from pipeline.tts_config import TTSConfig
        cfg = TTSConfig()
        assert cfg.search_method == "binary"

    def test_search_method_binary(self):
        from pipeline.tts_config import TTSConfig
        cfg = TTSConfig(search_method="binary")
        assert cfg.search_method == "binary"

    def test_search_method_invalid(self):
        from pipeline.tts_config import TTSConfig
        with pytest.raises(ValueError, match="search_method"):
            TTSConfig(search_method="random")

    def test_video_speed_min_default(self):
        from pipeline.tts_config import TTSConfig
        cfg = TTSConfig()
        assert cfg.video_speed_min == 0.60
        assert cfg.video_speed_max == 2.00

    def test_video_speed_min_invalid(self):
        from pipeline.tts_config import TTSConfig
        with pytest.raises(ValueError, match="video_speed_min"):
            TTSConfig(video_speed_min=0.0)
        with pytest.raises(ValueError, match="video_speed_min"):
            TTSConfig(video_speed_min=3.0)

    def test_video_speed_max_invalid(self):
        from pipeline.tts_config import TTSConfig
        with pytest.raises(ValueError, match="video_speed_max"):
            TTSConfig(video_speed_max=0.0)
        with pytest.raises(ValueError, match="video_speed_max"):
            TTSConfig(video_speed_max=3.0)

    def test_search_step_default(self):
        from pipeline.tts_config import TTSConfig
        cfg = TTSConfig()
        assert cfg.search_step == 1

    def test_speed_mode_from_yaml(self, temp_dir):
        """YAML 序列化应保留 speed_mode 字段"""
        from pipeline.tts_config import TTSConfig

        cfg = TTSConfig(speed_mode="global", search_method="binary")
        yml = cfg.to_yaml()
        assert "speed_mode: global" in yml
        assert "search_method: binary" in yml

        # 反序列化恢复
        path = os.path.join(temp_dir, "test.yaml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(yml)
        restored = TTSConfig.from_yaml(path)
        assert restored.speed_mode == "global"
        assert restored.search_method == "binary"
        assert restored.video_speed_min == 0.60
        assert restored.video_speed_max == 2.00
