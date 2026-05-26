"""
TASK 10 — Speaker Model Split

Three-layer model:
- Acoustic: immutable, from diarization
- Logical: patchable, user-editable
- Runtime: render-only, TTS voice mapping
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AcousticSpeaker:
    speaker_id: str
    label: str = ""


@dataclass
class LogicalSpeaker:
    speaker_id: str
    display_name: str = ""
    acoustic_ids: list[str] | None = None

    def __post_init__(self):
        if self.acoustic_ids is None:
            self.acoustic_ids = [self.speaker_id]


@dataclass
class RuntimeSpeaker:
    speaker_id: str
    display_name: str
    voice_id: str = ""
    color: str = ""


def acoustic_from_timeline(timeline: list[dict]) -> dict[str, AcousticSpeaker]:
    acoustic = {}
    for seg in timeline:
        spk = seg.get("speaker")
        if spk and spk not in acoustic:
            acoustic[spk] = AcousticSpeaker(speaker_id=spk, label=spk)
    return acoustic


def logical_from_acoustic(acoustic: dict) -> dict[str, LogicalSpeaker]:
    return {spk_id: LogicalSpeaker(speaker_id=spk_id) for spk_id in acoustic}


def runtime_from_logical(
    logical: dict, voice_map: dict | None = None,
) -> dict[str, RuntimeSpeaker]:
    voice_map = voice_map or {}
    return {
        spk_id: RuntimeSpeaker(
            speaker_id=spk_id,
            display_name=logical[spk_id].display_name or spk_id,
            voice_id=voice_map.get(spk_id, ""),
        )
        for spk_id in logical
    }
