"""
VADBoundaryAdapter — Silero VAD 语音边界检测适配器 (Chapter 10 §10.3)

封装现有 VAD_Segmenter.get_segments()。
输出 SEGMENT_INSERT patch 列表——每个 patch 代表一个候选 segment。

VAD 在新架构中的定位:
  Segment Boundary Proposal Engine（分段边界提议引擎）
  不是最终答案，是供 Timeline IR 使用的边界候选。
  SemanticMergePass (Ch2) 可后处理合并过碎的 segment。
"""
from __future__ import annotations
from dataclasses import dataclass
from core.runtime.patch import Patch, OpCode


@dataclass
class VADBoundaryContext:
    """VAD 边界检测输入。"""
    audio_path: str
    min_silence_gap: float = 0.5
    min_speech_duration: float = 0.5
    max_segment_duration: float = 30.0
    threshold: float = 0.25


class VADBoundaryAdapter:
    """封装 VAD_Segmenter.get_segments() → SEGMENT_INSERT patch 列表。

    VAD 在新架构中的定位:
      Segment Boundary Proposal Engine（分段边界提议引擎）
      输出边界候选，不是最终分段。

    每个 SEGMENT_INSERT patch 的 value 包含:
      {start, end, confidence, source: "silero_vad"}
    """

    def configure(self, event_config = None):
        if not event_config: return
        if "vad_threshold" in event_config: self._vad_threshold = event_config["vad_threshold"]
    def detect_boundaries(self, ctx: VADBoundaryContext) -> list[Patch]:
        """运行 VAD，返回 SEGMENT_INSERT patch 列表。

        每个 patch 代表一个候选语音 segment。
        调用方通过 PatchEngine.apply() 逐条写入 Timeline IR。
        """
        import os

        try:
            from SRT.VAD_Segmenter import VAD_Segmenter

            segmenter = VAD_Segmenter(
                audio_path=ctx.audio_path,
                min_silence_gap=ctx.min_silence_gap,
                min_speech_duration=ctx.min_speech_duration,
                max_segment_duration=ctx.max_segment_duration,
                threshold=ctx.threshold,
                device="cpu",
            )
            segments = segmenter.get_segments()
        except Exception:
            return []

        patches = []
        for i, (start, end) in enumerate(segments):
            seg_id = f"vad_{os.path.basename(ctx.audio_path)}_{i:04d}"
            duration = end - start
            confidence = self._estimate_confidence(duration)

            patches.append(Patch(
                id=f"vad_seg_{seg_id}",
                target_id=seg_id,
                op=OpCode.SEGMENT_INSERT,
                value={
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "duration": round(duration, 3),
                    "confidence": confidence,
                    "source": "silero_vad",
                    "threshold": ctx.threshold,
                },
                author="system",
                confidence=confidence,
            ))

        return patches

    def get_vad_stats(self, ctx: VADBoundaryContext) -> dict:
        """返回 VAD 统计信息（不生成 patch）。"""
        patches = self.detect_boundaries(ctx)
        if not patches:
            return {"segment_count": 0, "total_speech_duration": 0.0,
                    "speech_ratio": 0.0, "audio_path": ctx.audio_path}

        total_dur = sum(p.value["duration"] for p in patches)
        try:
            import soundfile as sf
            info = sf.info(ctx.audio_path)
            audio_dur = info.duration
        except Exception:
            audio_dur = total_dur

        return {
            "segment_count": len(patches),
            "total_speech_duration": round(total_dur, 3),
            "speech_ratio": round(total_dur / audio_dur, 4) if audio_dur > 0 else 1.0,
            "audio_path": ctx.audio_path,
        }

    @staticmethod
    def _estimate_confidence(duration: float) -> float:
        """基于 segment 时长估算 VAD 置信度。

        极短 (<0.3s) 或极长 (>60s) 的 segment 置信度较低。
        """
        if duration < 0.3:
            return 0.60
        if duration > 60:
            return 0.65
        if 0.5 <= duration <= 30:
            return 0.90
        return 0.80
