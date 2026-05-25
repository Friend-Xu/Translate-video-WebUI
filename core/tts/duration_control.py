"""
DurationController — TTS 时长硬约束控制 (Chapter 5 §5.5)

三级策略:
  Level 1 — 预检通过: deviation ≤ tolerance → "accept"
  Level 2 — 语速调整: tolerance < deviation ≤ 30% → "stretch"
  Level 3 — 分段重生成: deviation > 30% → "split"
"""
from __future__ import annotations


class DurationController:
    """TTS 时长硬约束控制器。"""

    LEVEL2_FACTOR = 0.3
    MAX_STRETCH = 2.0
    MIN_STRETCH = 0.5
    CHARS_PER_SECOND = 5.0

    def check(self, actual_duration: float, target_duration: float,
              tolerance: float = 0.15) -> str:
        """判定时长处理策略: "accept" | "stretch" | "split" """
        if target_duration <= 0:
            return "accept"
        deviation = abs(actual_duration - target_duration) / target_duration
        if deviation <= tolerance:
            return "accept"
        if deviation <= self.LEVEL2_FACTOR:
            ratio = target_duration / actual_duration
            if self.MIN_STRETCH <= ratio <= self.MAX_STRETCH:
                return "stretch"
        return "split"

    def compute_stretch_ratio(self, actual: float, target: float) -> float:
        """计算 RubberBand 拉伸比，限制在 [0.5, 2.0]。"""
        if actual <= 0:
            return 1.0
        ratio = target / actual
        return max(self.MIN_STRETCH, min(self.MAX_STRETCH, ratio))

    def suggest_split(self, text: str, target_duration: float) -> list[str]:
        """将过长文本按标点拆分为多个子句。"""
        if not text or target_duration <= 0:
            return [text] if text else []

        max_chars = int(target_duration * self.CHARS_PER_SECOND)
        if max_chars <= 0 or len(text) <= max_chars:
            return [text]

        parts = []
        current = ""
        for ch in text:
            current += ch
            if ch in "。！？.!?,;；：:" and len(current) >= max_chars * 0.5:
                parts.append(current.strip())
                current = ""
        if current.strip():
            parts.append(current.strip())
        return parts if parts else [text]


def duration_fit_score(actual: float, target: float) -> float:
    """时长匹配度评分。deviation 50% 以上得 0。"""
    if target <= 0:
        return 1.0
    deviation = abs(actual - target) / target
    return round(max(0.0, 1.0 - deviation / 0.5), 4)
