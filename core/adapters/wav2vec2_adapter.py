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

        对齐失败时返回空列表，不阻断主流程。
        """
        if not segments:
            return []

        aligned_segments = self._run_alignment_subprocess(segments)
        if aligned_segments is None:
            return []

        patches: list[Patch] = []
        for i, seg in enumerate(aligned_segments):
            words = seg.get("words", [])
            patches.append(Patch(
                id=f"align_{i + 1:03d}",
                target_id=f"evt_{i + 1:03d}",
                op=OpCode.REFINE_ALIGNMENT,
                value={
                    "word_timestamps": [
                        {"word": w.get("word", ""), "start": w.get("start", 0.0),
                         "end": w.get("end", 0.0), "score": w.get("score", 0.0)}
                        for w in words
                    ],
                    "confidence_delta": self._compute_delta(
                        segments[i].get("words", []) if i < len(segments) else [],
                        words,
                    ),
                },
                author="system",
                confidence=self._avg_score(words),
            ))

        return patches

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
                aligned = data.get("segments")
                if aligned:
                    return self._merge_aligned(segments, aligned)
                return None
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
    def _merge_aligned(original: list[dict], aligned: list[dict]) -> list[dict]:
        """对齐结果尾部丢失时，用 whisper 原始词补齐覆盖。"""
        if not original or not aligned:
            return aligned or original
        orig_end = max(s["end"] for s in original)
        aligned_end = max(s["end"] for s in aligned)
        truncation = orig_end - aligned_end
        if truncation <= 1.0:
            return aligned
        tail_words = []
        for s in original:
            for w in s.get("words", []):
                if w["start"] >= aligned_end:
                    tail_words.append(w)
        if not tail_words:
            return aligned
        logger.warning(
            "对齐尾部丢失 %.1fs，用 whisper 原始时间戳补齐 %d 个词",
            truncation, len(tail_words),
        )
        result = list(aligned)
        result.append({
            "start": tail_words[0]["start"],
            "end": tail_words[-1]["end"],
            "text": " ".join(w["word"] for w in tail_words),
            "words": tail_words,
        })
        return result

    @staticmethod
    def _avg_score(words: list[dict]) -> float:
        scores = [w.get("score", 0.0) for w in words if w.get("score") is not None]
        return sum(scores) / len(scores) if scores else 1.0

    @staticmethod
    def _compute_delta(before: list[dict], after: list[dict]) -> float:
        before_avg = Wav2Vec2Adapter._avg_score(before)
        after_avg = Wav2Vec2Adapter._avg_score(after)
        return round(after_avg - before_avg, 4)
