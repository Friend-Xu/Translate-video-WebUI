"""
EmotionRecognizerAdapter — 双路径情感识别 (audio/text) → EmotionVector → ANNOTATE patch
"""
from __future__ import annotations
from dataclasses import dataclass
from core.runtime.patch import Patch, OpCode
from core.emotion.emotion_space import EmotionVector


@dataclass
class EmotionRecognizerContext:
    audio_path: str = ""
    text: str = ""
    segment_id: str = ""
    start: float = 0.0
    end: float = 0.0


class EmotionRecognizerAdapter:

    def configure(self, event_config = None):
        if not event_config: return
        if "fusion_strategy" in event_config: self._fusion_strategy = event_config["fusion_strategy"]
        if "audio_weight" in event_config: self._audio_weight = event_config["audio_weight"]
        if "text_weight" in event_config: self._text_weight = event_config["text_weight"]
        if "text_model" in event_config: self._text_model = event_config["text_model"]
        if "enabled" in event_config: self._enabled = event_config["enabled"]
    def recognize(self, ctx: EmotionRecognizerContext) -> Patch:
        if ctx.audio_path:
            return self.recognize_from_audio(ctx)
        if ctx.text:
            return self.recognize_from_text(ctx)
        return self._neutral(ctx.segment_id)

    def recognize_from_text(self, ctx: EmotionRecognizerContext) -> Patch:
        try:
            from core.tts.emotion import EmotionModeler
            tts_ctx = type("TTSSegmentContext", (), {
                "translation_text": ctx.text,
                "source_text": "",
                "speaker_id": "",
                "segment_id": ctx.segment_id,
                "start": ctx.start,
                "end": ctx.end,
            })()
            result = EmotionModeler().infer_emotion(tts_ctx)
            ev = EmotionVector.from_label(result.get("emotion_hint", "neutral"))
        except Exception:
            ev = EmotionVector()
        return self._patch(ctx.segment_id, ev)

    def recognize_from_audio(self, ctx: EmotionRecognizerContext) -> Patch:
        ev = EmotionVector()
        try:
            import os
            if os.path.exists(ctx.audio_path):
                from funasr import AutoModel
                model = AutoModel(model="iic/emotion2vec_plus_large")
                result = model.generate(ctx.audio_path, output_dir="./tmp_emo")
                if result and len(result) > 0:
                    ev = EmotionVector.from_9class_scores(result[0].get("scores", {}))
        except Exception:
            if ctx.text:
                return self.recognize_from_text(ctx)
        return self._patch(ctx.segment_id, ev)

    def _patch(self, seg_id: str, ev: EmotionVector) -> Patch:
        return Patch(
            id=f"emo_{seg_id}", target_id=seg_id,
            op=OpCode.UPDATE_EMOTION,
            value={"emotion": ev.to_dict()},
            confidence=ev.confidence, author="system",
        )

    def _neutral(self, seg_id: str) -> Patch:
        return self._patch(seg_id, EmotionVector())
