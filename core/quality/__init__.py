"""core/quality — 可插拔翻译质量把控策略"""
from core.quality.protocol import (
    QualityStrategy, QualityVerdict, ThresholdConfig,
    create_strategy, register_strategy, list_strategies,
)

__all__ = [
    "QualityStrategy", "QualityVerdict", "ThresholdConfig",
    "create_strategy", "register_strategy", "list_strategies",
]
