"""
Phase 4 — 旧版 Timeline IR 单元测试 (P0) — Phase 4 裁剪: schema.py 已退役

覆盖: TimelineWord, TimelineSegment, TimelineIR, SpeakerMapEntry
"""

import pytest
from pydantic import ValidationError
from timeline.ir import TimelineWord, TimelineSegment, TimelineIR, SpeakerMapEntry


# ═══════════════════════════════════════════════════════════
# TimelineWord
# ═══════════════════════════════════════════════════════════

class TestTimelineWord:
    """TimelineWord — 词级时间戳单元"""

    def test_construct_and_to_dict(self):
        w = TimelineWord(word="Hello", start=0.0, end=0.5, score=0.95, speaker="SPEAKER_00")
        d = w.to_dict()
        assert d["word"] == "Hello"
        assert d["start"] == 0.0
        assert d["end"] == 0.5
        assert d["score"] == 0.95
        assert d["speaker"] == "SPEAKER_00"

    def test_score_default(self):
        w = TimelineWord(word="x", start=0.0, end=0.1)
        assert w.score == 1.0

    def test_speaker_default_none(self):
        w = TimelineWord(word="x", start=0.0, end=0.1)
        assert w.speaker is None

    def test_from_dict_minimal(self):
        d = {"word": "Hi", "start": 1.0, "end": 1.5}
        w = TimelineWord.from_dict(d)
        assert w.word == "Hi"
        assert w.score == 1.0
        assert w.speaker is None

    def test_to_dict_omits_defaults(self):
        """to_dict 不输出 score=1.0 和 speaker=None"""
        w = TimelineWord(word="x", start=0.0, end=0.1)
        d = w.to_dict()
        assert "score" not in d
        assert "speaker" not in d

    def test_roundtrip(self):
        w = TimelineWord(word="Hello", start=0.0, end=0.5, score=0.8, speaker="S1")
        w2 = TimelineWord.from_dict(w.to_dict())
        assert w2.word == w.word
        assert w2.start == w.start
        assert w2.end == w.end
        assert w2.score == w.score
        assert w2.speaker == w.speaker


# ═══════════════════════════════════════════════════════════
# TimelineSegment
# ═══════════════════════════════════════════════════════════

class TestTimelineSegment:
    """TimelineSegment — 有起止时间的语义片段"""

    def test_construct_and_to_dict(self):
        seg = TimelineSegment(
            id="seg_001", type="speech", speaker="SPEAKER_00",
            start=0.0, end=2.5, text="Hello world",
        )
        d = seg.to_dict()
        assert d["id"] == "seg_001"
        assert d["type"] == "speech"
        assert d["speaker"] == "SPEAKER_00"
        assert d["start"] == 0.0
        assert d["end"] == 2.5
        assert d["text"] == "Hello world"

    def test_type_default_speech(self):
        seg = TimelineSegment(id="s1")
        assert seg.type == "speech"

    def test_overlap_default_false(self):
        seg = TimelineSegment(id="s1")
        assert seg.overlap is False

    def test_duration(self):
        seg = TimelineSegment(id="s1", start=1.0, end=3.5)
        assert seg.duration == 2.5

    def test_words_nested_serialization(self):
        seg = TimelineSegment(
            id="s1", start=0.0, end=2.0, text="Hi there",
            words=[TimelineWord(word="Hi", start=0.0, end=0.8),
                   TimelineWord(word="there", start=1.0, end=1.8)],
        )
        d = seg.to_dict()
        assert len(d["words"]) == 2
        assert d["words"][0]["word"] == "Hi"

    def test_empty_words(self):
        seg = TimelineSegment(id="s1")
        d = seg.to_dict()
        assert "words" not in d

    def test_from_dict_with_words(self):
        d = {
            "id": "s1", "start": 0.0, "end": 2.0, "text": "Hi",
            "words": [{"word": "Hi", "start": 0.0, "end": 1.5}],
        }
        seg = TimelineSegment.from_dict(d)
        assert len(seg.words) == 1
        assert seg.words[0].word == "Hi"

    def test_from_dict_minimal(self):
        d = {"id": "s1"}
        seg = TimelineSegment.from_dict(d)
        assert seg.id == "s1"
        assert seg.type == "speech"
        assert seg.text == ""

    def test_roundtrip(self):
        seg = TimelineSegment(
            id="s1", speaker="S1", start=0.0, end=2.0, text="Hello",
            translation="hello", overlap=True,
            words=[TimelineWord(word="Hello", start=0.0, end=1.8)],
        )
        seg2 = TimelineSegment.from_dict(seg.to_dict())
        assert seg2.id == seg.id
        assert seg2.speaker == seg.speaker
        assert seg2.translation == seg.translation
        assert seg2.overlap == seg.overlap
        assert len(seg2.words) == 1


# ═══════════════════════════════════════════════════════════
# TimelineIR
# ═══════════════════════════════════════════════════════════

class TestTimelineIR:
    """TimelineIR — 统一时间轴中间表示"""

    def test_construct_and_to_dict(self, sample_timeline_ir):
        ir = sample_timeline_ir
        d = ir.to_dict()
        assert d["audio_id"] == "test_audio"
        assert d["version"] == "1.0"
        assert len(d["timeline"]) == 3

    def test_speakers_property(self, sample_timeline_ir):
        spks = sample_timeline_ir.speakers
        assert spks == ["SPEAKER_00", "SPEAKER_01"]

    def test_total_duration(self, sample_timeline_ir):
        assert sample_timeline_ir.total_duration == 8.0

    def test_total_duration_empty(self):
        ir = TimelineIR(audio_id="empty")
        assert ir.total_duration == 0.0

    def test_roundtrip(self, sample_timeline_ir):
        ir2 = TimelineIR.from_dict(sample_timeline_ir.to_dict())
        assert ir2.audio_id == sample_timeline_ir.audio_id
        assert ir2.version == sample_timeline_ir.version
        assert len(ir2.timeline) == 3

    def test_speaker_map_roundtrip(self):
        ir = TimelineIR(
            audio_id="test", version="1.0",
            speaker_map={"S1": SpeakerMapEntry(alias="主持人", voice_id="v1")},
        )
        d = ir.to_dict()
        ir2 = TimelineIR.from_dict(d)
        assert ir2.speaker_map["S1"].alias == "主持人"
        assert ir2.speaker_map["S1"].voice_id == "v1"


