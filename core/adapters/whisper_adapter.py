"""
WhisperAdapter — faster-whisper → Patch 适配器 (Chapter 3 §3.2)

直接调用 faster-whisper + Silero VAD，内联转录逻辑。
不依赖旧 pipeline/transcriber.py。
"""
from __future__ import annotations
import logging
import os
import time
from dataclasses import dataclass
from core.runtime.patch import Patch, OpCode

logger = logging.getLogger(__name__)


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

    自包含 VAD + 转录逻辑，不依赖旧 pipeline/ 模块。
    """

    def __init__(self, context: EngineContext):
        self.ctx = context

    def configure(self, event_config=None):
        if not event_config:
            return
        if "model" in event_config:
            self.ctx.model_name = event_config["model"]
        if "device" in event_config:
            self.ctx.device = event_config["device"]
        if "language" in event_config:
            self.ctx.language = event_config["language"]
        if "compute_type" in event_config:
            self.ctx.compute_type = event_config["compute_type"]

    # ── public API ────────────────────────────────────────────

    def run(self) -> list[Patch]:
        """执行完整转录流程 (VAD → faster-whisper)，返回 Patch 列表。"""
        t0 = time.time()

        # Step 1: Silero VAD 分段
        vad_segments = self._run_vad()

        # Step 2: faster-whisper 转录
        segments, language, stats = self._transcribe(vad_segments)

        stats["transcribe_time"] = time.time() - t0
        return self._result_to_patches(segments, language, stats)

    # ── VAD (from SRT/VAD_Segmenter) ──────────────────────────

    def _run_vad(self) -> list[tuple[float, float]]:
        """Silero VAD 分段。"""
        from SRT.VAD_Segmenter import VAD_Segmenter

        vad = VAD_Segmenter(self.ctx.audio_path)
        return vad.get_segments(force=False)

    # ── faster-whisper 转录 ───────────────────────────────────

    def _transcribe(self, vad_segments: list[tuple[float, float]]) -> tuple[list[dict], str, dict]:
        """用 faster-whisper 转录 VAD 分段。"""
        from faster_whisper import WhisperModel

        download_root = self.ctx.model_root
        if not download_root:
            download_root = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "models", "whisper",
            )
        os.makedirs(download_root, exist_ok=True)

        model = WhisperModel(
            self.ctx.model_name,
            device=self.ctx.device,
            compute_type=self.ctx.compute_type,
            download_root=download_root,
            num_workers=self.ctx.num_workers,
        )

        segments: list[dict] = []
        language = self.ctx.language or ""
        total_words = 0

        for start, end in vad_segments:
            chunk_segments, info = model.transcribe(
                self.ctx.audio_path,
                language=self.ctx.language,
                word_timestamps=True,
                vad_filter=False,
            )
            language = info.language

            for seg in chunk_segments:
                seg_start = max(seg.start, start)
                seg_end = min(seg.end, end)
                words = [
                    {"word": w.word.strip(), "start": w.start, "end": w.end, "score": w.probability}
                    for w in (seg.words or [])
                ]
                text = seg.text.strip()
                if not text:
                    continue
                total_words += len(words)
                segments.append({
                    "start": seg_start,
                    "end": seg_end,
                    "text": text,
                    "words": words,
                })

        stats = {
            "segments_count": len(segments),
            "total_words": total_words,
        }
        return segments, language, stats

    # ── Patch 转换 ─────────────────────────────────────────────

    def _result_to_patches(self, segments: list[dict], language: str, stats: dict) -> list[Patch]:
        """将转录结果转换为 Patch 列表。"""
        patches: list[Patch] = []

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
