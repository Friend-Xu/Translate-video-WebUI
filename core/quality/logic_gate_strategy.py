"""
LogicGateStrategy — 逻辑门控策略 (MiniLM + PPL + TranslationScorer)

将现有 TranslationQualityPass 的评分逻辑提取为可插拔策略。
零行为变更 — 输出与当前一致的 gate_decision。

注册名: "logic_gate"
"""
from __future__ import annotations
from typing import TYPE_CHECKING

from core.quality.protocol import (
    QualityStrategy, QualityVerdict, ThresholdConfig, register_strategy,
)

if TYPE_CHECKING:
    from core.runtime.project_state import TimelineProjectState
    from core.config.global_config import GlobalConfig


@register_strategy("logic_gate")
class LogicGateStrategy(QualityStrategy):
    """逻辑门控 — MiniLM 语义相似度 + PPL 自然度 + 加权评分"""

    name = "logic_gate"

    def __init__(
        self,
        thresholds: ThresholdConfig | None = None,
        semantic_threshold: float = 0.70,
        sim_drop_limit: float = 0.05,
        skip_minilm: bool = False,
        skip_ppl: bool = False,
    ):
        self._thresholds = thresholds or ThresholdConfig(accept=0.65, review=0.50)
        self._semantic_threshold = semantic_threshold
        self._sim_drop_limit = sim_drop_limit
        self._skip_minilm = skip_minilm
        self._skip_ppl = skip_ppl
        self._mini_lm = None
        self._ppl = None
        self._scorer = None

    @property
    def thresholds(self) -> ThresholdConfig:
        return self._thresholds

    @classmethod
    def from_config(cls, config: "GlobalConfig | None" = None) -> "LogicGateStrategy":
        t = ThresholdConfig(accept=0.65, review=0.50)
        semantic_threshold = 0.70
        sim_drop_limit = 0.05
        if config is not None:
            gate_cfg = config.project.translation.get("gate", {})
            t.accept = gate_cfg.get("threshold_accept", 0.65)
            t.review = gate_cfg.get("threshold_reject", 0.50)
            semantic_threshold = gate_cfg.get("semantic_threshold", 0.70)
            sim_drop_limit = gate_cfg.get("sim_drop_limit", 0.05)
        return cls(thresholds=t, semantic_threshold=semantic_threshold,
                   sim_drop_limit=sim_drop_limit)

    def warmup(self) -> None:
        from core.adapters.minilm_adapter import MiniLMAdapter
        from core.adapters.ppl_adapter import PPLAdapter
        from core.scoring.translation_scorer import TranslationScorer
        self._mini_lm = MiniLMAdapter()
        self._ppl = PPLAdapter()
        self._scorer = TranslationScorer()

    def score_batch(
        self, state: "TimelineProjectState",
    ) -> dict[str, QualityVerdict]:
        from core.adapters.minilm_adapter import MiniLMContext
        from core.adapters.ppl_adapter import PPLContext
        from core.runtime.patch_engine import PatchEngine

        engine = PatchEngine()
        results: dict[str, QualityVerdict] = {}

        # 收集 segments
        segments = []
        for es in state.sorted_events():
            text = es.ir.text_ref or ""
            raw_trans = es.translation
            if isinstance(raw_trans, dict):
                trans_text = raw_trans.get("text", "")
            else:
                trans_text = raw_trans or ""
            if trans_text and text:
                segments.append((es.id, text, trans_text))

        if not segments:
            return results

        # MiniLM 语义相似度
        sim_map: dict[str, float] = {}
        if not self._skip_minilm and self._mini_lm:
            patches = self._mini_lm.batch_verify(
                [(src, trans, seg_id) for seg_id, src, trans in segments],
            )
            for patch in patches:
                engine.apply(state, patch)
                seg_id = patch.target_id
                trans_data = patch.value.get("translation", {})
                sim_map[seg_id] = trans_data.get("similarity", 0.0)
            # 对 batch_verify 未覆盖的 segments 补充
            for seg_id, src, trans in segments:
                if seg_id not in sim_map:
                    try:
                        patch = self._mini_lm.verify(MiniLMContext(
                            source_text=src, translated_text=trans,
                            threshold=self._semantic_threshold, segment_id=seg_id,
                        ))
                        engine.apply(state, patch)
                        trans_data = patch.value.get("translation", {})
                        sim_map[seg_id] = trans_data.get("similarity", 0.0)
                    except Exception:
                        sim_map[seg_id] = 0.0

        # PPL 自然度
        ppl_map: dict[str, float] = {}
        if not self._skip_ppl and self._ppl:
            texts = [t for _, _, t in segments]
            try:
                baseline = self._ppl.compute_baseline(texts) if hasattr(self._ppl, 'compute_baseline') else None
            except Exception:
                baseline = None
            for seg_id, _, trans in segments:
                try:
                    patch = self._ppl.evaluate(PPLContext(
                        text=trans, baseline_ppl=baseline, segment_id=seg_id,
                    ))
                    engine.apply(state, patch)
                    ppl_map[seg_id] = patch.value.get("ppl_ratio", 1.0)
                except Exception:
                    ppl_map[seg_id] = 1.0

        # TranslationScorer 加权评分
        for seg_id, src, trans in segments:
            es = state.get_event(seg_id)
            if es is None:
                continue

            sim = sim_map.get(seg_id, 0.0)
            ppl_ratio = ppl_map.get(seg_id, None)
            ts = self._scorer.score(
                semantic_similarity=sim,
                ppl_ratio=ppl_ratio,
                source_len=len(src),
                target_len=len(trans),
            )

            # 更新 event state — 与旧 TranslationQualityPass 行为一致
            trans_slot = es.translation
            if isinstance(trans_slot, str):
                es._data["translation"] = {"text": trans_slot}
            es.translation["quality_score"] = ts.composite
            es.translation["similarity"] = sim
            if ppl_ratio is not None:
                es.translation["ppl_ratio"] = round(ppl_ratio, 4)
            es.provenance["translation_quality"] = {
                "composite": ts.composite,
                "gate_decision": ts.gate_decision,
                "accepted": ts.accepted,
            }

            # Gate 决策
            if ts.accepted:
                es.review["gate_decision"] = "A"
            else:
                es.review["gate_decision"] = "B" if ts.composite > 0.4 else "C"
            if ts.hard_fail_reason:
                es.review.setdefault("flags", []).append("translation_hard_fail")
                es.review["notes"] = (es.review.get("notes", "") +
                                      f"; {ts.hard_fail_reason}")

            verdict = QualityVerdict.from_score(
                ts.composite, self._thresholds, self.name,
            )
            verdict.sub_scores = {
                "semantic_similarity": sim,
                "fluency_score": ts.fluency_score,
                "faithfulness_score": ts.faithfulness_score,
                "length_ratio": ts.length_ratio,
                "temporal_fit": ts.temporal_fit,
            }
            verdict.reason = f"composite={ts.composite:.3f}, accepted={ts.accepted}"
            results[seg_id] = verdict

        return results
