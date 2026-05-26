"""
TASK 09 — Conflict Detector

Detects: overlapping patches, invalid merges, speaker conflicts.
"""
from __future__ import annotations

from timeline.patch.model import TimelinePatch
from timeline.patch.opcode import OpCode


def detect_conflicts(
    patches: list[TimelinePatch],
    timeline: list[dict] | None = None,
) -> list[dict]:
    conflicts: list[dict] = []
    target_sets = {p.patch_id: set(p.targets) for p in patches}
    ids = list(target_sets.keys())
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            overlap = target_sets[ids[i]] & target_sets[ids[j]]
            if overlap:
                conflicts.append({
                    "type": "overlapping_targets",
                    "patches": [ids[i], ids[j]],
                    "shared_targets": list(overlap),
                })
    for p in patches:
        if p.opcode == OpCode.MERGE and timeline:
            speakers = set()
            for t in p.targets:
                for seg in (timeline or []):
                    if seg.get("id") == t and seg.get("speaker"):
                        speakers.add(seg["speaker"])
            if len(speakers) > 1:
                conflicts.append({
                    "type": "cross_speaker_merge",
                    "patch": p.patch_id,
                    "speakers": list(speakers),
                })
    return conflicts


def is_safe_to_apply(
    patch: TimelinePatch,
    existing_patches: list[TimelinePatch],
    timeline: list[dict],
) -> tuple[bool, str]:
    existing_keys = {p.idempotency_key for p in existing_patches}
    if patch.idempotency_key in existing_keys:
        return False, "idempotency: patch already applied"
    if patch.opcode == OpCode.MERGE:
        speakers = set()
        for t in patch.targets:
            for seg in timeline:
                if seg.get("id") == t and seg.get("speaker"):
                    speakers.add(seg["speaker"])
        if len(speakers) > 1:
            return False, f"cross_speaker: {speakers}"
    return True, "ok"
