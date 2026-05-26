"""
PatchPlanner — 评分信号 → Patch 计划 (Chapter 12 §)

Logic Gate accept/repair/downgrade/retry/manual_review → Patch list
"""
from __future__ import annotations
import time as _time
from core.runtime.patch import Patch, OpCode
from core.runtime.project_state import TimelineProjectState


class PatchPlanner:

    def plan(self, signals: dict, state: TimelineProjectState) -> list[Patch]:
        """signals: {seg_id: {score, accept, repair, downgrade, retry, manual_review, engine, ...}}"""
        patches: list[Patch] = []
        ts = _time.time()

        for seg_id, sig in signals.items():
            if sig.get("accept"):
                patches.append(Patch(
                    id=f"plan_accept_{seg_id}", target_id=seg_id,
                    op=OpCode.ANNOTATE,
                    value={
                        "provenance": {
                            "gate_decision": "accept",
                            "engine": sig.get("engine", "unknown"),
                            "score": sig.get("score", 0.0),
                        },
                        "runtime": {"status": "accepted"},
                    },
                    confidence=sig.get("score", 0.5),
                    reason=["logic_gate_accept"],
                ))
            elif sig.get("downgrade"):
                patches.append(Patch(
                    id=f"plan_downgrade_{seg_id}", target_id=seg_id,
                    op=OpCode.UPDATE_TTS_AUDIO,
                    value={
                        "generation_mode": "fallback",
                        "engine": sig.get("engine", "edge_tts"),
                    },
                    confidence=sig.get("score", 0.3),
                    reason=["downgrade_fallback"],
                ))
            elif sig.get("manual_review"):
                patches.append(Patch(
                    id=f"plan_review_{seg_id}", target_id=seg_id,
                    op=OpCode.ANNOTATE,
                    value={
                        "review": {"flags": ["needs_human_review"],
                                   "notes": sig.get("reason", "")},
                        "runtime": {"status": "pending_review"},
                    },
                    confidence=sig.get("score", 0.3),
                    reason=["manual_review_required"],
                ))
            elif sig.get("repair"):
                patches.append(Patch(
                    id=f"plan_repair_{seg_id}", target_id=seg_id,
                    op=OpCode.ANNOTATE,
                    value={"runtime": {"status": "repairing"}},
                    confidence=sig.get("score", 0.4),
                    reason=["repair_needed"],
                ))
        return patches
