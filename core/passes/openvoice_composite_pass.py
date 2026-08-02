"""
OpenVoiceCompositePass — OpenVoice fallback 域编排 (Chapter 8 §8.1-8.11)

编织 FallbackDecider + OpenVoiceTransferAdapter + OpenVoiceScorer。
OpenVoice 是 fallback 层——不主动执行，只在主引擎失败后触发。

依赖: ["speaker_composite"] (第四章，需要 speaker embedding 做参考)

与 Ch5-7 CompositePass 的核心差异:
  - 不主动执行 — 只在主引擎路径失败后由 FallbackDecider 触发
  - 输入是已有 TTS 音频（不是文本）
  - 输出标记 generation_mode=fallback
  - 评分阈值更低（0.60 vs 0.70）
"""
from __future__ import annotations
from core.engine.pass_base import TimelinePass
from core.runtime.project_state import TimelineProjectState
from core.runtime.patch_engine import PatchEngine
from core.adapters.openvoice_adapter import (
    OpenVoiceTransferAdapter, OpenVoiceTransferContext,
)
from core.tts.fallback_decider import FallbackDecider
from core.scoring.openvoice_scorer import OpenVoiceScorer


class OpenVoiceCompositePass(TimelinePass):
    """OpenVoice fallback 域编排。

    触发条件:
      1. 主引擎结果被 Logic Gate 拒绝
      2. es.runtime.tts_status == "rejected"
      3. FallbackDecider.decide() → should_fallback=True

    编排顺序:
      1. 收集所有被主引擎拒绝的 segment
      2. 对每个 rejected segment:
         a. FallbackDecider.decide() → 判断是否触发 fallback
         b. 构建 OpenVoiceTransferContext
         c. OpenVoiceTransferAdapter.transfer() → UPDATE_TTS_AUDIO patch
         d. OpenVoiceScorer.score() → accept/reject
         e. 标记 generation_mode=fallback + fallback_reason
      3. PatchEngine.apply → 写入 state.tts 槽位
    """

    name = "openvoice_composite"
    depends_on: list[str] = []

    def __init__(self, output_dir: str = ""):
        self.output_dir = output_dir

    def apply(self, state: TimelineProjectState) -> TimelineProjectState:
        engine = PatchEngine()
        decider = FallbackDecider()
        scorer = OpenVoiceScorer()

        prompt_map = self._build_prompt_map(state)
        transfer_history: list[dict] = self._build_transfer_history(state)

        # 收集被主引擎拒绝的 segment
        rejected = [
            es for es in state.sorted_events()
            if es.runtime.tts_status == "rejected" and not es.tts.audio_ref
        ]
        total = max(len(list(state.sorted_events())), 1)
        fallback_count = sum(
            1 for es in state.sorted_events()
            if es.tts.generation_mode == "fallback"
        )

        if not rejected:
            return state

        for es in rejected:
            # Step 1: FallbackDecider
            primary_score = es.provenance.get("tts_score")
            primary_error = es.runtime.reject_reason
            decision = decider.decide(
                segment_id=es.id,
                primary_score=primary_score,
                primary_error=primary_error,
                fallback_count=fallback_count,
                total_segments=total,
            )
            if not decision.should_fallback:
                es.runtime.engine_scores["fallback_status"] = "denied"
                es.runtime.engine_scores["fallback_deny_reason"] = decision.reason
                continue

            # Step 2: 构建 context
            existing_audio = es.tts.audio_ref
            speaker_id = es.speaker.speaker_id
            ctx = OpenVoiceTransferContext(
                segment_id=es.id,
                source_audio_ref=existing_audio,
                speaker_id=speaker_id,
                reference_audio_ref=prompt_map.get(speaker_id or "", ""),
                speaker_embedding_ref=es.speaker.embedding_ref,
                duration_target=es.end - es.start,
                fallback_reason=decision.reason,
            )

            # Step 3: TRANSFER
            adapter = OpenVoiceTransferAdapter(output_dir=self.output_dir)
            patch = adapter.transfer(ctx)

            # Step 4: SCORE
            score = scorer.score(ctx, patch, transfer_history)
            patch.confidence = score.composite

            if score.accepted:
                # 写入 fallback 标记到 patch
                pv = dict(patch.value)
                pv["generation_mode"] = "fallback"
                pv["fallback_reason"] = decision.reason
                pv["fallback_urgency"] = decision.urgency
                patch = patch.__class__(
                    id=patch.id, target_id=patch.target_id,
                    op=patch.op, value=pv,
                    timestamp=patch.timestamp, author=patch.author,
                    targets=patch.targets, reason=patch.reason,
                    score=patch.score, confidence=patch.confidence,
                    parent_version=patch.parent_version,
                    idempotency_key=patch.idempotency_key,
                )

                engine.apply(state, patch)
                es.provenance["openvoice_score"] = score.composite
                es.provenance["openvoice_detail"] = {
                    "transfer_quality": score.transfer_quality,
                    "speaker_match": score.speaker_match,
                    "fallback_validity": score.fallback_validity,
                }
                es.runtime.tts_status = "fallback_accepted"
                es.runtime.generation_mode = "fallback"
                es.runtime.engine_scores["fallback_reason"] = decision.reason
                fallback_count += 1
            else:
                es.runtime.tts_status = "fallback_rejected"
                es.runtime.engine_scores["fallback_reject_reason"] = f"composite={score.composite:.2f}"

            self._update_transfer_history(transfer_history, ctx, patch)

        return state

    @staticmethod
    def _build_prompt_map(state: TimelineProjectState) -> dict[str, str]:
        """从 speaker registry 构建 speaker_id → reference_audio 映射。"""
        pmap: dict[str, str] = {}
        for spk in state.ir.speakers.values():
            if spk.id and spk.embedding_ref:
                import os
                if os.path.isfile(spk.embedding_ref):
                    pmap[spk.id] = spk.embedding_ref
        return pmap

    @staticmethod
    def _build_transfer_history(state: TimelineProjectState) -> list[dict]:
        history: list[dict] = []
        for es in state.sorted_events():
            tts = es.tts
            if tts.get("engine") == "openvoice":
                history.append({
                    "speaker_id": es.speaker.speaker_id,
                    "reference_audio": tts.get("reference_audio", ""),
                    "fallback_reason": tts.get("fallback_reason", ""),
                })
        return history

    @staticmethod
    def _update_transfer_history(history: list[dict],
                                  ctx: OpenVoiceTransferContext,
                                  patch: Patch) -> None:
        history.append({
            "speaker_id": ctx.speaker_id,
            "reference_audio": ctx.reference_audio_ref,
            "fallback_reason": ctx.fallback_reason,
        })
