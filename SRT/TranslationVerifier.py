"""
TranslationVerifier.py — 翻译语义核对模块

使用 sentence-transformers 跨语言嵌入直接比较日语原文与中文译文，
跳过本地 MT 步骤（更轻量，一个模型搞定）。

流程：
1. 将日语原文和 DeepSeek 中文译文分别编码为向量
2. 计算余弦相似度
3. 低于阈值 → 标记为「待人工复核」

模型缓存到项目 models/hf_cache/（由 HF_HOME 环境变量控制）。
"""

import os
import time
import logging
import threading
import numpy as np
from typing import List, Tuple, Optional
import torch  # must import before transformers to avoid DLL load-order segfault

logger = logging.getLogger("TranslationVerifier")


# ══════════════════════════════════════════════════
# 跨语言语义相似度
# ══════════════════════════════════════════════════

class CrossLingualScorer:
    """
    跨语言语义相似度计算

    使用 paraphrase-multilingual-MiniLM-L12-v2（~470MB）
    支持中文、日文等多语言的跨语言语义匹配。

    直接比较日语原文和中文译文的嵌入向量，无需经过本地 MT 翻译。
    """

    def __init__(self, model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"):
        self.model_name = model_name
        self.model = None
        self._load_time = 0.0
        self._load_lock = threading.Lock()

    def _load(self):
        """延迟加载模型（双检锁，防止多线程并发加载 470MB 模型）"""
        if self.model is not None:
            return
        with self._load_lock:
            if self.model is not None:
                return
            if not os.environ.get("HF_ENDPOINT"):
                os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
            local_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "models", "sentence-transformers", "paraphrase-multilingual-MiniLM-L12-v2",
            )
            if os.path.isdir(local_path):
                os.environ["HF_HUB_OFFLINE"] = "1"
                os.environ["TRANSFORMERS_OFFLINE"] = "1"
                model_path = local_path
            else:
                model_path = self.model_name
            t0 = time.time()
            logger.info(f"加载跨语言语义模型: {model_path}")
            from transformers import AutoModel, AutoTokenizer
            self._tokenizer = AutoTokenizer.from_pretrained(model_path)
            self.model = AutoModel.from_pretrained(model_path)
            self._load_time = time.time() - t0
            logger.info(f"  加载完成，耗时: {self._load_time:.1f}s")

    def _encode(self, texts):
        """Mean-pooling encode — equivalent to SentenceTransformer for this model."""
        self._load()
        import torch
        inputs = self._tokenizer(texts, return_tensors="pt", padding=True, truncation=True)
        with torch.no_grad():
            outputs = self.model(**inputs)
        # Mean pooling over token dimension (model uses pooling_mode_mean_tokens)
        attn = inputs["attention_mask"].unsqueeze(-1).float()
        embeddings = (outputs.last_hidden_state * attn).sum(dim=1) / attn.sum(dim=1).clamp(min=1e-9)
        # L2 normalize
        embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)
        return embeddings.cpu().numpy()

    def similarity(self, text_a: str, text_b: str) -> float:
        """计算跨语言语义相似度 (0.0 ~ 1.0)"""
        emb = self._encode([text_a, text_b])
        return float(np.dot(emb[0], emb[1]))

    def batch_similarity(self, pairs: List[Tuple[str, str]]) -> List[float]:
        """批量计算"""
        all_texts = []
        for a, b in pairs:
            all_texts.extend([a, b])
        embeddings = self._encode(all_texts)
        results = []
        for i in range(0, len(embeddings), 2):
            sim = float(np.dot(embeddings[i], embeddings[i + 1]))
            results.append(sim)
        return results


# ══════════════════════════════════════════════════
# 翻译语义核验器
# ══════════════════════════════════════════════════

class TranslationVerifier:
    """
    翻译语义核对器

    使用跨语言嵌入直接比较原文和译文，无需本地 MT。

    用法：
        v = TranslationVerifier()
        result = v.verify("こんにちは", "你好")
        # result = {"similarity": 0.95, "flagged": False}
    """

    def __init__(self, threshold: float = 0.65):
        self.scorer = CrossLingualScorer()
        self.threshold = threshold

    def verify(self, source_text: str, translated_text: str) -> dict:
        """
        核对一条翻译。直接比较原文(日)↔译文(中)的语义相似度。

        Returns:
            {
                "similarity": float,   # 语义相似度 0~1
                "flagged": bool,       # True = 建议人工复核
                "elapsed_s": float,
            }
        """
        if not source_text.strip() or not translated_text.strip():
            return {"similarity": 1.0, "flagged": False, "elapsed_s": 0.0}

        t0 = time.time()
        sim = self.scorer.similarity(source_text, translated_text)
        elapsed = time.time() - t0

        return {
            "similarity": round(sim, 4),
            "flagged": sim < self.threshold,
            "elapsed_s": round(elapsed, 3),
        }

    def batch_verify(self, pairs: List[Tuple[str, str]]) -> List[dict]:
        """批量核对翻译"""
        if not pairs:
            return []

        t0 = time.time()
        similarities = self.scorer.batch_similarity(pairs)
        elapsed = time.time() - t0

        return [
            {
                "similarity": round(sim, 4),
                "flagged": sim < self.threshold,
                "elapsed_s": round(elapsed, 3),
            }
            for sim in similarities
        ]

    @property
    def stats(self) -> dict:
        return {
            "model": self.scorer.model_name,
            "load_time_s": round(self.scorer._load_time, 1),
            "threshold": self.threshold,
        }
