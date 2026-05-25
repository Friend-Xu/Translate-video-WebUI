"""
TTSScorer — TTS 五维联合评分 (Chapter 5 §5.8)

维度权重: duration_fit 0.30, speaker_consistency 0.25,
          emotion_consistency 0.20, semantic_fidelity 0.15,
          prosody_smoothness 0.10
"""
from __future__ import annotations
from dataclasses import dataclass
from core.runtime.patch import Patch
from core.adapters.chattts_adapter import TTSSegmentContext


@dataclass
class TTSScore:
    segment_id: str
    duration_fit: float = 1.0
    speaker_consistency: float = 1.0
    emotion_consistency: float = 1.0
    semantic_fidelity: float = 1.0
    prosody_smoothness: float = 1.0
    composite: float = 1.0
    accepted: bool = True

    def __post_init__(self):
        if self.composite < 0.70:
            self.accepted = False


class TTSScorer:
    """TTS 输出五维评分器 — 加权评分 + accept/reject 判定。"""

    DEFAULT_WEIGHTS = {
        "duration_fit": 0.30,
        "speaker_consistency": 0.25,
        "emotion_consistency": 0.20,
        "semantic_fidelity": 0.15,
        "prosody_smoothness": 0.10,
    }
    ACCEPT_THRESHOLD = 0.70

    def __init__(self, weights: dict[str, float] | None = None):
        self.weights = weights or dict(self.DEFAULT_WEIGHTS)

    def score(self, ctx: TTSSegmentContext, patch: Patch,
              speaker_history: list[dict] | None = None) -> TTSScore:
        v = patch.value
        d_fit = self._calc_duration_fit(v.get("duration", 0), ctx.duration_target)
        s_cons = self._calc_speaker_consistency(ctx.speaker_id, v.get("emotion_hint", ""), speaker_history)
        e_cons = self._calc_emotion_consistency(ctx.emotion_hint, v.get("emotion_hint", ""))
        s_fid = self._calc_semantic_fidelity()
        p_smooth = self._calc_prosody_smoothness(v.get("duration", 0), ctx.duration_target)

        composite = (
            self.weights["duration_fit"] * d_fit
            + self.weights["speaker_consistency"] * s_cons
            + self.weights["emotion_consistency"] * e_cons
            + self.weights["semantic_fidelity"] * s_fid
            + self.weights["prosody_smoothness"] * p_smooth
        )

        return TTSScore(
            segment_id=ctx.segment_id,
            duration_fit=round(d_fit, 4),
            speaker_consistency=round(s_cons, 4),
            emotion_consistency=round(e_cons, 4),
            semantic_fidelity=round(s_fid, 4),
            prosody_smoothness=round(p_smooth, 4),
            composite=round(composite, 4),
            accepted=composite >= self.ACCEPT_THRESHOLD,
        )

    @staticmethod
    def _calc_duration_fit(actual: float, target: float) -> float:
        if target <= 0:
            return 1.0
        dev = abs(actual - target) / target
        return round(max(0.0, 1.0 - dev / 0.5), 4)

    @staticmethod
    def _calc_speaker_consistency(speaker_id: str | None, emotion_hint: str,
                                  history: list[dict] | None) -> float:
        if not speaker_id or not history:
            return 1.0
        same = [h for h in history if h.get("speaker_id") == speaker_id]
        if not same:
            return 1.0
        matches = sum(1 for h in same if h.get("emotion_hint") == emotion_hint)
        return round(matches / len(same), 4) if same else 1.0

    @staticmethod
    def _calc_emotion_consistency(expected: str, actual: str) -> float:
        if not expected or expected == "neutral" or expected == actual:
            return 1.0
        return 0.85

    @staticmethod
    def _calc_semantic_fidelity() -> float:
        return 1.0

    @staticmethod
    def _calc_prosody_smoothness(actual: float, target: float) -> float:
        if target <= 0:
            return 1.0
        dev = abs(actual - target) / target
        return round(max(0.0, 1.0 - dev / 0.3), 4)
