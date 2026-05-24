"""
TASK 05 — Rollback System

Features:
- undo last patch (reverse a patch application)
- replay patch chain from source timeline
- rebuild state from source + patch log
"""
from __future__ import annotations

import copy
from timeline.patch.model import TimelinePatch


def replay_chain(
    source_timeline: list[dict],
    patches: list[TimelinePatch],
) -> list[dict]:
    """Replay entire patch chain from source timeline."""
    from timeline.patch.apply import apply_patch
    current = copy.deepcopy(source_timeline)
    for p in patches:
        current, _ = apply_patch(current, p)
    return current


def replay_to_patch(
    source_timeline: list[dict],
    patches: list[TimelinePatch],
    target_patch_id: str,
) -> list[dict]:
    """Replay patches up to (and including) target_patch_id."""
    from timeline.patch.apply import apply_patch
    current = copy.deepcopy(source_timeline)
    for p in patches:
        current, _ = apply_patch(current, p)
        if p.patch_id == target_patch_id:
            break
    return current


def compute_reverse_patch(
    timeline_before: list[dict],
    patch: TimelinePatch,
) -> dict | None:
    """Compute the reverse operation for a given patch."""
    if patch.opcode.value == "MERGE":
        targets = patch.targets
        original_segs = [s for s in timeline_before if s["id"] in targets]
        if len(original_segs) >= 2:
            return {
                "opcode": "SPLIT",
                "targets": targets,
                "original_segments": original_segs,
            }
    elif patch.opcode.value == "SPLIT":
        return {"opcode": "MERGE", "targets": patch.targets}
    elif patch.opcode.value == "RETAG_SPEAKER":
        original_speakers = {}
        for s in timeline_before:
            if s["id"] in patch.targets:
                original_speakers[s["id"]] = s.get("speaker")
        return {
            "opcode": "RETAG_SPEAKER",
            "targets": patch.targets,
            "original_speakers": original_speakers,
        }
    return None


def undo_last(
    source_timeline: list[dict],
    patches: list[TimelinePatch],
) -> list[dict] | None:
    """Undo the last patch in the chain. Returns state before last patch."""
    if not patches:
        return None
    return replay_chain(source_timeline, patches[:-1])
