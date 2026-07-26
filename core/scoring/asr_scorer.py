"""
ASRScorer — ASR 域联合评分 (Chapter 3 §3.6)

公式: S = w1*C_asr + w2*C_alignment + w3*C_speaker_hint + w4*C_semantic_consistency

各维度来源:
  C_asr       — Whisper segment 平均词置信度
  C_alignment — wav2vec2 对齐分数的均值
  C_speaker   — WordLevelRefiner 输出的 speaker_confidence 均值
  C_semantic  — embedding 与相邻 segment 的余弦相似度
"""
from __future__ import annotations
from dataclasses import dataclass, field
from core.runtime.event_state import TimelineEventState
from core.runtime.project_state import TimelineProjectState


@dataclass
class ASRScore:
    segment_id: str
    c_asr: float = 1.0
    c_alignment: float = 1.0
    c_speaker_hint: float = 1.0
    c_semantic: float | None = None  # None = 无数据（embedding 未接线），composite 自动按剩余维度归一化
    composite: float = 1.0

    @property
    def confidence_label(self) -> str:
        if self.composite >= 0.85:
            return "high"
        elif self.composite >= 0.60:
            return "medium"
        return "low"


class ASRScorer:
    """ASR 联合评分器。

    权重可通过配置覆盖，默认值偏向文本准确率。
    """

    DEFAULT_WEIGHTS = {
        "asr": 0.40,
        "alignment": 0.30,
        "speaker_hint": 0.15,
        "semantic": 0.15,
    }

    def __init__(self, weights: dict[str, float] | None = None):
        self.weights = weights or dict(self.DEFAULT_WEIGHTS)

    def score_segment(self, es: TimelineEventState,
                      prev_embedding: list[float] | None = None) -> ASRScore:
        """计算单个 segment 的联合评分。"""
        c_asr = self._calc_asr_confidence(es)
        c_alignment = self._calc_alignment_confidence(es)
        c_speaker = self._calc_speaker_confidence(es)
        c_semantic = self._calc_semantic_consistency(es, prev_embedding)

        composite = self._weighted_mean([
            (self.weights["asr"], c_asr),
            (self.weights["alignment"], c_alignment),
            (self.weights["speaker_hint"], c_speaker),
            (self.weights["semantic"], c_semantic),
        ])

        return ASRScore(
            segment_id=es.id,
            c_asr=round(c_asr, 4),
            c_alignment=round(c_alignment, 4),
            c_speaker_hint=round(c_speaker, 4),
            c_semantic=round(c_semantic, 4) if c_semantic is not None else None,
            composite=round(composite, 4),
        )

    @staticmethod
    def _weighted_mean(dims: list[tuple[float, float | None]]) -> float:
        """加权平均，跳过 None（无数据）维度并按剩余权重归一化。"""
        valid = [(w, v) for w, v in dims if v is not None]
        w_sum = sum(w for w, _ in valid)
        if w_sum <= 0:
            return 0.0
        return sum(w * v for w, v in valid) / w_sum

    def score_all(self, state: TimelineProjectState) -> dict[str, ASRScore]:
        """计算所有 segment 的联合评分，写入 runtime 槽位。"""
        scores: dict[str, ASRScore] = {}
        sorted_events = state.sorted_events()

        for i, es in enumerate(sorted_events):
            score = self.score_segment(es)
            scores[es.id] = score

            es.runtime["asr_score"] = score.composite
            es.runtime["asr_confidence_label"] = score.confidence_label
            es.provenance["score_components"] = {
                "c_asr": score.c_asr,
                "c_alignment": score.c_alignment,
                "c_speaker_hint": score.c_speaker_hint,
                "c_semantic": score.c_semantic,
            }

        return scores

    # ── per-dimension ─────────────────────────────────────

    @staticmethod
    def _calc_asr_confidence(es: TimelineEventState) -> float:
        words = es.asr.get("words", [])
        if not words:
            return es.asr.get("confidence", 1.0)
        scores = [w.get("score", 0.0) for w in words if w.get("score") is not None]
        return sum(scores) / len(scores) if scores else 1.0

    @staticmethod
    def _calc_alignment_confidence(es: TimelineEventState) -> float:
        align_patches = [p for p in es.patches if p.op == "refine_alignment"]
        if align_patches:
            return align_patches[-1].confidence
        return ASRScorer._calc_asr_confidence(es)

    @staticmethod
    def _calc_speaker_confidence(es: TimelineEventState) -> float:
        return es.speaker.get("confidence", 1.0)

    @staticmethod
    def _calc_semantic_consistency(es: TimelineEventState,
                                   prev_embedding: list[float] | None = None) -> float | None:
        """语义连续性 — 返回 None（无数据）。

        真实实现需要前后事件的 wav2vec2 embedding 向量做余弦相似度，
        当前未接线。返回 None 而非伪造 1.0，让 composite 按真实维度归一化，
        避免 gate 基于假满分自动放行。
        """
        return None
