"""
TASK 15 — Timeline API Layer

Public API for patch-driven timeline editing.
Bridges Patch Engine with FastAPI/WebUI.
"""
from __future__ import annotations

import os, json
from timeline.patch.model import TimelinePatch
from timeline.patch.apply import apply_patch
from timeline.patch.conflict import is_safe_to_apply
from timeline.patch.planner import plan as planner_plan
from timeline.rules.extractor import extract_signals, extract_segment_signals
from timeline.scorer.scorer import score_all
from timeline.safety.guard import gate_check
from timeline.recovery.replay import undo_last
from timeline.recovery.snapshot import create_snapshot, should_snapshot
from timeline import load_json as load_timeline, save_json as save_timeline


def generate_candidate_patches(timeline_path: str) -> dict:
    """Generate AI-suggested patches. Read-only, no modification."""
    tl = load_timeline(timeline_path)
    segments = [s.to_dict() for s in tl.timeline]
    pair_signals = extract_signals(segments)
    seg_signals = [extract_segment_signals(s) for s in segments]
    scores = score_all(pair_signals, seg_signals)
    patches = planner_plan(segments, pair_signals, scores)
    result = {"patches": [p.to_dict() for p in patches], "high": [], "medium": [], "low": []}
    for p in patches:
        result[p.confidence_label].append(p.to_dict())
    return result


def apply_user_patch(
    timeline_path: str, patch_dict: dict, patch_log_path: str | None = None,
) -> dict:
    """Apply a single patch: validate → apply → log."""
    patch = TimelinePatch.from_dict(patch_dict)
    tl = load_timeline(timeline_path)
    segments = [s.to_dict() for s in tl.timeline]
    existing = _load_patch_log(patch_log_path) if patch_log_path else []

    safe, reason = is_safe_to_apply(patch, existing, segments)
    if not safe:
        return {"status": "rejected", "reason": reason}

    acoustic = {s["id"]: s.get("speaker") for s in segments if s.get("speaker")}
    gate_check(patch, segments, acoustic)

    patch.parent_version = _hash_segments(segments)
    new_segments, diff = apply_patch(segments, patch)
    _update_timeline_segments(tl, new_segments)
    save_timeline(tl, timeline_path)

    if patch_log_path:
        existing.append(patch)
        _save_patch_log(existing, patch_log_path)

    if should_snapshot(len(existing)):
        snap = create_snapshot(new_segments, existing)
        snap_path = timeline_path.replace("timeline.json", "timeline_snapshot.json")
        with open(snap_path, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=2)

    return {"status": "applied", "patch_id": patch.patch_id, "diff": diff}


def undo_last_patch(
    source_timeline_path: str, working_timeline_path: str, patch_log_path: str,
) -> dict:
    source = load_timeline(source_timeline_path)
    source_segs = [s.to_dict() for s in source.timeline]
    existing = _load_patch_log(patch_log_path)
    if not existing:
        return {"status": "no_patches"}
    reverted = undo_last(source_segs, existing)
    if reverted is None:
        return {"status": "error"}
    removed = existing.pop()
    _save_patch_log(existing, patch_log_path)
    tl = load_timeline(working_timeline_path)
    _update_timeline_segments(tl, reverted)
    save_timeline(tl, working_timeline_path)
    return {"status": "undone", "patch_id": removed.patch_id}


def get_patch_log(patch_log_path: str) -> list[dict]:
    return [p.to_dict() for p in _load_patch_log(patch_log_path)]


def _load_patch_log(path: str) -> list[TimelinePatch]:
    if not path or not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [TimelinePatch.from_dict(d) for d in json.load(f)]


def _save_patch_log(patches: list[TimelinePatch], path: str):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([p.to_dict() for p in patches], f, ensure_ascii=False, indent=2)


def _update_timeline_segments(tl, new_segments: list[dict]):
    from timeline.ir import TimelineSegment
    for i, seg_data in enumerate(new_segments):
        if i < len(tl.timeline):
            seg = tl.timeline[i]
            seg.text = seg_data.get("text", seg.text)
            seg.start = seg_data.get("start", seg.start)
            seg.end = seg_data.get("end", seg.end)
            seg.speaker = seg_data.get("speaker", seg.speaker)
            seg.translation = seg_data.get("translation", seg.translation)
            seg.overlap = seg_data.get("overlap", seg.overlap)
        else:
            tl.timeline.append(TimelineSegment.from_dict(seg_data))
    while len(tl.timeline) > len(new_segments):
        tl.timeline.pop()


def _hash_segments(segments: list[dict]) -> str:
    import hashlib
    keys = ("id", "start", "end", "speaker", "text")
    raw = json.dumps([{k: s[k] for k in keys if k in s} for s in segments],
                     sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:12]
