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
from core.tts.duration_control import DurationController, SpeedDecision
from core.scoring.tts_scorer import TTSScorer


class TTSCompositePass(TimelinePass):
    """TTS 域完整编排。"""

    name = "tts_composite"
    depends_on: list[str] = []

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
            if es.tts.audio_ref:
                continue

            ctx = self._build_context(es)
            if not ctx.translation_text:
                continue

            emotion = emotion_modeler.infer_emotion(ctx, speaker_history)
            ctx.emotion_hint = emotion["emotion_hint"]
            ctx.prosody_hint = emotion["prosody"]

            import os as _os

            patch = adapter.synthesize(ctx)

            # ── LUFS 归一化 ──
            from pipeline.loudness import normalize_segment_loudness
            audio_path = patch.value.get("audio_ref", "")
            if audio_path:
                if not _os.path.isabs(audio_path):
                    audio_path = _os.path.join(self.output_dir, audio_path)
                if _os.path.isfile(audio_path):
                    normalize_segment_loudness(audio_path, target_lufs=-16.0)

            action = duration_ctrl.check(
                patch.value["duration"], ctx.duration_target,
            )
            if action == "split":
                es.runtime.tts_status = "needs_split"
                continue

            # ── 调速决策 + RubberBand 拉伸 ──
            sd = duration_ctrl.decide_speed(
                patch.value["duration"], ctx.duration_target,
                engine_has_native_rate=False,
            )
            if sd.strategy == "rubberband_stretch":
                audio_path = patch.value["audio_ref"]
                if not _os.path.isabs(audio_path):
                    audio_path = _os.path.join(self.output_dir, audio_path)
                if _os.path.isfile(audio_path):
                    duration_ctrl.apply_rubberband(audio_path, sd.stretch_ratio)
                    patch.value["duration"] = sd.final_duration
                    # 拉伸后重新判定 — 跳过 RubberBand 级防止无限拉伸
                    sd = duration_ctrl.decide_speed(
                        sd.final_duration, ctx.duration_target,
                        engine_has_native_rate=True,
                    )

            es.tts.speed_decision = sd.as_dict()

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
                es.runtime.tts_status = "rejected"

            self._update_history(speaker_history, ctx, patch)

        return state

    def _build_context(self, es) -> TTSSegmentContext:
        raw = es.translation
        if isinstance(raw, dict):
            translation = raw.get("text", "") or es.ir.text_ref
        elif isinstance(raw, str) and raw.strip():
            translation = raw
        else:
            translation = es.ir.text_ref
        return TTSSegmentContext(
            segment_id=es.id,
            translation_text=translation,
            source_text=es.ir.text_ref,
            speaker_id=es.speaker.speaker_id,
            speaker_embedding_ref=es.speaker.embedding_ref,
            duration_target=es.end - es.start,
            semantic_embedding_ref=es.semantic.embedding_ref,
        )

    @staticmethod
    def _build_speaker_history(state: TimelineProjectState) -> list[dict]:
        history = []
        for es in state.sorted_events():
            if es.tts.audio_ref:
                history.append({
                    "speaker_id": es.speaker.speaker_id,
                    "emotion_hint": es.tts.emotion_hint,
                    "duration": es.tts.duration,
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
