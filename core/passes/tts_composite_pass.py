"""
TTSCompositePass — TTS 域完整编排 (Chapter 5 §5.1-5.8)

编织 ChatTTSAdapter + EmotionModeler + DurationController + TTSScorer。
支持跨 segment 的 speaker_history 一致性维护和局部重算。

依赖: ["speaker_composite"] (第四章)
"""
from __future__ import annotations
from core.engine.pass_base import TimelinePass
from core.runtime.project_state import TimelineProjectState
from core.runtime.patch_engine import PatchEngine
from core.adapters.chattts_adapter import ChatTTSAdapter, TTSSegmentContext
from core.tts.emotion import EmotionModeler
from core.tts.duration_control import DurationController
from core.scoring.tts_scorer import TTSScorer


class TTSCompositePass(TimelinePass):
    """TTS 域完整编排。"""

    name = "tts_composite"
    depends_on = ["speaker_composite"]

    def __init__(self, output_dir: str = "", speaker_seed: int | None = None):
        self.output_dir = output_dir
        self.speaker_seed = speaker_seed
        self._resolved_config: dict | None = None

    def configure(self, resolved_config: dict | None = None) -> None:
        """接收 ConfigResolver 解析后的 tts 槽位配置。"""
        self._resolved_config = resolved_config or {}

    def apply(self, state: TimelineProjectState) -> TimelineProjectState:
        engine = PatchEngine()
        adapter = ChatTTSAdapter(
            speaker_seed=self.speaker_seed, output_dir=self.output_dir,
        )
        # 配置注入 (批次 B): ConfigResolver → Pass → Adapter
        if self._resolved_config:
            adapter.configure(self._resolved_config)
        emotion_modeler = EmotionModeler()
        duration_ctrl = DurationController()
        scorer = TTSScorer()
        speaker_history = self._build_speaker_history(state)

        for es in state.sorted_events():
            if es.tts.get("audio_ref"):
                continue

            ctx = self._build_context(es)
            if not ctx.translation_text:
                continue

            emotion = emotion_modeler.infer_emotion(ctx, speaker_history)
            ctx.emotion_hint = emotion["emotion_hint"]
            ctx.prosody_hint = emotion["prosody"]

            patch = adapter.synthesize(ctx)

            action = duration_ctrl.check(
                patch.value["duration"], ctx.duration_target,
            )
            if action == "split":
                es.runtime["tts_status"] = "needs_split"
                continue

            score = scorer.score(ctx, patch, speaker_history)
            patch.confidence = score.composite

            if score.accepted:
                engine.apply(state, patch)
                es.provenance["tts_score"] = score.composite
                es.provenance["tts_score_detail"] = {
                    "duration_fit": score.duration_fit,
                    "speaker_consistency": score.speaker_consistency,
                    "emotion_consistency": score.emotion_consistency,
                }
            else:
                es.runtime["tts_status"] = "rejected"

            self._update_history(speaker_history, ctx, patch)

        return state

    def _build_context(self, es) -> TTSSegmentContext:
        translation = es.translation.get("text", "") or es.ir.text_ref
        return TTSSegmentContext(
            segment_id=es.id,
            translation_text=translation,
            source_text=es.ir.text_ref,
            speaker_id=es.speaker.get("speaker_id"),
            speaker_embedding_ref=es.speaker.get("embedding_ref", ""),
            duration_target=es.end - es.start,
            semantic_embedding_ref=es.semantic.get("embedding_ref", ""),
        )

    @staticmethod
    def _build_speaker_history(state: TimelineProjectState) -> list[dict]:
        history = []
        for es in state.sorted_events():
            if es.tts.get("audio_ref"):
                history.append({
                    "speaker_id": es.speaker.get("speaker_id"),
                    "emotion_hint": es.tts.get("emotion_hint", ""),
                    "duration": es.tts.get("duration", 0),
                })
        return history

    @staticmethod
    def _update_history(history: list[dict], ctx: TTSSegmentContext,
                        patch: Patch) -> None:
        history.append({
            "speaker_id": ctx.speaker_id,
            "emotion_hint": ctx.emotion_hint,
            "duration": patch.value.get("duration", 0),
        })
