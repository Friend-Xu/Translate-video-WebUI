"""
RuntimeEvent — 结构化运行时事件类型 (设计文档 §11.1-§11.3)

所有发动机器 (StageExecutor, WorkflowOrchestrator, PatchEngine, PassManager)
通过 EventBus 发出结构化事件，CLI/WebUI 消费同一事件流。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
import time
import uuid


class RuntimeEventType(Enum):
    # ── 工作流级 ──
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_PAUSED = "workflow_paused"
    WORKFLOW_FAILED = "workflow_failed"
    WORKFLOW_CANCELLED = "workflow_cancelled"

    # ── 阶段级 ──
    STAGE_STARTED = "stage_started"
    STAGE_PROGRESS = "stage_progress"
    STAGE_COMPLETED = "stage_completed"
    STAGE_SKIPPED = "stage_skipped"

    # ── Pass 级 ──
    PASS_STARTED = "pass_started"
    PASS_COMPLETED = "pass_completed"
    PASS_FAILED = "pass_failed"

    # ── Patch/State ──
    PATCH_APPLIED = "patch_applied"
    STATE_DIRTY = "state_dirty"
    CONFIG_RESOLVED = "config_resolved"

    # ── 校验 ──
    VALIDATION_PASSED = "validation_passed"
    VALIDATION_FAILED = "validation_failed"
    VALIDATION_QUEUED = "validation_queued"

    # ── 资源 ──
    ADAPTER_LOADING = "adapter_loading"
    ADAPTER_READY = "adapter_ready"
    GPU_MEMORY_CHANGED = "gpu_memory_changed"

    # ── 操作 ──
    CHECKPOINT_SAVED = "checkpoint_saved"
    EXPORT_FINISHED = "export_finished"
    ERROR = "error"
    LOG = "log"


@dataclass
class RuntimeEvent:
    """结构化运行时事件。

    贯穿整个 Runtime 生命周期，CLI 和 WebUI 通过 EventBus 订阅。
    """
    event_type: RuntimeEventType
    timestamp: float = field(default_factory=time.time)
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    workspace_id: str = ""

    # 上下文定位
    stage: str = ""
    stage_label: str = ""
    node: str = ""

    # 内容
    message: str = ""
    payload: dict = field(default_factory=dict)

    # 性能
    duration_ms: float = 0.0

    # 进度
    total_items: int = 0
    current_item: int = 0

    def to_dict(self) -> dict:
        d = {
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "trace_id": self.trace_id,
            "workspace_id": self.workspace_id or "",
            "stage": self.stage,
            "stage_label": self.stage_label,
            "node": self.node,
            "message": self.message,
            "payload": self.payload,
            "duration_ms": self.duration_ms,
            "total_items": self.total_items,
            "current_item": self.current_item,
        }
        if self.total_items > 0:
            d["percent"] = self.current_item / self.total_items
        return d

    @property
    def percent(self) -> float | None:
        if self.total_items > 0:
            return self.current_item / self.total_items
        return None
