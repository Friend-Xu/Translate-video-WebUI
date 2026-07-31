"""
IR v2.1 新功能测试 (Chapter 2 实施验证)

测试九语义槽位、Timeline 中间层、版本系统、状态分类。
"""
import pytest
from core.ir.timeline_event import TimelineEventIR
from core.ir.speaker import SpeakerNodeIR
from core.ir.project import TimelineProjectIR
from core.ir.version import SCHEMA_VERSION, IR_VERSION, PATCH_VERSION, check_schema_compatible
from core.runtime.event_state import TimelineEventState
from core.runtime.project_state import TimelineProjectState
from core.runtime.patch import Patch, OpCode
from core.runtime.synthesis import SynthesisEngine


class TestNineSlots:
    """槽位默认值验证 (Phase 3A: 类型化对象, audio 死槽已删)"""

    def test_all_slots_default_empty(self):
        es = TimelineEventState(TimelineEventIR(
            id="e1", start=0, end=1, text_ref="hello", speaker_ref=None,
        ))
        assert es.asr.words == []
        assert es.speaker.speaker_id is None
        assert es.semantic.embedding_ref == ""
        assert es.translation.text == ""
        assert es.tts.audio_ref == ""
        assert es.review.review_status == "pending"
        assert es.runtime.tts_status == ""
        assert es.provenance == {}
        # audio 是死槽 (Phase 3b 上移项目级), 不应存在
        assert not hasattr(es, "audio")

    def test_slot_lazy_init(self):
        es = TimelineEventState(TimelineEventIR(
            id="e1", start=0, end=1, text_ref="hello", speaker_ref=None,
        ))
        es.translation.text = "hola"
        assert es.translation.text == "hola"

    def test_meta_lineage_slot(self):
        """Phase 3B: 血缘元数据走 meta, 不污染槽位容器自由键。"""
        es = TimelineEventState(TimelineEventIR(
            id="e1", start=0, end=1, text_ref="hello", speaker_ref=None,
        ))
        es.meta["merged_from"] = ["e0"]
        assert es.meta["merged_from"] == ["e0"]
        assert "meta" in es._data


class TestSpeakerV21:
    """SpeakerNodeIR v2.1 新字段"""

    def test_new_fields_default_none(self):
        spk = SpeakerNodeIR(id="SPK_01", name="主持人")
        assert spk.embedding_ref is None
        assert spk.gender_prob is None
        assert spk.voice_style is None
        assert spk.confidence is None

    def test_new_fields_set(self):
        spk = SpeakerNodeIR(
            id="SPK_01", name="主持人",
            embedding_ref="/path/emb.npy", gender_prob=0.92,
            voice_style="neutral", confidence=0.88,
        )
        assert spk.embedding_ref == "/path/emb.npy"
        assert spk.gender_prob == 0.92
        assert spk.voice_style == "neutral"
        assert spk.confidence == 0.88

    def test_old_constructor_still_works(self):
        spk = SpeakerNodeIR(id="SPK_00")
        assert spk.name is None
        assert spk.embedding_ref is None

    def test_frozen_with_new_fields(self):
        spk = SpeakerNodeIR(id="SPK_01", embedding_ref="/path")
        with pytest.raises(Exception):
            spk.embedding_ref = "/new"


class TestOpCodeEnum:
    """OpCode 枚举验证"""

    def test_all_opcodes_defined(self):
        assert len(OpCode) >= 11

    def test_backward_compat_aliases(self):
        assert OpCode.MERGE == "merge"
        assert OpCode.SPLIT == "split"
        assert OpCode.REPLACE == "replace"
        assert OpCode.PROPAGATE == "propagate"

    def test_new_opcodes(self):
        assert OpCode.SEGMENT_INSERT == "segment_insert"
        assert OpCode.UPDATE_TRANSCRIPTION == "update_transcription"
        assert OpCode.UPDATE_TTS_AUDIO == "update_tts_audio"
        assert OpCode.UPDATE_TRANSLATION == "update_translation"

    def test_str_compare_works(self):
        p = Patch(id="p1", target_id="e1", op="merge", value={})
        assert p.op == "merge"
        assert p.op == OpCode.MERGE

    def test_new_op_construct(self):
        p = Patch(id="p1", target_id="e1", op=OpCode.UPDATE_TRANSCRIPTION, value={"text": "hi"})
        assert p.op == "update_transcription"

    def test_protocol_version(self):
        assert Patch.PROTOCOL_VERSION == "2.0"


class TestVersionSystem:
    """版本系统验证"""

    def test_constants_defined(self):
        assert SCHEMA_VERSION == "3.0"
        assert IR_VERSION == "3.0"
        assert PATCH_VERSION == "2.0"

    def test_check_compatible_same_major(self):
        assert check_schema_compatible("3.0") is True
        assert check_schema_compatible("3.1") is True
        assert check_schema_compatible("3.99") is True

    def test_check_incompatible_different_major(self):
        assert check_schema_compatible("1.0") is False
        assert check_schema_compatible("2.0") is False

    def test_check_empty(self):
        assert check_schema_compatible("") is False

    def test_project_has_version(self):
        ir = TimelineProjectIR()
        assert ir.schema_version == SCHEMA_VERSION
        assert ir.ir_version == IR_VERSION
        assert ir.source_video is None
        assert ir.language is None


class TestSynthesisFiveLayer:
    """SynthesisEngine 5 层渲染验证"""

    def test_layer1_raw_state(self):
        es = TimelineEventState(TimelineEventIR(
            id="e1", start=0.5, end=3.0, text_ref="hello", speaker_ref="SPK_01",
        ))
        synth = SynthesisEngine()
        result = synth.render(es)
        assert result["id"] == "e1"
        assert result["start"] == 0.5
        assert result["end"] == 3.0
        assert result["text"] == "hello"
        assert result["speaker"] == "SPK_01"

    def test_derivatives_merged(self):
        es = TimelineEventState(TimelineEventIR(
            id="e1", start=0, end=1, text_ref="hello", speaker_ref=None,
        ))
        es.translation.text = "hola"
        es.emotion.emotion = "happy"
        synth = SynthesisEngine()
        result = synth.render(es)
        assert result["translation"]["text"] == "hola"
        assert result["emotion"]["emotion"] == "happy"

    def test_patches_override_derivatives(self):
        es = TimelineEventState(TimelineEventIR(
            id="e1", start=0, end=1, text_ref="hello", speaker_ref=None,
        ))
        es.translation.text = "hola"
        es.add_patch(Patch(
            id="p1", target_id="e1", op="replace",
            value={"translation": {"text": "replaced"}},
        ))
        synth = SynthesisEngine()
        result = synth.render(es)
        assert result["translation"]["text"] == "replaced"

    def test_render_speakers_with_new_fields(self):
        spk = SpeakerNodeIR(
            id="SPK_01", name="主持人", voice_id="voice_001",
            color="#FF5733", is_locked=True,
            embedding_ref="/emb/1", gender_prob=0.85,
            voice_style="calm", confidence=0.92,
        )
        ir = TimelineProjectIR(
            events={"e1": TimelineEventIR(id="e1", start=0, end=1, text_ref="hi", speaker_ref="SPK_01")},
            speakers={"SPK_01": spk},
        )
        state = TimelineProjectState(ir)
        synth = SynthesisEngine()
        speakers = synth.render_speakers(state)
        s = speakers[0]
        assert s["id"] == "SPK_01"
        assert s["name"] == "主持人"
        assert s["voice_id"] == "voice_001"
        assert s["color"] == "#FF5733"
        assert s["is_locked"] is True
        assert s["embedding_ref"] == "/emb/1"
        assert s["gender_prob"] == 0.85
        assert s["voice_style"] == "calm"
        assert s["confidence"] == 0.92


class TestStateClassification:
    """状态三层分类验证"""

    def test_raw_state_in_ir(self):
        evt = TimelineEventIR(id="e1", start=0, end=1, text_ref="hello", speaker_ref="SPK_01")
        assert evt.text_ref == "hello"
        assert evt.speaker_ref == "SPK_01"

    def test_derived_state_in_slots(self):
        es = TimelineEventState(TimelineEventIR(
            id="e1", start=0, end=1, text_ref="hello", speaker_ref=None,
        ))
        es.translation.text = "hola"
        es.tts.audio_ref = "tts://seg.wav"
        assert es.translation.text == "hola"
        assert es.tts.audio_ref == "tts://seg.wav"

    def test_decision_state_in_slots(self):
        es = TimelineEventState(TimelineEventIR(
            id="e1", start=0, end=1, text_ref="hello", speaker_ref=None,
        ))
        es.runtime.status = "accepted"
        es.runtime.generation_mode = "primary"
        es.provenance["engine"] = "cosyvoice"
        es.review.needs_human_review = False
        assert es.runtime.status == "accepted"
        assert es.provenance["engine"] == "cosyvoice"

    def test_slots_independent(self):
        es = TimelineEventState(TimelineEventIR(
            id="e1", start=0, end=1, text_ref="hello", speaker_ref=None,
        ))
        es.translation.text = "a"
        es.tts.audio_ref = "b"
        assert es.translation.text == "a"
        assert es.tts.audio_ref == "b"
        assert es.translation.engine == ""       # 类型化字段隔离
        assert es.tts.duration == 0.0
