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
from core.tts.duration_control import SpeedDecision


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

        unvoiced = [
            es for es in state.sorted_events()
            if not es.tts.get("audio_ref")
            or es.tts.get("transfer_status") == "failed"
        ]

        if not unvoiced:
            return state

        adjuster = self._get_timing_adjuster()

        for es in unvoiced:
            tts_status = es.runtime.get("tts_status", "")
            if tts_status == "fallback_rejected":
                reason = "openvoice_fallback_failed"
            elif tts_status == "rejected":
                reason = "all_primary_failed"
            else:
                reason = "no_tts_output"

            trans_raw = es.translation
            trans_lang = trans_raw.get("lang", "") if isinstance(trans_raw, dict) else ""
            lang = trans_lang or self.default_lang
            translation_text = (trans_raw.get("text", "") if isinstance(trans_raw, dict) else str(trans_raw or "")) or es.ir.text_ref
            target_dur = es.end - es.start
            ctx = EdgeTTSSegmentContext(
                segment_id=es.id,
                translation_text=translation_text,
                lang=lang,
                duration_target=target_dur,
                fallback_reason=reason,
            )

            if not ctx.translation_text:
                continue

            patch, sd = self._synthesize_with_search(ctx, adjuster, target_dur)
            es.tts["speed_decision"] = sd.as_dict()

            # ── LUFS 归一化 ──
            import os as _os
            from pipeline.loudness import normalize_segment_loudness
            audio_path = patch.value.get("audio_ref", "")
            if audio_path:
                if not _os.path.isabs(audio_path):
                    audio_path = _os.path.join(self.output_dir, audio_path)
                if _os.path.isfile(audio_path):
                    normalize_segment_loudness(audio_path, target_lufs=-16.0)

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

    @staticmethod
    def _get_timing_adjuster():
        from pipeline.tts_timing import TimingAdjuster
        return TimingAdjuster(speed_max=70, base_speed=30, search_method="binary")

    def _synthesize_with_search(self, ctx, adjuster, target_dur):
        """合成 Edge TTS 音频，若时长超标则二分搜索最优 rate。"""
        adapter = EdgeTTSAdapter(output_dir=self.output_dir)
        ctx.rate = "+0%"
        patch = adapter.synthesize(ctx)
        actual = patch.value.get("duration", target_dur)

        if target_dur <= 0:
            return patch, SpeedDecision(original_duration=actual, final_duration=actual)

        deviation = abs(actual - target_dur) / target_dur
        if actual <= target_dur or deviation <= 0.15:
            return patch, SpeedDecision(
                strategy="accept", original_duration=actual,
                final_duration=actual, deviation=deviation,
            )

        init_speed = adjuster._calc_initial_speed(actual, target_dur)
        search_iterations = 0

        def _synth_at_rate(rate_str):
            nonlocal search_iterations
            search_iterations += 1
            a = EdgeTTSAdapter(output_dir=self.output_dir)
            c = EdgeTTSSegmentContext(
                segment_id=ctx.segment_id,
                translation_text=ctx.translation_text,
                lang=ctx.lang,
                duration_target=target_dur,
                rate=rate_str,
            )
            return a.synthesize(c)

        # 试下限: 如果能 fit，直接返回
        rate_lo = f"+{init_speed}%"
        patch_lo = _synth_at_rate(rate_lo)
        dur_lo = patch_lo.value.get("duration", target_dur)
        if dur_lo <= target_dur:
            return patch_lo, SpeedDecision(
                strategy="accept", original_duration=actual,
                final_duration=dur_lo, tts_rate=rate_lo,
                search_method="binary", search_iterations=search_iterations,
                deviation=abs(dur_lo - target_dur) / target_dur,
                deviation_before=deviation,
            )

        # 试上限
        rate_hi = f"+{adjuster.speed_max}%"
        patch_hi = _synth_at_rate(rate_hi)
        dur_hi = patch_hi.value.get("duration", target_dur)
        if dur_hi > target_dur:
            return patch_hi, SpeedDecision(
                strategy="video_slowdown", original_duration=actual,
                final_duration=dur_hi, tts_rate=rate_hi,
                search_method="binary", search_iterations=search_iterations,
                search_reached_limit=True,
                video_speed_factor=max(0.60, target_dur / max(dur_hi, 0.001)),
                deviation=abs(dur_hi - target_dur) / target_dur,
                deviation_before=deviation,
            )

        # 二分搜索
        lo, hi = init_speed, adjuster.speed_max
        best_patch = patch_hi
        while lo < hi:
            mid = (lo + hi) // 2
            p_mid = _synth_at_rate(f"+{mid}%")
            if p_mid.value.get("duration", target_dur) <= target_dur:
                hi = mid
                best_patch = p_mid
            else:
                lo = mid + 1

        rate_final = f"+{lo}%"
        # 收敛后微调: 尝试降 1-2%
        for lower in range(lo - 1, max(lo - 3, adjuster.base_speed - 1), -1):
            if lower < adjuster.base_speed:
                break
            p_lower = _synth_at_rate(f"+{lower}%")
            if p_lower.value.get("duration", target_dur) <= target_dur:
                best_patch = p_lower
                rate_final = f"+{lower}%"
                break

        dur_final = best_patch.value.get("duration", target_dur)
        return best_patch, SpeedDecision(
            strategy="accept", original_duration=actual,
            final_duration=dur_final, tts_rate=rate_final,
            search_method="binary", search_iterations=search_iterations,
            deviation=abs(dur_final - target_dur) / target_dur,
            deviation_before=deviation,
        )
