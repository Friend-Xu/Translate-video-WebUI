"""
OpenVoice 适配器测试 (Chapter 8 实施验证)

测试 OpenVoiceTransferAdapter, FallbackDecider, OpenVoiceScorer。
使用 mock 数据避免 GPU/模型依赖。
"""
import pytest
from core.adapters.openvoice_adapter import (
    OpenVoiceTransferAdapter, OpenVoiceTransferContext,
)
from core.tts.fallback_decider import FallbackDecider, FallbackDecision
from core.scoring.openvoice_scorer import OpenVoiceScorer, OpenVoiceScore
from core.runtime.patch import OpCode, Patch


class TestOpenVoiceTransferContext:
    """OpenVoiceTransferContext 数据结构验证"""

    def test_defaults(self):
        ctx = OpenVoiceTransferContext(
            segment_id="seg_001", source_audio_ref="/tts/audio.wav",
        )
        assert ctx.segment_id == "seg_001"
        assert ctx.source_audio_ref == "/tts/audio.wav"
        assert ctx.fallback_reason == ""
        assert ctx.speaker_id is None

    def test_full_context_primary_low_confidence(self):
        ctx = OpenVoiceTransferContext(
            segment_id="seg_002", source_audio_ref="/tts/audio.wav",
            speaker_id="SPK_01", reference_audio_ref="/ref/speaker.wav",
            speaker_embedding_ref="/emb/SPK_01.pt",
            duration_target=2.84,
            fallback_reason="primary_low_confidence",
        )
        assert ctx.speaker_id == "SPK_01"
        assert ctx.reference_audio_ref == "/ref/speaker.wav"
        assert ctx.fallback_reason == "primary_low_confidence"
        assert ctx.duration_target == 2.84

    def test_fallback_reason_enums(self):
        """验证 fallback_reason 枚举值"""
        reasons = [
            "primary_low_confidence",
            "primary_timeout",
            "primary_resource_unavailable",
            "quick_fix",
            "low_priority_segment",
        ]
        for reason in reasons:
            ctx = OpenVoiceTransferContext(
                segment_id="s1", source_audio_ref="/t.wav",
                fallback_reason=reason,
            )
            assert ctx.fallback_reason == reason


class TestFallbackDecider:
    """FallbackDecider 降级决策验证"""

    def test_primary_error_triggers_immediate(self):
        decider = FallbackDecider()
        d = decider.decide(primary_error="worker crash")
        assert d.should_fallback is True
        assert d.reason == "primary_error"
        assert d.urgency == "immediate"

    def test_low_confidence_triggers_immediate(self):
        decider = FallbackDecider()
        d = decider.decide(primary_score=0.50)
        assert d.should_fallback is True
        assert d.reason == "primary_low_confidence"
        assert d.urgency == "immediate"

    def test_marginal_confidence_triggers_normal(self):
        decider = FallbackDecider()
        d = decider.decide(primary_score=0.67)
        assert d.should_fallback is True
        assert d.reason == "primary_marginal"
        assert d.urgency == "normal"

    def test_high_confidence_no_fallback(self):
        decider = FallbackDecider()
        d = decider.decide(primary_score=0.85)
        assert d.should_fallback is False
        assert d.reason == "no_trigger_condition"

    def test_quick_fix_triggers_normal(self):
        decider = FallbackDecider()
        d = decider.decide(primary_score=0.85, is_quick_fix=True)
        assert d.should_fallback is True
        assert d.reason == "quick_fix"
        assert d.urgency == "normal"

    def test_low_priority_triggers_optional(self):
        decider = FallbackDecider()
        d = decider.decide(primary_score=0.85, is_low_priority=True)
        assert d.should_fallback is True
        assert d.reason == "low_priority_segment"
        assert d.urgency == "optional"

    def test_max_fallback_ratio_exceeded(self):
        decider = FallbackDecider()
        d = decider.decide(
            primary_error="crash",
            fallback_count=4, total_segments=10,  # 40% > 30%
        )
        assert d.should_fallback is False
        assert d.reason == "fallback_ratio_exceeded"

    def test_max_fallback_ratio_within_limit(self):
        decider = FallbackDecider()
        d = decider.decide(
            primary_error="crash",
            fallback_count=2, total_segments=10,  # 20% < 30%
        )
        assert d.should_fallback is True

    def test_should_replace_fallback(self):
        decider = FallbackDecider()
        assert decider.should_replace_fallback(new_primary_available=True) is True
        assert decider.should_replace_fallback(new_primary_available=False) is False

    def test_error_takes_priority_over_score(self):
        """主引擎错误优先级高于评分"""
        decider = FallbackDecider()
        d = decider.decide(primary_score=0.85, primary_error="OOM")
        assert d.should_fallback is True
        assert d.reason == "primary_error"


class TestOpenVoiceScorer:
    """OpenVoiceScorer 五维评分验证"""

    def test_perfect_score(self):
        scorer = OpenVoiceScorer()
        ctx = OpenVoiceTransferContext(
            segment_id="s1", source_audio_ref="/t.wav",
            speaker_id="SPK_A", duration_target=3.0,
            fallback_reason="primary_low_confidence",
        )
        patch = Patch(
            id="p1", target_id="s1", op=OpCode.UPDATE_TTS_AUDIO,
            value={
                "duration": 3.0, "transfer_score": 0.85,
                "engine": "openvoice", "generation_mode": "fallback",
            },
        )
        score = scorer.score(ctx, patch)
        assert score.composite > 0.70
        assert score.accepted is True

    def test_transfer_failed_zero_score(self):
        scorer = OpenVoiceScorer()
        ctx = OpenVoiceTransferContext(
            segment_id="s1", source_audio_ref="/t.wav",
            fallback_reason="primary_low_confidence",
        )
        patch = Patch(
            id="p1", target_id="s1", op=OpCode.UPDATE_TTS_AUDIO,
            value={"transfer_status": "failed"},
        )
        score = scorer.score(ctx, patch)
        assert score.composite == 0.0
        assert score.accepted is False

    def test_accept_threshold(self):
        """OpenVoice 使用 0.60 阈值（低于主引擎的 0.70）"""
        assert OpenVoiceScore("s1", composite=0.65).accepted is True
        assert OpenVoiceScore("s2", composite=0.60).accepted is True
        assert OpenVoiceScore("s3", composite=0.59).accepted is False

    def test_weights_sum(self):
        scorer = OpenVoiceScorer()
        assert sum(scorer.weights.values()) == 1.0

    def test_fallback_validity_immediate(self):
        scorer = OpenVoiceScorer()
        ctx = OpenVoiceTransferContext(
            segment_id="s1", source_audio_ref="/t.wav",
            fallback_reason="primary_low_confidence",
        )
        patch = Patch(
            id="p1", target_id="s1", op=OpCode.UPDATE_TTS_AUDIO,
            value={
                "duration": 3.0, "transfer_score": 0.79,
                "engine": "openvoice",
            },
        )
        score = scorer.score(ctx, patch)
        assert score.fallback_validity == 0.92

    def test_fallback_validity_optional(self):
        scorer = OpenVoiceScorer()
        ctx = OpenVoiceTransferContext(
            segment_id="s1", source_audio_ref="/t.wav",
            fallback_reason="low_priority_segment",
        )
        patch = Patch(
            id="p1", target_id="s1", op=OpCode.UPDATE_TTS_AUDIO,
            value={
                "duration": 3.0, "transfer_score": 0.79,
                "engine": "openvoice",
            },
        )
        score = scorer.score(ctx, patch)
        assert score.fallback_validity == 0.78

    def test_duration_fit_inherited(self):
        """音色迁移不改时长，duration_fit 通常高分"""
        scorer = OpenVoiceScorer()
        ctx = OpenVoiceTransferContext(
            segment_id="s1", source_audio_ref="/t.wav",
            duration_target=3.0, fallback_reason="quick_fix",
        )
        patch = Patch(
            id="p1", target_id="s1", op=OpCode.UPDATE_TTS_AUDIO,
            value={
                "duration": 3.05, "transfer_score": 0.79,
                "engine": "openvoice",
            },
        )
        score = scorer.score(ctx, patch)
        assert score.duration_fit > 0.90

    def test_speaker_match_with_history(self):
        scorer = OpenVoiceScorer()
        ctx = OpenVoiceTransferContext(
            segment_id="s2", source_audio_ref="/t.wav",
            speaker_id="SPK_A", reference_audio_ref="/ref.wav",
            fallback_reason="primary_marginal",
        )
        patch = Patch(
            id="p2", target_id="s2", op=OpCode.UPDATE_TTS_AUDIO,
            value={
                "duration": 3.0, "transfer_score": 0.79,
                "engine": "openvoice",
            },
        )
        history = [
            {"speaker_id": "SPK_A", "reference_audio": "/ref.wav"},
            {"speaker_id": "SPK_A", "reference_audio": "/ref.wav"},
        ]
        score = scorer.score(ctx, patch, transfer_history=history)
        assert score.speaker_match == 0.90
