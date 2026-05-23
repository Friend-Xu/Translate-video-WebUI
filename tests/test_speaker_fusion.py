"""
Test SpeakerFusion — word-level speaker assignment + boundary splitting.

Pure numpy computation, zero GPU, safe to run in CI.
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from pipeline.speaker_fusion import (
    assign_word_speakers,
    split_at_speaker_boundaries,
    detect_overlaps,
)


# ── assign_word_speakers ──────────────────────────────

def test_assign_empty_timeline_returns_unchanged():
    words = [{"word": "hello", "start": 0.0, "end": 0.5}]
    result = assign_word_speakers(words, [])
    assert result == words
    assert "speaker" not in result[0]


def test_assign_single_speaker():
    timeline = [("SPEAKER_00", 0.0, 5.0, 1.0)]
    words = [
        {"word": "hello", "start": 0.0, "end": 0.5},
        {"word": "world", "start": 0.5, "end": 1.0},
    ]
    result = assign_word_speakers(words, timeline)
    for w in result:
        assert w["speaker"] == "SPEAKER_00"


def test_assign_two_speakers():
    timeline = [
        ("SPEAKER_00", 0.0, 2.5, 1.0),
        ("SPEAKER_01", 2.5, 5.0, 1.0),
    ]
    words = [
        {"word": "hi", "start": 0.0, "end": 0.8},
        {"word": "there", "start": 0.8, "end": 2.0},
        {"word": "hello", "start": 2.6, "end": 3.5},
        {"word": "world", "start": 3.5, "end": 4.5},
    ]
    result = assign_word_speakers(words, timeline)
    assert result[0]["speaker"] == "SPEAKER_00"
    assert result[1]["speaker"] == "SPEAKER_00"
    assert result[2]["speaker"] == "SPEAKER_01"
    assert result[3]["speaker"] == "SPEAKER_01"


def test_assign_with_gap_uses_best_match():
    timeline = [("SPEAKER_00", 0.0, 3.0, 1.0)]
    words = [
        {"word": "a", "start": 0.0, "end": 1.0},
        {"word": "b", "start": 1.0, "end": 2.0},
        {"word": "c", "start": 5.0, "end": 6.0},  # gap, no speaker coverage
    ]
    result = assign_word_speakers(words, timeline)
    assert result[0].get("speaker") == "SPEAKER_00"
    assert result[1].get("speaker") == "SPEAKER_00"
    # Word at 5.0-6.0 has zero intersection with 0.0-3.0, no speaker assigned
    assert result[2].get("speaker") is None


def test_assign_fill_nearest():
    timeline = [("SPEAKER_00", 0.0, 2.0, 1.0)]
    words = [
        {"word": "x", "start": 10.0, "end": 11.0},
    ]
    result = assign_word_speakers(words, timeline, fill_nearest=True)
    assert result[0]["speaker"] == "SPEAKER_00"


# ── split_at_speaker_boundaries ───────────────────────

def test_split_no_boundaries_returns_single():
    segments = [{
        "start": 0.0, "end": 2.0, "text": "hello world",
        "words": [
            {"word": "hello", "start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"},
            {"word": "world", "start": 1.0, "end": 2.0, "speaker": "SPEAKER_00"},
        ],
    }]
    result = split_at_speaker_boundaries(segments)
    assert len(result) == 1
    assert result[0]["speaker"] == "SPEAKER_00"


def test_split_on_speaker_change():
    segments = [{
        "start": 0.0, "end": 4.0, "text": "hi hello",
        "words": [
            {"word": "hi", "start": 0.0, "end": 1.5, "speaker": "SPEAKER_00"},
            {"word": "hello", "start": 2.5, "end": 4.0, "speaker": "SPEAKER_01"},
        ],
    }]
    result = split_at_speaker_boundaries(segments)
    assert len(result) == 2
    assert result[0]["speaker"] == "SPEAKER_00"
    assert result[1]["speaker"] == "SPEAKER_01"


def test_split_skips_short_fragments():
    segments = [{
        "start": 0.0, "end": 3.0, "text": "a b c",
        "words": [
            {"word": "a", "start": 0.0, "end": 1.4, "speaker": "SPEAKER_00"},
            {"word": "b", "start": 1.5, "end": 1.6, "speaker": "SPEAKER_01"},
            {"word": "c", "start": 1.7, "end": 3.0, "speaker": "SPEAKER_00"},
        ],
    }]
    result = split_at_speaker_boundaries(segments, min_duration_s=0.3)
    # SPEAKER_01 word is 0.1s (< 0.3s min) → filtered out
    # Remaining 2 segments are both SPEAKER_00
    assert len(result) == 2
    assert result[0]["speaker"] == "SPEAKER_00"
    assert result[1]["speaker"] == "SPEAKER_00"
    assert "b" not in result[0]["text"] and "b" not in result[1]["text"]


def test_split_preserves_text():
    segments = [{
        "start": 0.0, "end": 2.0, "text": "x y",
        "words": [
            {"word": "x", "start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"},
            {"word": "y", "start": 1.0, "end": 2.0, "speaker": "SPEAKER_01"},
        ],
    }]
    result = split_at_speaker_boundaries(segments, min_duration_s=0.1)
    assert len(result) == 2
    assert result[0]["text"].strip() != ""
    assert result[1]["text"].strip() != ""


# ── detect_overlaps ───────────────────────────────────

def test_detect_no_overlap():
    timeline = [
        ("SPEAKER_00", 0.0, 2.0, 1.0),
        ("SPEAKER_01", 2.5, 5.0, 1.0),
    ]
    overlaps = detect_overlaps(timeline)
    assert len(overlaps) == 0


def test_detect_overlap():
    timeline = [
        ("SPEAKER_00", 0.0, 3.0, 1.0),
        ("SPEAKER_01", 2.0, 5.0, 1.0),
    ]
    overlaps = detect_overlaps(timeline, min_overlap_s=0.5)
    assert len(overlaps) == 1
    assert overlaps[0]["start"] == 2.0
    assert overlaps[0]["end"] == 3.0
    assert set(overlaps[0]["speakers"]) == {"SPEAKER_00", "SPEAKER_01"}


def test_detect_small_overlap_filtered():
    timeline = [
        ("SPEAKER_00", 0.0, 2.0, 1.0),
        ("SPEAKER_01", 1.8, 5.0, 1.0),
    ]
    overlaps = detect_overlaps(timeline, min_overlap_s=0.5)
    assert len(overlaps) == 0
