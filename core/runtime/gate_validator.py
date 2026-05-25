"""
GateValidator — Patch 预应用校验 (Chapter 12 §)

OpCode 合法性, target 存在性, confidence 范围, 幂等性, value 结构
"""
from __future__ import annotations
from dataclasses import dataclass
from core.runtime.patch import Patch, OpCode
from core.runtime.project_state import TimelineProjectState


@dataclass
class GateRejection:
    patch_id: str
    reason: str
    detail: str
    suggestion: str = ""


_REQUIRED: dict[OpCode, list[str]] = {
    OpCode.SEGMENT_INSERT: ["start", "end"],
    OpCode.SEGMENT_SPLIT: ["at"],
    OpCode.SEGMENT_MERGE: ["target_ids"],
    OpCode.ASSIGN_SPEAKER: ["speaker_id"],
    OpCode.MERGE_SPEAKERS: ["from_ids", "into_id"],
    OpCode.SPLIT_SEGMENT_BY_SPEAKER: ["boundaries"],
}

_NO_TARGET = {OpCode.SEGMENT_INSERT}


class GateValidator:

    def validate(self, patch: Patch, state: TimelineProjectState) -> list[GateRejection]:
        r: list[GateRejection] = []

        if not isinstance(patch.op, OpCode):
            r.append(GateRejection(patch.id, "invalid_opcode",
                     f"unknown: {patch.op}", "use valid OpCode"))
            return r

        if patch.op not in _NO_TARGET and state.get_event(patch.target_id) is None:
            r.append(GateRejection(patch.id, "target_not_found",
                     f"id={patch.target_id}", "create segment first"))

        if not (0.0 <= patch.confidence <= 1.0):
            r.append(GateRejection(patch.id, "invalid_confidence",
                     f"conf={patch.confidence}", "must be [0,1]"))

        if patch.idempotency_key:
            for es in state.event_states.values():
                if any(e.idempotency_key == patch.idempotency_key for e in es.patches):
                    r.append(GateRejection(patch.id, "duplicate_idempotency",
                             f"key={patch.idempotency_key}", "skip or new key"))
                    return r

        for field in _REQUIRED.get(patch.op, []):
            if field not in patch.value:
                r.append(GateRejection(patch.id, "missing_field",
                         f"op={patch.op.value} needs '{field}'",
                         f"add '{field}' to value"))

        return r

    def validate_many(self, patches: list[Patch],
                      state: TimelineProjectState) -> dict[str, list[GateRejection]]:
        result: dict[str, list[GateRejection]] = {}
        for p in patches:
            rejections = self.validate(p, state)
            if rejections:
                result[p.id] = rejections
        return result
