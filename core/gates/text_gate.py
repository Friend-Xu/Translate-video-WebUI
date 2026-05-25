"""
TextGate — 文本层三门决策器 (Chapter 14 §14.6)

Gate A — 语义安全 | Gate C — 内容保真 | Gate B — 自然度提升
两模式: logic_gate (A AND C AND B) | joint_formula (beta*(1-ratio)+gamma*sim)
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class TextGateResult:
    accepted: bool
    decision: str
    kept_version: str
    reason: str
    scores: dict = field(default_factory=dict)
    gate_trace: dict = field(default_factory=dict)


class TextGate:

    def __init__(self, semantic_threshold: float = 0.70,
                 sim_drop_limit: float = 0.05, mode: str = "logic_gate",
                 beta: float = 0.6, gamma: float = 0.4):
        self.semantic_threshold = semantic_threshold
        self.sim_drop_limit = sim_drop_limit
        self.mode = mode
        self.beta = beta
        self.gamma = gamma

    def decide(self, old_sim: float, new_sim: float,
               old_ppl_ratio: float, new_ppl_ratio: float) -> TextGateResult:
        if self.mode == "joint_formula":
            return self._joint(old_sim, new_sim, old_ppl_ratio, new_ppl_ratio)
        return self._logic(old_sim, new_sim, old_ppl_ratio, new_ppl_ratio)

    def decide_with_scores(self, old_score, new_score) -> TextGateResult:
        old_r = (1.0 / max(old_score.fluency_score, 0.001) - 1.0) if old_score.fluency_score > 0 else 1.0
        new_r = (1.0 / max(new_score.fluency_score, 0.001) - 1.0) if new_score.fluency_score > 0 else 1.0
        return self.decide(old_score.semantic_similarity, new_score.semantic_similarity, old_r, new_r)

    def _logic(self, old_sim, new_sim, old_ratio, new_ratio) -> TextGateResult:
        t = {"mode": "logic_gate", "gates_checked": []}
        t["gates_checked"].append("A")
        if new_sim < self.semantic_threshold:
            t["gate_A"] = "FAIL"
            return TextGateResult(False, "retry", "original", "semantic_drift",
                                  {"old_sim": old_sim, "new_sim": new_sim}, t)
        t["gate_A"] = "PASS"
        if self.sim_drop_limit > 0:
            t["gates_checked"].append("C")
            if new_sim < old_sim - self.sim_drop_limit:
                t["gate_C"] = "FAIL"
                return TextGateResult(False, "retry", "original", "content_degraded",
                                      {"old_sim": old_sim, "new_sim": new_sim,
                                       "sim_drop": round(old_sim - new_sim, 4)}, t)
            t["gate_C"] = "PASS"
        t["gates_checked"].append("B")
        if new_ratio < old_ratio:
            t["gate_B"] = "PASS"
            return TextGateResult(True, "accept", "retry", "naturalness_improved",
                                  {"old_sim": old_sim, "new_sim": new_sim,
                                   "old_ratio": old_ratio, "new_ratio": new_ratio}, t)
        t["gate_B"] = "FAIL"
        return TextGateResult(False, "retry", "original", "no_naturalness_gain",
                              {"old_sim": old_sim, "new_sim": new_sim,
                               "old_ratio": old_ratio, "new_ratio": new_ratio}, t)

    def _joint(self, old_sim, new_sim, old_ratio, new_ratio) -> TextGateResult:
        if new_sim < self.semantic_threshold:
            return TextGateResult(False, "retry", "original", "semantic_drift",
                                  {"old_sim": old_sim, "new_sim": new_sim},
                                  {"gate_A": "FAIL"})
        old_s = self.beta * (1.0 - min(old_ratio, 1.0)) + self.gamma * old_sim
        new_s = self.beta * (1.0 - min(new_ratio, 1.0)) + self.gamma * new_sim
        t = {"mode": "joint_formula", "old_joint": round(old_s, 4),
             "new_joint": round(new_s, 4)}
        if new_s > old_s:
            return TextGateResult(True, "accept", "retry", "joint_improved",
                                  {"old_joint": round(old_s, 4), "new_joint": round(new_s, 4)}, t)
        return TextGateResult(False, "retry", "original", "no_joint_improvement",
                              {"old_joint": round(old_s, 4), "new_joint": round(new_s, 4)}, t)
