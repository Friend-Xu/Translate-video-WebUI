"""
ProgressReport — 标准化进度事件 (定稿 §17.3 可观测性)

工作流执行过程中，每个阶段的开始/进度/完成/失败均通过统一的
ProgressReport 结构对外通知。

设计原则:
  - 每个事件自包含（含 stage、timestamp、payload）
  - 支持嵌套进度（总数 + 当前）
  - 失败事件携带可诊断的 error 信息
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
import time


class ProgressEventType(Enum):
    STAGE_STARTED = "stage_started"
    STAGE_PROGRESS = "stage_progress"
    STAGE_COMPLETED = "stage_completed"
    STAGE_FAILED = "stage_failed"
    STAGE_PAUSED = "stage_paused"
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    WORKFLOW_CANCELLED = "workflow_cancelled"


@dataclass
class ProgressReport:
    """标准化的进度事件。

    Attributes:
        event_type: 事件类型
        stage: 当前阶段标识 (e.g. "translate")
        stage_label: 阶段中文标签 (e.g. "翻译与审校")
        total_items: 本阶段总处理项数（0 = 未知）
        current_item: 当前处理项索引（0-based）
        message: 人类可读的状态消息
        timestamp: 事件时间戳（epoch seconds）
        payload: 附加数据（如 Gate 评分、错误信息）
    """
    event_type: ProgressEventType
    stage: str
    stage_label: str = ""
    total_items: int = 0
    current_item: int = 0
    message: str = ""
    timestamp: float = field(default_factory=time.time)
    payload: dict = field(default_factory=dict)

    @property
    def percent(self) -> float:
        if self.total_items <= 0:
            return 0.0
        return min(self.current_item / self.total_items, 1.0)

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type.value,
            "stage": self.stage,
            "stage_label": self.stage_label,
            "total_items": self.total_items,
            "current_item": self.current_item,
            "percent": round(self.percent, 3),
            "message": self.message,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }


@dataclass
class StageProgress:
    """单个阶段的执行进度追踪器。"""
    stage: str
    total: int = 0
    current: int = 0
    started_at: float = 0.0
    completed_at: float = 0.0

    @property
    def elapsed(self) -> float:
        if self.started_at == 0:
            return 0.0
        end = self.completed_at or time.time()
        return end - self.started_at

    @property
    def is_done(self) -> bool:
        return self.completed_at > 0

    def advance(self, n: int = 1) -> None:
        if self.total > 0:
            self.current = min(self.current + n, self.total)
        else:
            self.current += n
