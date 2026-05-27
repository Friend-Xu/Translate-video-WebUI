"""
MiniLMAdapter — 语义相似度适配器 (Chapter 14 §14.5)

封装 SRT/TranslationVerifier.py CrossLingualScorer → ANNOTATE patch
"""
from __future__ import annotations
from dataclasses import dataclass
from core.runtime.patch import Patch, OpCode


@dataclass
class MiniLMContext:
    source_text: str
    translated_text: str
    threshold: float = 0.70
    segment_id: str = ""


class MiniLMAdapter:

    def __init__(self):
        self._scorer = None

    def _get_scorer(self):
        if self._scorer is None:
            from SRT.TranslationVerifier import CrossLingualScorer
            self._scorer = CrossLingualScorer()
        return self._scorer

    def configure(self, event_config = None):
        if not event_config: return
        if "gate_threshold_accept" in event_config: self._threshold = event_config["gate_threshold_accept"]
        if "gate_sim_drop_limit" in event_config: self._sim_drop = event_config["gate_sim_drop_limit"]
    def verify(self, ctx: MiniLMContext) -> Patch:
        scorer = self._get_scorer()
        try:
            sim = scorer.similarity(ctx.source_text, ctx.translated_text)
        except Exception:
            sim = 0.0
        flagged = sim < ctx.threshold
        return Patch(
            id=f"minilm_{ctx.segment_id}", target_id=ctx.segment_id,
            op=OpCode.ANNOTATE,
            value={
                "translation": {"similarity": round(sim, 4), "flagged": flagged},
                "provenance": {
                    "gate_semantic": {
                        "model": "paraphrase-multilingual-MiniLM-L12-v2",
                        "similarity": round(sim, 4),
                        "threshold": ctx.threshold, "flagged": flagged,
                    },
                },
            },
            confidence=round(sim, 4), author="system",
        )

    def batch_verify(self, pairs: list[tuple[str, str, str]]) -> list[Patch]:
        if not pairs:
            return []
        scorer = self._get_scorer()
        try:
            sims = scorer.batch_similarity([(s, t) for s, t, _ in pairs])
        except Exception:
            sims = [0.0] * len(pairs)
        patches = []
        for i, (src, tgt, seg_id) in enumerate(pairs):
            sim = sims[i]
            flagged = sim < 0.70
            patches.append(Patch(
                id=f"minilm_{seg_id}", target_id=seg_id,
                op=OpCode.ANNOTATE,
                value={
                    "translation": {"similarity": round(sim, 4), "flagged": flagged},
                    "provenance": {
                        "gate_semantic": {
                            "model": "paraphrase-multilingual-MiniLM-L12-v2",
                            "similarity": round(sim, 4),
                            "threshold": 0.70, "flagged": flagged,
                        },
                    },
                },
                confidence=round(sim, 4), author="system",
            ))
        return patches
