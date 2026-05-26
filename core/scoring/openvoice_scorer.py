"""
OpenVoiceScorer — OpenVoice 五维联合评分 (Chapter 8 §8.9)

维度权重: transfer_quality 0.25, speaker_match 0.25,
          duration_fit 0.15, fallback_validity 0.25,
          cross_segment_continuity 0.10

与 Ch5-7 Scorer 的核心差异:
  - ACCEPT_THRESHOLD = 0.60（低于主引擎的 0.70）
  - fallback_validity 权重最高 — "能不能用"比"好不好听"更重要
  - duration_fit 通常高分（音色迁移不改时长）
"""
from __future__ import annotations
from dataclasses import dataclass
from core.runtime.patch import Patch
from core.adapters.openvoice_adapter import OpenVoiceTransferContext


@dataclass
class OpenVoiceScore:
    segment_id: str
    transfer_quality: float = 1.0
    speaker_match: float = 1.0
    duration_fit: float = 1.0
    fallback_validity: float = 1.0
    cross_segment_continuity: float = 1.0
    composite: float = 1.0
    accepted: bool = True

    def __post_init__(self):
        if self.composite < 0.60:
            self.accepted = False


class OpenVoiceScorer:
    """OpenVoice 五维评分器 — 侧重可用性而非极致质量。

    fallback_validity 权重最高: "能不能交付" > "好不好听"
    """

    DEFAULT_WEIGHTS = {
        "transfer_quality": 0.25,
        "speaker_match": 0.25,
        "duration_fit": 0.15,
        "fallback_validity": 0.25,
        "cross_segment_continuity": 0.10,
    }
    ACCEPT_THRESHOLD = 0.60

    def __init__(self, weights: dict[str, float] | None = None):
        self.weights = weights or dict(self.DEFAULT_WEIGHTS)

    def score(self, ctx: OpenVoiceTransferContext, patch: Patch,
              transfer_history: list[dict] | None = None) -> OpenVoiceScore:
        v = patch.value

        # transfer 失败直接返回 0
        if v.get("transfer_status") == "failed":
            return OpenVoiceScore(
                segment_id=ctx.segment_id,
                transfer_quality=0.0, speaker_match=0.0,
                duration_fit=0.0, fallback_validity=0.0,
                cross_segment_continuity=0.0,
                composite=0.0, accepted=False,
            )

        t_qual = self._calc_transfer_quality(v.get("transfer_score", 0.79))
        s_match = self._calc_speaker_match(ctx.speaker_id, transfer_history)
        d_fit = self._calc_duration_fit(v.get("duration", 0), ctx.duration_target)
        f_valid = self._calc_fallback_validity(ctx.fallback_reason)
        c_cont = self._calc_cross_segment_continuity(ctx, transfer_history)

        composite = (
            self.weights["transfer_quality"] * t_qual
            + self.weights["speaker_match"] * s_match
            + self.weights["duration_fit"] * d_fit
            + self.weights["fallback_validity"] * f_valid
            + self.weights["cross_segment_continuity"] * c_cont
        )

        return OpenVoiceScore(
            segment_id=ctx.segment_id,
            transfer_quality=round(t_qual, 4),
            speaker_match=round(s_match, 4),
            duration_fit=round(d_fit, 4),
            fallback_validity=round(f_valid, 4),
            cross_segment_continuity=round(c_cont, 4),
            composite=round(composite, 4),
            accepted=composite >= self.ACCEPT_THRESHOLD,
        )

    @staticmethod
    def _calc_transfer_quality(transfer_score: float) -> float:
        """音色迁移质量 — 直接使用 adapter 输出的 transfer_score。"""
        return transfer_score

    @staticmethod
    def _calc_speaker_match(speaker_id: str | None,
                             history: list[dict] | None) -> float:
        """迁移后 speaker 匹配度 — 基于历史迁移一致性。"""
        if not speaker_id or not history:
            return 0.80
        same_spk = [h for h in history
                    if h.get("speaker_id") == speaker_id]
        if not same_spk:
            return 0.80
        refs = {h.get("reference_audio", "") for h in same_spk}
        if len(refs) == 1 and "" not in refs:
            return 0.90
        return 0.80

    @staticmethod
    def _calc_duration_fit(actual: float, target: float) -> float:
        """时长保持度 — 音色迁移不改时长，通常高分。"""
        if target <= 0 or actual <= 0:
            return 0.95
        dev = abs(actual - target) / target
        return round(max(0.0, 1.0 - dev / 0.5), 4)

    @staticmethod
    def _calc_fallback_validity(fallback_reason: str) -> float:
        """降级可用性 — 基于 fallback_reason 的语义评分。

        immediate 原因→高分（确实需要降级）
        optional 原因→略低（非必需降级）
        """
        if not fallback_reason:
            return 0.75
        if fallback_reason in ("primary_low_confidence", "primary_error"):
            return 0.92
        if fallback_reason in ("primary_marginal", "quick_fix"):
            return 0.85
        if fallback_reason == "low_priority_segment":
            return 0.78
        return 0.80

    @staticmethod
    def _calc_cross_segment_continuity(ctx: OpenVoiceTransferContext,
                                        history: list[dict] | None) -> float:
        """跨段风格连续性 — 检查 reference_audio 是否与前后段一致。"""
        if not history:
            return 1.0
        if len(history) < 1:
            return 1.0
        last = history[-1]
        if last.get("reference_audio") != ctx.reference_audio_ref:
            return 0.85
        return 0.95
