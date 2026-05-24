"""
TASK 11 — Speaker Adapter

User speaker operations → RETAG_SPEAKER / ANNOTATE patches.
"""
from __future__ import annotations

import uuid
from timeline.patch.model import TimelinePatch
from timeline.patch.opcode import OpCode


def _make_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def rename_speaker_patch(
    segment_ids: list[str], new_name: str, author: str = "user",
) -> TimelinePatch:
    return TimelinePatch(
        patch_id=_make_id("rename"),
        opcode=OpCode.RETAG_SPEAKER,
        targets=segment_ids,
        payload={"new_speaker": new_name},
        reason=["user_rename"],
        author=author,
    )


def merge_speaker_patch(
    source_seg_ids: list[str], target_speaker: str, author: str = "user",
) -> TimelinePatch:
    return TimelinePatch(
        patch_id=_make_id("merge_spk"),
        opcode=OpCode.RETAG_SPEAKER,
        targets=source_seg_ids,
        payload={"new_speaker": target_speaker},
        reason=["user_merge"],
        author=author,
    )


def set_voice_patch(
    segment_ids: list[str], voice_id: str, author: str = "user",
) -> TimelinePatch:
    return TimelinePatch(
        patch_id=_make_id("voice"),
        opcode=OpCode.ANNOTATE,
        targets=segment_ids,
        payload={"key": "voice_id", "value": voice_id},
        reason=["tts_voice_map"],
        author=author,
    )


def set_translation_patch(
    segment_id: str, translation: str, author: str = "system",
) -> TimelinePatch:
    return TimelinePatch(
        patch_id=_make_id("trans"),
        opcode=OpCode.SET_TRANSLATION,
        targets=[segment_id],
        payload={"translation": translation},
        reason=["translation"],
        author=author,
    )
