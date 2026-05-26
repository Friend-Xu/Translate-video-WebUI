"""
TranslationScorer — 文本联合评分器 (Chapter 14 §14.6)

5 维度加权 + 硬门槛 → composite ∈ [0,1]
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class TranslationScore:
    semantic_similarity: float = 0.0
    fluency_score: float = 0.0
    faithfulness_score: float = 0.0
    length_ratio: float = 1.0
    temporal_fit: float = 1.0
    accepted: bool = False
    gate_decision: str = ""
    composite: float = 0.0
    hard_fail_reason: str = ""

    def __post_init__(self):
        if not self.gate_decision and self.accepted:
            self.gate_decision = "accept"


class TranslationScorer:
    """文本质量联合评分器。

    硬门槛: semantic < 0.50 → reject, PPL_ratio > 5.0 → reject,
            length_ratio > 3.0 or < 0.3 → mark review
    """

    DEFAULT_WEIGHTS = {
        "semantic": 0.25, "fluency": 0.25, "faithfulness": 0.20,
        "temporal_fit": 0.20, "length_ratio": 0.10,
    }
    ACCEPT_THRESHOLD = 0.65
    HARD_MIN_SIMILARITY = 0.50
    HARD_MAX_PPL_RATIO = 5.0
    HARD_MAX_LENGTH_RATIO = 3.0
    HARD_MIN_LENGTH_RATIO = 0.3

    def __init__(self, weights: dict | None = None):
        self.weights = weights or dict(self.DEFAULT_WEIGHTS)

    def score(
        self,
        semantic_similarity: float,
        ppl_ratio: float | None = None,
        faithfulness: float = 0.0,
        source_len: int = 0,
        target_len: int = 0,
        segment_duration: float = 0.0,
    ) -> TranslationScore:
        s = TranslationScore()
        s.semantic_similarity = semantic_similarity

        if semantic_similarity < self.HARD_MIN_SIMILARITY:
            s.hard_fail_reason = f"semantic too low: {semantic_similarity:.2f}"
            return s

        if ppl_ratio is not None:
            if ppl_ratio > self.HARD_MAX_PPL_RATIO:
                s.hard_fail_reason = f"PPL ratio too high: {ppl_ratio:.1f}"
                return s
            s.fluency_score = round(1.0 / (1.0 + ppl_ratio), 4)

        s.faithfulness_score = faithfulness

        if source_len > 0 and target_len > 0:
            s.length_ratio = round(target_len / source_len, 3)
            if s.length_ratio > self.HARD_MAX_LENGTH_RATIO:
                s.hard_fail_reason = f"length ratio too high: {s.length_ratio}"
            elif s.length_ratio < self.HARD_MIN_LENGTH_RATIO:
                s.hard_fail_reason = f"length ratio too low: {s.length_ratio}"
            s.temporal_fit = round(
                1.0 - min(abs(s.length_ratio - 1.0) / 2.0, 1.0), 4,
            )

        if s.hard_fail_reason:
            return s

        s.composite = round(
            self.weights["semantic"] * semantic_similarity
            + self.weights["fluency"] * s.fluency_score
            + self.weights["faithfulness"] * faithfulness
            + self.weights["temporal_fit"] * s.temporal_fit
            + self.weights["length_ratio"] * s.length_ratio,
            4,
        )

        s.accepted = s.composite >= self.ACCEPT_THRESHOLD
        s.gate_decision = (
            "accept" if s.accepted
            else "repair" if s.composite >= self.ACCEPT_THRESHOLD - 0.15
            else "review"
        )
        return s

    def score_batch(self, segments: list[dict]) -> list[TranslationScore]:
        return [self.score(**seg) for seg in segments]
