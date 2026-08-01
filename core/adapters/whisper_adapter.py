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
        """用 faster-whisper 逐 VAD 段切片转录。

        与旧 pipeline/transcriber.py 一致：为每个 VAD 段从音频文件中切出精确窗口，
        单独送给 whisper 转录。这样 whisper 只看到 VAD 窗口内的音频，不会产生越界
        segment，无需事后过滤。
        """
        from faster_whisper import WhisperModel
        import soundfile as sf
        import numpy as np

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

        # 加载完整音频到内存（一次 I/O 替代逐段 sf.read）
        audio, sr = sf.read(self.ctx.audio_path)
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        # 合并相邻 VAD 段以减少 whisper 调用次数
        merge_gap = 0.5       # ≤此间隙合并
        merge_max_dur = 45.0  # 合并后最大时长
        merged_segs = []
        cur_start, cur_end = None, None
        for s, e in vad_segments:
            if cur_start is None:
                cur_start, cur_end = s, e
            elif s - cur_end < merge_gap and (e - cur_start) < merge_max_dur:
                cur_end = e
            else:
                merged_segs.append((cur_start, cur_end))
                cur_start, cur_end = s, e
        if cur_start is not None:
            merged_segs.append((cur_start, cur_end))

        language = self.ctx.language
        all_words: list[dict] = []
        segment_gap = 1.5  # 词间停顿超过此值则分裂为新 segment

        for seg_start, seg_end in merged_segs:
            seg_dur = seg_end - seg_start
            start_sample = int(seg_start * sr)
            num_samples = int(seg_dur * sr)

            if num_samples <= 0:
                continue

            audio_seg = audio[start_sample:start_sample + num_samples].copy()

            chunk_segments, info = model.transcribe(
                audio_seg,
                language=self.ctx.language,
                word_timestamps=True,
                vad_filter=False,
            )
            if language is None:
                language = info.language

            for seg in chunk_segments:
                if not seg.words:
                    continue
                for w in seg.words:
                    # adapter 边界清洗: whisper 尾部词 end 可能为 None,
                    # 坏时间戳会经 segmentation 拆出 start>=end 的坏事件
                    if w.start is None or w.end is None or w.end <= w.start:
                        continue
                    all_words.append({
                        "word": w.word.strip(),
                        "start": w.start + seg_start,
                        "end": w.end + seg_start,
                        "score": w.probability,
                    })

            del audio_seg, chunk_segments

        # 按停顿将词分组为 segments（与 legacy transcriber._group_into_segments 一致）
        all_words.sort(key=lambda w: w["start"])
        segments: list[dict] = []
        cur_words: list[dict] = []
        cur_begin, cur_finish = None, None

        for w in all_words:
            ws, we = w["start"], w["end"]
            if cur_begin is None:
                cur_begin, cur_finish = ws, we
                cur_words.append(w)
                continue
            gap = ws - cur_finish
            if gap > segment_gap:
                segments.append({
                    "text": " ".join(w2["word"] for w2 in cur_words),
                    "start": cur_begin,
                    "end": cur_finish,
                    "words": cur_words,
                })
                cur_words = [w]
                cur_begin, cur_finish = ws, we
            else:
                cur_finish = we
                cur_words.append(w)

        if cur_words:
            segments.append({
                "text": " ".join(w2["word"] for w2 in cur_words),
                "start": cur_begin,
                "end": cur_finish,
                "words": cur_words,
            })

        stats = {
            "segments_count": len(segments),
            "total_words": len(all_words),
        }

        segments.sort(key=lambda s: s["start"])
        _close_segment_gaps(segments, vad_segments)

        return segments, language or "auto", stats

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


def _close_segment_gaps(segments: list[dict], vad_segments: list[tuple[float, float]],
                        vad_adjacency_gap: float = 0.5) -> None:
    """闭合 VAD 语音连续区间内因 faster-whisper 内部分段产生的间隙。

    如果两个连续 segment 落在同一 VAD 区间或相邻 VAD 区间（区间间隙 ≤ vad_adjacency_gap），
    则用前段 end 去碰后段 start 消除间隙。
    """
    for i in range(len(segments) - 1):
        gap = segments[i + 1]["start"] - segments[i]["end"]
        if gap <= 0:
            continue

        a_start = segments[i]["start"]
        a_end = segments[i + 1]["end"]

        # 找覆盖两段的 VAD 区间对（允许跨相邻区间）
        first = None
        for s, e in vad_segments:
            if s - vad_adjacency_gap <= a_start <= e + vad_adjacency_gap:
                first = (s, e)
                break
        last = None
        for s, e in reversed(vad_segments):
            if s - vad_adjacency_gap <= a_end <= e + vad_adjacency_gap:
                last = (s, e)
                break
        if first is None or last is None:
            continue

        # 检查 first→last 之间的 VAD 区间间隙是否都 ≤ 阈值
        try:
            idx_first = vad_segments.index(first)
            idx_last = vad_segments.index(last)
        except ValueError:
            continue
        ok = True
        for j in range(idx_first, idx_last):
            if vad_segments[j + 1][0] - vad_segments[j][1] > vad_adjacency_gap:
                ok = False
                break
        if ok:
            segments[i]["end"] = segments[i + 1]["start"]
