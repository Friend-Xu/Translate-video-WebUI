"""
OpenVoiceTransferAdapter — OpenVoice → Patch 适配器 (Chapter 8 §8.3-8.4)

封装现有 OpenVoiceCloner，不做修改。
OpenVoice 定位为"辅助语音迁移引擎"——不生成语音，只转换已有 TTS 音频的音色。
输入: 已有 TTS 音频 + 参考音频 → 输出: 音色迁移后的音频

与 Ch5-7 适配器的根本差异:
  - 不是 TTS 引擎 — 不做文本→语音合成
  - 输入是音频路径（不是文本）
  - 输出标记 generation_mode=fallback
"""
from __future__ import annotations
from dataclasses import dataclass
from core.runtime.patch import Patch, OpCode


@dataclass
class OpenVoiceTransferContext:
    """OpenVoice 音色迁移输入 — 需要已有 TTS 音频 + 参考音频。

    fallback_reason 记录为什么触发降级，决定后续策略:
      "primary_low_confidence"     — 主引擎置信度不足
      "primary_timeout"            — 主引擎超时
      "primary_resource_unavailable" — GPU 资源不足
      "quick_fix"                  — 局部快速修复
      "low_priority_segment"       — 低优先级片段
    """
    segment_id: str
    source_audio_ref: str              # 已有 TTS 音频路径（输入）
    speaker_id: str | None = None
    reference_audio_ref: str = ""      # target speaker 参考音频
    speaker_embedding_ref: str = ""    # 预提取的 speaker embedding
    duration_target: float = 0.0
    fallback_reason: str = ""


class OpenVoiceTransferAdapter:
    """将 OpenVoice 音色迁移结果转为 UPDATE_TTS_AUDIO patch。

    封装现有 OpenVoiceCloner，不做修改。
    OpenVoice 定位为"辅助语音迁移引擎"——轻量、快速、适合 fallback。
    """

    def __init__(self, output_dir: str = ""):
        self._output_dir = output_dir
        self._cloner = None

    def configure(self, event_config = None):
        if not event_config: return
        if "speed_factor" in event_config: self._speed = event_config["speed_factor"]

    def transfer(self, ctx: OpenVoiceTransferContext) -> Patch:
        """对已有 TTS 音频做音色迁移，返回 UPDATE_TTS_AUDIO patch。

        流程:
          1. 从 ctx 读取 source_audio_ref（已有 TTS 音频）
          2. 从 ctx 读取 reference_audio_ref（目标 speaker 参考）
          3. 调用 OpenVoiceCloner.clone(source_audio, output_dir)
          4. 返回 Patch（标记 generation_mode=fallback）
        """
        import os
        from pipeline.vc_openvoice import OpenVoiceCloner
        from pipeline.vc_base import VoiceCloneConfig

        cloner = self._get_or_create_cloner(ctx)
        output_dir = self._output_dir or os.path.dirname(ctx.source_audio_ref) or "."

        result_path = cloner.clone(ctx.source_audio_ref, output_dir)

        if result_path is None or not os.path.isfile(result_path):
            return Patch(
                id=f"ov_fail_{ctx.segment_id}",
                target_id=ctx.segment_id,
                op=OpCode.UPDATE_TTS_AUDIO,
                value={
                    "audio_ref": "",
                    "duration": 0,
                    "engine": "openvoice",
                    "generation_mode": "fallback",
                    "fallback_reason": ctx.fallback_reason,
                    "transfer_status": "failed",
                },
                author="system",
                confidence=0.0,
            )

        # 音色迁移不改时长，继承源音频时长
        duration = self._estimate_duration(result_path, ctx.duration_target)
        quality = self._estimate_transfer_quality()

        return Patch(
            id=f"ov_transfer_{ctx.segment_id}",
            target_id=ctx.segment_id,
            op=OpCode.UPDATE_TTS_AUDIO,
            value={
                "audio_ref": result_path,
                "duration": round(duration, 3),
                "transfer_score": quality,
                "speaker_match_score": 0.80,
                "fallback_score": 0.88,
                "quality_score": quality,
                "engine": "openvoice",
                "generation_mode": "fallback",
                "fallback_reason": ctx.fallback_reason,
                "source_audio": ctx.source_audio_ref,
                "reference_audio": ctx.reference_audio_ref,
            },
            author="system",
            confidence=quality,
        )

    def _get_or_create_cloner(self, ctx: OpenVoiceTransferContext):
        if self._cloner is not None:
            return self._cloner
        from pipeline.vc_openvoice import OpenVoiceCloner
        from pipeline.vc_base import VoiceCloneConfig

        config = VoiceCloneConfig(
            engine="openvoice",
            device="auto",
            model_dir="",
            color_audio_path=ctx.reference_audio_ref or ctx.speaker_embedding_ref,
        )
        cloner = OpenVoiceCloner(config)
        if ctx.reference_audio_ref:
            cloner.prepare(ctx.reference_audio_ref)
        self._cloner = cloner
        return cloner

    @staticmethod
    def _estimate_duration(audio_path: str, fallback: float) -> float:
        """估算音频时长。音色迁移不改时长，首选源音频实际时长。"""
        try:
            import soundfile as sf
            info = sf.info(audio_path)
            return info.duration
        except Exception:
            return fallback

    @staticmethod
    def _estimate_transfer_quality() -> float:
        """OpenVoice 音色迁移质量估算 — placeholder。

        完整实现需基于 source/target embedding cosine 距离。
        """
        return 0.79
