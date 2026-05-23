"""
Test DiarizationVerifier — 4-layer auto verification.

Pure Python computation, zero GPU, safe in CI.
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from pipeline.diarization_verify import verify_diarization


def test_verify_empty_timeline():
    report = verify_diarization([], total_audio_dur=60.0)
    assert report.passes_all
    assert report.summary["turns"] == 0


def test_verify_single_speaker_no_warnings():
    timeline = [
        ("SPEAKER_00", 0.0, 5.0, 1.0),
        ("SPEAKER_00", 6.0, 10.0, 1.0),
    ]
    report = verify_diarization(timeline, total_audio_dur=60.0)
    assert report.passes_all


def test_verify_short_fragments_warning():
    timeline = [
        ("SPEAKER_00", 0.0, 5.0, 1.0),
        ("SPEAKER_00", 5.1, 5.2, 1.0),   # 0.1s fragment
        ("SPEAKER_00", 6.0, 10.0, 1.0),
    ]
    report = verify_diarization(timeline, total_audio_dur=60.0)
    warnings = [i for i in report.issues if i.layer == 1]
    assert len(warnings) >= 1
    assert "碎片段" in warnings[0].message


def test_verify_speaker_balance_info():
    timeline = [
        ("SPEAKER_00", 0.0, 29.0, 1.0),
        ("SPEAKER_01", 29.1, 30.0, 1.0),  # 0.9s out of 30s = 3%
    ]
    report = verify_diarization(timeline, total_audio_dur=30.0)
    infos = [i for i in report.issues if i.layer == 2]
    assert len(infos) >= 1


def test_verify_many_turns_warning():
    timeline = []
    for i in range(20):
        spk = f"SPEAKER_{i % 2:02d}"
        timeline.append((spk, i * 2.9, i * 2.9 + 2.8, 1.0))
    report = verify_diarization(timeline, total_audio_dur=58.0)
    assert report.passes_all


def test_verify_no_audio_dur_defaults():
    timeline = [
        ("SPEAKER_00", 0.0, 5.0, 1.0),
    ]
    report = verify_diarization(timeline)
    assert report.passes_all
    assert len([i for i in report.issues if i.layer == 0]) == 0


def test_verify_with_transcript():
    transcript = {
        "segments": [
            {"start": 0.0, "end": 5.0, "text": "hello"},
            {"start": 7.5, "end": 10.0, "text": "world"},
        ]
    }
    timeline = [
        ("SPEAKER_00", 0.0, 5.0, 1.0),
        ("SPEAKER_00", 6.0, 10.0, 1.0),
    ]
    report = verify_diarization(timeline, transcript=transcript)
    gap_issues = [i for i in report.issues if i.layer == 3]
    assert len(gap_issues) >= 1  # gap between 5.0 and 6.0


def test_verify_empty_transcript_errors():
    transcript = {"segments": []}
    timeline = [("SPEAKER_00", 0.0, 5.0, 1.0)]
    report = verify_diarization(timeline, transcript=transcript)
    errors = [i for i in report.issues if i.severity == "error"]
    assert len(errors) >= 1


def test_verify_summary_counts():
    timeline = [
        ("SPEAKER_00", 0.0, 5.0, 1.0),
        ("SPEAKER_01", 6.0, 10.0, 1.0),
    ]
    report = verify_diarization(timeline, total_audio_dur=60.0)
    assert report.summary["speakers"] == 2
    assert report.summary["turns"] == 2
    assert "errors" in report.summary
    assert "warnings" in report.summary
