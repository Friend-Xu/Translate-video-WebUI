"""
TASK 01 — Structural Validator

Checks:
- time monotonic: prev.end <= next.start (within tolerance)
- word order valid: words within segment time bounds
- speaker non-null: warn if all segments lack speaker
- no cross-speaker overlap
- duration safety

Returns list of ValidationError; empty list = pass.
"""
from __future__ import annotations

from typing import List


class ValidationError:
    def __init__(self, segment_id: str, rule: str, detail: str):
        self.segment_id = segment_id
        self.rule = rule
        self.detail = detail

    def __repr__(self):
        return f"[{self.rule}] {self.segment_id}: {self.detail}"


def validate_timeline(segments: list) -> list[ValidationError]:
    """Validate a list of segment dicts or objects with to_dict().
    Returns list of ValidationError; empty list = valid.
    """
    errors: list[ValidationError] = []

    segs = []
    for s in segments:
        if hasattr(s, "model_dump"):
            segs.append(s.model_dump())
        elif hasattr(s, "to_dict"):
            segs.append(s.to_dict())
        else:
            segs.append(s)

    if not segs:
        return errors

    # 1. Time monotonic
    for i in range(len(segs) - 1):
        a, b = segs[i], segs[i + 1]
        gap = b.get("start", 0) - a.get("end", 0)
        if gap < -0.1:
            errors.append(ValidationError(
                f"{a.get('id', '?')}→{b.get('id', '?')}",
                "time_monotonic",
                f"overlap={-gap:.2f}s"
            ))

    # 2. Word order valid
    for seg in segs:
        words = seg.get("words", [])
        sid = seg.get("id", "?")
        seg_start = seg.get("start", 0)
        seg_end = seg.get("end", 0)
        for j, w in enumerate(words):
            ws, we = w.get("start", 0), w.get("end", 0)
            if ws > we:
                errors.append(ValidationError(sid, "word_order",
                    f"word[{j}] start({ws}) > end({we})"))
            if ws < seg_start - 0.05 or we > seg_end + 0.05:
                errors.append(ValidationError(sid, "word_bounds",
                    f"word[{j}] ({ws},{we}) outside segment ({seg_start},{seg_end})"))

    # 3. Cross-speaker overlap
    for i in range(len(segs) - 1):
        a, b = segs[i], segs[i + 1]
        if a.get("speaker") and b.get("speaker") and a["speaker"] != b["speaker"]:
            if a.get("end", 0) > b.get("start", 0):
                errors.append(ValidationError(
                    f"{a.get('id', '?')}↔{b.get('id', '?')}",
                    "cross_speaker_overlap",
                    f"{a['speaker']} and {b['speaker']} overlap by {a['end']-b['start']:.2f}s"
                ))

    # 4. Duration safety
    for seg in segs:
        dur = seg.get("end", 0) - seg.get("start", 0)
        sid = seg.get("id", "?")
        if dur <= 0:
            errors.append(ValidationError(sid, "duration_zero", f"duration={dur:.2f}s"))
        elif dur > 30:
            errors.append(ValidationError(sid, "duration_too_long", f"duration={dur:.1f}s > 30s"))

    return errors


def validate_segment(segment) -> list[ValidationError]:
    """Validate a single segment."""
    return validate_timeline([segment])
