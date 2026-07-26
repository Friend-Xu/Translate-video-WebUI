"""
CosyVoiceScorer — CosyVoice 五维联合评分 (Chapter 6 §6.8)

维度权重: speaker_match 0.30, duration_fit 0.30,
          language_naturalness 0.20, segment_continuity 0.10,
          semantic_fidelity 0.10

与 Ch5 TTSScorer 差异:
  - 去掉 emotion_consistency（CosyVoice 不原生支持情绪）
  - 增加 language_naturalness（跨语种场景关键指标）
  - speaker_match 替代 speaker_consistency（侧重声纹匹配而非情绪一致性）
"""
from __future__ import annotations
from dataclasses import dataclass
from core.runtime.patch import Patch
from core.adapters.cosyvoice_adapter import CosyVoiceSegmentContext


@dataclass
class CosyVoiceScore:
    segment_id: str
    speaker_match: float = 1.0
    duration_fit: float = 1.0
    language_naturalness: float | None = None  # None = 无数据（需 ASR 回读评估，未实现）
    segment_continuity: float = 1.0
    semantic_fidelity: float | None = None     # None = 无数据（未实现）
    composite: float = 1.0
    accepted: bool = True

    def __post_init__(self):
        if self.composite < 0.70:
            self.accepted = False


class CosyVoiceScorer:
    """CosyVoice 五维评分器 — 权重侧重 speaker_match 和 duration_fit。"""

    DEFAULT_WEIGHTS = {
        "speaker_match": 0.30,
        "duration_fit": 0.30,
        "language_naturalness": 0.20,
        "segment_continuity": 0.10,
        "semantic_fidelity": 0.10,
    }
    ACCEPT_THRESHOLD = 0.70

    def __init__(self, weights: dict[str, float] | None = None):
        self.weights = weights or dict(self.DEFAULT_WEIGHTS)

    def score(self, ctx: CosyVoiceSegmentContext, patch: Patch,
              speaker_history: list[dict] | None = None) -> CosyVoiceScore:
        v = patch.value
        s_match = self._calc_speaker_match(ctx.speaker_id, v.get("prompt_audio", ""), speaker_history)
        d_fit = self._calc_duration_fit(v.get("duration", 0), ctx.duration_target)
        l_nat = self._calc_language_naturalness(v.get("lang", ""), v.get("mode", ""))
        s_cont = self._calc_segment_continuity(ctx, patch, speaker_history)
        s_fid = self._calc_semantic_fidelity()

        composite = self._weighted_mean([
            (self.weights["speaker_match"], s_match),
            (self.weights["duration_fit"], d_fit),
            (self.weights["language_naturalness"], l_nat),
            (self.weights["segment_continuity"], s_cont),
            (self.weights["semantic_fidelity"], s_fid),
        ])

        return CosyVoiceScore(
            segment_id=ctx.segment_id,
            speaker_match=round(s_match, 4),
            duration_fit=round(d_fit, 4),
            language_naturalness=round(l_nat, 4) if l_nat is not None else None,
            segment_continuity=round(s_cont, 4),
            semantic_fidelity=round(s_fid, 4) if s_fid is not None else None,
            composite=round(composite, 4),
            accepted=composite >= self.ACCEPT_THRESHOLD,
        )

    @staticmethod
    def _weighted_mean(dims: list[tuple[float, float | None]]) -> float:
        """加权平均，跳过 None（无数据）维度并按剩余权重归一化。"""
        valid = [(w, v) for w, v in dims if v is not None]
        w_sum = sum(w for w, _ in valid)
        if w_sum <= 0:
            return 0.0
        return sum(w * v for w, v in valid) / w_sum

    @staticmethod
    def _calc_speaker_match(speaker_id: str | None, prompt_audio: str,
                            history: list[dict] | None) -> float:
        """基于 prompt_audio 的声纹匹配度评分。

        当前简化实现: 同 speaker_id + 同 prompt_audio → 高分。
        完整实现需调用 speaker embedding cosine 相似度。
        """
        if not speaker_id or not history:
            return 0.90
        same_spk = [h for h in history if h.get("speaker_id") == speaker_id]
        if not same_spk:
            return 0.90
        same_prompt = sum(1 for h in same_spk
                         if h.get("prompt_audio") == prompt_audio)
        return round(0.80 + 0.20 * (same_prompt / len(same_spk)), 4)

    @staticmethod
    def _calc_duration_fit(actual: float, target: float) -> float:
        if target <= 0:
            return 1.0
        dev = abs(actual - target) / target
        return round(max(0.0, 1.0 - dev / 0.5), 4)

    @staticmethod
    def _calc_language_naturalness(lang: str, mode: str) -> float | None:
        """跨语种自然度 — 返回 None（无数据）。

        真实实现需接入发音质量评估 (ASR 回读 + CER/WER)，当前不可用。
        返回 None 而非固定先验，避免 accept/reject 基于伪测量值。
        """
        return None

    @staticmethod
    def _calc_segment_continuity(ctx: CosyVoiceSegmentContext,
                                 patch: Patch,
                                 history: list[dict] | None) -> float:
        """段间风格连续性 — 检查 speed 和 lang 是否与相邻段一致。"""
        if not history:
            return 1.0
        if len(history) < 1:
            return 1.0
        last = history[-1]
        score = 1.0
        if last.get("speed") and patch.value.get("speed"):
            speed_diff = abs(last["speed"] - patch.value["speed"])
            if speed_diff > 0.3:
                score -= 0.15
        if last.get("lang") and last["lang"] != patch.value.get("lang"):
            score -= 0.1
        return round(max(0.0, score), 4)

    @staticmethod
    def _calc_semantic_fidelity() -> float | None:
        """语义保真度 — 返回 None（无数据，未实现），composite 按真实维度归一化。"""
        return None
