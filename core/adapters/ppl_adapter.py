"""
PPLAdapter — 自然度评估适配器 (Chapter 14 §14.4)

封装 pipeline/ppl_evaluator.py PPLEvaluator → ANNOTATE patch
"""
from __future__ import annotations
from dataclasses import dataclass
from core.runtime.patch import Patch, OpCode


@dataclass
class PPLContext:
    text: str
    baseline_ppl: float | None = None
    threshold_ratio: float = 3.0
    segment_id: str = ""


class PPLAdapter:

    def __init__(self):
        self._evaluator = None

    def _get_evaluator(self):
        if self._evaluator is None:
            from pipeline.ppl_evaluator import PPLEvaluator
            self._evaluator = PPLEvaluator()
        return self._evaluator

    def evaluate(self, ctx: PPLContext) -> Patch:
        ev = self._get_evaluator()
        try:
            ppl = ev.perplexity(ctx.text)
        except Exception:
            ppl = float("inf")

        ratio = ppl / ctx.baseline_ppl if ctx.baseline_ppl and ctx.baseline_ppl > 0 else 1.0
        flagged = ratio > ctx.threshold_ratio

        return Patch(
            id=f"ppl_{ctx.segment_id}", target_id=ctx.segment_id,
            op=OpCode.ANNOTATE,
            value={
                "translation": {
                    "ppl": round(ppl, 2), "ppl_ratio": round(ratio, 4),
                    "naturalness_flagged": flagged,
                },
                "provenance": {
                    "gate_naturalness": {
                        "model": "Qwen2-0.5B", "ppl": round(ppl, 2),
                        "baseline_ppl": ctx.baseline_ppl,
                        "ratio": round(ratio, 4),
                        "threshold": ctx.threshold_ratio, "flagged": flagged,
                    },
                },
            },
            confidence=round(max(0.0, 1.0 - ratio / 10.0), 4),
            author="system",
        )

    def compute_baseline(self, texts: list[str]) -> float:
        if not texts:
            return 0.0
        ev = self._get_evaluator()
        try:
            ppls = [ev.perplexity(t) for t in texts]
        except Exception:
            return 0.0
        ppls = sorted(p for p in ppls if p > 0)
        if not ppls:
            return 0.0
        top_n = max(1, len(ppls) // 3)
        return ppls[top_n // 2] if top_n > 1 else ppls[0]

    def batch_evaluate(self, texts: list[str], segment_ids: list[str],
                       baseline: float | None = None) -> list[Patch]:
        if not texts:
            return []
        bl = baseline or self.compute_baseline(texts)
        return [
            self.evaluate(PPLContext(text=t, baseline_ppl=bl, segment_id=sid))
            for t, sid in zip(texts, segment_ids)
        ]
