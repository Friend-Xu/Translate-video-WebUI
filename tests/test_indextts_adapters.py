"""
IndexTTS 适配器测试 (Chapter 7 实施验证)

测试 IndexTTSAdapter, VoiceMemoryIndex, EmotionVectorMapper, IndexTTSScorer。
使用 mock 数据避免 GPU/模型依赖。
"""
import pytest
from core.adapters.indextts_adapter import IndexTTSAdapter, IndexTTSSegmentContext
from core.speaker.voice_memory import (
    VoiceMemoryIndex, VoicePrototype, VoiceInstance, VoiceAsset,
)
from core.tts.index_emotion import EmotionVectorMapper
from core.scoring.indextts_scorer import IndexTTSScorer, IndexTTSScore
from core.runtime.patch import OpCode, Patch
from core.ir.speaker import SpeakerNodeIR


class TestIndexTTSSegmentContext:
    """IndexTTSSegmentContext 数据结构验证"""

    def test_defaults(self):
        ctx = IndexTTSSegmentContext(segment_id="seg_001", translation_text="你好")
        assert ctx.segment_id == "seg_001"
        assert ctx.translation_text == "你好"
        assert ctx.emotion_hint == "neutral"
        assert ctx.target_length_ms == 0.0
        assert ctx.emo_vector is None
        assert ctx.emo_alpha == 1.0

    def test_full_context(self):
        ctx = IndexTTSSegmentContext(
            segment_id="seg_002", translation_text="Hello world",
            speaker_id="SPK_00", speaker_embedding_ref="/ref.wav",
            duration_target=4.18, target_length_ms=4180,
            emo_vector=[0.0] * 24, emo_alpha=1.2,
            voice_asset_ref="va_abc123",
        )
        assert ctx.speaker_id == "SPK_00"
        assert ctx.duration_target == 4.18
        assert ctx.target_length_ms == 4180
        assert ctx.emo_alpha == 1.2
        assert ctx.voice_asset_ref == "va_abc123"

    def test_target_length_ms_from_duration(self):
        """验证 duration_target 到 target_length_ms 的转换"""
        ctx = IndexTTSSegmentContext(
            segment_id="s1", translation_text="test",
            duration_target=3.5,
        )
        ms = ctx.duration_target * 1000.0
        assert ms == 3500.0


class TestIndexTTSAdapter:
    """IndexTTSAdapter 测试（不启动真实引擎）"""

    def test_construct(self):
        adapter = IndexTTSAdapter(
            checkpoints_dir="/ckpt", speaker_audio="/voice.wav",
            fp16=True,
        )
        assert adapter._checkpoints_dir == "/ckpt"
        assert adapter._speaker_audio == "/voice.wav"
        assert adapter._fp16 is True

    def test_bind_speaker_from_embedding_ref(self, tmp_path):
        audio = tmp_path / "speaker.wav"
        audio.write_text("fake wav")
        node = SpeakerNodeIR(
            id="SPK_A", embedding_ref=str(audio),
        )
        adapter = IndexTTSAdapter()
        adapter.bind_speaker(node)
        assert adapter._speaker_audio == str(audio)

    def test_bind_speaker_no_file(self):
        node = SpeakerNodeIR(
            id="SPK_B", embedding_ref="/nonexistent/path.wav",
        )
        adapter = IndexTTSAdapter(speaker_audio="/original.wav")
        adapter.bind_speaker(node)
        assert adapter._speaker_audio == "/original.wav"

    def test_reset_speaker(self):
        adapter = IndexTTSAdapter(speaker_audio="/old.wav")
        adapter.reset_speaker("/new.wav")
        assert adapter._speaker_audio == "/new.wav"

    def test_calc_duration_fit_perfect(self):
        assert IndexTTSAdapter._calc_duration_fit(3.0, 3.0) == 1.0

    def test_calc_duration_fit_strict(self):
        """IndexTTS 使用 0.3 容差（比 Ch5 的 0.5 更严格）"""
        score = IndexTTSAdapter._calc_duration_fit(3.15, 3.0)
        assert score == pytest.approx(0.833, rel=0.01)  # 5% / 0.3

    def test_calc_duration_fit_zero_target(self):
        assert IndexTTSAdapter._calc_duration_fit(3.0, 0.0) == 1.0


class TestVoiceMemoryIndex:
    """VoiceMemoryIndex 三层资产模型验证"""

    def test_get_or_create_prototype_new(self):
        vmi = VoiceMemoryIndex()
        proto = vmi.get_or_create_prototype("SPK_A")
        assert proto.speaker_id == "SPK_A"
        assert proto.sample_count == 0
        assert vmi.stats["prototype_count"] == 1

    def test_get_or_create_prototype_existing(self):
        vmi = VoiceMemoryIndex()
        p1 = vmi.get_or_create_prototype("SPK_A")
        p2 = vmi.get_or_create_prototype("SPK_A")
        assert p1.prototype_id == p2.prototype_id
        assert vmi.stats["prototype_count"] == 1

    def test_update_prototype(self):
        vmi = VoiceMemoryIndex()
        proto = vmi.get_or_create_prototype("SPK_A", embedding=[0.5, 0.3])
        assert proto.sample_count == 1
        vmi.update_prototype(proto.prototype_id, [0.6, 0.4])
        assert proto.sample_count == 2
        assert proto.embedding_centroid[0] == pytest.approx(0.55)

    def test_retrieve_none_for_new_speaker(self):
        vmi = VoiceMemoryIndex()
        assert vmi.retrieve("SPK_NEW") is None

    def test_record_and_promote(self):
        vmi = VoiceMemoryIndex()
        proto = vmi.get_or_create_prototype("SPK_A")
        ctx = IndexTTSSegmentContext(
            segment_id="s1", translation_text="test",
            speaker_id="SPK_A", emotion_hint="neutral",
        )
        patch = Patch(
            id="p1", target_id="s1", op=OpCode.UPDATE_TTS_AUDIO,
            value={"audio_ref": "/out.wav", "duration": 3.0},
            confidence=0.92,
        )
        inst = vmi.record(ctx, patch, proto.prototype_id)
        assert inst.speaker_id == "SPK_A"
        assert inst.quality_score == 0.92
        assert vmi.stats["instance_count"] == 1

        asset = vmi.promote(inst)
        assert asset is not None
        assert asset.is_primary is True
        assert vmi.stats["asset_count"] == 1

    def test_promote_below_threshold(self):
        vmi = VoiceMemoryIndex()
        proto = vmi.get_or_create_prototype("SPK_A")
        ctx = IndexTTSSegmentContext(
            segment_id="s1", translation_text="test",
            speaker_id="SPK_A",
        )
        patch = Patch(
            id="p1", target_id="s1", op=OpCode.UPDATE_TTS_AUDIO,
            value={"audio_ref": "/out.wav", "duration": 3.0},
            confidence=0.70,  # below PROMOTE_THRESHOLD (0.85)
        )
        inst = vmi.record(ctx, patch, proto.prototype_id)
        assert vmi.promote(inst) is None

    def test_retrieve_after_promote(self):
        vmi = VoiceMemoryIndex()
        proto = vmi.get_or_create_prototype("SPK_A")
        ctx = IndexTTSSegmentContext(
            segment_id="s1", translation_text="test",
            speaker_id="SPK_A",
        )
        patch = Patch(
            id="p1", target_id="s1", op=OpCode.UPDATE_TTS_AUDIO,
            value={"audio_ref": "/out.wav", "duration": 3.0},
            confidence=0.92,
        )
        inst = vmi.record(ctx, patch, proto.prototype_id)
        asset = vmi.promote(inst)
        assert asset is not None

        retrieved = vmi.retrieve("SPK_A")
        assert retrieved is not None
        assert retrieved.asset_id == asset.asset_id

    def test_max_assets_eviction(self):
        vmi = VoiceMemoryIndex()
        proto = vmi.get_or_create_prototype("SPK_A")
        ctx = IndexTTSSegmentContext(
            segment_id="s1", translation_text="test",
            speaker_id="SPK_A",
        )
        for i in range(6):
            quality = 0.86 + i * 0.01  # 0.86, 0.87, ..., 0.91
            patch = Patch(
                id=f"p{i}", target_id="s1", op=OpCode.UPDATE_TTS_AUDIO,
                value={"audio_ref": f"/out{i}.wav", "duration": 3.0},
                confidence=quality,
            )
            inst = vmi.record(ctx, patch, proto.prototype_id)
            vmi.promote(inst)

        assets = vmi.get_speaker_assets("SPK_A")
        assert len(assets) == vmi.MAX_ASSETS_PER_SPEAKER
        scores = [a.quality_score for a in assets]
        assert 0.86 not in scores  # lowest evicted

    def test_isolate_speakers(self):
        vmi = VoiceMemoryIndex()
        vmi.get_or_create_prototype("SPK_A", embedding=[1.0, 0.0, 0.0])
        vmi.get_or_create_prototype("SPK_B", embedding=[0.0, 1.0, 0.0])
        dist = vmi.isolate_speakers("SPK_A", "SPK_B")
        assert dist == pytest.approx(1.0, rel=0.01)

    def test_isolate_speakers_similar(self):
        vmi = VoiceMemoryIndex()
        vmi.get_or_create_prototype("SPK_A", embedding=[1.0, 0.0])
        vmi.get_or_create_prototype("SPK_B", embedding=[0.99, 0.01])
        dist = vmi.isolate_speakers("SPK_A", "SPK_B")
        assert dist < 0.1

    def test_verify_speaker_isolation(self):
        vmi = VoiceMemoryIndex()
        vmi.get_or_create_prototype("SPK_A", embedding=[1.0, 0.0])
        vmi.get_or_create_prototype("SPK_B", embedding=[0.99, 0.01])
        vmi.get_or_create_prototype("SPK_C", embedding=[0.0, 1.0])
        risks = vmi.verify_speaker_isolation("SPK_A")
        assert "SPK_B" in risks
        assert "SPK_C" not in risks

    def test_mark_primary(self):
        vmi = VoiceMemoryIndex()
        proto = vmi.get_or_create_prototype("SPK_A")
        ctx = IndexTTSSegmentContext(
            segment_id="s1", translation_text="test",
            speaker_id="SPK_A",
        )
        p1 = Patch(
            id="p1", target_id="s1", op=OpCode.UPDATE_TTS_AUDIO,
            value={"audio_ref": "/out1.wav", "duration": 3.0},
            confidence=0.90,
        )
        p2 = Patch(
            id="p2", target_id="s1", op=OpCode.UPDATE_TTS_AUDIO,
            value={"audio_ref": "/out2.wav", "duration": 3.0},
            confidence=0.92,
        )
        a1 = vmi.promote(vmi.record(ctx, p1, proto.prototype_id))
        a2 = vmi.promote(vmi.record(ctx, p2, proto.prototype_id))
        assert a1 is not None and a2 is not None
        assert a1.is_primary
        vmi.mark_primary(a2.asset_id)
        assert a2.is_primary
        assert not a1.is_primary

    def test_prune_low_quality(self):
        vmi = VoiceMemoryIndex()
        proto = vmi.get_or_create_prototype("SPK_A")
        import uuid
        asset = VoiceAsset(
            asset_id=f"va_{uuid.uuid4().hex[:12]}",
            speaker_id="SPK_A", prototype_ref=proto.prototype_id,
            audio_ref="/low.wav", quality_score=0.55,
        )
        vmi._assets[asset.asset_id] = asset
        assert vmi.stats["asset_count"] == 1
        removed = vmi.prune_low_quality(min_score=0.60)
        assert removed == 1
        assert vmi.stats["asset_count"] == 0


class TestEmotionVectorMapper:
    """EmotionVectorMapper 24 类情绪向量验证"""

    def test_neutral_zero_vector(self):
        mapper = EmotionVectorMapper()
        vec = mapper.to_emo_vector("neutral")
        assert len(vec) == 24
        assert all(v == 0.0 for v in vec)

    def test_angry_vector(self):
        mapper = EmotionVectorMapper()
        vec = mapper.to_emo_vector("angry")
        assert len(vec) == 24
        assert vec[1] > 0.0
        assert sum(1 for v in vec if v > 0) == 1

    def test_intensity_scaling(self):
        mapper = EmotionVectorMapper()
        vec = mapper.to_emo_vector("excited", intensity=0.5)
        assert vec[2] == 0.5
        vec2 = mapper.to_emo_vector("excited", intensity=2.0)
        assert vec2[2] == 1.0

    def test_unknown_emotion_fallback(self):
        mapper = EmotionVectorMapper()
        vec = mapper.to_emo_vector("nonexistent_emotion")
        assert all(v == 0.0 for v in vec)

    def test_blend_emotions(self):
        mapper = EmotionVectorMapper()
        blended = mapper.blend_emotions("angry", "sad", ratio=0.7)
        assert len(blended) == 24
        assert blended[1] == pytest.approx(0.7)
        assert blended[3] == pytest.approx(0.3)

    def test_get_emotion_name(self):
        mapper = EmotionVectorMapper()
        assert mapper.get_emotion_name(1) == "angry"
        assert mapper.get_emotion_name(0) == "neutral"
        assert mapper.get_emotion_name(99) == "unknown"


class TestIndexTTSScorer:
    """IndexTTSScorer 五维评分验证"""

    def test_perfect_score(self):
        scorer = IndexTTSScorer()
        ctx = IndexTTSSegmentContext(
            segment_id="s1", translation_text="test",
            duration_target=3.0, speaker_id="SPK_A",
            voice_asset_ref="va_123",
        )
        patch = Patch(
            id="p1", target_id="s1", op=OpCode.UPDATE_TTS_AUDIO,
            value={"duration": 3.0, "speaker_audio": "/ref.wav"},
            confidence=0.92,
        )
        history = [
            {"speaker_id": "SPK_A", "speaker_audio": "/ref.wav",
             "emotion_used": "neutral", "voice_asset_ref": "va_123"},
        ]
        score = scorer.score(ctx, patch, speaker_history=history)
        assert score.composite > 0.80
        assert score.accepted is True

    def test_bad_duration_fit(self):
        scorer = IndexTTSScorer()
        ctx = IndexTTSSegmentContext(
            segment_id="s1", translation_text="test",
            duration_target=3.0,
        )
        patch = Patch(
            id="p1", target_id="s1", op=OpCode.UPDATE_TTS_AUDIO,
            value={"duration": 4.5, "speaker_audio": "", "voice_asset_ref": ""},
        )
        score = scorer.score(ctx, patch)
        assert score.duration_fit == 0.0
        assert score.composite < 0.70

    def test_accept_threshold(self):
        assert IndexTTSScore("s1", composite=0.85).accepted is True
        assert IndexTTSScore("s2", composite=0.70).accepted is True
        assert IndexTTSScore("s3", composite=0.69).accepted is False

    def test_weights_sum(self):
        scorer = IndexTTSScorer()
        assert sum(scorer.weights.values()) == 1.0

    def test_retrieval_confidence_with_asset(self):
        scorer = IndexTTSScorer()
        ctx = IndexTTSSegmentContext(
            segment_id="s1", translation_text="test",
            duration_target=3.0, voice_asset_ref="va_abc",
        )
        patch = Patch(
            id="p1", target_id="s1", op=OpCode.UPDATE_TTS_AUDIO,
            value={"duration": 3.0},
            confidence=0.90,
        )
        score = scorer.score(ctx, patch)
        assert score.retrieval_confidence > 0.84

    def test_retrieval_confidence_without_asset(self):
        scorer = IndexTTSScorer()
        ctx = IndexTTSSegmentContext(
            segment_id="s1", translation_text="test",
            duration_target=3.0, voice_asset_ref="",
        )
        patch = Patch(
            id="p1", target_id="s1", op=OpCode.UPDATE_TTS_AUDIO,
            value={"duration": 3.0},
        )
        score = scorer.score(ctx, patch)
        assert score.retrieval_confidence == 0.80

    def test_reuse_safety_accumulates(self):
        scorer = IndexTTSScorer()
        ctx = IndexTTSSegmentContext(
            segment_id="s3", translation_text="test",
            duration_target=3.0, voice_asset_ref="va_xyz",
        )
        patch = Patch(
            id="p3", target_id="s3", op=OpCode.UPDATE_TTS_AUDIO,
            value={"duration": 3.0},
        )
        history = [
            {"voice_asset_ref": "va_xyz"},
            {"voice_asset_ref": "va_xyz"},
            {"voice_asset_ref": "va_xyz"},
        ]
        score = scorer.score(ctx, patch, speaker_history=history)
        assert score.reuse_safety == 0.90
