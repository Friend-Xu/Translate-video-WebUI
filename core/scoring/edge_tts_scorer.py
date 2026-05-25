"""
EdgeTTSScorer — Edge TTS 联合评分 (Chapter 9 §9.6)

维度权重: availability 0.40, duration_fit 0.25,
          language_match 0.20, fallback_validity 0.15

与其他 Scorer 的关键差异:
  - 只有 4 个维度（最简）
  - ACCEPT_THRESHOLD = 0.55（全系统最低）
  - availability 权重最高 — "能不能出声" > "好不好听"
"""
from __future__ import annotations
from dataclasses import dataclass
from core.runtime.patch import Patch
from core.adapters.edge_tts_adapter import EdgeTTSSegmentContext


@dataclass
class EdgeTTSScore:
    segment_id: str
    availability: float = 1.0
    duration_fit: float = 1.0
    language_match: float = 1.0
    fallback_validity: float = 1.0
    composite: float = 1.0
    accepted: bool = True

    def __post_init__(self):
        if self.composite < 0.55:
            self.accepted = False


class EdgeTTSScorer:
    """Edge TTS 四维评分器 — 可用性是核心。

    ACCEPT_THRESHOLD = 0.55: 全系统最低阈值。
    作为最后一道防线，Edge TTS 只需"出声"即可通过。
    """

    DEFAULT_WEIGHTS = {
        "availability": 0.40,
        "duration_fit": 0.25,
        "language_match": 0.20,
        "fallback_validity": 0.15,
    }
    ACCEPT_THRESHOLD = 0.55

    def __init__(self, weights: dict[str, float] | None = None):
        self.weights = weights or dict(self.DEFAULT_WEIGHTS)

    def score(self, ctx: EdgeTTSSegmentContext, patch: Patch) -> EdgeTTSScore:
        v = patch.value

        avail = self._calc_availability(v.get("availability_score", 0.99))
        d_fit = self._calc_duration_fit(v.get("duration", 0), ctx.duration_target)
        l_match = self._calc_language_match(v.get("voice", ""), ctx.lang)
        f_valid = self._calc_fallback_validity(ctx.fallback_reason)

        composite = (
            self.weights["availability"] * avail
            + self.weights["duration_fit"] * d_fit
            + self.weights["language_match"] * l_match
            + self.weights["fallback_validity"] * f_valid
        )

        return EdgeTTSScore(
            segment_id=ctx.segment_id,
            availability=round(avail, 4),
            duration_fit=round(d_fit, 4),
            language_match=round(l_match, 4),
            fallback_validity=round(f_valid, 4),
            composite=round(composite, 4),
            accepted=composite >= self.ACCEPT_THRESHOLD,
        )

    @staticmethod
    def _calc_availability(availability_score: float) -> float:
        """Edge TTS 几乎永远可用（有网络的前提下）。"""
        return availability_score

    @staticmethod
    def _calc_duration_fit(actual: float, target: float) -> float:
        if target <= 0:
            return 1.0
        dev = abs(actual - target) / target
        return round(max(0.0, 1.0 - dev / 0.5), 4)

    @staticmethod
    def _calc_language_match(voice: str, lang: str) -> float:
        """检查 voice 是否匹配目标语言。"""
        if not lang or not voice:
            return 0.90
        lang_lower = lang.lower().replace("-", "").replace("_", "")
        voice_lower = voice.lower()
        if lang_lower[:2] in voice_lower:
            return 0.99
        if lang in voice_lower or lang_lower in voice_lower:
            return 0.95
        return 0.80

    @staticmethod
    def _calc_fallback_validity(fallback_reason: str) -> float:
        """兜底可用性 — 最后一道防线的合理性评估。"""
        if not fallback_reason:
            return 0.80
        if fallback_reason in ("all_primary_failed", "openvoice_fallback_failed"):
            return 0.95
        if fallback_reason in ("offline_mode", "low_resource_mode"):
            return 0.90
        return 0.85
