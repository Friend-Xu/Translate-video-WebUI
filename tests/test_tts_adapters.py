"""
TTS 适配器测试 (Chapter 5 实施验证)

测试 ChatTTSAdapter, DurationController, EmotionModeler, TTSScorer。
使用 mock 数据避免 GPU/模型依赖。
"""
import pytest
from core.adapters.chattts_adapter import ChatTTSAdapter, TTSSegmentContext
from core.tts.duration_control import DurationController, duration_fit_score
from core.tts.emotion import EmotionModeler
from core.scoring.tts_scorer import TTSScorer, TTSScore
from core.runtime.patch import OpCode


class TestTTSSegmentContext:
    """TTSSegmentContext 数据结构验证"""

    def test_defaults(self):
        ctx = TTSSegmentContext(segment_id="seg_001", translation_text="你好")
        assert ctx.segment_id == "seg_001"
        assert ctx.translation_text == "你好"
        assert ctx.emotion_hint == "neutral"
        assert ctx.speaker_id is None

    def test_full_context(self):
        ctx = TTSSegmentContext(
            segment_id="seg_002", translation_text="Hello",
            speaker_id="SPEAKER_00", emotion_hint="angry",
            duration_target=3.42, prev_segment_id="seg_001",
        )
        assert ctx.speaker_id == "SPEAKER_00"
        assert ctx.emotion_hint == "angry"
        assert ctx.duration_target == 3.42


class TestChatTTSAdapter:
    """ChatTTSAdapter 测试（不启动真实引擎）"""

    def test_construct(self):
        adapter = ChatTTSAdapter(speaker_seed=42)
        assert adapter._speaker_seed == 42

    def test_build_refine_prompt_default(self):
        ctx = TTSSegmentContext(segment_id="s1", translation_text="test")
        prompt = ChatTTSAdapter._build_refine_prompt(ctx)
        assert prompt == "[oral_2][laugh_0][break_5]"

    def test_build_refine_prompt_angry(self):
        ctx = TTSSegmentContext(segment_id="s1", translation_text="test",
                                emotion_hint="angry")
        prompt = ChatTTSAdapter._build_refine_prompt(ctx)
        assert "oral_7" in prompt

    def test_build_refine_prompt_sad(self):
        ctx = TTSSegmentContext(segment_id="s1", translation_text="test",
                                emotion_hint="sad")
        prompt = ChatTTSAdapter._build_refine_prompt(ctx)
        assert "oral_1" in prompt

    def test_build_refine_prompt_prosody(self):
        ctx = TTSSegmentContext(segment_id="s1", translation_text="test",
                                prosody_hint={"energy": 0.9, "speed": 0.7})
        prompt = ChatTTSAdapter._build_refine_prompt(ctx)
        assert "oral_8" in prompt

    def test_estimate_confidence_perfect(self):
        ctx = TTSSegmentContext(segment_id="s1", translation_text="test",
                                duration_target=3.0)
        conf = ChatTTSAdapter._estimate_confidence(ctx, 3.0)
        assert conf == 1.0

    def test_estimate_confidence_deviation(self):
        ctx = TTSSegmentContext(segment_id="s1", translation_text="test",
                                duration_target=3.0)
        conf = ChatTTSAdapter._estimate_confidence(ctx, 3.6)
        assert conf == pytest.approx(0.8)


class TestDurationController:
    """DurationController 三级策略验证"""

    def test_accept_within_tolerance(self):
        ctrl = DurationController()
        assert ctrl.check(3.1, 3.0, tolerance=0.15) == "accept"

    def test_stretch_within_level2(self):
        ctrl = DurationController()
        assert ctrl.check(3.5, 3.0, tolerance=0.15) == "stretch"

    def test_split_beyond_level2(self):
        ctrl = DurationController()
        assert ctrl.check(5.0, 3.0, tolerance=0.15) == "split"

    def test_zero_target(self):
        ctrl = DurationController()
        assert ctrl.check(3.0, 0.0) == "accept"

    def test_compute_stretch_ratio(self):
        ctrl = DurationController()
        # TTS=5s longer than target=3s → rate > 1 to speed up
        assert ctrl.compute_stretch_ratio(5.0, 3.0) == pytest.approx(1.667, abs=0.001)

    def test_stretch_ratio_clamped(self):
        ctrl = DurationController()
        # TTS too short (rate → 0.2), clamped to MIN_STRETCH=0.5
        assert ctrl.compute_stretch_ratio(1.0, 5.0) == 0.5
        # TTS way too long (rate → 6.0), clamped to MAX_STRETCH=2.0
        assert ctrl.compute_stretch_ratio(6.0, 1.0) == 2.0

    def test_suggest_split(self):
        ctrl = DurationController()
        parts = ctrl.suggest_split("你好。这是测试。", 1.0)
        assert len(parts) >= 1

    def test_duration_fit_score(self):
        assert duration_fit_score(3.0, 3.0) == 1.0
        assert duration_fit_score(3.3, 3.0) == pytest.approx(0.8)
        assert duration_fit_score(4.5, 3.0) == 0.0


class TestEmotionModeler:
    """EmotionModeler 情绪推断验证"""

    def test_detect_angry(self):
        emotion = EmotionModeler._detect_sentiment("这太可恶了")
        assert emotion == "angry"

    def test_detect_excited(self):
        emotion = EmotionModeler._detect_sentiment("太好了！amazing！")
        assert emotion == "excited"

    def test_detect_neutral(self):
        emotion = EmotionModeler._detect_sentiment("今天天气不错")
        assert emotion is None

    def test_infer_emotion_default(self):
        modeler = EmotionModeler()
        ctx = TTSSegmentContext(segment_id="s1", translation_text="你好")
        result = modeler.infer_emotion(ctx)
        assert result["emotion_hint"] == "neutral"
        assert "prosody" in result

    def test_infer_emotion_from_text(self):
        modeler = EmotionModeler()
        ctx = TTSSegmentContext(segment_id="s1", translation_text="这太可恶了")
        result = modeler.infer_emotion(ctx)
        assert result["emotion_hint"] == "angry"

    def test_to_refine_prompt(self):
        modeler = EmotionModeler()
        prompt = modeler.to_refine_prompt({"emotion_hint": "angry"})
        assert "oral_7" in prompt and "laugh_0" in prompt

    def test_history_baseline(self):
        history = [
            {"speaker_id": "SPK_A", "emotion_hint": "angry"},
            {"speaker_id": "SPK_A", "emotion_hint": "angry"},
        ]
        result = EmotionModeler._get_history_baseline("SPK_A", history)
        assert result == "angry"


class TestTTSScorer:
    """TTSScorer 五维评分验证"""

    def test_perfect_score(self):
        scorer = TTSScorer()
        ctx = TTSSegmentContext(segment_id="s1", translation_text="test",
                                duration_target=3.0, emotion_hint="neutral")

        class FakePatch:
            value = {"duration": 3.0, "emotion_hint": "neutral"}
        score = scorer.score(ctx, FakePatch())
        assert score.composite > 0.9
        assert score.accepted is True

    def test_bad_duration_fit(self):
        scorer = TTSScorer()
        ctx = TTSSegmentContext(segment_id="s1", translation_text="test",
                                duration_target=3.0)

        class FakePatch:
            value = {"duration": 4.5, "emotion_hint": "neutral"}
        score = scorer.score(ctx, FakePatch())
        assert score.duration_fit == 0.0
        assert score.composite < 0.7

    def test_accept_threshold(self):
        assert TTSScore("s1", composite=0.85).accepted is True
        assert TTSScore("s2", composite=0.70).accepted is True
        assert TTSScore("s3", composite=0.69).accepted is False

    def test_weights_sum(self):
        scorer = TTSScorer()
        assert sum(scorer.weights.values()) == 1.0
