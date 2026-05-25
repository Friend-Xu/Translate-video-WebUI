"""
SpeakerClustering — 基于 embedding 的说话人层次聚类 (Chapter 4 §4.5)

决策阈值 (§4.5.3):
  sim > HIGH (0.85) → same speaker, auto-merge
  LOW < sim ≤ HIGH  → logic gate decision
  sim ≤ LOW (0.70)  → different speaker, keep separate
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from core.runtime.patch import Patch, OpCode


@dataclass
class ClusterResult:
    canonical_id: str       # 主 speaker_id
    merged_ids: list[str]   # 被合并的 speaker_id 列表
    similarity: float       # 平均余弦相似度
    confidence: str         # "auto" | "gate"


class SpeakerClustering:
    """基于 embedding 质心的说话人层次聚类。"""

    HIGH_THRESHOLD = 0.85
    LOW_THRESHOLD = 0.70

    def cluster(self, centroids: dict[str, list[float]]
                ) -> list[ClusterResult]:
        """对所有 speaker pair 计算相似度并分类。

        Returns:
            [ClusterResult, ...] — 仅返回 sim > LOW 的 pair
        """
        results: list[ClusterResult] = []
        ids = list(centroids.keys())

        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                sim = self._cosine_similarity(centroids[ids[i]], centroids[ids[j]])
                if sim > self.LOW_THRESHOLD:
                    results.append(ClusterResult(
                        canonical_id=ids[i],
                        merged_ids=[ids[j]],
                        similarity=round(sim, 4),
                        confidence="auto" if sim > self.HIGH_THRESHOLD else "gate",
                    ))

        return results

    def to_patches(self, results: list[ClusterResult]) -> list[Patch]:
        """将聚类结果转为 MERGE_SPEAKERS patch。"""
        patches: list[Patch] = []
        for r in results:
            patches.append(Patch(
                id=f"cluster_{r.canonical_id}_{'_'.join(r.merged_ids)}",
                target_id=r.canonical_id,
                op=OpCode.MERGE_SPEAKERS,
                value={
                    "merged_ids": r.merged_ids,
                    "similarity": r.similarity,
                    "method": "cosine_hierarchical",
                    "auto_apply": r.confidence == "auto",
                    "confidence": r.confidence,
                },
                author="system",
                confidence=r.similarity,
                reason=["speaker_clustering", f"sim={r.similarity:.3f}"],
            ))
        return patches

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        a_arr, b_arr = np.asarray(a), np.asarray(b)
        norm = np.linalg.norm(a_arr) * np.linalg.norm(b_arr)
        return float(np.dot(a_arr, b_arr) / norm) if norm > 0 else 0.0
