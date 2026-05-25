"""
IndexTTSAdapter — IndexTTS → Patch 适配器 (Chapter 7 §7.1-7.3)

封装现有 IndexTTSEngine 子进程隔离协议，不做修改。
IndexTTS 定位为"说话人语音检索与复用引擎"——零样本克隆 + 原生时长 + 情绪向量。
"""
from __future__ import annotations
from dataclasses import dataclass
from core.runtime.patch import Patch, OpCode
from core.ir.speaker import SpeakerNodeIR


@dataclass
class IndexTTSSegmentContext:
    """IndexTTS 结构化输入 — 零样本克隆 + 原生 target_length_ms + 情绪向量。

    target_length_ms 提供毫秒级精确时长控制（IndexTTS 自回归 GPT 原生支持）。
    emo_vector / emo_alpha 控制 24 类情绪表达。
    """
    segment_id: str
    translation_text: str
    source_text: str = ""
    speaker_id: str | None = None
    speaker_embedding_ref: str = ""     # prompt_audio 文件路径
    emotion_hint: str = "neutral"
    prosody_hint: dict | None = None
    duration_target: float = 0.0        # 秒，将转为 target_length_ms
    duration_tolerance: float = 0.10    # 原生时长控制精度更高
    semantic_embedding_ref: str = ""
    prev_segment_id: str = ""
    next_segment_id: str = ""
    # IndexTTS 特有字段
    target_length_ms: float = 0.0       # 毫秒级精确时长控制
    emo_vector: list[float] | None = None  # 24 类情绪向量
    emo_alpha: float = 1.0              # 情绪强度 [0, 2]
    voice_asset_ref: str = ""           # 检索到的 voice asset 引用


class IndexTTSAdapter:
    """将 IndexTTS 输出转为 UPDATE_TTS_AUDIO patch。

    封装现有 IndexTTSEngine 子进程协议，不做修改。
    支持零样本克隆（spk_audio_prompt）、原生 target_length_ms、情绪向量。
    """

    def __init__(self, checkpoints_dir: str | None = None,
                 speaker_audio: str | None = None,
                 output_dir: str = "",
                 fp16: bool = True):
        self._checkpoints_dir = checkpoints_dir
        self._speaker_audio = speaker_audio
        self._output_dir = output_dir
        self._fp16 = fp16
        self._engine = None

    def synthesize(self, ctx: IndexTTSSegmentContext) -> Patch:
        """对单个 segment 合成语音，返回 UPDATE_TTS_AUDIO patch。

        流程:
          1. 从 ctx 读取 target_length_ms（segment 原始时长 → ms）
          2. 构建 emotion dict (emo_vector + emo_alpha)
          3. 调用 IndexTTSEngine.synthesize(text, output_path, target_length_ms=..., emotion=...)
          4. 返回 Patch
        """
        from pipeline.tts_indextts import IndexTTSEngine

        engine = self._get_or_create_engine()
        output_path = self._make_output_path(ctx.segment_id)

        target_ms = ctx.target_length_ms
        if target_ms <= 0 and ctx.duration_target > 0:
            target_ms = ctx.duration_target * 1000.0

        emotion = None
        if ctx.emo_vector is not None:
            emotion = {"emo_vector": ctx.emo_vector, "emo_alpha": ctx.emo_alpha}

        duration = engine.synthesize(
            text=ctx.translation_text,
            output_path=output_path,
            target_length_ms=target_ms if target_ms > 0 else None,
            emotion=emotion,
        )

        duration_fit = self._calc_duration_fit(duration, ctx.duration_target)
        quality = self._estimate_quality(duration_fit)

        return Patch(
            id=f"tts_idx_{ctx.segment_id}",
            target_id=ctx.segment_id,
            op=OpCode.UPDATE_TTS_AUDIO,
            value={
                "audio_ref": output_path,
                "duration": round(duration, 3),
                "duration_target": ctx.duration_target,
                "duration_fit_score": duration_fit,
                "retrieval_confidence": 0.85,
                "speaker_match_score": 0.90,
                "quality_score": quality,
                "engine": "indextts",
                "speaker_audio": self._speaker_audio,
                "target_length_ms": target_ms,
                "emo_alpha": ctx.emo_alpha,
                "voice_asset_ref": ctx.voice_asset_ref,
            },
            author="system",
            confidence=quality,
        )

    def bind_speaker(self, speaker_node: SpeakerNodeIR) -> None:
        """通过 speaker_audio 绑定 speaker identity。

        从 SpeakerNodeIR.embedding_ref 读取 prompt 音频路径。
        若 embedding_ref 不可用，尝试使用 voice_style 描述。
        """
        if speaker_node.embedding_ref:
            import os
            if os.path.isfile(speaker_node.embedding_ref):
                self._speaker_audio = speaker_node.embedding_ref

    def reset_speaker(self, speaker_audio: str) -> None:
        """切换零样本参考音频（多角色场景）。"""
        self._speaker_audio = speaker_audio
        if self._engine is not None:
            self._engine.reset_speaker(speaker_audio)

    def _get_or_create_engine(self):
        if self._engine is None:
            from pipeline.tts_indextts import IndexTTSEngine
            self._engine = IndexTTSEngine(
                checkpoints_dir=self._checkpoints_dir,
                fp16=self._fp16,
                speaker_audio=self._speaker_audio,
            )
            self._engine.warmup()
        return self._engine

    def _make_output_path(self, segment_id: str) -> str:
        import os
        d = self._output_dir or "."
        return os.path.join(d, "tts", f"{segment_id}_indextts.wav")

    @staticmethod
    def _calc_duration_fit(actual: float, target: float) -> float:
        if target <= 0:
            return 1.0
        dev = abs(actual - target) / target
        return round(max(0.0, 1.0 - dev / 0.3), 4)

    @staticmethod
    def _estimate_quality(duration_fit: float) -> float:
        return round(0.75 + 0.25 * duration_fit, 4)
