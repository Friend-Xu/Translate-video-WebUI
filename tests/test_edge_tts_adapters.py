"""
Edge TTS 适配器测试 (Chapter 9 实施验证)

测试 EdgeTTSAdapter, EdgeTTSScorer。
使用 mock 数据避免网络依赖。
"""
import pytest
from core.adapters.edge_tts_adapter import EdgeTTSAdapter, EdgeTTSSegmentContext
from core.scoring.edge_tts_scorer import EdgeTTSScorer, EdgeTTSScore
from core.runtime.patch import OpCode, Patch


class TestEdgeTTSSegmentContext:
    """EdgeTTSSegmentContext 数据结构验证"""

    def test_defaults(self):
        ctx = EdgeTTSSegmentContext(
            segment_id="seg_001", translation_text="你好",
        )
        assert ctx.segment_id == "seg_001"
        assert ctx.translation_text == "你好"
        assert ctx.lang == ""
        assert ctx.voice == ""
        assert ctx.rate == "+0%"
        assert ctx.fallback_reason == ""

    def test_full_context(self):
        ctx = EdgeTTSSegmentContext(
            segment_id="seg_002", translation_text="Hello world",
            lang="en", voice="en-US-AriaNeural",
            duration_target=2.65, rate="+40%",
            fallback_reason="all_primary_failed",
        )
        assert ctx.lang == "en"
        assert ctx.voice == "en-US-AriaNeural"
        assert ctx.duration_target == 2.65
        assert ctx.rate == "+40%"
        assert ctx.fallback_reason == "all_primary_failed"

    def test_fallback_reasons(self):
        reasons = [
            "all_primary_failed",
            "openvoice_fallback_failed",
            "offline_mode",
            "low_resource_mode",
        ]
        for r in reasons:
            ctx = EdgeTTSSegmentContext(
                segment_id="s1", translation_text="t",
                fallback_reason=r,
            )
            assert ctx.fallback_reason == r


class TestEdgeTTSAdapter:
    """EdgeTTSAdapter 测试（不启动真实引擎）"""

    def test_construct(self):
        adapter = EdgeTTSAdapter(voice="zh-CN-XiaoxiaoNeural")
        assert adapter._voice == "zh-CN-XiaoxiaoNeural"

    def test_resolve_voice_exact_match(self):
        assert EdgeTTSAdapter._resolve_voice("zh-CN") == "zh-CN-XiaoxiaoNeural"
        assert EdgeTTSAdapter._resolve_voice("ja") == "ja-JP-NanamiNeural"
        assert EdgeTTSAdapter._resolve_voice("en") == "en-US-AriaNeural"

    def test_resolve_voice_short_code(self):
        """zh → zh-CN-XiaoxiaoNeural"""
        assert "zh-CN-XiaoxiaoNeural" in EdgeTTSAdapter._resolve_voice("zh")

    def test_resolve_voice_unknown(self):
        assert EdgeTTSAdapter._resolve_voice("xx") == ""

    def test_resolve_voice_empty(self):
        assert EdgeTTSAdapter._resolve_voice("") == ""

    def test_calc_duration_fit_perfect(self):
        assert EdgeTTSAdapter._calc_duration_fit(3.0, 3.0) == 1.0

    def test_calc_duration_fit_deviation(self):
        score = EdgeTTSAdapter._calc_duration_fit(3.25, 3.0)
        assert score == pytest.approx(0.833, rel=0.01)

    def test_calc_duration_fit_zero_target(self):
        assert EdgeTTSAdapter._calc_duration_fit(3.0, 0.0) == 1.0


class TestEdgeTTSScorer:
    """EdgeTTSScorer 四维评分验证"""

    def test_perfect_score(self):
        scorer = EdgeTTSScorer()
        ctx = EdgeTTSSegmentContext(
            segment_id="s1", translation_text="test",
            lang="zh", duration_target=3.0,
            fallback_reason="all_primary_failed",
        )
        patch = Patch(
            id="p1", target_id="s1", op=OpCode.UPDATE_TTS_AUDIO,
            value={
                "duration": 3.0, "availability_score": 0.99,
                "voice": "zh-CN-XiaoxiaoNeural",
                "engine": "edge_tts", "generation_mode": "fallback",
            },
        )
        score = scorer.score(ctx, patch)
        assert score.composite > 0.75
        assert score.accepted is True

    def test_accept_threshold(self):
        """Edge TTS 使用 0.55 阈值（全系统最低）"""
        assert EdgeTTSScore("s1", composite=0.60).accepted is True
        assert EdgeTTSScore("s2", composite=0.55).accepted is True
        assert EdgeTTSScore("s3", composite=0.54).accepted is False

    def test_weights_sum(self):
        scorer = EdgeTTSScorer()
        assert sum(scorer.weights.values()) == 1.0

    def test_language_match_exact(self):
        scorer = EdgeTTSScorer()
        ctx = EdgeTTSSegmentContext(
            segment_id="s1", translation_text="test",
            lang="zh-CN", fallback_reason="all_primary_failed",
        )
        patch = Patch(
            id="p1", target_id="s1", op=OpCode.UPDATE_TTS_AUDIO,
            value={
                "duration": 3.0, "availability_score": 0.99,
                "voice": "zh-CN-XiaoxiaoNeural",
            },
        )
        score = scorer.score(ctx, patch)
        assert score.language_match > 0.95

    def test_language_match_mismatch(self):
        scorer = EdgeTTSScorer()
        ctx = EdgeTTSSegmentContext(
            segment_id="s1", translation_text="test",
            lang="ja", fallback_reason="all_primary_failed",
        )
        patch = Patch(
            id="p1", target_id="s1", op=OpCode.UPDATE_TTS_AUDIO,
            value={
                "duration": 3.0, "availability_score": 0.99,
                "voice": "zh-CN-XiaoxiaoNeural",
            },
        )
        score = scorer.score(ctx, patch)
        assert score.language_match < 0.90

    def test_fallback_validity_primary_failed(self):
        scorer = EdgeTTSScorer()
        ctx = EdgeTTSSegmentContext(
            segment_id="s1", translation_text="test",
            fallback_reason="all_primary_failed",
        )
        patch = Patch(
            id="p1", target_id="s1", op=OpCode.UPDATE_TTS_AUDIO,
            value={"duration": 3.0, "availability_score": 0.99, "voice": "zh-CN"},
        )
        score = scorer.score(ctx, patch)
        assert score.fallback_validity == 0.95

    def test_fallback_validity_offline(self):
        scorer = EdgeTTSScorer()
        ctx = EdgeTTSSegmentContext(
            segment_id="s1", translation_text="test",
            fallback_reason="offline_mode",
        )
        patch = Patch(
            id="p1", target_id="s1", op=OpCode.UPDATE_TTS_AUDIO,
            value={"duration": 3.0, "availability_score": 0.99, "voice": "zh-CN"},
        )
        score = scorer.score(ctx, patch)
        assert score.fallback_validity == 0.90

    def test_dimension_count(self):
        """Edge TTS 只有 4 个维度（最简）"""
        scorer = EdgeTTSScorer()
        assert len(scorer.weights) == 4
        assert "availability" in scorer.weights
