"""
Phase 6 — Fusion 集成层单元测试 (P1)

覆盖: from_extract_result, _mark_overlaps
"""

import pytest
from timeline.fusion import from_extract_result
from timeline.ir import TimelineIR


class TestFusion:
    """from_extract_result — Pipeline → TimelineIR 转换"""

    def test_normal_input(self, sample_asr_segments):
        ir = from_extract_result(sample_asr_segments, audio_id="test_audio")
        assert isinstance(ir, TimelineIR)
        assert ir.audio_id == "test_audio"
        assert ir.version == "1.0"
        assert len(ir.timeline) == 3

    def test_segment_ids_sequential(self, sample_asr_segments):
        ir = from_extract_result(sample_asr_segments)
        ids = [s.id for s in ir.timeline]
        assert ids == ["seg_001", "seg_002", "seg_003"]

    def test_segment_text_preserved(self, sample_asr_segments):
        ir = from_extract_result(sample_asr_segments)
        assert ir.timeline[0].text == "Hello world"
        assert ir.timeline[1].text == "How are you"

    def test_segment_words_preserved(self, sample_asr_segments):
        ir = from_extract_result(sample_asr_segments)
        assert len(ir.timeline[0].words) == 2
        assert ir.timeline[0].words[0].word == "Hello"

    def test_speaker_map_built(self, sample_asr_segments):
        ir = from_extract_result(sample_asr_segments)
        assert "SPEAKER_00" in ir.speaker_map
        assert "SPEAKER_01" in ir.speaker_map

    def test_empty_segments(self):
        ir = from_extract_result([], audio_id="empty")
        assert ir.timeline == []
        assert ir.speaker_map == {}
        assert ir.total_duration == 0.0

    def test_overlap_detection(self):
        segments = [
            {"start": 0.0, "end": 3.0, "text": "A", "speaker": "S1", "words": []},
            {"start": 2.0, "end": 5.0, "text": "B", "speaker": "S2", "words": []},
        ]
        ir = from_extract_result(segments)
        assert ir.timeline[0].overlap is True
        assert ir.timeline[1].overlap is True

    def test_no_overlap_same_speaker(self):
        segments = [
            {"start": 0.0, "end": 3.0, "text": "A", "speaker": "S1", "words": []},
            {"start": 2.0, "end": 5.0, "text": "B", "speaker": "S1", "words": []},
        ]
        ir = from_extract_result(segments)
        assert ir.timeline[0].overlap is False

    def test_no_overlap_no_time_intersection(self):
        segments = [
            {"start": 0.0, "end": 2.0, "text": "A", "speaker": "S1", "words": []},
            {"start": 3.0, "end": 5.0, "text": "B", "speaker": "S2", "words": []},
        ]
        ir = from_extract_result(segments)
        assert ir.timeline[0].overlap is False

    def test_metadata_passed(self, sample_asr_segments):
        ir = from_extract_result(sample_asr_segments, metadata={"lang": "en", "duration": 8.0})
        assert ir.metadata["lang"] == "en"

    def test_no_speaker_segment(self):
        segments = [{"start": 0.0, "end": 2.0, "text": "No speaker", "words": []}]
        ir = from_extract_result(segments)
        assert ir.timeline[0].speaker is None
        assert ir.speaker_map == {}

    def test_single_segment(self):
        segments = [{"start": 0.0, "end": 2.0, "text": "Solo", "speaker": "S1", "words": []}]
        ir = from_extract_result(segments, audio_id="solo")
        assert len(ir.timeline) == 1
        assert ir.total_duration == 2.0
