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
import numpy as np
from typing import List, Tuple, Optional

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

    def _load(self):
        """延迟加载模型"""
        if self.model is not None:
            return
        # 在中国大陆访问 HuggingFace 需要镜像，默认设置
        if not os.environ.get("HF_ENDPOINT"):
            os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
        t0 = time.time()
        logger.info(f"加载跨语言语义模型: {self.model_name}")
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(self.model_name)
        self._load_time = time.time() - t0
        logger.info(f"  加载完成，耗时: {self._load_time:.1f}s")

    def similarity(self, text_a: str, text_b: str) -> float:
        """计算跨语言语义相似度 (0.0 ~ 1.0)"""
        self._load()
        emb = self.model.encode([text_a, text_b])
        vec_a, vec_b = emb[0], emb[1]
        return float(np.dot(vec_a, vec_b) / (np.linalg.norm(vec_a) * np.linalg.norm(vec_b)))

    def batch_similarity(self, pairs: List[Tuple[str, str]]) -> List[float]:
        """批量计算"""
        self._load()
        all_texts = []
        for a, b in pairs:
            all_texts.extend([a, b])
        embeddings = self.model.encode(all_texts)
        results = []
        for i in range(0, len(embeddings), 2):
            va, vb = embeddings[i], embeddings[i + 1]
            sim = float(np.dot(va, vb) / (np.linalg.norm(va) * np.linalg.norm(vb)))
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
