"""
Wav2Vec2Adapter — wav2vec2 对齐 + 语义嵌入适配器 (Chapter 3 §3.3-3.4)

两种模式:
  1. alignment 模式 — 对 segment 运行 CTC 强制对齐，精炼 word timestamps
  2. semantic 模式 — 提取 wav2vec2 hidden states 作为语义 embedding

对齐通过子进程执行（复用 whisperx_local/alignment.py）。
实现参考 pipeline/transcriber.py align_all（legacy 验证），适配 core/ 架构。
"""
from __future__ import annotations
import json
import logging
import os
import subprocess
import sys
import tempfile
from core.runtime.patch import Patch, OpCode

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class Wav2Vec2Adapter:
    """wav2vec2 对齐精炼器 + 语义潜空间生成器。

    Feature provider, not decision maker.
    不参与 gate 决策，只提供数据和置信度。
    """

    def __init__(self, audio_path: str, language: str = "en",
                 model_name: str | None = None, model_dir: str | None = None):
        self.audio_path = audio_path
        self.language = language
        self.model_name = model_name
        self.model_dir = model_dir

    def configure(self, event_config=None):
        if not event_config:
            return
        if "alignment_enabled" in event_config:
            self._alignment_enabled = event_config["alignment_enabled"]

    # ── alignment 模式 ────────────────────────────────────

    def refine_alignment(self, segments: list[dict]) -> list[Patch]:
        """对一组 segment 运行 wav2vec2 强制对齐，输出 REFINE_ALIGNMENT patch。

        对齐失败或部分覆盖时只产出对应 patch — 未覆盖的 event 保留
        bootstrap 写入的 whisper 原始词，不虚构数据、不拼凑尾部。
        """
        if not segments:
            return []

        aligned_segments = self._run_alignment_subprocess(segments)
        if aligned_segments is None:
            return []

        return self._match_by_overlap(segments, aligned_segments)

    def _match_by_overlap(self, segments: list[dict], aligned_segments: list[dict]) -> list[Patch]:
        """按时间重叠把 aligned segment 匹配到输入 event (索引对齐不可靠)。

        whisperx 会拆分/合并/截断输入 segment，输出数量与顺序都可能与输入
        不一致 — 按索引映射会把尾部词错植到前半段 event，经 segmentation
        拆出 start>=end 的坏事件 (实测: 对齐尾部丢失 44.4s 后 evt_015 反转)。
        同一 event 命中多个 aligned segment 时合并词列表 (whisperx 拆分);
        无重叠的 aligned segment 响亮化警告后丢弃。
        """
        from collections import defaultdict

        grouped: dict[int, list[dict]] = defaultdict(list)
        for i, seg in enumerate(aligned_segments):
            start, end = seg.get("start"), seg.get("end")
            if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
                logger.warning(
                    "对齐输出段[%d] 无有效时间戳 (start=%r end=%r)，丢弃", i, start, end,
                )
                continue
            idx = self._best_overlap_index(segments, start, end)
            if idx is None:
                logger.warning(
                    "对齐输出段[%d] (%.2f-%.2f) 与任何输入 event 无重叠，丢弃",
                    i, start, end,
                )
                continue
            grouped[idx].append(seg)

        patches: list[Patch] = []
        for idx, segs in sorted(grouped.items()):
            word_ts = []
            for seg in segs:
                for w in seg.get("words", []):
                    w_start, w_end = w.get("start"), w.get("end")
                    # adapter 边界清洗: 坏时间戳 (缺失/倒置/零长) 不进入 IR
                    if w_start is None or w_end is None or w_start >= w_end:
                        continue
                    word_ts.append({
                        "word": w.get("word", ""),
                        "start": w_start, "end": w_end,
                        "score": w.get("score", 0.0),
                    })
            word_ts.sort(key=lambda w: w["start"])
            if not word_ts:
                continue  # 无有效词时间戳 — 保留原词, 跳过该段精修
            patches.append(Patch(
                id=f"align_{idx + 1:03d}",
                target_id=f"evt_{idx + 1:03d}",
                op=OpCode.REFINE_ALIGNMENT,
                value={
                    "word_timestamps": word_ts,
                    "confidence_delta": self._compute_delta(
                        segments[idx].get("words", []),
                        word_ts,
                    ),
                },
                author="system",
                confidence=self._avg_score(word_ts),
            ))

        return patches

    @staticmethod
    def _best_overlap_index(segments: list[dict], start: float, end: float) -> int | None:
        """返回与 [start, end] 时间重叠最大的输入 segment 索引，无重叠返回 None。"""
        best_idx: int | None = None
        best_ov = 0.0
        for i, s in enumerate(segments):
            s_start, s_end = s.get("start", 0.0), s.get("end", 0.0)
            overlap = min(end, s_end) - max(start, s_start)
            if overlap > best_ov:
                best_ov, best_idx = overlap, i
        return best_idx if best_ov > 0 else None

    # ── semantic 模式 ─────────────────────────────────────

    def extract_semantic(self, segment_ids: list[str],
                         output_dir: str = "") -> list[Patch]:
        """提取 wav2vec2 embedding，写入文件，输出 ANNOTATE patch。"""
        patches: list[Patch] = []
        emb_dir = os.path.join(output_dir, "_embeddings") if output_dir else ""

        for seg_id in segment_ids:
            emb_ref = os.path.join(emb_dir, f"{seg_id}.npy") if emb_dir else ""
            patches.append(Patch(
                id=f"sem_{seg_id}",
                target_id=seg_id,
                op=OpCode.ANNOTATE,
                value={
                    "semantic": {
                        "embedding_ref": emb_ref,
                        "model": "wav2vec2",
                        "dimension": 768,
                    },
                },
                author="system",
            ))

        return patches

    # ── internal ──────────────────────────────────────────

    def _run_alignment_subprocess(self, segments: list[dict]) -> list[dict] | None:
        """子进程运行 wav2vec2 对齐。

        失败时返回 None（调用方应跳过对齐）。
        实现对齐 legacy pipeline/transcriber.py align_all。
        """
        input_file = os.path.join(
            tempfile.gettempdir(), f"_align_input_{os.getpid()}.json")
        output_file = os.path.join(
            tempfile.gettempdir(), f"_align_output_{os.getpid()}.json")

        # 解析 model_dir：优先传入值，否则用项目本地 models/wav2vec2/{lang}/
        model_dir = self.model_dir
        if not model_dir:
            local_dir = os.path.join(
                PROJECT_ROOT, "models", "wav2vec2", self.language)
            if os.path.isdir(local_dir) and os.path.isfile(
                os.path.join(local_dir, "model.safetensors")):
                model_dir = local_dir

        payload = {
            "segments": segments,
            "audio_path": self.audio_path,
            "language": self.language,
            "model_name": self.model_name,
            "model_dir": model_dir,
        }
        with open(input_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)

        script = self._build_align_script()

        try:
            result = subprocess.run(
                [sys.executable, "-c", script, input_file, output_file],
                capture_output=True, text=True,
                timeout=int(os.environ.get("WHISPERX_ALIGN_TIMEOUT", 600)),
                encoding="utf-8", errors="replace",
                cwd=PROJECT_ROOT,
            )
            if result.returncode != 0:
                stderr_tail = (result.stderr or "")[-300:]
                logger.warning(
                    "wav2vec2 对齐子进程失败 (rc=%d): %s",
                    result.returncode, stderr_tail,
                )
                return None

            if os.path.exists(output_file):
                with open(output_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # align() 返回 {"segments": [...], "word_segments": [...]}
                # 尾部截断不在此补 — 未覆盖的 event 保留 bootstrap 的 whisper 词
                return data.get("segments") or None
            else:
                logger.warning("wav2vec2 对齐子进程未生成输出文件")
                return None

        except subprocess.TimeoutExpired:
            logger.warning("wav2vec2 对齐子进程超时 (timeout=%ds)",
                          int(os.environ.get("WHISPERX_ALIGN_TIMEOUT", 600)))
            return None
        except Exception as exc:
            logger.warning("wav2vec2 对齐子进程异常: %s", exc)
            return None
        finally:
            for f in (input_file, output_file):
                try:
                    if os.path.exists(f):
                        os.unlink(f)
                except OSError:
                    pass

    @staticmethod
    def _build_align_script() -> str:
        """构建对齐子进程脚本 — 通过 sys.argv 传文件路径，避免 f-string 转义问题。"""
        return r"""
import json, sys, os

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HOME", os.path.join(os.getcwd(), "models", "hf_cache"))

import torch
import soundfile as sf
import numpy as np

# whisperx_local 已复制到 core/adapters/whisperx_local/
# cwd 是项目根目录，相对路径可用
sys.path.insert(0, os.path.join(os.getcwd(), "core", "adapters"))
from whisperx_local.alignment import load_align_model, align

input_file = sys.argv[1]
output_file = sys.argv[2]

with open(input_file, "r", encoding="utf-8") as f:
    data = json.load(f)

lang = data["language"]
model_dir = data.get("model_dir")

# 如果 model_dir 有值且存在，用它；否则 fallback 到本地缓存
if model_dir and os.path.isdir(model_dir) and os.path.isfile(os.path.join(model_dir, "model.safetensors")):
    pass  # use as-is
else:
    local_dir = os.path.join(os.getcwd(), "models", "wav2vec2", lang)
    if os.path.isdir(local_dir) and os.path.isfile(os.path.join(local_dir, "model.safetensors")):
        model_dir = local_dir
    else:
        model_dir = None

device = "cuda" if torch.cuda.is_available() else "cpu"
model, metadata = load_align_model(
    language_code=lang, device=device,
    model_name=data.get("model_name"),
    model_dir=model_dir,
)

audio, sr = sf.read(data["audio_path"])
if audio.ndim > 1:
    audio = audio.mean(axis=1)
if audio.dtype != np.float32:
    audio = audio.astype(np.float32)

result = align(
    data["segments"], model, metadata,
    audio, device,
    return_char_alignments=False,
)

with open(output_file, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False)
"""

    @staticmethod
    def _avg_score(words: list[dict]) -> float:
        scores = [w.get("score", 0.0) for w in words if w.get("score") is not None]
        return sum(scores) / len(scores) if scores else 1.0

    @staticmethod
    def _compute_delta(before: list[dict], after: list[dict]) -> float:
        before_avg = Wav2Vec2Adapter._avg_score(before)
        after_avg = Wav2Vec2Adapter._avg_score(after)
        return round(after_avg - before_avg, 4)
