"""
Conflict Detection & Resolution — 冲突检测与消解 (Chapter 12 §12.6)

4 类冲突: OVERWRITE, TEMPORAL, IDENTITY, SEMANTIC
3 种消解: rule-based (engine priority), confidence (max), range (union/split)
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from core.runtime.patch import Patch, OpCode
from core.runtime.project_state import TimelineProjectState


class ConflictType(Enum):
    OVERWRITE = "overwrite"
    TEMPORAL = "temporal"
    IDENTITY = "identity"
    SEMANTIC = "semantic"


@dataclass
class Conflict:
    conflict_type: ConflictType
    patch_a: Patch
    patch_b: Patch
    target_id: str
    description: str
    resolution: str | None = None


_ENGINE_PRIORITY: dict[str, int] = {
    "logic_gate": 100,
    "asr": 90, "whisper": 90, "wav2vec2": 88,
    "speaker": 80, "pyannote": 80,
    "alignment": 70, "whisperx": 70,
    "cosyvoice": 60, "chattts": 59, "indextts": 58,
    "openvoice": 40, "edge_tts": 30,
    "system": 0,
}

_OVERWRITE_OPS = {
    OpCode.REPLACE, OpCode.UPDATE_TRANSCRIPTION, OpCode.UPDATE_TTS_AUDIO,
    OpCode.UPDATE_TRANSLATION, OpCode.ANNOTATE,
}


class ConflictDetector:
    """检测 patch 之间的冲突。"""

    def detect(self, patches: list[Patch]) -> list[Conflict]:
        conflicts: list[Conflict] = []
        for i in range(len(patches)):
            for j in range(i + 1, len(patches)):
                c = self._check_pair(patches[i], patches[j])
                if c:
                    conflicts.append(c)
        return conflicts

    def _check_pair(self, a: Patch, b: Patch) -> Conflict | None:
        if a.target_id != b.target_id:
            return None

        if a.op in _OVERWRITE_OPS and b.op in _OVERWRITE_OPS:
            overlap = set(a.value.keys()) & set(b.value.keys())
            if overlap:
                return Conflict(
                    ConflictType.OVERWRITE, a, b, a.target_id,
                    f"field overlap on {a.target_id}: {overlap}",
                )

        speaker_ops = {OpCode.ASSIGN_SPEAKER, OpCode.MERGE_SPEAKERS}
        if a.op in speaker_ops and b.op in speaker_ops:
            spk_a = a.value.get("speaker_id", "")
            spk_b = b.value.get("speaker_id", "")
            if spk_a and spk_b and spk_a != spk_b:
                return Conflict(
                    ConflictType.IDENTITY, a, b, a.target_id,
                    f"speaker mismatch: {spk_a} vs {spk_b}",
                )

        return None

    def is_safe_to_apply(
        self, patch: Patch, state: TimelineProjectState,
    ) -> tuple[bool, str]:
        target = state.get_event(patch.target_id)
        if target is None and patch.op != OpCode.SEGMENT_INSERT:
            return False, f"target not found: {patch.target_id}"
        if patch.op == OpCode.SEGMENT_INSERT:
            if state.get_event(patch.target_id) is not None:
                return False, f"segment already exists: {patch.target_id}"
        if patch.confidence < 0.0 or patch.confidence > 1.0:
            return False, f"invalid confidence: {patch.confidence}"
        return True, "ok"


class ConflictResolver:
    """消解冲突 — 3 种策略。"""

    def resolve(
        self, conflicts: list[Conflict], strategy: str = "rule",
    ) -> list[Patch]:
        if strategy == "confidence":
            return self._by_confidence(conflicts)
        if strategy == "range":
            return self._by_range(conflicts)
        return self._by_rule(conflicts)

    def _by_rule(self, conflicts: list[Conflict]) -> list[Patch]:
        kept: dict[str, Patch] = {}
        for c in conflicts:
            pri_a = _ENGINE_PRIORITY.get(c.patch_a.author, 0)
            pri_b = _ENGINE_PRIORITY.get(c.patch_b.author, 0)
            winner = c.patch_a if pri_a >= pri_b else c.patch_b
            loser = c.patch_b if pri_a >= pri_b else c.patch_a
            c.resolution = f"rule: kept {winner.id} (pri={max(pri_a, pri_b)})"
            kept[winner.id] = winner
            kept.pop(loser.id, None)
        return list(kept.values())

    def _by_confidence(self, conflicts: list[Conflict]) -> list[Patch]:
        kept: dict[str, Patch] = {}
        for c in conflicts:
            winner = (
                c.patch_a if c.patch_a.confidence >= c.patch_b.confidence
                else c.patch_b
            )
            loser = c.patch_b if winner is c.patch_a else c.patch_a
            c.resolution = f"confidence: kept {winner.id}"
            kept[winner.id] = winner
            kept.pop(loser.id, None)
        return list(kept.values())

    def _by_range(self, conflicts: list[Conflict]) -> list[Patch]:
        kept: dict[str, Patch] = {}
        for c in conflicts:
            if c.conflict_type == ConflictType.TEMPORAL:
                a_s, a_e = c.patch_a.value.get("start", 0), c.patch_a.value.get("end", 0)
                b_s, b_e = c.patch_b.value.get("start", 0), c.patch_b.value.get("end", 0)
                if a_s <= b_e and b_s <= a_e:
                    c.patch_a.value["start"] = min(a_s, b_s)
                    c.patch_a.value["end"] = max(a_e, b_e)
                    c.resolution = f"range: union [{min(a_s, b_s)}, {max(a_e, b_e)}]"
                    kept[c.patch_a.id] = c.patch_a
            else:
                kept[c.patch_a.id] = c.patch_a
                kept[c.patch_b.id] = c.patch_b
        return list(kept.values())
