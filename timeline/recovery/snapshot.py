"""
TASK 12 — Snapshot System. Snapshot every N patches for fast rollback.
"""
from __future__ import annotations

import copy
from timeline.patch.model import TimelinePatch

SNAPSHOT_INTERVAL = 10


def should_snapshot(patch_count: int) -> bool:
    return patch_count > 0 and patch_count % SNAPSHOT_INTERVAL == 0


def create_snapshot(timeline: list[dict], patches: list[TimelinePatch]) -> dict:
    return {
        "timeline": copy.deepcopy(timeline),
        "patch_count": len(patches),
        "last_patch_id": patches[-1].patch_id if patches else None,
    }


def restore_from_snapshot(snapshot: dict) -> list[dict]:
    return copy.deepcopy(snapshot["timeline"])


def replay_from_snapshot(snapshot: dict, patches: list[TimelinePatch]) -> list[dict]:
    from timeline.patch.apply import apply_patch
    current = copy.deepcopy(snapshot["timeline"])
    for p in patches[snapshot["patch_count"]:]:
        current, _ = apply_patch(current, p)
    return current
