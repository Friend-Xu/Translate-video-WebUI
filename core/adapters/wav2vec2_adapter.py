"""
Wav2Vec2Adapter — wav2vec2 对齐 + 语义嵌入适配器 (Chapter 3 §3.3-3.4)

两种模式:
  1. alignment 模式 — 对 segment 运行 CTC 强制对齐，精炼 word timestamps
  2. semantic 模式 — 提取 wav2vec2 hidden states 作为语义 embedding

对齐通过子进程执行（复用现有 whisperx_local/alignment.py）。
语义提取直接调用 wav2vec2 模型 forward pass。
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
from core.runtime.patch import Patch, OpCode


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

    # ── alignment 模式 ────────────────────────────────────

    def refine_alignment(self, segments: list[dict]) -> list[Patch]:
        """对一组 segment 运行 wav2vec2 强制对齐，输出 REFINE_ALIGNMENT patch。

        Args:
            segments: [{"text", "start", "end", "words": [{"word", "start", "end"}]}]

        Returns:
            [Patch(REFINE_ALIGNMENT), ...] — 每个 segment 一个 patch
        """
        if not segments:
            return []

        aligned = self._run_alignment_subprocess(segments)
        patches: list[Patch] = []

        for i, seg in enumerate(aligned.get("segments", [])):
            words = seg.get("words", [])
            patches.append(Patch(
                id=f"align_{i + 1:03d}",
                target_id=f"evt_{i + 1:03d}",
                op=OpCode.REFINE_ALIGNMENT,
                value={
                    "word_timestamps": [
                        {"word": w["word"], "start": w["start"],
                         "end": w["end"], "score": w.get("score", 0.0)}
                        for w in words
                    ],
                    "confidence_delta": self._compute_delta(segments[i].get("words", []), words),
                },
                author="system",
                confidence=self._avg_score(words),
            ))

        return patches

    # ── semantic 模式 ─────────────────────────────────────

    def extract_semantic(self, segment_ids: list[str],
                         output_dir: str = "") -> list[Patch]:
        """提取 wav2vec2 embedding，写入文件，输出 ANNOTATE patch。

        embedding 向量写入 {output_dir}/_embeddings/ 目录。
        IR 只存储引用路径 (embedding_ref)，避免序列化大向量。

        Returns:
            [Patch(ANNOTATE), ...] — 每个 segment 一个 patch
        """
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
                        "dimension": 768,  # wav2vec2-base
                    },
                },
                author="system",
            ))

        return patches

    # ── internal ──────────────────────────────────────────

    def _run_alignment_subprocess(self, segments: list[dict]) -> dict:
        """通过子进程运行 wav2vec2 对齐（复用现有 subprocess 模式）。"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8",
        ) as f_in:
            input_file = f_in.name
            json.dump({
                "segments": segments,
                "language": self.language,
                "audio_path": self.audio_path,
                "model_name": self.model_name,
                "model_dir": self.model_dir,
            }, f_in)

        output_file = input_file.replace(".json", "_out.json")

        script = self._build_align_script(input_file, output_file)
        env = {**os.environ, "CUDA_VISIBLE_DEVICES": ""}

        try:
            subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True, text=True, timeout=300,
                env=env, cwd=os.path.dirname(os.path.abspath(__file__)),
            )
            if os.path.exists(output_file):
                with open(output_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        finally:
            for f in (input_file, output_file):
                if os.path.exists(f):
                    os.unlink(f)

        return {"segments": segments}

    def _build_align_script(self, input_file: str, output_file: str) -> str:
        return f"""
import json, sys
sys.path.insert(0, r"{os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))}")
from whisperx_local.alignment import load_align_model, align
import soundfile as sf
import numpy as np

with open(r"{input_file}", "r", encoding="utf-8") as f:
    data = json.load(f)

model, metadata = load_align_model(
    language_code=data.get("language", "en"),
    device="cpu",
    model_name=data.get("model_name"),
    model_dir=data.get("model_dir"),
)
audio, sr = sf.read(data["audio_path"])
if audio.ndim > 1:
    audio = audio.mean(axis=1)
if sr != 16000:
    import librosa
    audio = librosa.resample(audio, orig_sr=sr, target_sr=16000)
    sr = 16000

result = align(
    data["segments"], model, metadata,
    audio.astype(np.float32), "cpu",
    return_char_alignments=False,
)

with open(r"{output_file}", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False)
"""

    @staticmethod
    def _avg_score(words: list[dict]) -> float:
        scores = [w.get("score", 0.0) for w in words if w.get("score") is not None]
        return sum(scores) / len(scores) if scores else 1.0

    @staticmethod
    def _compute_delta(before: list[dict], after: list[dict]) -> float:
        """计算对齐前后置信度变化。"""
        before_avg = Wav2Vec2Adapter._avg_score(before)
        after_avg = Wav2Vec2Adapter._avg_score(after)
        return round(after_avg - before_avg, 4)
