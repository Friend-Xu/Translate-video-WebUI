"""
Timestamp diagnostic tool — trace SRT timestamps through the extraction pipeline.

Usage:
    # Analyze existing pipeline output
    python tests/diag_timestamps.py source_file/test_out

Output:
    Prints a health report showing timestamp drift at each pipeline node.
    Flags segments with missing word timestamps, impossible durations, overlaps.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SegmentDiag:
    """Diagnostic info for a single segment."""
    index: int
    start: float
    end: float
    duration: float
    text: str
    word_count: int
    missing_ts_words: int = 0
    expected_duration_min: float = 0.0
    health: str = "OK"

    @property
    def words_per_second(self) -> float:
        dur = max(self.duration, 0.001)
        return self.word_count / dur


@dataclass
class DiagReport:
    """Full diagnostic report."""
    source_dir: str
    audio_duration: float = 0.0
    vad_segments: int = 0
    whisper_segments: int = 0
    srt_entries: int = 0
    total_missing_ts_words: int = 0
    critical_segments: list[SegmentDiag] = field(default_factory=list)
    warning_segments: list[SegmentDiag] = field(default_factory=list)
    ok_segments: list[SegmentDiag] = field(default_factory=list)
    all_segments: list[SegmentDiag] = field(default_factory=list)


def _find_json(base: str) -> Optional[str]:
    for name in os.listdir(base):
        if name.endswith(".json") and not name.endswith("-translate-log.json") and \
           not name.endswith("_vad_segments.json"):
            path = os.path.join(base, name)
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                if "segments" in data and isinstance(data["segments"], list):
                    if data["segments"] and "words" in data["segments"][0]:
                        return path
            except (json.JSONDecodeError, KeyError):
                continue
    return None


def _find_srt(base: str) -> Optional[str]:
    for name in os.listdir(base):
        if name.endswith(".srt") and "auto-replace" not in name:
            return os.path.join(base, name)
    return None


def _find_vad_json(base: str) -> Optional[str]:
    for name in os.listdir(base):
        if name.endswith("_vad_segments.json"):
            return os.path.join(base, name)
    return None


def _calculate_expected_duration(word_count: int) -> float:
    """Minimum viable duration for a given word count (English).

    Normal speech: ~150 wpm → ~400ms/word.
    TTS at +100% (max speed): ~200ms/word.
    180ms/word = absolute physical minimum before speech becomes unintelligible.
    """
    return word_count * 0.180


def _classify_health(seg: SegmentDiag) -> str:
    if seg.duration <= 0:
        return "CRITICAL"
    if seg.expected_duration_min <= 0:
        return "OK"
    ratio = seg.duration / seg.expected_duration_min
    if ratio < 0.5:
        return "CRITICAL"
    if ratio < 0.8:
        return "WARN"
    return "OK"


def analyze_srt(srt_path: str, whisper_json_path: Optional[str] = None) -> list[SegmentDiag]:
    segments = []
    with open(srt_path, "r", encoding="utf-8") as f:
        content = f.read().strip()

    whisper_words = []
    if whisper_json_path:
        with open(whisper_json_path, "r") as f:
            wdata = json.load(f)
        for seg in wdata.get("segments", []):
            for w in seg.get("words", []):
                whisper_words.append(w)

    for block in re.split(r"\n\s*\n", content):
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        m = re.match(
            r"(\d+):(\d+):(\d+)[,.]?(\d*)\s*-->>?\s*(\d+):(\d+):(\d+)[,.]?(\d*)",
            lines[1],
        )
        if not m:
            continue
        h1, m1, s1, ms1 = int(m[1]), int(m[2]), int(m[3]), (m[4] or "0").ljust(3, "0")[:3]
        h2, m2, s2, ms2 = int(m[5]), int(m[6]), int(m[7]), (m[8] or "0").ljust(3, "0")[:3]
        start = h1 * 3600 + m1 * 60 + s1 + int(ms1) / 1000.0
        end = h2 * 3600 + m2 * 60 + s2 + int(ms2) / 1000.0

        text = "\n".join(lines[2:])
        word_count = len(text.split())

        missing = sum(
            1 for w in whisper_words
            if w.get("start") is not None and w.get("end") is not None
            and start <= w["start"] <= end
            and (w.get("start") is None or w.get("end") is None)
        )

        seg = SegmentDiag(
            index=int(lines[0]),
            start=start,
            end=end,
            duration=end - start,
            text=text,
            word_count=word_count,
            missing_ts_words=missing,
            expected_duration_min=_calculate_expected_duration(word_count),
        )
        seg.health = _classify_health(seg)
        segments.append(seg)

    return segments


def analyze_whisper_json(json_path: str) -> dict:
    with open(json_path, "r") as f:
        data = json.load(f)

    total_words = 0
    missing_ts = 0
    segments_info = []

    for seg in data.get("segments", []):
        words = seg.get("words", [])
        seg_total = len(words)
        seg_missing = sum(1 for w in words if w.get("start") is None or w.get("end") is None)
        total_words += seg_total
        missing_ts += seg_missing

        gaps = []
        for i in range(len(words) - 1):
            e1 = words[i].get("end")
            s2 = words[i + 1].get("start")
            if e1 is not None and s2 is not None:
                gap = s2 - e1
                if gap > 0.5:
                    gaps.append((i, words[i]["word"], words[i + 1]["word"], gap))

        segments_info.append({
            "start": seg["start"],
            "end": seg["end"],
            "duration": seg["end"] - seg["start"],
            "word_count": seg_total,
            "missing_ts": seg_missing,
            "large_gaps": gaps,
        })

    return {
        "num_segments": len(data.get("segments", [])),
        "total_words": total_words,
        "missing_timestamp_words": missing_ts,
        "segments": segments_info,
    }


def print_report(report: DiagReport) -> None:
    sep = "=" * 80

    print(f"\n{sep}")
    print(f"  TIMESTAMP DIAGNOSTIC REPORT")
    print(f"  Source: {report.source_dir}")
    print(f"{sep}")

    print(f"\n  Audio duration:      {report.audio_duration:.2f}s")
    print(f"  VAD segments:        {report.vad_segments}")
    print(f"  Whisper segments:    {report.whisper_segments}")
    print(f"  SRT entries:         {report.srt_entries}")
    print(f"  Missing timestamps:  {report.total_missing_ts_words} words")
    print(f"  CRITICAL segments:   {len(report.critical_segments)}")
    print(f"  WARN segments:       {len(report.warning_segments)}")

    if report.critical_segments:
        print(f"\n  {'─' * 76}")
        print(f"  CRITICAL — duration too short for word count (TTS will hit speed limit)")
        print(f"  {'─' * 76}")
        print(f"  {'#':<5} {'Start':>8} {'End':>8} {'Dur':>7} {'Words':>6} {'WPS':>6}  Text")
        print(f"  {'─' * 76}")
        for seg in report.critical_segments:
            text_preview = seg.text[:55] + "..." if len(seg.text) > 55 else seg.text
            print(f"  {seg.index:<5} {seg.start:>8.3f} {seg.end:>8.3f} {seg.duration:>7.3f} "
                  f"{seg.word_count:>6} {seg.words_per_second:>6.1f}  {text_preview}")
            print(f"           expected min: {seg.expected_duration_min:.3f}s, "
                  f"actual: {seg.duration:.3f}s "
                  f"({seg.duration/seg.expected_duration_min*100:.0f}% of minimum)")

    if report.warning_segments:
        print(f"\n  WARNING — duration below comfort threshold:")
        for seg in report.warning_segments:
            text_preview = seg.text[:55] + "..." if len(seg.text) > 55 else seg.text
            print(f"  {seg.index}: {seg.duration:.3f}s for {seg.word_count} words "
                  f"({seg.words_per_second:.1f} wps) — {text_preview}")

    print(f"\n  ALL SEGMENTS:")
    print(f"  {'#':<5} {'Start':>8} {'End':>8} {'Dur':>7} {'Words':>6} {'WPS':>6} {'Health':>10}  Text")
    print(f"  {'─' * 76}")
    for seg in report.all_segments:
        text_preview = seg.text[:50] + "..." if len(seg.text) > 50 else seg.text
        print(f"  {seg.index:<5} {seg.start:>8.3f} {seg.end:>8.3f} {seg.duration:>7.3f} "
              f"{seg.word_count:>6} {seg.words_per_second:>6.1f} {seg.health:>10}  {text_preview}")

    print(f"\n{sep}\n")


def run_diagnostic(source_dir: str) -> DiagReport:
    report = DiagReport(source_dir=source_dir)

    srt_path = _find_srt(source_dir)
    if not srt_path:
        print(f"[ERROR] No SRT file found in {source_dir}")
        sys.exit(1)

    json_path = _find_json(source_dir)
    whisper_info = None
    if json_path:
        whisper_info = analyze_whisper_json(json_path)
        report.whisper_segments = whisper_info["num_segments"]
        report.total_missing_ts_words = whisper_info["missing_timestamp_words"]

        if whisper_info["missing_timestamp_words"] > 0:
            print(f"\n  [!] {whisper_info['missing_timestamp_words']} words have MISSING timestamps in whisper JSON:")
            for seg in whisper_info["segments"]:
                if seg["missing_ts"] > 0:
                    print(f"      Segment [{seg['start']:.3f}-{seg['end']:.3f}]: "
                          f"{seg['missing_ts']}/{seg['word_count']} words missing timestamps")
                if seg["large_gaps"]:
                    for idx, w1, w2, gap in seg["large_gaps"]:
                        print(f"      Large gap ({gap:.3f}s): '{w1}' -> '{w2}'")

    vad_path = _find_vad_json(source_dir)
    if vad_path:
        with open(vad_path, "r") as f:
            vad_data = json.load(f)
        report.vad_segments = len(vad_data.get("segments", []))
        if report.vad_segments == 1:
            seg0 = vad_data["segments"][0]
            params = vad_data.get("parameters", {})
            print(f"\n  [!] VAD produced only {report.vad_segments} segment: "
                  f"[{seg0['start']:.1f}s - {seg0['end']:.1f}s] "
                  f"(min_silence_gap={params.get('min_silence_gap', '?')}s)")
            print(f"      Whisper received one giant audio chunk — internal timestamps may drift.")

    segments = analyze_srt(srt_path, json_path)
    report.srt_entries = len(segments)

    for seg in segments:
        report.all_segments.append(seg)
        if seg.health == "CRITICAL":
            report.critical_segments.append(seg)
        elif seg.health == "WARN":
            report.warning_segments.append(seg)
        else:
            report.ok_segments.append(seg)

    return report


def main():
    parser = argparse.ArgumentParser(description="Timestamp pipeline diagnostic")
    parser.add_argument("source", help="Output directory (e.g. source_file/test_out)")
    parser.add_argument("--json-only", action="store_true", help="Output JSON instead of text report")
    args = parser.parse_args()

    report = run_diagnostic(args.source)

    if args.json_only:
        print(json.dumps({
            "critical": [
                {"index": s.index, "start": s.start, "end": s.end, "duration": s.duration,
                 "word_count": s.word_count, "words_per_second": s.words_per_second,
                 "text": s.text}
                for s in report.critical_segments
            ],
            "total_missing_timestamps": report.total_missing_ts_words,
        }, indent=2, ensure_ascii=False))
    else:
        print_report(report)

    if report.critical_segments:
        sys.exit(1)


if __name__ == "__main__":
    main()
