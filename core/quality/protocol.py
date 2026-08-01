"""
QualityStrategy Protocol — 质量把控策略抽象层

与 WorkflowPolicy 同层。用户在配置中选择策略，
门控路由逻辑 (A/B/C) 不变，只更换评分引擎。

调用方: core/passes/translation_quality_pass.py
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.runtime.project_state import TimelineProjectState
    from core.runtime.event_state import TimelineEventState
    from core.config.global_config import GlobalConfig


@dataclass
class ThresholdConfig:
    """策略级阈值 — 不同策略有不同默认值"""
    accept: float = 0.65    # >= accept → Gate A
    review: float = 0.50    # >= review → Gate B, < review → Gate C


@dataclass
class QualityVerdict:
    """统一输出契约 — WorkflowOrchestrator 只看 gate_decision"""
    score: float
    sub_scores: dict = field(default_factory=dict)
    gate_decision: str = ""     # "A" | "B" | "C"
    reason: str = ""
    needs_human: bool = False
    strategy_name: str = ""

    @classmethod
    def from_score(cls, score: float, thresholds: ThresholdConfig,
                   strategy_name: str = "") -> "QualityVerdict":
        """根据分数 + 阈值自动计算 gate_decision"""
        if score >= thresholds.accept:
            return cls(score=score, gate_decision="A", reason="quality_above_accept",
                       strategy_name=strategy_name)
        if score >= thresholds.review:
            return cls(score=score, gate_decision="B", reason="quality_needs_review",
                       needs_human=True, strategy_name=strategy_name)
        return cls(score=score, gate_decision="C", reason="quality_below_review",
                   needs_human=True, strategy_name=strategy_name)


class QualityStrategy(ABC):
    """质量把控策略协议"""
    name: str = ""

    @abstractmethod
    def score_batch(
        self, state: "TimelineProjectState",
    ) -> dict[str, QualityVerdict]:
        """批量评分 — 返回 {event_id: QualityVerdict}"""
        ...

    @property
    @abstractmethod
    def thresholds(self) -> ThresholdConfig:
        ...

    @classmethod
    def from_config(cls, config: "GlobalConfig | None" = None) -> "QualityStrategy":
        """工厂: 从 GlobalConfig 构建策略实例"""
        raise NotImplementedError

    def warmup(self) -> None:
        """可选: 预加载模型"""
        pass


# 策略注册表
_STRATEGY_REGISTRY: dict[str, type[QualityStrategy]] = {}


def register_strategy(name: str) -> callable:
    """装饰器: 注册策略类"""
    def decorator(cls: type[QualityStrategy]) -> type[QualityStrategy]:
        _STRATEGY_REGISTRY[name] = cls
        return cls
    return decorator


def create_strategy(name: str, config: "GlobalConfig | None" = None) -> QualityStrategy:
    """工厂: 按名称创建策略实例。

    注册表由策略模块 import 时装饰器填充 — 首次调用懒加载全部策略模块,
    避免调用方只 import protocol 时注册表为空 (E2E 复验暴露)。
    """
    if not _STRATEGY_REGISTRY:
        from core.quality import logic_gate_strategy  # noqa: F401
        from core.quality import xcomet_strategy      # noqa: F401
    cls = _STRATEGY_REGISTRY.get(name)
    if cls is None:
        available = ", ".join(sorted(_STRATEGY_REGISTRY.keys()))
        raise ValueError(f"未知 QualityStrategy: '{name}'. 可用: {available}")
    return cls.from_config(config)


def list_strategies() -> list[str]:
    return sorted(_STRATEGY_REGISTRY.keys())
