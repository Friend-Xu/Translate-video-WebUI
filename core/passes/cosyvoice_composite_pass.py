"""
CosyVoiceCompositePass — CosyVoice 域完整编排 (Chapter 6 §6.1-6.11)

编织 CosyVoiceAdapter + CosyVoiceDurationController + CrossLingualProcessor + CosyVoiceScorer。
支持跨 speaker 的 prompt_history 一致性维护和局部重算。

依赖: ["speaker_composite"] (第四章)

与 Ch5 TTSCompositePass 差异:
  - CosyVoiceDurationController (原生 speed) vs DurationController (RubberBand)
  - CrossLingualProcessor 管理 language tags
  - CosyVoiceScorer (speaker_match + language_naturalness) vs TTSScorer (emotion)
  - prompt_audio 多角色绑定 vs speaker_seed
"""
from __future__ import annotations
from core.engine.pass_base import TimelinePass
from core.runtime.project_state import TimelineProjectState
from core.runtime.patch_engine import PatchEngine
from core.adapters.cosyvoice_adapter import CosyVoiceAdapter, CosyVoiceSegmentContext
from core.tts.cosyvoice_duration import CosyVoiceDurationController
from core.tts.duration_control import SpeedDecision
from core.tts.cross_lingual import CrossLingualProcessor
from core.scoring.cosyvoice_scorer import CosyVoiceScorer


class CosyVoiceCompositePass(TimelinePass):
    """CosyVoice 域完整编排。

    编织顺序:
      1. 收集 speaker prompt 映射（speaker_id → prompt_audio_path）
      2. 对每个 segment:
         a. 构建 CosyVoiceSegmentContext（从 IR 各槽位读取 + 跨语种处理）
         b. CosyVoiceDurationController.compute_speed → 预计算最佳 speed
         c. CrossLingualProcessor.build_tagged_text → 带 language tag 文本
         d. CosyVoiceAdapter.synthesize → UPDATE_TTS_AUDIO patch
         e. CosyVoiceDurationController.check → accept/retry_with_speed/split
         f. CosyVoiceScorer.score → accept/reject
      3. PatchEngine.apply → 写入 state.tts 槽位
      4. Speaker prompt history 更新
    """

    name = "cosyvoice_composite"
    depends_on: list[str] = []

    def __init__(self, output_dir: str = "",
                 model_version: str = "v2",
                 default_lang: str = "",
                 fp16: bool = True,
                 default_speed: float = 1.0):
        self.output_dir = output_dir
        self.model_version = model_version
        self.default_lang = default_lang
        self.fp16 = fp16
        self.default_speed = default_speed

    def apply(self, state: TimelineProjectState) -> TimelineProjectState:
        engine = PatchEngine()
        cross_lingual = CrossLingualProcessor()
        duration_ctrl = CosyVoiceDurationController()
        scorer = CosyVoiceScorer()

        prompt_map = self._build_prompt_map(state)
        prompt_history: list[dict] = self._build_prompt_history(state)

        for es in state.sorted_events():
            if es.tts.get("audio_ref"):
                continue

            ctx = self._build_context(es, prompt_map)
            if not ctx.translation_text:
                continue

            # 跨语种: 确定语言并预构建 tagged text (供 adapter 参考)
            lang = cross_lingual.normalize_lang(ctx.lang) or self.default_lang
            if lang:
                ctx.lang = lang

            # 预计算 speed
            estimated = duration_ctrl.estimate_duration(
                ctx.translation_text, ctx.speed, ctx.lang,
            )
            if ctx.duration_target > 0 and estimated > 0:
                optimal_speed = duration_ctrl.compute_speed(
                    estimated, ctx.duration_target,
                )
                ctx.speed = optimal_speed

            # 创建 adapter 并合成
            adapter = CosyVoiceAdapter(
                model_version=ctx.model_version or self.model_version,
                prompt_audio=prompt_map.get(ctx.speaker_id or "", ""),
                prompt_text=ctx.prompt_text,
                output_dir=self.output_dir,
                fp16=self.fp16,
                default_speed=ctx.speed,
                lang=ctx.lang or self.default_lang,
            )
            patch = adapter.synthesize(ctx)

            # 时长检查
            action = duration_ctrl.check(
                patch.value["duration"], ctx.duration_target,
            )
            if action == "retry_with_speed":
                retry_speed = duration_ctrl.compute_retry_speed(
                    patch.value["duration"], ctx.duration_target,
                )
                ctx.speed = round(ctx.speed * retry_speed, 3)
                if 0.5 <= ctx.speed <= 2.0:
                    patch = adapter.synthesize(ctx)
                    # 重试后重新判定
                    action = duration_ctrl.check(
                        patch.value["duration"], ctx.duration_target,
                    )
                if action == "split":
                    es.runtime["tts_status"] = "needs_split"
            elif action == "split":
                es.runtime["tts_status"] = "needs_split"

            # ── 调速决策 ──
            if action == "split" or es.runtime.get("tts_status") == "needs_split":
                sd = SpeedDecision(
                    strategy="video_slowdown",
                    original_duration=patch.value["duration"],
                    final_duration=patch.value["duration"],
                    search_method="oneshot",
                    search_iterations=1,
                    search_reached_limit=True,
                    video_speed_factor=max(0.60, ctx.duration_target / max(patch.value["duration"], 0.001)),
                    deviation=abs(patch.value["duration"] - ctx.duration_target) / max(ctx.duration_target, 0.001),
                    deviation_before=abs(patch.value["duration"] - ctx.duration_target) / max(ctx.duration_target, 0.001),
                )
            else:
                dur = patch.value["duration"]
                target = ctx.duration_target
                sd = SpeedDecision(
                    strategy="accept",
                    original_duration=dur,
                    final_duration=dur,
                    deviation=abs(dur - target) / max(target, 0.001),
                )
            es.tts["speed_decision"] = sd.as_dict()

            if es.runtime.get("tts_status") == "needs_split":
                continue

            # 评分
            score = scorer.score(ctx, patch, prompt_history)
            patch.confidence = score.composite

            if score.accepted:
                engine.apply(state, patch)
                es.provenance["cosyvoice_score"] = score.composite
                es.provenance["cosyvoice_detail"] = {
                    "speaker_match": score.speaker_match,
                    "duration_fit": score.duration_fit,
                    "language_naturalness": score.language_naturalness,
                    "segment_continuity": score.segment_continuity,
                }
            else:
                es.runtime["tts_status"] = "rejected"

            self._update_prompt_history(prompt_history, ctx, patch)

        return state

    @staticmethod
    def _build_prompt_map(state: TimelineProjectState) -> dict[str, str]:
        """从 speaker registry 构建 speaker_id → prompt_audio 映射。"""
        pmap: dict[str, str] = {}
        for spk in state.ir.speakers.values():
            if spk.id and spk.embedding_ref:
                import os
                if os.path.isfile(spk.embedding_ref):
                    pmap[spk.id] = spk.embedding_ref
        return pmap

    @staticmethod
    def _build_prompt_history(state: TimelineProjectState) -> list[dict]:
        history: list[dict] = []
        for es in state.sorted_events():
            tts = es.tts
            if tts.get("audio_ref") and tts.get("engine") == "cosyvoice":
                history.append({
                    "speaker_id": es.speaker.get("speaker_id"),
                    "prompt_audio": tts.get("prompt_audio", ""),
                    "speed": tts.get("speed", 1.0),
                    "lang": tts.get("lang", ""),
                    "duration": tts.get("duration", 0),
                })
        return history

    @staticmethod
    def _update_prompt_history(history: list[dict],
                               ctx: CosyVoiceSegmentContext,
                               patch: Patch) -> None:
        history.append({
            "speaker_id": ctx.speaker_id,
            "prompt_audio": patch.value.get("prompt_audio", ""),
            "speed": patch.value.get("speed", 1.0),
            "lang": patch.value.get("lang", ""),
            "duration": patch.value.get("duration", 0),
        })

    def _build_context(self, es,
                       prompt_map: dict[str, str]) -> CosyVoiceSegmentContext:
        trans_raw = es.translation
        translation = (trans_raw.get("text", "") if isinstance(trans_raw, dict) else str(trans_raw or "")) or es.ir.text_ref
        trans_lang = trans_raw.get("lang", "") if isinstance(trans_raw, dict) else ""
        speaker_id = es.speaker.get("speaker_id")
        return CosyVoiceSegmentContext(
            segment_id=es.id,
            translation_text=translation,
            source_text=es.ir.text_ref,
            speaker_id=speaker_id,
            speaker_embedding_ref=prompt_map.get(speaker_id or "", ""),
            duration_target=es.end - es.start,
            semantic_embedding_ref=es.semantic.get("embedding_ref", ""),
            lang=trans_lang or self.default_lang,
            model_version=self.model_version,
            speed=self.default_speed,
            mode="cross_lingual",
        )
