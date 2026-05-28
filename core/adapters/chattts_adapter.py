"""
ChatTTSAdapter — ChatTTS → Patch 适配器 (Chapter 5 §5.1-5.3)

封装现有 ChatTTSEngine 子进程协议，输入从 Segment Context 读取，
输出 UPDATE_TTS_AUDIO patch。
"""
from __future__ import annotations
from dataclasses import dataclass
from core.runtime.patch import Patch, OpCode
from core.ir.speaker import SpeakerNodeIR


@dataclass
class TTSSegmentContext:
    """ChatTTS 结构化输入 — 来自 Timeline IR 各槽位的完整 segment 上下文。"""
    segment_id: str
    translation_text: str
    source_text: str = ""
    speaker_id: str | None = None
    speaker_embedding_ref: str = ""
    emotion_hint: str = "neutral"
    prosody_hint: dict | None = None
    duration_target: float = 0.0
    duration_tolerance: float = 0.15
    semantic_embedding_ref: str = ""
    prev_segment_id: str = ""
    next_segment_id: str = ""


class ChatTTSAdapter:
    """将 ChatTTS 输出转为 UPDATE_TTS_AUDIO patch。

    封装现有 ChatTTSEngine 子进程协议，不做修改。
    """

    def __init__(self, speaker_seed: int | None = None,
                 model_source: str = "local",
                 model_path: str | None = None,
                 output_dir: str = ""):
        self._speaker_seed = speaker_seed
        self._model_source = model_source
        self._model_path = model_path
        self._output_dir = output_dir
        self._engine = None

    def configure(self, event_config = None):
        if not event_config: return
        if "speaker_seed" in event_config: self._speaker_seed = event_config["speaker_seed"]
        if "chattts_speaker_seed" in event_config: self._speaker_seed = event_config["chattts_speaker_seed"]
        if "chattts_temperature" in event_config: self._temperature = event_config["chattts_temperature"]
        if "chattts_top_k" in event_config: self._top_k = event_config["chattts_top_k"]
        if "chattts_top_p" in event_config: self._top_p = event_config["chattts_top_p"]
        if "chattts_emotion_injection" in event_config: self._emotion_inject = event_config["chattts_emotion_injection"]
        if "speed_factor" in event_config: self._speed_factor = event_config["speed_factor"]

    def synthesize(self, ctx: TTSSegmentContext) -> Patch:
        """对单个 segment 合成语音，返回 UPDATE_TTS_AUDIO patch。"""
        from pipeline.tts_chattts import ChatTTSEngine

        engine = self._get_or_create_engine()
        output_path = self._make_output_path(ctx.segment_id)
        prompt = self._build_refine_prompt(ctx)

        duration = engine.synthesize(
            text=ctx.translation_text,
            output_path=output_path,
            emotion=prompt if prompt else None,
        )

        return Patch(
            id=f"tts_{ctx.segment_id}",
            target_id=ctx.segment_id,
            op=OpCode.UPDATE_TTS_AUDIO,
            value={
                "audio_ref": output_path,
                "duration": round(duration, 3),
                "duration_target": ctx.duration_target,
                "engine": "chattts",
                "speaker_seed": self._speaker_seed,
                "emotion_hint": ctx.emotion_hint,
            },
            author="system",
            confidence=self._estimate_confidence(ctx, duration),
        )

    def bind_speaker(self, speaker_node: SpeakerNodeIR) -> None:
        """通过 speaker_seed 绑定 speaker identity。"""
        if speaker_node.voice_id:
            try:
                self._speaker_seed = int(speaker_node.voice_id)
            except (ValueError, TypeError):
                pass

    def _get_or_create_engine(self):
        if self._engine is None:
            from pipeline.tts_chattts import ChatTTSEngine
            self._engine = ChatTTSEngine(
                speaker_seed=self._speaker_seed,
                model_source=self._model_source,
                model_path=self._model_path,
            )
            self._engine.warmup()
        return self._engine

    def _make_output_path(self, segment_id: str) -> str:
        import os
        d = self._output_dir or "."
        return os.path.join(d, "03_tts", f"{segment_id}_chattts.wav")

    @staticmethod
    def _build_refine_prompt(ctx: TTSSegmentContext) -> str:
        if ctx.emotion_hint == "angry":
            return "[oral_7][laugh_0][break_2]"
        elif ctx.emotion_hint == "excited":
            return "[oral_7][laugh_2][break_3]"
        elif ctx.emotion_hint == "sad":
            return "[oral_1][laugh_0][break_7]"
        elif ctx.emotion_hint == "serious":
            return "[oral_3][laugh_0][break_5]"
        if ctx.prosody_hint:
            energy = ctx.prosody_hint.get("energy", 0.5)
            speed = ctx.prosody_hint.get("speed", 1.0)
            oral = max(0, min(9, int(energy * 9)))
            brk = max(0, min(9, int((2.0 - speed) * 4)))
            return f"[oral_{oral}][laugh_0][break_{brk}]"
        return "[oral_2][laugh_0][break_5]"

    @staticmethod
    def _estimate_confidence(ctx: TTSSegmentContext,
                             actual_duration: float) -> float:
        if ctx.duration_target <= 0:
            return 0.85
        deviation = abs(actual_duration - ctx.duration_target) / ctx.duration_target
        return round(max(0.0, 1.0 - deviation), 4)
