"""
SpeakerDriftDetector — 三信号身份漂移检测 (Chapter 4 §4.6)

Drift 定义: 同一个人被拆成多个 speaker_id

三信号模型 (§4.6.2):
  信号1 — embedding distance: cosine_similarity(centroid_a, centroid_b)
  信号2 — temporal continuity: 两个 speaker 的 turn 是否交织出现
  信号3 — semantic continuity: 相邻 segment 文本是否语义连续但 speaker 不同

联合评分: composite = 0.50×embedding + 0.25×temporal + 0.25×semantic
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
from core.runtime.patch import Patch, OpCode


@dataclass
class DriftCandidate:
    speaker_a: str
    speaker_b: str
    embedding_sim: float       # 信号1: cosine similarity
    temporal_score: float      # 信号2: 时间连续性
    semantic_score: float      # 信号3: ASR 内容连续性
    composite_score: float     # 加权总分
    recommended_action: str = "keep_separate"


class SpeakerDriftDetector:
    """三信号 drift 检测器。

    权重: embedding 0.50, temporal 0.25, semantic 0.25
    """

    DEFAULT_WEIGHTS = {"embedding": 0.50, "temporal": 0.25, "semantic": 0.25}
    AUTO_MERGE_THRESHOLD = 0.80
    GATE_THRESHOLD = 0.60

    def __init__(self, weights: dict[str, float] | None = None):
        self.weights = weights or dict(self.DEFAULT_WEIGHTS)

    def detect(self, centroids: dict[str, list[float]],
               speaker_timeline: list[tuple],
               state=None  # TimelineProjectState, optional for semantic signal
               ) -> list[DriftCandidate]:
        """检测所有疑似 drift 的 speaker pair。

        仅返回 composite_score > GATE_THRESHOLD 的候选。
        """
        candidates: list[DriftCandidate] = []
        ids = list(centroids.keys())

        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                emb_sim = self._cosine_similarity(
                    centroids[ids[i]], centroids[ids[j]],
                )
                temporal = self._calc_temporal_score(
                    ids[i], ids[j], speaker_timeline,
                )
                semantic = self._calc_semantic_score(
                    ids[i], ids[j], speaker_timeline,
                )

                composite = (
                    self.weights["embedding"] * emb_sim
                    + self.weights["temporal"] * temporal
                    + self.weights["semantic"] * semantic
                )

                if composite > self.GATE_THRESHOLD:
                    action = "auto_merge" if composite > self.AUTO_MERGE_THRESHOLD else "gate"
                    candidates.append(DriftCandidate(
                        speaker_a=ids[i], speaker_b=ids[j],
                        embedding_sim=round(emb_sim, 4),
                        temporal_score=round(temporal, 4),
                        semantic_score=round(semantic, 4),
                        composite_score=round(composite, 4),
                        recommended_action=action,
                    ))

        return candidates

    def repair(self, candidates: list[DriftCandidate]) -> list[Patch]:
        """将 drift 候选转为 MERGE_SPEAKERS patch。"""
        patches: list[Patch] = []
        for c in candidates:
            patches.append(Patch(
                id=f"drift_{c.speaker_a}_{c.speaker_b}",
                target_id=c.speaker_a,
                op=OpCode.MERGE_SPEAKERS,
                value={
                    "merged_ids": [c.speaker_b],
                    "embedding_sim": c.embedding_sim,
                    "temporal_score": c.temporal_score,
                    "semantic_score": c.semantic_score,
                    "composite_score": c.composite_score,
                    "auto_apply": c.recommended_action == "auto_merge",
                    "method": "drift_detection",
                },
                author="system",
                confidence=c.composite_score,
                reason=["speaker_drift", f"composite={c.composite_score:.3f}"],
            ))
        return patches

    # ── signal calculators ────────────────────────────────

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        a_arr, b_arr = np.asarray(a), np.asarray(b)
        norm = np.linalg.norm(a_arr) * np.linalg.norm(b_arr)
        return float(np.dot(a_arr, b_arr) / norm) if norm > 0 else 0.0

    @staticmethod
    def _calc_temporal_score(speaker_a: str, speaker_b: str,
                             speaker_timeline: list[tuple]) -> float:
        """信号2: 时间连续性 — 两个 speaker 的 turn 是否交织出现。"""
        turns_a = [(s, e) for spk, s, e, _ in speaker_timeline if spk == speaker_a]
        turns_b = [(s, e) for spk, s, e, _ in speaker_timeline if spk == speaker_b]

        if not turns_a or not turns_b:
            return 0.0

        interleaving = 0
        for sa, ea in turns_a:
            for sb, eb in turns_b:
                gap = min(abs(ea - sb), abs(eb - sa))
                if gap < 0.5:
                    interleaving += 1

        return min(interleaving / max(len(turns_a), 1), 1.0)

    @staticmethod
    def _calc_semantic_score(speaker_a: str, speaker_b: str,
                             speaker_timeline: list[tuple]) -> float:
        """信号3: 语义连续性 — placeholder。

        完整实现需检查 state 中相邻 segment 的文本连续性。
        """
        return 0.8 * SpeakerDriftDetector._calc_temporal_score(
            speaker_a, speaker_b, speaker_timeline,
        )
