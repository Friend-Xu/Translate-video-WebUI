"""
Phase 7 — 规则引擎 + 评分器单元测试 (P2)

覆盖: extract_signals, extract_segment_signals, score_signals, confidence_label
"""

import pytest
from timeline.rules.extractor import extract_signals, extract_segment_signals
from timeline.scorer.scorer import score_signals, score_all, confidence_label


class TestExtractSignals:
    """extract_signals — 相邻 segment pair 信号提取"""

    def test_same_speaker(self):
        segs = [
            {"start": 0, "end": 2, "text": "Hello.", "speaker": "S1", "words": []},
            {"start": 2, "end": 4, "text": "World.", "speaker": "S1", "words": []},
        ]
        signals = extract_signals(segs)
        assert len(signals) == 1
        assert signals[0]["same_speaker"] is True

    def test_different_speaker(self):
        segs = [
            {"start": 0, "end": 2, "text": "Hello.", "speaker": "S1", "words": []},
            {"start": 2, "end": 4, "text": "World.", "speaker": "S2", "words": []},
        ]
        signals = extract_signals(segs)
        assert signals[0]["same_speaker"] is False

    def test_gap_calculation(self):
        segs = [
            {"start": 0, "end": 2.0, "text": "A", "speaker": "S1", "words": []},
            {"start": 3.5, "end": 5.0, "text": "B", "speaker": "S1", "words": []},
        ]
        signals = extract_signals(segs)
        assert signals[0]["gap"] == 1.5

    def test_incomplete_ending(self):
        segs = [
            {"start": 0, "end": 2, "text": "No period here", "speaker": "S1", "words": []},
            {"start": 2, "end": 4, "text": "Next", "speaker": "S1", "words": []},
        ]
        signals = extract_signals(segs)
        assert signals[0]["incomplete_ending"] is True

    def test_complete_ending(self):
        segs = [
            {"start": 0, "end": 2, "text": "Finished.", "speaker": "S1", "words": []},
            {"start": 2, "end": 4, "text": "Next", "speaker": "S1", "words": []},
        ]
        signals = extract_signals(segs)
        assert signals[0]["incomplete_ending"] is False

    def test_semantic_continuation(self):
        segs = [
            {"start": 0, "end": 2, "text": "Start", "speaker": "S1", "words": []},
            {"start": 2, "end": 4, "text": "but continue", "speaker": "S1", "words": []},
        ]
        signals = extract_signals(segs)
        assert signals[0]["semantic_continuation"] is True

    def test_empty_segments(self):
        assert extract_signals([]) == []

    def test_single_segment(self):
        segs = [{"start": 0, "end": 2, "text": "Solo", "speaker": "S1", "words": []}]
        assert extract_signals(segs) == []


class TestExtractSegmentSignals:
    """extract_segment_signals — 单 segment 信号提取"""

    def test_basic(self):
        sig = extract_segment_signals({"start": 0, "end": 5, "text": "Hello.", "words": []})
        assert sig["duration"] == 5
        assert sig["char_count"] == 6
        assert sig["cps"] == pytest.approx(1.2)
        assert sig["sentence_enders"] == 1
        assert sig["too_long"] is False

    def test_long_segment(self):
        sig = extract_segment_signals({"start": 0, "end": 20, "text": "x" * 100, "words": []})
        assert sig["too_long"] is True

    def test_word_gap(self):
        sig = extract_segment_signals({
            "start": 0, "end": 5, "text": "x",
            "words": [{"start": 0, "end": 1}, {"start": 3, "end": 4}],
        })
        assert sig["max_word_gap"] == 2.0
        assert sig["has_word_gap"] is True


class TestScorer:
    """score_signals — 4 维加权评分"""

    def test_high_semantic_same_speaker(self):
        pair = {"same_speaker": True, "semantic_continuation": True,
                "incomplete_ending": True, "gap": 0.1, "merged_duration": 3.0}
        score = score_signals(pair)
        assert 0.8 < score <= 1.0

    def test_low_score_different_speaker(self):
        pair = {"same_speaker": False, "semantic_continuation": False,
                "incomplete_ending": False, "gap": 2.0, "merged_duration": 15.0}
        score = score_signals(pair)
        assert score < 0.5

    def test_score_in_range(self):
        for gap in [0.0, 0.2, 0.5, 1.0, 2.0, 10.0]:
            pair = {"same_speaker": True, "semantic_continuation": False,
                    "incomplete_ending": False, "gap": gap, "merged_duration": 3.0}
            s = score_signals(pair)
            assert 0.0 <= s <= 1.0

    def test_score_all(self):
        pairs = [
            {"same_speaker": True, "semantic_continuation": False,
             "incomplete_ending": False, "gap": 0.1, "merged_duration": 3.0},
            {"same_speaker": False, "semantic_continuation": True,
             "incomplete_ending": True, "gap": 0.2, "merged_duration": 5.0},
        ]
        scores = score_all(pairs)
        assert len(scores) == 2

    def test_confidence_label_high(self):
        assert confidence_label(0.95) == "high"

    def test_confidence_label_medium(self):
        assert confidence_label(0.75) == "medium"

    def test_confidence_label_low(self):
        assert confidence_label(0.5) == "low"

    def test_confidence_label_boundaries(self):
        assert confidence_label(0.91) == "high"
        assert confidence_label(0.70) == "medium"
