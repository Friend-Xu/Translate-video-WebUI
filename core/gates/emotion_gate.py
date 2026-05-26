"""
EmotionGate — 情感门控 (Chapter 15 §15.6)
E1:情感断裂 E2:置信度 E3:说话人-情感冲突 | strict/relaxed
"""
from __future__ import annotations
from dataclasses import dataclass, field
from core.emotion.emotion_space import EmotionVector


@dataclass
class EmotionGateResult:
    accepted: bool; decision: str; reason: str
    scores: dict = field(default_factory=dict)
    gate_trace: dict = field(default_factory=dict)


class EmotionGate:

    def __init__(self, max_break: float = 1.5, min_confidence: float = 0.3,
                 max_conflict: float = 1.0, mode: str = "strict"):
        self.max_break = max_break; self.min_confidence = min_confidence
        self.max_conflict = max_conflict; self.mode = mode

    def decide(self, cur: EmotionVector, prev: EmotionVector | None = None,
               spk: EmotionVector | None = None) -> EmotionGateResult:
        return self._relaxed(cur) if self.mode == "relaxed" else self._strict(cur, prev, spk)

    def _strict(self, cur, prev, spk) -> EmotionGateResult:
        t = {"mode": "strict", "gates_checked": ["E2"]}
        if cur.confidence < self.min_confidence:
            return EmotionGateResult(False, "downgrade", "low_confidence",
                                     {"confidence": cur.confidence}, {**t, "E2": "FAIL"})
        t["E2"] = "PASS"
        if prev is not None:
            t["gates_checked"].append("E1"); d = cur.distance(prev)
            if d > self.max_break:
                return EmotionGateResult(False, "repair", "emotion_break",
                                         {"vad_distance": round(d, 4)}, {**t, "E1": "FAIL"})
            t["E1"] = "PASS"
        if spk is not None:
            t["gates_checked"].append("E3"); d = cur.distance(spk)
            if d > self.max_conflict:
                return EmotionGateResult(False, "downgrade", "speaker_emotion_conflict",
                                         {"conflict_distance": round(d, 4)}, {**t, "E3": "FAIL"})
            t["E3"] = "PASS"
        return EmotionGateResult(True, "accept", "all_passed",
                                 {"confidence": cur.confidence}, t)

    def _relaxed(self, cur) -> EmotionGateResult:
        t = {"mode": "relaxed", "gates_checked": ["E2"]}
        if cur.confidence < self.min_confidence:
            return EmotionGateResult(False, "downgrade", "low_confidence",
                                     {"confidence": cur.confidence}, {**t, "E2": "FAIL"})
        return EmotionGateResult(True, "accept", "confidence_ok",
                                 {"confidence": cur.confidence}, {**t, "E2": "PASS"})
