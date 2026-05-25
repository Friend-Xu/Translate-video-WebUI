"""
CosyVoice 适配器测试 (Chapter 6 实施验证)

测试 CosyVoiceAdapter, CosyVoiceDurationController, CrossLingualProcessor, CosyVoiceScorer。
使用 mock 数据避免 GPU/模型依赖。
"""
import pytest
from core.adapters.cosyvoice_adapter import CosyVoiceAdapter, CosyVoiceSegmentContext
from core.tts.cosyvoice_duration import (
    CosyVoiceDurationController, estimate_tts_duration, LANG_CPS,
)
from core.tts.cross_lingual import CrossLingualProcessor
from core.scoring.cosyvoice_scorer import CosyVoiceScorer, CosyVoiceScore
from core.runtime.patch import OpCode, Patch
from core.ir.speaker import SpeakerNodeIR


class TestCosyVoiceSegmentContext:
    """CosyVoiceSegmentContext 数据结构验证"""

    def test_defaults(self):
        ctx = CosyVoiceSegmentContext(segment_id="seg_001", translation_text="你好")
        assert ctx.segment_id == "seg_001"
        assert ctx.translation_text == "你好"
        assert ctx.emotion_hint == "neutral"
        assert ctx.speaker_id is None
        assert ctx.lang == ""
        assert ctx.speed == 1.0
        assert ctx.model_version == "v2"
        assert ctx.mode == "cross_lingual"

    def test_full_context_cross_lingual(self):
        ctx = CosyVoiceSegmentContext(
            segment_id="seg_002", translation_text="Hello world",
            speaker_id="SPEAKER_00", speaker_embedding_ref="/path/to/prompt.wav",
            prompt_text="你好，这是我的声音",
            duration_target=3.42, lang="en", model_version="v3",
            speed=0.95, mode="cross_lingual",
        )
        assert ctx.speaker_id == "SPEAKER_00"
        assert ctx.speaker_embedding_ref == "/path/to/prompt.wav"
        assert ctx.prompt_text == "你好，这是我的声音"
        assert ctx.duration_target == 3.42
        assert ctx.lang == "en"
        assert ctx.model_version == "v3"
        assert ctx.speed == 0.95

    def test_speed_clamped(self):
        """speed 应在构造时由 adapter 内部 clamp，context 不做 clamp"""
        ctx = CosyVoiceSegmentContext(
            segment_id="s1", translation_text="test",
            speed=3.0,
        )
        assert ctx.speed == 3.0  # context 不做 clamp


class TestCosyVoiceAdapter:
    """CosyVoiceAdapter 测试（不启动真实引擎）"""

    def test_construct(self):
        adapter = CosyVoiceAdapter(model_version="v3", fp16=True,
                                   prompt_audio="/ref.wav")
        assert adapter._model_version == "v3"
        assert adapter._fp16 is True
        assert adapter._prompt_audio == "/ref.wav"

    def test_construct_default_speed_clamped(self):
        adapter = CosyVoiceAdapter(default_speed=3.0)
        assert adapter._default_speed == 2.0  # clamp to max
        adapter2 = CosyVoiceAdapter(default_speed=0.1)
        assert adapter2._default_speed == 0.5  # clamp to min

    def test_speed_to_rate_str_positive(self):
        assert CosyVoiceAdapter._speed_to_rate_str(1.1) == "+10%"
        assert CosyVoiceAdapter._speed_to_rate_str(1.0) == "+0%"
        assert CosyVoiceAdapter._speed_to_rate_str(1.5) == "+50%"

    def test_speed_to_rate_str_negative(self):
        assert CosyVoiceAdapter._speed_to_rate_str(0.9) == "-10%"
        assert CosyVoiceAdapter._speed_to_rate_str(0.75) == "-25%"

    def test_normalize_lang_valid(self):
        assert CosyVoiceAdapter._normalize_lang("zh") == "zh"
        assert CosyVoiceAdapter._normalize_lang("en") == "en"
        assert CosyVoiceAdapter._normalize_lang("ja") == "ja"

    def test_normalize_lang_with_dash(self):
        assert CosyVoiceAdapter._normalize_lang("zh-CN") == "zh"
        assert CosyVoiceAdapter._normalize_lang("en-US") == "en"

    def test_normalize_lang_invalid(self):
        assert CosyVoiceAdapter._normalize_lang("fr") == ""
        assert CosyVoiceAdapter._normalize_lang("") == ""

    def test_bind_speaker_from_embedding_ref(self, tmp_path):
        """bind_speaker 从 SpeakerNodeIR.embedding_ref 读取 prompt 音频"""
        audio = tmp_path / "speaker.wav"
        audio.write_text("fake wav")
        node = SpeakerNodeIR(
            id="SPK_A", embedding_ref=str(audio),
            voice_style="calm",
        )
        adapter = CosyVoiceAdapter()
        adapter.bind_speaker(node)
        assert adapter._prompt_audio == str(audio)
        assert adapter._prompt_text == "calm"

    def test_bind_speaker_no_file(self):
        """embedding_ref 指向不存在的文件，不更新 prompt_audio"""
        node = SpeakerNodeIR(
            id="SPK_B",
            embedding_ref="/nonexistent/path.wav",
        )
        adapter = CosyVoiceAdapter(prompt_audio="/original.wav")
        adapter.bind_speaker(node)
        assert adapter._prompt_audio == "/original.wav"

    def test_reset_speaker(self):
        adapter = CosyVoiceAdapter(prompt_audio="/old.wav")
        adapter.reset_speaker("/new.wav", "new text")
        assert adapter._prompt_audio == "/new.wav"
        assert adapter._prompt_text == "new text"

    def test_calc_duration_fit_perfect(self):
        assert CosyVoiceAdapter._calc_duration_fit(3.0, 3.0) == 1.0

    def test_calc_duration_fit_deviation(self):
        score = CosyVoiceAdapter._calc_duration_fit(3.15, 3.0)
        assert score == pytest.approx(0.9)  # 5% dev → 1.0 - 0.05/0.5 = 0.9

    def test_calc_duration_fit_zero_target(self):
        assert CosyVoiceAdapter._calc_duration_fit(3.0, 0.0) == 1.0


class TestCosyVoiceDurationController:
    """CosyVoiceDurationController 四级策略验证"""

    def test_compute_speed_perfect(self):
        ctrl = CosyVoiceDurationController()
        assert ctrl.compute_speed(3.0, 3.0) == 1.0

    def test_compute_speed_faster(self):
        ctrl = CosyVoiceDurationController()
        speed = ctrl.compute_speed(4.0, 3.0)  # estimated > target, need faster
        assert speed == 0.75  # 3/4 = 0.75

    def test_compute_speed_slower(self):
        ctrl = CosyVoiceDurationController()
        speed = ctrl.compute_speed(2.0, 3.0)  # estimated < target, need slower
        assert speed == 1.5  # 3/2 = 1.5

    def test_compute_speed_clamped_max(self):
        ctrl = CosyVoiceDurationController()
        speed = ctrl.compute_speed(1.0, 5.0)
        assert speed == 2.0  # clamped to MAX_SPEED

    def test_compute_speed_clamped_min(self):
        ctrl = CosyVoiceDurationController()
        speed = ctrl.compute_speed(10.0, 1.0)
        assert speed == 0.5  # clamped to MIN_SPEED

    def test_compute_speed_zero(self):
        ctrl = CosyVoiceDurationController()
        assert ctrl.compute_speed(0, 3.0) == 1.0
        assert ctrl.compute_speed(3.0, 0) == 1.0

    def test_check_accept(self):
        ctrl = CosyVoiceDurationController()
        assert ctrl.check(3.1, 3.0, tolerance=0.15) == "accept"

    def test_check_retry_with_speed(self):
        ctrl = CosyVoiceDurationController()
        assert ctrl.check(3.6, 3.0, tolerance=0.10) == "retry_with_speed"

    def test_check_split(self):
        ctrl = CosyVoiceDurationController()
        assert ctrl.check(5.0, 3.0, tolerance=0.15) == "split"

    def test_check_zero_target(self):
        ctrl = CosyVoiceDurationController()
        assert ctrl.check(3.0, 0.0) == "accept"

    def test_compute_retry_speed(self):
        ctrl = CosyVoiceDurationController()
        assert ctrl.compute_retry_speed(3.6, 3.0) == pytest.approx(0.833, rel=0.01)

    def test_estimate_duration_zh(self):
        ctrl = CosyVoiceDurationController()
        dur = ctrl.estimate_duration("今天天气不错", speed=1.0, lang="zh")
        assert dur == pytest.approx(1.5, rel=0.1)  # 6 chars / 4 cps = 1.5

    def test_estimate_duration_with_speed(self):
        ctrl = CosyVoiceDurationController()
        dur = ctrl.estimate_duration("Hello world", speed=2.0, lang="en")
        assert dur == pytest.approx(0.55, rel=0.1)  # 11 / 10 / 2 = 0.55

    def test_estimate_duration_empty(self):
        ctrl = CosyVoiceDurationController()
        assert ctrl.estimate_duration("", lang="zh") == 0.0


class TestEstimateTtsDuration:
    """estimate_tts_duration 独立函数验证"""

    def test_zh(self):
        assert estimate_tts_duration("测试文本", "zh") == pytest.approx(1.0, rel=0.1)

    def test_en(self):
        dur = estimate_tts_duration("Hello world test", "en")
        assert dur == pytest.approx(1.6, rel=0.1)  # 16 / 10

    def test_unknown_lang_fallback(self):
        dur = estimate_tts_duration("Test", "fr")
        assert dur == pytest.approx(0.8, rel=0.1)  # fallback to 5 cps

    def test_empty(self):
        assert estimate_tts_duration("", "zh") == 0.0


class TestCrossLingualProcessor:
    """CrossLingualProcessor 语言标签管理验证"""

    def test_normalize_lang_valid(self):
        clp = CrossLingualProcessor()
        assert clp.normalize_lang("zh") == "zh"
        assert clp.normalize_lang("EN") == "en"
        assert clp.normalize_lang("Ja") == "ja"

    def test_normalize_lang_with_region(self):
        clp = CrossLingualProcessor()
        assert clp.normalize_lang("zh-CN") == "zh"
        assert clp.normalize_lang("en_US") == "en"

    def test_normalize_lang_invalid(self):
        clp = CrossLingualProcessor()
        assert clp.normalize_lang("fr") == ""
        assert clp.normalize_lang("") == ""

    def test_build_tagged_text_v3(self):
        clp = CrossLingualProcessor()
        result = clp.build_tagged_text("今天天气不错", "zh", model_version="v3")
        assert "<|zh|>" in result
        assert "<|endofprompt|>" in result
        assert "今天天气不错" in result
        assert result.startswith("You are a helpful assistant.")

    def test_build_tagged_text_v2(self):
        clp = CrossLingualProcessor()
        result = clp.build_tagged_text("今天天气不错", "zh", model_version="v2")
        assert result == "<|zh|>今天天气不错"

    def test_build_tagged_text_no_lang(self):
        clp = CrossLingualProcessor()
        result = clp.build_tagged_text("Hello", "", model_version="v3")
        assert "<|endofprompt|>" in result
        assert "Hello" in result

    def test_is_valid_lang(self):
        clp = CrossLingualProcessor()
        assert clp.is_valid_lang("zh") is True
        assert clp.is_valid_lang("fr") is False

    def test_get_language_pair_constraints_same(self):
        clp = CrossLingualProcessor()
        c = clp.get_language_pair_constraints("zh", "zh")
        assert c["speed_default"] == 1.0

    def test_get_language_pair_constraints_cross(self):
        clp = CrossLingualProcessor()
        c = clp.get_language_pair_constraints("zh", "en")
        assert 0.8 < c["speed_default"] < 1.0

    def test_get_language_pair_constraints_unknown(self):
        clp = CrossLingualProcessor()
        c = clp.get_language_pair_constraints("zh", "fr")
        assert c["speed_default"] == 1.0


class TestCosyVoiceScorer:
    """CosyVoiceScorer 五维评分验证"""

    def test_perfect_score(self):
        scorer = CosyVoiceScorer()
        ctx = CosyVoiceSegmentContext(
            segment_id="s1", translation_text="test",
            duration_target=3.0, lang="zh", mode="cross_lingual",
        )
        patch = Patch(
            id="p1", target_id="s1", op=OpCode.UPDATE_TTS_AUDIO,
            value={"duration": 3.0, "prompt_audio": "/ref.wav",
                   "lang": "zh", "mode": "cross_lingual", "speed": 1.0},
        )
        score = scorer.score(ctx, patch)
        assert score.composite > 0.85
        assert score.accepted is True

    def test_bad_duration_fit(self):
        scorer = CosyVoiceScorer()
        ctx = CosyVoiceSegmentContext(
            segment_id="s1", translation_text="test",
            duration_target=3.0,
        )
        patch = Patch(
            id="p1", target_id="s1", op=OpCode.UPDATE_TTS_AUDIO,
            value={"duration": 4.5, "prompt_audio": "", "lang": "", "mode": "", "speed": 1.0},
        )
        score = scorer.score(ctx, patch)
        assert score.duration_fit == 0.0
        assert score.composite < 0.7

    def test_accept_threshold(self):
        assert CosyVoiceScore("s1", composite=0.85).accepted is True
        assert CosyVoiceScore("s2", composite=0.70).accepted is True
        assert CosyVoiceScore("s3", composite=0.69).accepted is False

    def test_weights_sum(self):
        scorer = CosyVoiceScorer()
        assert sum(scorer.weights.values()) == 1.0

    def test_speaker_match_with_history(self):
        scorer = CosyVoiceScorer()
        ctx = CosyVoiceSegmentContext(
            segment_id="s1", translation_text="test",
            speaker_id="SPK_A", duration_target=3.0,
        )
        patch = Patch(
            id="p1", target_id="s1", op=OpCode.UPDATE_TTS_AUDIO,
            value={"duration": 3.0, "prompt_audio": "/ref.wav",
                   "lang": "", "mode": "", "speed": 1.0},
        )
        history = [
            {"speaker_id": "SPK_A", "prompt_audio": "/ref.wav"},
            {"speaker_id": "SPK_A", "prompt_audio": "/ref.wav"},
        ]
        score = scorer.score(ctx, patch, speaker_history=history)
        assert score.speaker_match > 0.90

    def test_segment_continuity_speed_drift(self):
        scorer = CosyVoiceScorer()
        ctx = CosyVoiceSegmentContext(
            segment_id="s2", translation_text="test",
            duration_target=3.0, speed=1.5,
        )
        patch = Patch(
            id="p2", target_id="s2", op=OpCode.UPDATE_TTS_AUDIO,
            value={"duration": 3.0, "prompt_audio": "", "lang": "zh",
                   "mode": "", "speed": 1.5},
        )
        history = [{"speed": 1.0, "lang": "zh"}]  # large speed jump
        score = scorer.score(ctx, patch, speaker_history=history)
        assert score.segment_continuity < 1.0  # penalized for speed drift
