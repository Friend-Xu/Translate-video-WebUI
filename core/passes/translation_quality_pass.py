"""
TranslationQualityPass — 翻译质量评估编排 (Chapter 14 §14.6-14.7)

v2.0: 解耦评分引擎 — 接受 QualityStrategy 而非硬编码 MiniLM+PPL。
用户可在配置中选择 "logic_gate" 或 "xcomet"，门控路由逻辑不变。
"""
from __future__ import annotations
from core.engine.pass_base import TimelinePass
from core.runtime import TimelineProjectState, PatchEngine
from core.quality.protocol import QualityStrategy, QualityVerdict


class TranslationQualityPass(TimelinePass):
    """翻译质量评估 — 策略可插拔"""

    name = "translation_quality"
    depends_on = ["llm_translation"]

    def __init__(self, quality_strategy: QualityStrategy | None = None,
                 skip_minilm: bool = False, skip_ppl: bool = False,
                 auto_retry: bool = False, semantic_threshold: float = 0.70,
                 naturalness_threshold: float = 3.0):
        self._strategy = quality_strategy
        # 保留旧参数签名用于向后兼容 — 当 strategy 为 None 时自动用 logic_gate
        self._skip_minilm = skip_minilm
        self._skip_ppl = skip_ppl

    def configure(self, resolved_config: dict | None = None) -> None:
        if resolved_config and "quality_strategy" in resolved_config:
            self._strategy = resolved_config["quality_strategy"]

    def apply(self, state: TimelineProjectState) -> TimelineProjectState:
        strategy = self._strategy
        if strategy is None:
            from core.quality.protocol import create_strategy
            strategy = create_strategy("logic_gate")

        try:
            strategy.warmup()
        except Exception:
            pass

        verdicts = strategy.score_batch(state)

        for es in state.sorted_events():
            verdict = verdicts.get(es.id)
            if verdict is None:
                continue
            es.review.gate_decision = verdict.gate_decision
            es.translation.quality_score = verdict.score
            if verdict.sub_scores:
                # 子评分并入 provenance.translation_quality (类型化后 translation 槽无动态 key)
                tq = es.provenance.setdefault("translation_quality", {})
                tq.update(verdict.sub_scores)
            if verdict.needs_human:
                es.review.needs_human_review = True

        return state
