"""
IndexTTSScorer — IndexTTS 五维联合评分 (Chapter 7 §7.8)

维度权重: retrieval_confidence 0.25, identity_stability 0.25,
          duration_fit 0.20, segment_fit 0.15, reuse_safety 0.15

与 Ch5 TTSScorer 差异:
  - 增加 retrieval_confidence（检索质量是 IndexTTS 核心指标）
  - 增加 identity_stability（跨段身份连续性）
  - 增加 reuse_safety（资产可复用安全性）
  - 去掉 emotion_consistency / prosody_smoothness
  - duration_fit 更严格（0.3 容差 vs 0.5），因为原生 target_length_ms 精度更高
"""
from __future__ import annotations
from dataclasses import dataclass
from core.runtime.patch import Patch
from core.adapters.indextts_adapter import IndexTTSSegmentContext


@dataclass
class IndexTTSScore:
    segment_id: str
    retrieval_confidence: float = 1.0
    identity_stability: float = 1.0
    duration_fit: float = 1.0
    segment_fit: float = 1.0
    reuse_safety: float = 1.0
    composite: float = 1.0
    accepted: bool = True

    def __post_init__(self):
        if self.composite < 0.70:
            self.accepted = False


class IndexTTSScorer:
    """IndexTTS 五维评分器 — 权重侧重检索可信度和身份稳定性。"""

    DEFAULT_WEIGHTS = {
        "retrieval_confidence": 0.25,
        "identity_stability": 0.25,
        "duration_fit": 0.20,
        "segment_fit": 0.15,
        "reuse_safety": 0.15,
    }
    ACCEPT_THRESHOLD = 0.70

    def __init__(self, weights: dict[str, float] | None = None):
        self.weights = weights or dict(self.DEFAULT_WEIGHTS)

    def score(self, ctx: IndexTTSSegmentContext, patch: Patch,
              speaker_history: list[dict] | None = None) -> IndexTTSScore:
        v = patch.value
        r_conf = self._calc_retrieval_confidence(ctx.voice_asset_ref, patch.confidence)
        i_stab = self._calc_identity_stability(ctx.speaker_id, speaker_history)
        d_fit = self._calc_duration_fit(v.get("duration", 0), ctx.duration_target)
        s_fit = self._calc_segment_fit(ctx.emotion_hint, speaker_history)
        r_safe = self._calc_reuse_safety(ctx.voice_asset_ref, speaker_history)

        composite = (
            self.weights["retrieval_confidence"] * r_conf
            + self.weights["identity_stability"] * i_stab
            + self.weights["duration_fit"] * d_fit
            + self.weights["segment_fit"] * s_fit
            + self.weights["reuse_safety"] * r_safe
        )

        return IndexTTSScore(
            segment_id=ctx.segment_id,
            retrieval_confidence=round(r_conf, 4),
            identity_stability=round(i_stab, 4),
            duration_fit=round(d_fit, 4),
            segment_fit=round(s_fit, 4),
            reuse_safety=round(r_safe, 4),
            composite=round(composite, 4),
            accepted=composite >= self.ACCEPT_THRESHOLD,
        )

    @staticmethod
    def _calc_retrieval_confidence(voice_asset_ref: str,
                                   patch_confidence: float) -> float:
        """检索到的 VoiceAsset 匹配置信度。

        若有 asset_ref 说明命中检索，置信度基于 patch 综合质量。
        无 asset_ref 说明未命中，使用默认 prompt_audio — 得分略低。
        """
        if voice_asset_ref:
            return round(0.85 + 0.10 * patch_confidence, 4)
        return 0.80

    @staticmethod
    def _calc_identity_stability(speaker_id: str | None,
                                  history: list[dict] | None) -> float:
        """跨段身份稳定性 — 与历史中同 speaker 的一致性。

        同 speaker_id 的历史越多、越一致，稳定性越高。
        """
        if not speaker_id or not history:
            return 0.90
        same = [h for h in history if h.get("speaker_id") == speaker_id]
        if not same:
            return 0.90
        # 检查 speaker_audio 是否一致
        if len(same) >= 2:
            audios = {h.get("speaker_audio", "") for h in same}
            if len(audios) == 1:
                return 0.95
        return round(0.85 + 0.05 * min(len(same) / 5, 1.0), 4)

    @staticmethod
    def _calc_duration_fit(actual: float, target: float) -> float:
        """原生 target_length_ms 时长控制精度评分。

        比 Ch5 更严格: 0.3 容差 vs 0.5，
        因为 IndexTTS 自回归 GPT 原生支持精确时长控制。
        """
        if target <= 0:
            return 1.0
        dev = abs(actual - target) / target
        return round(max(0.0, 1.0 - dev / 0.3), 4)

    @staticmethod
    def _calc_segment_fit(emotion_hint: str,
                           history: list[dict] | None) -> float:
        """情绪/风格适配度 — 与 speaker 历史情绪基线比较。"""
        if not history:
            return 1.0
        same_emo = [h for h in history
                    if h.get("emotion_used") == emotion_hint]
        if not same_emo:
            return 0.85
        ratio = len(same_emo) / len(history)
        return round(0.80 + 0.20 * ratio, 4)

    @staticmethod
    def _calc_reuse_safety(voice_asset_ref: str,
                            history: list[dict] | None) -> float:
        """资产可复用安全性 — 被验证次数越多越安全。

        首次使用（无历史）: 0.75（一般安全）
        多次复用验证: 逐渐升高至 1.0
        """
        if not voice_asset_ref:
            return 0.75
        if not history:
            return 0.80
        reuse_count = sum(
            1 for h in history
            if h.get("voice_asset_ref") == voice_asset_ref
        )
        return round(min(1.0, 0.75 + 0.05 * reuse_count), 4)
