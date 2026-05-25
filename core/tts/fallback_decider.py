"""
FallbackDecider — 降级决策器 (Chapter 8 §8.1-8.2)

控制 OpenVoice fallback 的触发时机和条件。
决定"何时"以及"为何"主引擎结果应被降级到 OpenVoice。

核心原则:
  1. 主引擎失败时才触发 — 不主动抢占主引擎任务
  2. MAX_FALLBACK_RATIO 硬限制 — 防止系统过度依赖降级
  3. fallback_reason 不可丢失 — 元信息用于后续替换和审计
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class FallbackDecision:
    """降级决策结果。"""
    should_fallback: bool
    reason: str = ""
    urgency: str = "normal"          # "immediate" | "normal" | "optional"


class FallbackDecider:
    """降级决策器 — 判断是否应触发 OpenVoice fallback。

    决策依据（按优先级降序）:
      1. 主引擎结果被 Logic Gate 拒绝 → immediate
      2. 主引擎 confidence < MIN_CONFIDENCE_THRESHOLD → immediate
      3. 主引擎资源不可用（GPU OOM, worker crash）→ immediate
      4. 快速修复请求（局部重算场景）→ normal
      5. 低优先级片段（节省主引擎资源）→ optional

    硬限制:
      fallback_count / total_segments > MAX_FALLBACK_RATIO → 拒绝降级
    """

    MIN_CONFIDENCE_THRESHOLD = 0.65
    MAX_FALLBACK_RATIO = 0.30

    def decide(self, segment_id: str = "",
               primary_score: float | None = None,
               primary_error: str | None = None,
               is_quick_fix: bool = False,
               is_low_priority: bool = False,
               fallback_count: int = 0,
               total_segments: int = 1) -> FallbackDecision:
        """综合判断是否触发 fallback。

        Args:
            primary_score: 主引擎综合评分（None = 未执行）
            primary_error: 主引擎错误信息（None = 无错误）
            is_quick_fix: 是否快速修复请求
            is_low_priority: 是否低优先级片段
            fallback_count: 当前已降级片段数
            total_segments: 总片段数
        """
        # 硬限制: 降级比例不得超过 MAX_FALLBACK_RATIO
        if total_segments > 0 and fallback_count / total_segments > self.MAX_FALLBACK_RATIO:
            return FallbackDecision(
                should_fallback=False,
                reason="fallback_ratio_exceeded",
                urgency="normal",
            )

        # 优先级 1: 主引擎执行失败
        if primary_error:
            return FallbackDecision(
                should_fallback=True,
                reason="primary_error",
                urgency="immediate",
            )

        # 优先级 2: 主引擎置信度不足
        if primary_score is not None and primary_score < self.MIN_CONFIDENCE_THRESHOLD:
            return FallbackDecision(
                should_fallback=True,
                reason="primary_low_confidence",
                urgency="immediate",
            )

        # 优先级 3: 主引擎结果边缘
        if primary_score is not None and primary_score < 0.70:
            return FallbackDecision(
                should_fallback=True,
                reason="primary_marginal",
                urgency="normal",
            )

        # 优先级 4: 快速修复请求
        if is_quick_fix:
            return FallbackDecision(
                should_fallback=True,
                reason="quick_fix",
                urgency="normal",
            )

        # 优先级 5: 低优先级片段
        if is_low_priority:
            return FallbackDecision(
                should_fallback=True,
                reason="low_priority_segment",
                urgency="optional",
            )

        # 无触发条件
        return FallbackDecision(
            should_fallback=False,
            reason="no_trigger_condition",
            urgency="normal",
        )

    def should_replace_fallback(self,
                                 new_primary_available: bool = False) -> bool:
        """判断是否应该用新的主引擎结果替换已有的 fallback 结果。

        当主引擎资源恢复或重新执行后结果可用时，应替换 fallback。
        """
        return new_primary_available
