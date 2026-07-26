"""
TASK 04 — Patch Apply Engine

Rules:
- No in-place mutation: always returns a NEW timeline (list of segment dicts)
- Must log diff (before/after)
- All 6 opcodes supported
"""
from __future__ import annotations

import copy
from .opcode import OpCode
from .model import TimelinePatch


def apply_patch(
    timeline: list[dict],
    patch: TimelinePatch,
) -> tuple[list[dict], dict]:
    """Apply a single patch to timeline, returning (new_timeline, diff).
    Original timeline is NOT mutated.
    """
    segments = copy.deepcopy(timeline)
    diff = {"before": {}, "after": {}}

    target_indices = _resolve_targets(segments, patch.targets)

    if patch.opcode == OpCode.MERGE:
        segments, diff = _apply_merge(segments, target_indices, patch)
    elif patch.opcode == OpCode.SPLIT:
        segments, diff = _apply_split(segments, target_indices, patch)
    elif patch.opcode == OpCode.RETAG_SPEAKER:
        segments, diff = _apply_retag(segments, target_indices, patch)
    elif patch.opcode == OpCode.SET_TRANSLATION:
        segments, diff = _apply_set_translation(segments, target_indices, patch)
    elif patch.opcode == OpCode.RELINK_WORDS:
        segments, diff = _apply_relink(segments, target_indices, patch)
    elif patch.opcode == OpCode.RESIZE:
        segments, diff = _apply_resize(segments, target_indices, patch)
    elif patch.opcode == OpCode.ANNOTATE:
        segments, diff = _apply_annotate(segments, target_indices, patch)

    return segments, diff


def apply_patch_chain(
    timeline: list[dict],
    patches: list[TimelinePatch],
) -> tuple[list[dict], list[dict]]:
    """Apply patches sequentially. Returns (final_timeline, diffs)."""
    current = copy.deepcopy(timeline)
    diffs = []
    for p in patches:
        current, diff = apply_patch(current, p)
        diffs.append(diff)
    return current, diffs


def _resolve_targets(segments: list[dict], target_ids: list[str]) -> list[int]:
    """Map segment ids to indices in the segments list."""
    id_to_idx = {s["id"]: i for i, s in enumerate(segments)}
    indices = []
    for tid in target_ids:
        if tid in id_to_idx:
            indices.append(id_to_idx[tid])
    return sorted(indices)


def _apply_merge(segments: list[dict], indices: list[int], patch: TimelinePatch):
    if len(indices) < 2:
        return segments, {"error": "merge requires >= 2 targets"}
    first, last = indices[0], indices[-1]
    merged = copy.deepcopy(segments[first])
    merged["id"] = segments[first]["id"]
    merged["end"] = segments[last]["end"]
    merged["text"] = " ".join(segments[i]["text"] for i in indices)
    all_words = []
    for i in indices:
        all_words.extend(segments[i].get("words", []))
    merged["words"] = all_words

    diff = {
        "before": [segments[i]["id"] for i in indices],
        "after": [merged["id"]],
        "op": "merge"
    }
    new_segs = [s for i, s in enumerate(segments) if i not in indices]
    insert_at = indices[0] - sum(1 for j in indices if j < indices[0])
    new_segs.insert(insert_at, merged)
    return new_segs, diff


def _apply_split(segments: list[dict], indices: list[int], patch: TimelinePatch):
    if len(indices) != 1:
        return segments, {"error": "split requires exactly 1 target"}
    idx = indices[0]
    seg = segments[idx]
    split_point = patch.payload.get("split_point", seg["start"] + (seg["end"] - seg["start"]) / 2)

    words_a, words_b = [], []
    for w in seg.get("words", []):
        if w.get("start", 0) < split_point:
            words_a.append(copy.deepcopy(w))
        else:
            words_b.append(copy.deepcopy(w))

    seg_a = copy.deepcopy(seg)
    seg_a["end"] = split_point
    seg_a["words"] = words_a
    seg_a["text"] = " ".join(w["word"] for w in words_a)

    seg_b = copy.deepcopy(seg)
    seg_b["id"] = _next_seg_id(segments, seg["id"])
    seg_b["start"] = split_point
    seg_b["words"] = words_b
    seg_b["text"] = " ".join(w["word"] for w in words_b)

    diff = {
        "before": [seg["id"]],
        "after": [seg_a["id"], seg_b["id"]],
        "op": "split"
    }
    new_segs = segments[:idx] + [seg_a, seg_b] + segments[idx + 1:]
    return new_segs, diff


def _apply_retag(segments: list[dict], indices: list[int], patch: TimelinePatch):
    new_speaker = patch.payload["new_speaker"]
    for i in indices:
        segments[i]["speaker"] = new_speaker
        for w in segments[i].get("words", []):
            w["speaker"] = new_speaker
    diff = {
        "before": {segments[i]["id"]: segments[i].get("speaker") for i in indices},
        "after": {segments[i]["id"]: new_speaker for i in indices},
        "op": "retag"
    }
    return segments, diff


def _apply_set_translation(segments: list[dict], indices: list[int], patch: TimelinePatch):
    translation = patch.payload["translation"]
    for i in indices:
        existing = segments[i].get("translation")
        if isinstance(existing, dict) and isinstance(translation, str):
            # 保留 v2 译文对象封套（质量分等元数据），只覆盖文本
            existing["text"] = translation
            existing["user_edited"] = True
        else:
            segments[i]["translation"] = translation
    diff = {"op": "set_translation", "targets": [segments[i]["id"] for i in indices]}
    return segments, diff


def _apply_relink(segments: list[dict], indices: list[int], patch: TimelinePatch):
    word_mapping = patch.payload.get("word_mapping", {})
    for i in indices:
        for w in segments[i].get("words", []):
            if w.get("word") in word_mapping:
                new_seg_id = word_mapping[w["word"]]
                for s in segments:
                    if s["id"] == new_seg_id:
                        s.setdefault("words", []).append(copy.deepcopy(w))
                        break
        segments[i]["words"] = [w for w in segments[i].get("words", [])
                                 if w.get("word") not in word_mapping]
    diff = {"op": "relink_words", "mapping": word_mapping}
    return segments, diff


def _apply_resize(segments: list[dict], indices: list[int], patch: TimelinePatch):
    """Resize segment boundaries — changes start and/or end time."""
    new_start = patch.payload.get("new_start")
    new_end = patch.payload.get("new_end")
    before_state = {}
    for i in indices:
        before_state[segments[i]["id"]] = {"start": segments[i].get("start"), "end": segments[i].get("end")}
        if new_start is not None:
            segments[i]["start"] = new_start
        if new_end is not None:
            segments[i]["end"] = new_end
    diff = {
        "before": before_state,
        "after": {segments[i]["id"]: {"start": new_start, "end": new_end} for i in indices},
        "op": "resize"
    }
    return segments, diff


def _apply_annotate(segments: list[dict], indices: list[int], patch: TimelinePatch):
    key, value = patch.payload["key"], patch.payload["value"]
    for i in indices:
        segments[i].setdefault("annotations", {})[key] = value
    diff = {"op": "annotate", "key": key, "targets": [segments[i]["id"] for i in indices]}
    return segments, diff


def _next_seg_id(segments: list[dict], base_id: str) -> str:
    """Generate a unique segment id by suffixing."""
    existing = {s["id"] for s in segments}
    for suffix in "abcdefghij":
        candidate = f"{base_id}{suffix}"
        if candidate not in existing:
            return candidate
    return f"{base_id}_split"
