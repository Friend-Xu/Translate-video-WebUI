"""
PPLEvaluator — Qwen2-0.5B 中文自然度评估

计算句子级困惑度 (perplexity)，用于检测翻译腔 (translationese)。

用法：
    evaluator = PPLEvaluator()
    ppl = evaluator.perplexity("那我们直接开始吧")
    # ppl ≈ 63  (自然)
    pp2 = evaluator.perplexity("那么，我们就直线跳跃进去吧")
    # pp2 ≈ 271 (翻译腔)
"""

from __future__ import annotations

import logging
import os
import time
import threading
from typing import Optional, List

import torch

logger = logging.getLogger("PPLEvaluator")

_MODEL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "models", "Qwen", "Qwen2-0.5B",
)


class PPLEvaluator:

    def __init__(self, model_path: Optional[str] = None,
                 device: Optional[str] = None,
                 batch_size: int = 32):
        self._model_path = model_path or _MODEL_DIR
        self._device_str = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._batch_size = batch_size
        self._model = None
        self._tokenizer = None
        self._load_lock = threading.Lock()

    def _load(self):
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            from transformers import AutoModelForCausalLM, AutoTokenizer

            # Prevent HF download when local model exists
            if os.path.isdir(self._model_path) and any(
                f.endswith((".safetensors", ".bin"))
                for f in os.listdir(self._model_path)
            ):
                os.environ["HF_HUB_OFFLINE"] = "1"
                os.environ["TRANSFORMERS_OFFLINE"] = "1"

            t0 = time.time()
            logger.info(f"加载 Qwen2-0.5B: {self._model_path}")
            self._tokenizer = AutoTokenizer.from_pretrained(
                self._model_path, trust_remote_code=True,
            )
            self._model = AutoModelForCausalLM.from_pretrained(
                self._model_path,
                dtype=torch.float16 if self._device_str == "cuda" else torch.float32,
                device_map="auto" if self._device_str == "cuda" else None,
                trust_remote_code=True,
            )
            if self._device_str == "cpu":
                self._model = self._model.to("cpu")
            self._model.eval()
            logger.info(f"Qwen2-0.5B 加载完成, {time.time() - t0:.1f}s, "
                        f"设备={self._device_str}")

    def perplexity(self, text: str) -> float:
        self._load()
        inputs = self._tokenizer(text, return_tensors="pt").to(self._model.device)
        input_ids = inputs["input_ids"]
        num_tokens = input_ids.shape[1]
        if num_tokens < 2:
            return 0.0
        with torch.no_grad():
            outputs = self._model(**inputs, labels=input_ids)
            total_nll = outputs.loss.item() * num_tokens
        return float(torch.exp(torch.tensor(total_nll / num_tokens)).item())

    def batch_perplexity(self, texts: List[str]) -> List[float]:
        self._load()
        results: List[float] = []
        for text in texts:
            if len(text) < 3:
                results.append(0.0)
                continue
            try:
                results.append(self.perplexity(text))
            except Exception:
                results.append(0.0)
        return results

    def compute_baseline(self, texts: List[str],
                         min_entries: int = 5,
                         static_fallback: Optional[float] = None) -> float:
        """从高语义相似度译文计算自适应自然度基线。"""
        if len(texts) < min_entries:
            fb = static_fallback or 60.0
            logger.info(f"基线样本不足 ({len(texts)} < {min_entries}), 使用静态值 {fb}")
            return fb
        ppls = self.batch_perplexity(texts)
        valid = [p for p in ppls if p > 0]
        if len(valid) < min_entries:
            return static_fallback or 60.0
        valid.sort()
        median = valid[len(valid) // 2]
        logger.info(f"自适应自然度基线: {median:.1f} (from {len(valid)} entries)")
        return median
