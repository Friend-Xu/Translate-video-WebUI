"""
EdgeTTSCompositePass — Edge TTS 最后兜底层编排 (Chapter 9 §9.1-9.11)

编织 EdgeTTSAdapter + EdgeTTSScorer。
Edge TTS 是最后一道防线——仅在所有主引擎 + OpenVoice 全部失败后运行。

与 Ch5-8 CompositePass 的核心差异:
  - depends_on = [] — 无依赖，最后防线
  - 无 DurationControl, EmotionModeler, VoiceMemoryIndex, FallbackDecider
  - 评分阈值最低: 0.55
  - 不维护任何 history（Edge TTS 输出不参与后续优化）
"""
from __future__ import annotations
from core.engine.pass_base import TimelinePass
from core.runtime.project_state import TimelineProjectState
from core.runtime.patch_engine import PatchEngine
from core.adapters.edge_tts_adapter import EdgeTTSAdapter, EdgeTTSSegmentContext
from core.scoring.edge_tts_scorer import EdgeTTSScorer


class EdgeTTSCompositePass(TimelinePass):
    """Edge TTS 最后兜底层编排。

    触发条件:
      1. segment 没有任何有效 TTS 输出（主引擎 + OpenVoice 全部失败）
      2. 或 es.runtime["tts_status"] in ("fallback_rejected", "rejected")
    """

    name = "edge_tts_composite"
    depends_on = []  # 无依赖，最后防线

    def __init__(self, output_dir: str = "",
                 default_lang: str = ""):
        self.output_dir = output_dir
        self.default_lang = default_lang

    def apply(self, state: TimelineProjectState) -> TimelineProjectState:
        engine = PatchEngine()
        scorer = EdgeTTSScorer()

        # 收集仍无有效 TTS 输出的 segment
        unvoiced = [
            es for es in state.sorted_events()
            if not es.tts.get("audio_ref")
            or es.tts.get("transfer_status") == "failed"
        ]

        if not unvoiced:
            return state

        for es in unvoiced:
            # 确定 fallback_reason
            tts_status = es.runtime.get("tts_status", "")
            if tts_status == "fallback_rejected":
                reason = "openvoice_fallback_failed"
            elif tts_status == "rejected":
                reason = "all_primary_failed"
            else:
                reason = "no_tts_output"

            # 构建最简 context
            trans_raw = es.translation
            trans_lang = trans_raw.get("lang", "") if isinstance(trans_raw, dict) else ""
            lang = trans_lang or self.default_lang
            translation_text = (trans_raw.get("text", "") if isinstance(trans_raw, dict) else str(trans_raw or "")) or es.ir.text_ref
            ctx = EdgeTTSSegmentContext(
                segment_id=es.id,
                translation_text=translation_text,
                lang=lang,
                duration_target=es.end - es.start,
                fallback_reason=reason,
            )

            if not ctx.translation_text:
                continue

            # SYNTHESIZE
            adapter = EdgeTTSAdapter(output_dir=self.output_dir)
            patch = adapter.synthesize(ctx)

            # SCORE
            score = scorer.score(ctx, patch)
            patch.confidence = score.composite

            if score.accepted:
                engine.apply(state, patch)
                es.provenance["edge_tts_score"] = score.composite
                es.provenance["edge_tts_detail"] = {
                    "availability": score.availability,
                    "duration_fit": score.duration_fit,
                    "language_match": score.language_match,
                }
                es.runtime["tts_status"] = "edge_tts_fallback"
                es.runtime["generation_mode"] = "fallback"
                es.runtime["fallback_reason"] = reason
            else:
                es.runtime["tts_status"] = "edge_tts_rejected"
                es.runtime["edge_tts_reject_reason"] = f"composite={score.composite:.2f}"

        return state
