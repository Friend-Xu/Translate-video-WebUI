"""
Unit tests for SRT timestamp interpolation fix.

Tests the _interpolate_word_timestamps method in both
EnglishProcessor and JapaneseProcessor, plus end-to-end
tests for split_long_segments with missing timestamps.
"""

from __future__ import annotations

import json
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "SRT"))

from Json_Convert_Srt_EN import EnglishProcessor
from Json_Convert_Srt_JP import JapaneseProcessor


def _make_word(word: str, start: float | None, end: float | None) -> dict:
    d = {"word": word}
    if start is not None:
        d["start"] = start
    if end is not None:
        d["end"] = end
    return d


def _has_all_timestamps(words: list) -> bool:
    return all(
        w.get("start") is not None and w.get("end") is not None
        for w in words
    )


def _timestamps_monotonic(words: list) -> bool:
    prev_end = None
    for w in words:
        s = w.get("start")
        e = w.get("end")
        if s is None or e is None:
            return False
        if s > e:
            return False
        if prev_end is not None and s < prev_end:
            return False
        prev_end = e
    return True


class TestEnglishInterpolateTimestamps:
    """Tests for EnglishProcessor._interpolate_word_timestamps."""

    def test_all_present_unchanged(self):
        words = [
            _make_word("hello", 0.0, 0.5),
            _make_word("world", 0.6, 1.0),
        ]
        original = [dict(w) for w in words]
        EnglishProcessor._interpolate_word_timestamps(words, 0.0, 1.0)
        assert words == original

    def test_empty_list_safe(self):
        EnglishProcessor._interpolate_word_timestamps([], 0.0, 1.0)

    def test_single_missing_middle(self):
        words = [
            _make_word("I", 0.0, 0.2),
            _make_word("am", None, None),
            _make_word("here", 1.0, 1.5),
        ]
        EnglishProcessor._interpolate_word_timestamps(words, 0.0, 1.5)
        assert _has_all_timestamps(words)
        assert 0.2 <= words[1]["start"] <= 0.3
        assert 0.9 <= words[1]["end"] <= 1.0
        assert _timestamps_monotonic(words)

    def test_multiple_missing_run(self):
        words = [
            _make_word("A", 0.0, 0.1),
            _make_word("1", None, None),
            _make_word(".5", None, None),
            _make_word("B", 1.0, 1.1),
        ]
        EnglishProcessor._interpolate_word_timestamps(words, 0.0, 1.1)
        assert _has_all_timestamps(words)
        assert _timestamps_monotonic(words)
        assert abs(words[1]["end"] - words[1]["start"] - 0.3) < 0.01
        assert abs(words[2]["end"] - words[2]["start"] - 0.6) < 0.01

    def test_missing_at_start(self):
        words = [
            _make_word("first", None, None),
            _make_word("second", 1.0, 1.5),
        ]
        EnglishProcessor._interpolate_word_timestamps(words, 0.5, 2.0)
        assert _has_all_timestamps(words)
        assert words[0]["start"] == 0.5
        assert 0.99 <= words[0]["end"] <= 1.0

    def test_missing_at_end(self):
        words = [
            _make_word("first", 0.0, 0.5),
            _make_word("last", None, None),
        ]
        EnglishProcessor._interpolate_word_timestamps(words, 0.0, 2.0)
        assert _has_all_timestamps(words)
        assert words[1]["start"] == 0.5
        assert words[1]["end"] == 2.0

    def test_all_missing(self):
        words = [
            _make_word("a", None, None),
            _make_word("b", None, None),
        ]
        EnglishProcessor._interpolate_word_timestamps(words, 0.0, 2.0)
        assert _has_all_timestamps(words)
        assert _timestamps_monotonic(words)
        assert abs(words[0]["end"] - words[0]["start"] - 1.0) < 0.01
        assert abs(words[1]["end"] - words[1]["start"] - 1.0) < 0.01

    def test_real_world_decimal_tokens(self):
        words = [
            _make_word("from", 18.829, 19.009),
            _make_word("1", None, None),
            _make_word(".18,", None, None),
            _make_word("but", 20.29, 20.39),
        ]
        EnglishProcessor._interpolate_word_timestamps(words, 8.3, 24.3)
        assert _has_all_timestamps(words)
        assert _timestamps_monotonic(words)
        assert words[3]["start"] == 20.29
        assert abs(words[2]["end"] - 20.29) < 0.01


class TestJapaneseInterpolateTimestamps:
    """Tests for JapaneseProcessor._interpolate_word_timestamps."""

    def test_all_present_unchanged(self):
        words = [
            _make_word("kyou", 0.0, 0.3),
            _make_word("ha", 0.3, 0.5),
        ]
        original = [dict(w) for w in words]
        JapaneseProcessor._interpolate_word_timestamps(words, 0.0, 0.5)
        assert words == original

    def test_missing_middle(self):
        words = [
            _make_word("watashi", 0.0, 0.2),
            _make_word("ha", None, None),
            _make_word("tanaka", 1.0, 1.5),
        ]
        JapaneseProcessor._interpolate_word_timestamps(words, 0.0, 1.5)
        assert _has_all_timestamps(words)
        assert _timestamps_monotonic(words)


class TestSplitLongSegmentsWithMissingTimestamps:
    """End-to-end tests: split_long_segments with missing word timestamps."""

    def test_no_segment_starvation(self):
        proc = EnglishProcessor(max_chars=10, min_duration=0.5, max_gap=0.5)

        words = [
            _make_word("so", 16.668, 16.768),
            _make_word("that", 16.808, 16.928),
            _make_word("is", 16.968, 17.028),
            _make_word("why", 17.068, 17.228),
            _make_word("we", 17.268, 17.349),
            _make_word("are", 17.429, 17.529),
            _make_word("also", 17.609, 17.809),
            _make_word("including", 17.849, 18.249),
            _make_word("some", 18.289, 18.409),
            _make_word("modpacks", 18.429, 18.809),
            _make_word("from", 18.829, 19.009),
            _make_word("1", None, None),
            _make_word(".18,", None, None),
            _make_word("but", 20.29, 20.39),
            _make_word("I", 20.43, 20.51),
            _make_word("promise", 20.55, 20.81),
            _make_word("you", 20.83, 20.91),
            _make_word("guys", 20.93, 21.17),
            _make_word("these", 21.21, 21.411),
            _make_word("are", 21.431, 21.491),
            _make_word("the", 21.531, 22.051),
            _make_word("10", None, None),
            _make_word("best", 22.171, 22.491),
            _make_word("modpacks", 22.571, 23.011),
            _make_word("available", 23.071, 23.612),
            _make_word("right", 23.732, 23.972),
            _make_word("now.", 24.052, 24.272),
        ]

        seg = {
            "text": " ".join(w["word"] for w in words),
            "start": 16.668,
            "end": 24.272,
            "words": words,
        }

        result = proc.split_long_segments([seg])
        assert len(result) >= 2

        for entry in result:
            duration = entry["end"] - entry["start"]
            word_count = len(entry["text"].split())
            min_duration = word_count * 0.15
            assert duration >= min_duration, (
                f"Segment '{entry['text'][:50]}' has {word_count} words "
                f"but only {duration:.3f}s (need {min_duration:.3f}s)"
            )

    def test_segment_boundaries_small_gaps_only(self):
        proc = EnglishProcessor(max_chars=8, min_duration=0.1, max_gap=0.5)

        words = [
            _make_word("one", 0.0, 0.3),
            _make_word("two", 0.4, 0.7),
            _make_word("three", 0.8, 1.1),
            _make_word("four", None, None),
            _make_word("five", 1.5, 1.8),
            _make_word("six", 1.9, 2.2),
            _make_word("seven", 2.3, 2.6),
            _make_word("eight", 2.7, 3.0),
            _make_word("nine.", 3.1, 3.5),
            _make_word("ten", 3.6, 3.9),
            _make_word("eleven.", 4.0, 4.5),
        ]

        seg = {
            "text": " ".join(w["word"] for w in words),
            "start": 0.0,
            "end": 4.5,
            "words": words,
        }

        result = proc.split_long_segments([seg])

        for i in range(1, len(result)):
            prev_end = result[i - 1]["end"]
            curr_start = result[i]["start"]
            # min_duration can push end past next start — fixed by
            # ensure_time_sync later in the pipeline
            gap = curr_start - prev_end
            assert gap > -0.3, (
                f"Large overlap: seg {i - 1} ends at {prev_end:.3f} "
                f"but seg {i} starts at {curr_start:.3f} (gap={gap:.3f}s)"
            )

    def test_time_allocation_proportional(self):
        proc = EnglishProcessor(max_chars=6, min_duration=0.5, max_gap=0.5)

        words = [
            _make_word(f"word{i}", float(i), float(i + 0.8))
            for i in range(12)
        ]
        words[3] = _make_word("word3", None, None)
        words[4] = _make_word("word4", None, None)

        seg = {
            "text": " ".join(w["word"] for w in words),
            "start": 0.0,
            "end": 12.0,
            "words": words,
        }

        result = proc.split_long_segments([seg])
        total_srt_duration = sum(e["end"] - e["start"] for e in result)
        assert abs(total_srt_duration - 12.0) < 1.0


def test_interpolation_on_real_whisper_output():
    """Verify interpolation fills all missing timestamps in real test data."""
    test_json = os.path.join(
        os.path.dirname(__file__), "..", "source_file", "test_out", "test.json"
    )
    if not os.path.exists(test_json):
        pytest.skip("test.json not found")

    with open(test_json, "r") as f:
        data = json.load(f)

    for seg in data["segments"]:
        words = seg.get("words", [])
        EnglishProcessor._interpolate_word_timestamps(
            words, seg["start"], seg["end"]
        )

        missing = sum(1 for w in words if w.get("start") is None or w.get("end") is None)
        assert missing == 0, (
            f"{missing} words still missing timestamps "
            f"in segment [{seg['start']:.3f}-{seg['end']:.3f}]"
        )
        assert _timestamps_monotonic(words), (
            f"Timestamps not monotonic in segment [{seg['start']:.3f}-{seg['end']:.3f}]"
        )
