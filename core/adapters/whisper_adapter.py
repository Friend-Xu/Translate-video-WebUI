"""
WhisperAdapter — faster-whisper → Patch 适配器 (Chapter 3 §3.2)

封装现有 VADTranscriber，将其输出转换为 Patch 列表。
不做任何文件 I/O，不修改原始引擎代码。
"""
from __future__ import annotations
from dataclasses import dataclass
from core.runtime.patch import Patch, OpCode


@dataclass
class EngineContext:
    """引擎运行上下文 — 传给所有 Adapter 的标准化配置。"""
    audio_path: str
    device: str = "cuda"
    model_name: str = "small"
    compute_type: str = "float16"
    language: str | None = None
    sample_rate: int = 16000
    num_workers: int = 1
    model_root: str | None = None


class WhisperAdapter:
    """将 faster-whisper 输出转为 SEGMENT_INSERT + ANNOTATE patch。

    不修改 VADTranscriber。只做薄封装：
    调用现有引擎 → 转换输出格式 → 生成 Patch 列表。
    """

    def __init__(self, context: EngineContext):
        self.ctx = context

    def run(self) -> list[Patch]:
        """执行完整转录流程，返回 Patch 列表。

        Returns:
            [SEGMENT_INSERT...] — 每个 ASR segment 一个 patch
            [+ ANNOTATE] — 全局元信息（语言、模型、统计）
        """
        from pipeline.transcriber import VADTranscriber

        transcriber = VADTranscriber(
            audio_path=self.ctx.audio_path,
            model_name=self.ctx.model_name,
            device=self.ctx.device,
            compute_type=self.ctx.compute_type,
            download_root=self.ctx.model_root,
            num_workers=self.ctx.num_workers,
        )

        # VAD
        transcriber.run_vad(force=False)

        # 转录 + 对齐
        result = transcriber.transcribe_all(
            language=self.ctx.language,
            enable_align=True,
        )

        return self._result_to_patches(result)

    def _result_to_patches(self, result: dict) -> list[Patch]:
        """将 VADTranscriber 输出转换为 Patch 列表。"""
        patches: list[Patch] = []
        segments = result.get("segments", [])
        language = result.get("language", "")
        stats = result.get("stats", {})

        for i, seg in enumerate(segments):
            seg_id = f"evt_{i + 1:03d}"
            patch = Patch(
                id=f"asr_{seg_id}",
                target_id=seg_id,
                op=OpCode.SEGMENT_INSERT,
                value={
                    "start": seg.get("start", 0.0),
                    "end": seg.get("end", 0.0),
                    "text": seg.get("text", "").strip(),
                    "words": seg.get("words", []),
                    "language": language,
                    "source": "faster-whisper",
                },
                author="system",
                confidence=self._avg_word_confidence(seg.get("words", [])),
            )
            patches.append(patch)

        # 全局元信息 patch
        patches.append(Patch(
            id="asr_meta",
            target_id="timeline",
            op=OpCode.ANNOTATE,
            value={
                "language": language,
                "model_name": self.ctx.model_name,
                "total_words": stats.get("total_words", 0),
                "segments_count": stats.get("segments_count", 0),
                "transcribe_time": stats.get("transcribe_time", 0),
                "align_time": stats.get("align_time", 0),
            },
            author="system",
        ))

        return patches

    @staticmethod
    def _avg_word_confidence(words: list[dict]) -> float:
        if not words:
            return 1.0
        scores = [w.get("score", 0.0) for w in words if w.get("score") is not None]
        return sum(scores) / len(scores) if scores else 1.0
