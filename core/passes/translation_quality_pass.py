"""
TranslationQualityPass — 翻译质量评估编排 (Chapter 14 §14.6-14.7)
"""
from __future__ import annotations
from core.engine.pass_base import TimelinePass
from core.runtime import TimelineProjectState, PatchEngine


class TranslationQualityPass(TimelinePass):

    name = "translation_quality"
    depends_on = ["llm_translation"]

    def __init__(self, skip_minilm: bool = False, skip_ppl: bool = False,
                 auto_retry: bool = False, semantic_threshold: float = 0.70,
                 naturalness_threshold: float = 3.0):
        self.skip_minilm = skip_minilm
        self.skip_ppl = skip_ppl
        self.auto_retry = auto_retry
        self.semantic_threshold = semantic_threshold
        self.naturalness_threshold = naturalness_threshold

    def apply(self, state: TimelineProjectState) -> TimelineProjectState:
        from core.adapters.minilm_adapter import MiniLMAdapter, MiniLMContext
        from core.adapters.ppl_adapter import PPLAdapter, PPLContext
        from core.scoring.translation_scorer import TranslationScorer

        engine = PatchEngine()
        scorer = TranslationScorer()

        segments = []
        for es in state.sorted_events():
            text = es.ir.text_ref or ""
            raw_trans = es.translation
            if isinstance(raw_trans, dict):
                trans = raw_trans.get("text", "")
            else:
                trans = raw_trans or es.derivatives.get("translation", "")
            if not isinstance(trans, str):
                trans = str(trans)
            if trans and text:
                segments.append((es.id, text, trans))

        if not segments:
            return state

        if not self.skip_minilm:
            minilm = MiniLMAdapter()
            for seg_id, src, trans in segments:
                engine.apply(state, minilm.verify(MiniLMContext(
                    source_text=src, translated_text=trans,
                    threshold=self.semantic_threshold, segment_id=seg_id,
                )))

        if not self.skip_ppl:
            ppl = PPLAdapter()
            texts = [t for _, _, t in segments]
            baseline = ppl.compute_baseline(texts)
            for seg_id, _, trans in segments:
                engine.apply(state, ppl.evaluate(PPLContext(
                    text=trans, baseline_ppl=baseline,
                    threshold_ratio=self.naturalness_threshold,
                    segment_id=seg_id,
                )))

        for seg_id, src, trans in segments:
            es = state.get_event(seg_id)
            if es is None:
                continue
            trans_slot = es.translation
            trans_dict = trans_slot if isinstance(trans_slot, dict) else {"text": trans_slot}
            sim = trans_dict.get("similarity", 0.0)
            ts = scorer.score(
                semantic_similarity=sim,
                ppl_ratio=trans_dict.get("ppl_ratio"),
                source_len=len(src), target_len=len(trans),
            )
            es.translation["quality_score"] = ts.composite
            es.provenance["translation_quality"] = {
                "composite": ts.composite,
                "gate_decision": ts.gate_decision,
                "accepted": ts.accepted,
            }
            # Gate 路由映射: WorkflowOrchestrator 读取 A/B/C
            if ts.accepted:
                es.provenance["gate_decision"] = "A"
            else:
                es.provenance["gate_decision"] = "B" if ts.composite > 0.4 else "C"
            if ts.hard_fail_reason:
                es.review.setdefault("flags", []).append("translation_hard_fail")
                es.review["notes"] = (es.review.get("notes", "") +
                                      f"; {ts.hard_fail_reason}")

        return state
