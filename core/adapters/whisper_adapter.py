"""
WhisperAdapter — faster-whisper → Patch 适配器 (CLI Runtime 计划书 §5)

直接调用 faster-whisper + Silero VAD，内联转录逻辑。
不依赖旧 pipeline/transcriber.py。

实现 AdapterProtocol，capability_id = "asr.whisper"。
"""
from __future__ import annotations
import logging
import os
import time
from dataclasses import dataclass
from core.runtime.patch import Patch, OpCode
from core.adapters.protocol import (
    AdapterProtocol, AdapterCapability, AdapterResult,
    ErrorCategory, ResourceRequirement,
)

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


class WhisperAdapter(AdapterProtocol):
    """将 faster-whisper 输出转为 SEGMENT_INSERT + ANNOTATE patch。

    自包含 VAD + 转录逻辑，不依赖旧 pipeline/ 模块。
    """

    def __init__(self, context: EngineContext, workspace_dir: str = ""):
        self.ctx = context
        self.workspace_dir = workspace_dir

    # ── AdapterProtocol 实现 ──────────────────────────────────

    @property
    def capability(self) -> AdapterCapability:
        return AdapterCapability(
            capability_id="asr.whisper",
            display_name="Whisper ASR (faster-whisper + Silero VAD)",
            resources=ResourceRequirement(gpu=self.ctx.device == "cuda", vram_mb=3000),
            failure_policy="retry",
        )

    def execute(self, **kwargs) -> AdapterResult:
        """统一执行入口。委托 run()，包装为 AdapterResult。"""
        try:
            patches = self.run()
            return AdapterResult(ok=True, patches=patches, data={"language": self.ctx.language})
        except Exception as exc:
            return AdapterResult(
                ok=False, error=str(exc),
                error_category=self._categorize(exc),
            )

    @staticmethod
    def _categorize(exc: Exception) -> ErrorCategory:
        msg = str(exc).lower()
        if "cuda" in msg or "out of memory" in msg or "gpu" in msg:
            return ErrorCategory.RETRYABLE
        if "not found" in msg or "download" in msg:
            return ErrorCategory.RETRYABLE
        if "model" in msg or "unsupported" in msg:
            return ErrorCategory.FATAL
        return ErrorCategory.RETRYABLE

    # ── 配置注入 ─────────────────────────────────────────────
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
        """执行完整转录流程 (VAD → faster-whisper)，返回 Patch 列表。

        同时将原始转录结果 + VAD 分段写入工作目录 01_extract/。
        """
        t0 = time.time()

        # Step 1: Silero VAD 分段
        vad_segments = self._run_vad()

        # Step 2: faster-whisper 转录
        segments, language, stats = self._transcribe(vad_segments)

        stats["transcribe_time"] = time.time() - t0

        # Step 3: 持久化原始转录结果
        self._persist_transcript(segments, language, stats, vad_segments)

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
                if seg_start >= seg_end:
                    continue
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

    def _persist_transcript(self, segments: list[dict], language: str,
                            stats: dict, vad_segments: list[tuple[float, float]]) -> None:
        """将原始转录结果写入 01_extract/transcript.json 和 vad_segments.json。"""
        import json
        if not self.workspace_dir:
            return
        extract_dir = os.path.join(self.workspace_dir, "01_extract")
        os.makedirs(extract_dir, exist_ok=True)

        transcript_path = os.path.join(extract_dir, "transcript.json")
        with open(transcript_path, "w", encoding="utf-8") as f:
            json.dump({
                "segments": segments,
                "language": language,
                "words": [w for seg in segments for w in seg.get("words", [])],
                "stats": stats,
            }, f, ensure_ascii=False, indent=2)

        vad_path = os.path.join(extract_dir, "vad_segments.json")
        with open(vad_path, "w", encoding="utf-8") as f:
            json.dump(
                [{"start": s, "end": e} for s, e in vad_segments],
                f, ensure_ascii=False, indent=2,
            )

    @staticmethod
    def _avg_word_confidence(words: list[dict]) -> float:
        if not words:
            return 1.0
        scores = [w.get("score", 0.0) for w in words if w.get("score") is not None]
        return sum(scores) / len(scores) if scores else 1.0
