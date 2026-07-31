"""
契约测试 — Event 模型 + timeline v3 schema + 字段契约 (数据结构重设计 Phase 1)

锁死三件事:
  1. persist/reload 互逆: to_dict → from_dict → to_dict 恒等
  2. to_dict 输出符合 timeline_v3.schema.json
  3. from_dict 缺必填字段显式报错 (禁止兜底)
"""
import pytest
from core.runtime.event_model import (
    Event, Project, ProjectAudio, Word, Translation, TTSAudio,
    Review, Semantic, Speaker, EventRuntime, join_words,
)
from core.runtime.field_contract import PassContract, validate_field_ref
from core.testing.schema_validator import assert_valid_timeline_v3


def _sample_event() -> Event:
    return Event(
        id="evt_001", start=0.0, end=12.3,
        text="Today guys, we're going to look at mods.",
        speaker="spk_01", confidence=0.95,
        words=[
            Word("Today", 0.0, 0.3, 0.98),
            Word("guys,", 0.35, 0.6, 0.97),
            Word("we're", 0.62, 0.8, 0.96),
        ],
        semantic=Semantic(embedding_ref="_embeddings/evt_001.npy"),
        translation=Translation(text="各位朋友,今天我们来看模组。",
                                engine="deepseek", quality_score=0.85, similarity=0.92),
        tts=TTSAudio(audio_path="03_tts/evt_001.wav", duration=11.8,
                     engine="cosyvoice", speed_factor=1.05, quality_score=0.88),
        review=Review(status="pending", flags=["low_confidence"],
                      gate_decision="B", notes=""),
    )


def _sample_project() -> Project:
    return Project(
        id="test_project", source_video="test.mp4",
        source_lang="en", target_lang="zh",
        created_at="2026-07-27T04:00:00",
        audio=ProjectAudio(vocals_path="01_extract/vocals.wav",
                           bgm_path="01_extract/bgm.wav", sample_rate=16000),
        speakers={"spk_01": Speaker(id="spk_01", label="Speaker 1",
                                    embedding_ref="_embeddings/speaker_spk_01.npy",
                                    confidence=0.92, color="#FF5733")},
        events=[_sample_event()],
    )


@pytest.mark.schema
class TestEventRoundtrip:
    def test_event_roundtrip_identity(self):
        e = _sample_event()
        d = e.to_dict()
        assert Event.from_dict(d).to_dict() == d

    def test_project_roundtrip_identity(self):
        p = _sample_project()
        d = p.to_dict()
        assert Project.from_dict(d).to_dict() == d

    def test_runtime_not_persisted(self):
        """EventRuntime 是内存 only, 不得出现在 to_dict 输出里。"""
        e = _sample_event()
        e.runtime.tts_status = "rejected"
        e.runtime.dirty_flags = {"tts": True}
        d = e.to_dict()
        assert "runtime" not in d
        assert "tts_status" not in d
        assert "dirty_flags" not in d

    def test_lineage_defaults_to_self(self):
        e = _sample_event()
        assert e.lineage == "evt_001"


@pytest.mark.schema
class TestEventSchemaV3:
    def test_project_to_dict_valid_v3(self):
        assert_valid_timeline_v3(_sample_project().to_dict())

    def test_minimal_event_valid(self):
        p = Project(id="p", source_video="v.mp4", source_lang="en", target_lang="zh",
                    created_at="2026-07-27T04:00:00",
                    events=[Event(id="e1", start=0.0, end=1.0, text="hi")])
        assert_valid_timeline_v3(p.to_dict())

    def test_translation_is_dict_not_string(self):
        """v3 关键约束: translation 是 dict, 不是 v2 的 string。"""
        d = _sample_event().to_dict()
        assert isinstance(d["translation"], dict)
        assert d["translation"]["text"] == "各位朋友,今天我们来看模组。"


@pytest.mark.schema
class TestFromDictFailLoud:
    def test_missing_text_raises(self):
        with pytest.raises(ValueError, match="text"):
            Event.from_dict({"id": "e1", "start": 0.0, "end": 1.0})

    def test_missing_id_raises(self):
        with pytest.raises(ValueError, match="id"):
            Event.from_dict({"start": 0.0, "end": 1.0, "text": "x"})

    def test_bad_time_range_raises(self):
        with pytest.raises(ValueError, match="start"):
            Event(id="e1", start=2.0, end=1.0, text="x")

    def test_bad_review_status_raises(self):
        with pytest.raises(ValueError, match="status"):
            Review.from_dict({"status": "INVALID"})

    def test_missing_words_defaults_empty(self):
        """words 缺失默认 [] (外部 SRT 导入), 不崩。"""
        e = Event.from_dict({"id": "e1", "start": 0.0, "end": 1.0, "text": "x"})
        assert e.words == []


@pytest.mark.schema
class TestJoinWords:
    def test_latin_joins_with_space(self):
        ws = [Word("hello", 0, 0.5), Word("world", 0.5, 1.0)]
        assert join_words(ws, "en") == "hello world"

    def test_cjk_joins_without_space(self):
        ws = [Word("你好", 0, 0.5), Word("世界", 0.5, 1.0)]
        assert join_words(ws, "zh") == "你好世界"


@pytest.mark.schema
class TestFieldContract:
    def test_valid_field_refs(self):
        validate_field_ref("event", "text")
        validate_field_ref("translation", "quality_score")
        validate_field_ref("tts", "audio_ref")       # 实测: 运行时用 audio_ref, 非 audio_path
        validate_field_ref("review", "gate_decision")
        validate_field_ref("runtime", "tts_status")
        validate_field_ref("asr", "words")
        validate_field_ref("speaker", "speaker_id")
        validate_field_ref("emotion", "gate_decision")
        validate_field_ref("provenance", "translation_quality")

    def test_invalid_slot_raises(self):
        with pytest.raises(ValueError, match="非法 slot"):
            validate_field_ref("nonexistent_slot", "x")

    def test_invalid_field_raises(self):
        with pytest.raises(ValueError, match="无字段"):
            validate_field_ref("translation", "nonexistent_field")

    def test_pass_contract_validates(self):
        class GoodPass(PassContract):
            READS = frozenset({("event", "text")})
            WRITES = frozenset({("translation", "text"), ("translation", "engine")})
        assert GoodPass.validate_contract() == []

    def test_pass_contract_catches_bad_field(self):
        class BadPass(PassContract):
            WRITES = frozenset({("translation", "bogus_field")})
        errs = BadPass.validate_contract()
        assert len(errs) == 1
        assert "bogus_field" in errs[0]
