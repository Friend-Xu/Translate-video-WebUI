"""
IndexTTSCompositePass — IndexTTS 域完整编排 (Chapter 7 §7.1-7.10)

编织 VoiceMemoryIndex + EmotionVectorMapper + IndexTTSAdapter + IndexTTSScorer。
核心差异化: RETRIEVE → SYNTHESIZE → SCORE → PROMOTE 闭环。

依赖: ["speaker_composite"] (第四章)

与 Ch5 TTSCompositePass / Ch6 CosyVoiceCompositePass 的核心差异:
  增加 RETRIEVE 步骤: 先查 VoiceMemoryIndex，
  命中 → 使用 asset.audio_ref 作为更稳定的 prompt_audio
  未命中 → 使用 speaker_registry 默认 prompt_audio
"""
from __future__ import annotations
from core.engine.pass_base import TimelinePass
from core.runtime.project_state import TimelineProjectState
from core.runtime.patch_engine import PatchEngine
from core.adapters.indextts_adapter import IndexTTSAdapter, IndexTTSSegmentContext
from core.speaker.voice_memory import VoiceMemoryIndex
from core.tts.index_emotion import EmotionVectorMapper
from core.scoring.indextts_scorer import IndexTTSScorer


class IndexTTSCompositePass(TimelinePass):
    """IndexTTS 域完整编排。

    编排顺序 (体现"检索优先于生成"):
      1. 初始化 VoiceMemoryIndex（加载已有 asset 索引）
      2. 对每个 segment:
         a. 构建 IndexTTSSegmentContext（从 IR 各槽位读取）
         b. RETRIEVE: VoiceMemoryIndex.retrieve(speaker_id, emotion, duration)
            → 若命中: 使用 asset.audio_ref 作为 prompt_audio
            → 若未命中: 使用 speaker_registry 中的默认 prompt_audio
         c. EmotionVectorMapper.to_emo_vector → emo_vector + emo_alpha
         d. IndexTTSAdapter.synthesize → UPDATE_TTS_AUDIO patch
         e. IndexTTSScorer.score → accept/reject
         f. RECORD: VoiceMemoryIndex.record(ctx, patch)
         g. PROMOTE: 若 score > 阈值 → VoiceMemoryIndex.promote(instance)
      3. PatchEngine.apply → 写入 state.tts 槽位
    """

    name = "indextts_composite"
    depends_on: list[str] = []

    def __init__(self, output_dir: str = "",
                 fp16: bool = True):
        self.output_dir = output_dir
        self.fp16 = fp16

    def apply(self, state: TimelineProjectState) -> TimelineProjectState:
        engine = PatchEngine()
        voice_memory = VoiceMemoryIndex()
        emotion_mapper = EmotionVectorMapper()
        scorer = IndexTTSScorer()

        prompt_map = self._build_prompt_map(state)
        prompt_history: list[dict] = self._build_prompt_history(state)

        for es in state.sorted_events():
            if es.tts.get("audio_ref"):
                continue

            ctx = self._build_context(es, prompt_map)
            if not ctx.translation_text:
                continue

            # Step 1: RETRIEVE — 先查 VoiceMemoryIndex
            asset = voice_memory.retrieve(
                ctx.speaker_id or "",
                emotion_hint=ctx.emotion_hint,
                duration_target=ctx.duration_target,
            )
            if asset is not None:
                ctx.voice_asset_ref = asset.asset_id
                # 使用检索到的 asset 作为更稳定的 prompt_audio
                if asset.audio_ref:
                    ctx.speaker_embedding_ref = asset.audio_ref

            # Step 2: EmotionVectorMapper
            if ctx.emotion_hint and ctx.emotion_hint != "neutral":
                ctx.emo_vector = emotion_mapper.to_emo_vector(
                    ctx.emotion_hint, intensity=1.0,
                )

            # Step 3: SYNTHESIZE
            adapter = IndexTTSAdapter(
                speaker_audio=prompt_map.get(ctx.speaker_id or "", ""),
                output_dir=self.output_dir,
                fp16=self.fp16,
            )
            patch = adapter.synthesize(ctx)

            # Step 4: SCORE
            score = scorer.score(ctx, patch, prompt_history)
            patch.confidence = score.composite

            # Step 5: RECORD
            proto = voice_memory.get_or_create_prototype(
                ctx.speaker_id or "unknown",
            )
            instance = voice_memory.record(ctx, patch, proto.prototype_id)

            # Step 6: PROMOTE
            if score.accepted:
                engine.apply(state, patch)
                es.provenance["indextts_score"] = score.composite
                es.provenance["indextts_detail"] = {
                    "retrieval_confidence": score.retrieval_confidence,
                    "identity_stability": score.identity_stability,
                    "duration_fit": score.duration_fit,
                    "segment_fit": score.segment_fit,
                    "reuse_safety": score.reuse_safety,
                }
                # 高质量结果晋升为 VoiceAsset
                if score.composite >= voice_memory.PROMOTE_THRESHOLD:
                    promoted = voice_memory.promote(instance)
                    if promoted:
                        es.provenance["voice_asset_promoted"] = promoted.asset_id
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
            if tts.get("audio_ref") and tts.get("engine") == "indextts":
                history.append({
                    "speaker_id": es.speaker.get("speaker_id"),
                    "speaker_audio": tts.get("speaker_audio", ""),
                    "duration": tts.get("duration", 0),
                    "emotion_used": tts.get("emo_alpha", ""),
                    "voice_asset_ref": tts.get("voice_asset_ref", ""),
                })
        return history

    @staticmethod
    def _update_prompt_history(history: list[dict],
                               ctx: IndexTTSSegmentContext,
                               patch: Patch) -> None:
        history.append({
            "speaker_id": ctx.speaker_id,
            "speaker_audio": patch.value.get("speaker_audio", ""),
            "duration": patch.value.get("duration", 0),
            "emotion_used": ctx.emotion_hint,
            "voice_asset_ref": ctx.voice_asset_ref,
        })

    def _build_context(self, es,
                       prompt_map: dict[str, str]) -> IndexTTSSegmentContext:
        trans_raw = es.translation
        translation = (trans_raw.get("text", "") if isinstance(trans_raw, dict) else str(trans_raw or "")) or es.ir.text_ref
        speaker_id = es.speaker.get("speaker_id")
        return IndexTTSSegmentContext(
            segment_id=es.id,
            translation_text=translation,
            source_text=es.ir.text_ref,
            speaker_id=speaker_id,
            speaker_embedding_ref=prompt_map.get(speaker_id or "", ""),
            duration_target=es.end - es.start,
            semantic_embedding_ref=es.semantic.get("embedding_ref", ""),
        )
