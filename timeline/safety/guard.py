"""
TASK 14 — Apply Validator Gate. Final safety check before patch apply.
"""
from __future__ import annotations

from timeline.patch.model import TimelinePatch
from timeline.patch.opcode import is_valid_opcode


class GateRejection(Exception):
    def __init__(self, rule: str, detail: str):
        self.rule = rule
        self.detail = detail
        super().__init__(f"[{rule}] {detail}")


def gate_check(
    patch: TimelinePatch,
    timeline_before: list[dict],
    acoustic_speakers: dict[str, str] | None = None,
) -> None:
    # 1. No unknown opcode
    if not is_valid_opcode(patch.opcode.value):
        raise GateRejection("unknown_opcode", f"'{patch.opcode.value}' not in allowed set")

    # 2. Targets must exist
    existing_ids = {s["id"] for s in timeline_before}
    for tid in patch.targets:
        if tid not in existing_ids:
            raise GateRejection("invalid_target", f"segment '{tid}' not found")

    # 3. Confidence bounds
    if not (0.0 <= patch.confidence <= 1.0):
        raise GateRejection("invalid_confidence", f"{patch.confidence} out of [0,1]")
