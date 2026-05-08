"""
VAD 分段 + faster-whisper 转录 + wav2vec2 对齐模块 (NODE 3)

流程:
    VAD 分割 → faster-whisper 转录 → wav2vec2 强制对齐（精修词级时间戳）

接口:
    VADTranscriber
        .run_vad(force=False) -> list     # 执行 VAD 分段
        .detect_language() -> str         # 语言检测（取前 30s）
        .transcribe_all(language) -> dict # 逐段转录 + wav2vec2 对齐 + 词级分组

输出 dict 格式:
    {
        "segments": [{ "text": str, "start": float, "end": float, "words": [...] }],
        "language": str,
        "words": [{ "word": str, "start": float, "end": float }],
        "stats": {
            "vad_count": int,        # VAD 原始段数
            "merged_count": int,     # 合并后批次数
            "total_words": int,      # 总词数
            "segments_count": int,   # 最终 segments 数
            "vad_time": float,
            "model_load_time": float,
            "transcribe_time": float,
            "total_speech_dur": float,
            "silence_dur": float,
        }
    }
"""
import logging
import os
import gc
import queue
import time
import json
from typing import List, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from pipeline.logger import get_logger

logger = get_logger(__name__)

import soundfile as sf
import numpy as np


def _normalize_device(device: str) -> str:
    """归一化设备名并提供可用性验证。

    ctranslate2 / torch 均使用 "cuda"，不识别 "gpu"。
    若 CUDA 不可用则自动回退到 CPU。
    """
    if device not in ("gpu", "cuda"):
        return device
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
        logger.warning("CUDA 不可用，回退到 CPU")
    except ImportError:
        pass
    return "cpu"


class VADTranscriber:
    """VAD 分段 + faster-whisper 逐段转录"""

    def __init__(
        self,
        audio_path: str,
        model_name: str = "small",
        device: str = "cpu",
        compute_type: str = "int8",
        download_root: Optional[str] = None,
        merge_gap: float = 0.5,
        merge_max_dur: float = 120.0,
        segment_gap: float = 1.5,
        sample_rate: int = 16000,
        num_workers: int = 1,
        cpu_threads: int = 0,
    ):
        self.audio_path = audio_path
        self.model_name = model_name
        # 归一化设备名并验证可用性：ctranslate2 / torch 使用 "cuda"
        self.device = _normalize_device(device)
        self.compute_type = compute_type
        self.download_root = download_root
        self.merge_gap = merge_gap
        self.merge_max_dur = merge_max_dur
        self.segment_gap = segment_gap
        self.sample_rate = sample_rate
        self.num_workers = num_workers
        self.cpu_threads = cpu_threads

        self._model_pool = None
        self._vad_segments = None
        self._audio_len = 0.0
        self._align_model = None
        self._align_metadata = None

    # ── VAD ──────────────────────────────────────────────────────

    def run_vad(self, force: bool = False) -> List[Tuple[float, float]]:
        """执行 Silero VAD 分段，返回 [(start, end), ...]"""
        from VAD_Segmenter import VAD_Segmenter

        t0 = time.time()
        vad = VAD_Segmenter(self.audio_path)
        self._vad_segments = vad.get_segments(force=force)
        vad_time = time.time() - t0

        # 获取音频时长
        self._audio_len = sum(e - s for s, e in self._vad_segments)

        # 获取 WAV 文件总时长（从文件元数据）
        info = sf.SoundFile(self.audio_path)
        self._audio_len = info.frames / info.samplerate
        info.close()

        return self._vad_segments, vad_time

    def get_vad_stats(self) -> dict:
        """返回 VAD 统计信息"""
        if not self._vad_segments:
            return {}
        total_speech = sum(e - s for s, e in self._vad_segments)
        silence = self._audio_len - total_speech
        return {
            "vad_count": len(self._vad_segments),
            "audio_len": self._audio_len,
            "total_speech_dur": total_speech,
            "silence_dur": silence,
            "first_segment": self._vad_segments[0] if self._vad_segments else None,
            "last_segment": self._vad_segments[-1] if self._vad_segments else None,
        }

    # ── 模型加载 ────────────────────────────────────────────────

    def _compute_vram_limit(self, model_path: str, requested: int) -> int:
        """根据 model.bin 大小和可用 VRAM 计算最大实例数。

        模型权重已由 CTranslate2 量化为固定格式 (model.bin)，VRAM ≈ 文件大小。
        compute_type 只影响计算时的中间缓冲区精度，不改变权重占用。
        额外 ×1.2 覆盖运行时缓冲区 (KV cache / encoder state)。
        保留 15% VRAM 给 CUDA 上下文和音频缓存。
        CPU 模式不限实例数。
        """
        if self.device != "cuda":
            return requested

        bin_path = os.path.join(model_path, "model.bin")
        if not os.path.isfile(bin_path):
            return max(requested, 1)
        bin_size_mb = os.path.getsize(bin_path) / (1024 * 1024)
        per_instance_mb = bin_size_mb * 1.2

        import torch
        free_mb, total_mb = torch.cuda.mem_get_info()
        free_mb = free_mb / (1024 * 1024)

        usable_mb = free_mb * 0.85
        max_by_vram = max(1, int(usable_mb / per_instance_mb))

        result = min(requested, max_by_vram)
        logger = logging.getLogger(__name__)
        logger.info(
            "VRAM: 可用 %.0fMB / 共 %.0fMB, 单模型 ~%.0fMB (model.bin %.0fMB ×1.2), 上限 %d → 实际 %d",
            free_mb, total_mb, per_instance_mb, bin_size_mb, max_by_vram, result,
        )
        return result

    def _load_model_pool(self, count: int):
        """加载模型池 — count 个独立 WhisperModel 实例。

        每个模型实例 cpu_threads=0, num_workers=1，并发由外部线程池管理。
        GPU 下根据 VRAM 自动限制实例数，避免 OOM。
        """
        from faster_whisper import WhisperModel
        logger = logging.getLogger(__name__)

        local_root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models", "whisper")
        local_path = os.path.join(local_root, self.model_name)
        if os.path.isdir(local_path) and os.path.isfile(os.path.join(local_path, "model.bin")):
            model_path = local_path
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
        else:
            model_path = self.model_name

        count = self._compute_vram_limit(model_path, count)

        t0 = time.time()
        self._model_pool = queue.Queue(maxsize=count)
        for i in range(count):
            logger.info("加载模型 %d/%d: %s", i + 1, count, model_path)
            model = WhisperModel(
                model_path,
                device=self.device,
                compute_type=self.compute_type,
                download_root=self.download_root,
                cpu_threads=0,
                num_workers=1,
            )
            self._model_pool.put(model)
        return time.time() - t0

    # ── 语言检测 ────────────────────────────────────────────────

    def detect_language(self) -> Tuple[str, float]:
        """
        检测音频语言（取前 30s）。
        Returns:
            (language_code, confidence)
        """
        if self._model_pool is None:
            self._load_model_pool(1)

        model = self._model_pool.get()
        try:
            detect_dur = min(15.0, self._audio_len)
            audio_data, sr = sf.read(self.audio_path, start=0, frames=int(detect_dur * self.sample_rate))
            seg_gen, detect_info = model.transcribe(audio_data, beam_size=2)
            for _ in seg_gen:
                pass
            language = detect_info.language if detect_info else "en"
            lang_prob = getattr(detect_info, "language_probability", -1)
            del audio_data, seg_gen
            gc.collect()
            return language, lang_prob
        finally:
            self._model_pool.put(model)

    # ── wav2vec2 对齐 ────────────────────────────────────────────

    def _init_aligner(self, language: str = "ja"):
        """懒加载 whisperX 的 wav2vec2 对齐模型"""
        if self._align_model is not None:
            return
        import os
        if not os.environ.get("HF_ENDPOINT"):
            os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
        from whisperx_local.alignment import load_align_model
        local_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "models", "wav2vec2", language,
        )
        if os.path.isdir(local_path) and os.path.isfile(os.path.join(local_path, "config.json")):
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
            self._align_model, self._align_metadata = load_align_model(
                language_code=language, device=self.device,
                model_name=local_path,
            )
        else:
            self._align_model, self._align_metadata = load_align_model(
                language_code=language, device=self.device,
            )

    def align_all(self, segments: List[dict], language: str = "ja") -> List[dict]:
        """
        用 wav2vec2 强制对齐精修词级时间戳。

        Args:
            segments: [{text, start, end}, ...] — faster-whisper 的初步结果
            language: 语言代码

        Returns:
            更新后的 segments，各 segment 含 "words" 字段（精准时间戳）
        """
        import torch
        import soundfile as sf
        import numpy as np
        from whisperx_local.alignment import align

        self._init_aligner(language)

        # 加载完整音频（float32）
        audio, sr = sf.read(self.audio_path)
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        # align() 处理整段音频，按 segments 的 start/end 自动切割
        aligned = align(
            segments, self._align_model, self._align_metadata,
            audio, device=self.device, return_char_alignments=False,
        )

        del audio
        gc.collect()

        return aligned.get("segments", segments)

    # ── 段合并 ──────────────────────────────────────────────────

    def merge_segments(self, segments: List[Tuple[float, float]]
                       ) -> List[Tuple[float, float]]:
        """合并短段，减少推理调用次数"""
        merged = []
        current_start = None
        current_end = None

        for s, e in segments:
            if current_start is None:
                current_start = s
                current_end = e
            else:
                gap = s - current_end
                if gap < self.merge_gap and (e - current_start) < self.merge_max_dur:
                    current_end = e
                else:
                    merged.append((current_start, current_end))
                    current_start = s
                    current_end = e

        if current_start is not None:
            merged.append((current_start, current_end))

        return merged

    # ── 转录 ────────────────────────────────────────────────────

    def _transcribe_batch(self, seg_start: float, seg_end: float,
                         audio_array: Optional[np.ndarray] = None,
                         model=None) -> list:
        """转录单个音频段，返回词列表。

        Args:
            seg_start, seg_end: 全局时间范围
            audio_array: 若提供则从内存切片（并行模式，避免 soundfile 线程安全
                         问题）；否则从文件读取（串行模式）。
            model: WhisperModel 实例；None 则从模型池借用
        """
        seg_dur = seg_end - seg_start
        start_sample = int(seg_start * self.sample_rate)
        num_samples = int(seg_dur * self.sample_rate)

        if audio_array is not None:
            audio_seg = audio_array[start_sample:start_sample + num_samples].copy()
            if audio_seg.dtype != np.float32:
                audio_seg = audio_seg.astype(np.float32)
        else:
            audio_seg, _ = sf.read(self.audio_path, start=start_sample, frames=num_samples)
            audio_seg = audio_seg.astype(np.float32)

        whisper_model = model if model is not None else self._model_pool.get()
        seg_words = []
        segments, info = whisper_model.transcribe(
            audio_seg,
            language=self._language,
            word_timestamps=True,
            beam_size=2,
            vad_filter=False,
        )
        for seg in segments:
            if seg.words:
                for w in seg.words:
                    seg_words.append({
                        "word": w.word.strip(),
                        "start": w.start + seg_start,
                        "end": w.end + seg_start,
                    })

        del audio_seg, segments
        return seg_words

    def _group_into_segments(self, all_words: list) -> list:
        """将词级时间戳按停顿分组为 segments"""
        segments = []
        current_words = []
        current_start = None
        current_end = None

        for w in all_words:
            ws, we = w["start"], w["end"]
            if current_start is None:
                current_start = ws
                current_end = we
                current_words.append(w)
                continue
            gap = ws - current_end
            if gap > self.segment_gap:
                text = " ".join(w2["word"] for w2 in current_words)
                segments.append({
                    "text": text,
                    "start": current_start,
                    "end": current_end,
                    "words": current_words,
                })
                current_words = [w]
                current_start = ws
                current_end = we
            else:
                current_words.append(w)
                current_end = we

        if current_words:
            text = " ".join(w2["word"] for w2 in current_words)
            segments.append({
                "text": text,
                "start": current_start,
                "end": current_end,
                "words": current_words,
            })

        return segments

    # ── 全流程 ──────────────────────────────────────────────────

    def transcribe_all(self, language: Optional[str] = None,
                       align_language: Optional[str] = None) -> dict:
        """
        完整转录流程：加载模型 → 语言检测 → 合并段 → 并行/串行转录
        → 词级分组 → [可选] wav2vec2 强制对齐精修时间戳

        当 num_workers > 1 且 merged 段数 > 1 时，使用 ThreadPoolExecutor
        并行转录各段，预加载完整音频到内存避免 soundfile 线程安全问题。
        收集结果后按词级绝对时间戳排序，保证时间轴准确性不受并行调度影响。

        Args:
            language: 强制指定语言代码；None 则自动检测
            align_language: 指定 wav2vec2 对齐语言（如 "ja"）
                           传入时启用 wav2vec2 对齐；None 则不启用

        Returns:
            {
                "segments": [...],
                "language": str,
                "words": [...],
                "stats": {...}
            }
        """
        # 模型池: count = num_workers (GPU 自动限制 max 2)
        # 最少 1 段也加载 1 个模型；多于 1 段才值得多模型
        pool_size = self.num_workers if (self.num_workers > 1 and len(self._vad_segments) > 1) else 1
        model_load_time = self._load_model_pool(pool_size)

        # 语言检测
        if language is None:
            t0 = time.time()
            self._language, lang_prob = self.detect_language()
            detect_time = time.time() - t0
        else:
            self._language = language
            lang_prob = -1
            detect_time = 0

        # 自动启用 wav2vec2 对齐（检测到语言后自动使用）
        if align_language is None and self._language:
            align_language = self._language

        # 合并 VAD 段
        merged = self.merge_segments(self._vad_segments)
        merged_count = len(merged)
        vad_count = len(self._vad_segments)

        # ── 转录（并行 / 串行） ──────────────────────────────

        seg_times = []
        t0_total = time.time()

        if pool_size > 1 and len(merged) > 1:
            # ── 并行模式（模型池） ───────────────────────
            # 预加载完整音频到内存，避免 soundfile 线程安全问题
            audio_data, _ = sf.read(self.audio_path)
            logger = logging.getLogger(__name__)
            logger.info(
                "并行转录: %d 段, %d workers, %d 模型实例",
                len(merged), pool_size, pool_size,
            )

            def _transcribe_one(idx: int, seg_start: float, seg_end: float
                               ) -> Tuple[int, float, float, list, float]:
                model = self._model_pool.get(timeout=120)
                try:
                    t_seg = time.time()
                    seg_words = self._transcribe_batch(
                        seg_start, seg_end, audio_array=audio_data, model=model,
                    )
                    return idx, seg_start, seg_end, seg_words, time.time() - t_seg
                finally:
                    self._model_pool.put(model)

            results: List[Tuple[int, float, float, list, float]] = []
            thread_count = min(pool_size, len(merged))
            with ThreadPoolExecutor(max_workers=thread_count) as pool:
                futures = {
                    pool.submit(_transcribe_one, i, s, e): i
                    for i, (s, e) in enumerate(merged, 1)
                }
                for fut in as_completed(futures):
                    try:
                        results.append(fut.result())
                    except Exception as exc:
                        logger.error(
                            "转录 segment %d 失败: %s",
                            futures[fut], exc,
                        )
                        raise

            # 按 segment index 排序，恢复原始顺序
            results.sort(key=lambda r: r[0])

            all_words = []
            for idx, seg_start, seg_end, seg_words, elapsed in results:
                all_words.extend(seg_words)
                seg_times.append({
                    "index": idx,
                    "start": seg_start,
                    "end": seg_end,
                    "words": len(seg_words),
                    "time": elapsed,
                })

            del audio_data
            gc.collect()

        else:
            # ── 串行模式 ────────────────────────────────
            # 从池中借用模型，循环内复用同一个实例
            model = self._model_pool.get()
            try:
                all_words = []
                for idx, (seg_start, seg_end) in enumerate(merged, 1):
                    t0 = time.time()
                    seg_words = self._transcribe_batch(seg_start, seg_end, model=model)
                    elapsed = time.time() - t0
                    all_words.extend(seg_words)
                    seg_times.append({
                        "index": idx,
                        "start": seg_start,
                        "end": seg_end,
                        "words": len(seg_words),
                        "time": elapsed,
                    })

                    if idx % 10 == 0:
                        gc.collect()
            finally:
                self._model_pool.put(model)

        transcribe_time = time.time() - t0_total

        # 按词级绝对时间戳排序，保证 _group_into_segments 的 gap 计算正确
        all_words.sort(key=lambda w: w["start"])

        # 词级 → 分组
        t0 = time.time()
        segments = self._group_into_segments(all_words)
        group_time = time.time() - t0

        # wav2vec2 强制对齐（可选，不参与并行，确保对齐精度）
        align_time = 0
        if align_language is not None:
            logger = logging.getLogger(__name__)
            logger.info(f"开始 wav2vec2 对齐 (lang={align_language})...")
            t0 = time.time()
            segments = self.align_all(segments, language=align_language)
            align_time = time.time() - t0
            logger.info(f"wav2vec2 对齐完成，耗时: {align_time:.1f}s")

        # 清理模型池 — 排空队列，逐个 del 释放显存/内存
        if self._model_pool:
            logger = logging.getLogger(__name__)
            destroyed = 0
            while True:
                try:
                    m = self._model_pool.get_nowait()
                    del m
                    destroyed += 1
                except queue.Empty:
                    break
            self._model_pool = None
            if destroyed:
                logger.info("已释放 %d 个模型实例", destroyed)
        gc.collect()

        return {
            "segments": segments,
            "language": self._language,
            "words": all_words,
            "stats": {
                "vad_count": vad_count,
                "merged_count": merged_count,
                "total_words": len(all_words),
                "segments_count": len(segments),
                "model_load_time": model_load_time,
                "detect_time": detect_time,
                "lang_probability": lang_prob,
                "transcribe_time": transcribe_time,
                "group_time": group_time,
                "align_time": align_time,  # wav2vec2 对齐耗时
                "batch_details": seg_times,
            },
        }

    @staticmethod
    def save_json(result: dict, output_path: str) -> int:
        """保存转录结果为 JSON 文件，返回文件大小"""
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return os.path.getsize(output_path)
