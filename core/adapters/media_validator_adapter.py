"""
MediaValidatorAdapter — 音频缺陷诊断 + 修复适配器 (Chapter 10 §10.2-10.4)

封装现有 MediaValidator.diagnose() + ensure_audio_duration()。
输出 ANNOTATE patch 写入 audio 槽位。

这是整个系统最前置的适配器——所有下游引擎依赖它提供的干净音频。
"""
from __future__ import annotations
from dataclasses import dataclass
from core.runtime.patch import Patch, OpCode


@dataclass
class AudioDefectContext:
    """音频缺陷诊断输入。"""
    video_path: str
    output_audio_path: str = ""
    sample_rate: int = 16000
    channels: int = 1


class MediaValidatorAdapter:
    """封装 MediaValidator → ANNOTATE patch。

    封装现有 MediaValidator.diagnose() + ensure_audio_duration()。
    输出 ANNOTATE patch 写入 audio 槽位。
    """

    def configure(self, event_config = None):
        if not event_config: return
        if "loudness_compensation" in event_config: self._loudness_norm = event_config["loudness_compensation"]
        if "target_loudness" in event_config: self._target_loudness = event_config["target_loudness"]
        if "high_pass_filter" in event_config: self._high_pass = event_config["high_pass_filter"]
    def diagnose(self, ctx: AudioDefectContext) -> Patch:
        """运行缺陷诊断，返回 ANNOTATE patch。

        不修改任何文件，只分析视频的音频健康状况。
        """
        from SRT.MediaValidator import MediaValidator

        validator = MediaValidator()
        result = validator.diagnose(ctx.video_path)

        needs_repair = result.defect_type is not None and result.defect_type != ""

        return Patch(
            id=f"audio_defect_{self._slug(ctx.video_path)}",
            target_id="audio",
            op=OpCode.ANNOTATE,
            value={
                "defect_status": result.status,
                "defect_type": result.defect_type or "none",
                "container_duration": getattr(result, "container_duration", 0),
                "decoded_audio_duration": getattr(result, "decoded_audio_duration", 0),
                "needs_repair": needs_repair,
                "source": "media_validator",
            },
            author="system",
            confidence=0.95,
        )

    def repair_and_extract(self, ctx: AudioDefectContext) -> Patch:
        """执行 C2 修复 + 音频提取，返回 ANNOTATE patch。

        复用 ensure_audio_duration() 的统一音频提取:
          aresample=async=1:first_pts=0 + -t <container_duration>

        输出: 16kHz mono PCM16 WAV。
        """
        import os
        from SRT.MediaValidator import MediaValidator, ensure_audio_duration

        validator = MediaValidator()
        result = validator.diagnose(ctx.video_path)

        audio_path = ctx.output_audio_path
        if not audio_path:
            base = os.path.splitext(os.path.basename(ctx.video_path))[0]
            parent = os.path.dirname(ctx.video_path) or "."
            ws_dir = os.path.join(parent, f"{base}_project", "01_extract")
            os.makedirs(ws_dir, exist_ok=True)
            audio_path = os.path.join(ws_dir, f"{base}_extracted.wav")

        ensure_audio_duration(
            ctx.video_path, audio_path,
            sr=ctx.sample_rate, ch=ctx.channels,
        )

        # Get actual duration from the output wav
        try:
            import soundfile as sf
            info = sf.info(audio_path)
            actual_dur = info.duration
        except Exception:
            actual_dur = 0.0

        repair_applied = result.defect_type in ("C2", "A2")

        return Patch(
            id=f"audio_extract_{self._slug(ctx.video_path)}",
            target_id="audio",
            op=OpCode.ANNOTATE,
            value={
                "audio_ref": audio_path,
                "sample_rate": ctx.sample_rate,
                "channels": ctx.channels,
                "duration": round(actual_dur, 3),
                "repair_applied": repair_applied,
                "repair_method": "aresample" if repair_applied else "none",
                "defect_type": result.defect_type or "none",
                "source": "media_validator",
            },
            author="system",
            confidence=0.95,
        )

    @staticmethod
    def _slug(path: str) -> str:
        import hashlib
        return hashlib.md5(path.encode()).hexdigest()[:8]
