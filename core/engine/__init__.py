"""core/engine — Pass 调度系统 + 工作流编排

Pass 是 pipeline 步骤的抽象。每个 Pass 接收 TimelineProjectState，
返回新的 state。PassManager 按拓扑序调度执行。

v2.0: 新增 WorkflowOrchestrator（五阶段编排器）+ StageExecutor（单阶段执行器）
"""
from core.engine.pass_base import TimelinePass
from core.engine.pass_manager import PassManager
from core.engine.stage_executor import StageExecutor
from core.engine.workflow_orchestrator import WorkflowOrchestrator, WorkflowStatus
from core.engine.progress import ProgressReport, ProgressEventType, StageProgress

__all__ = [
    "TimelinePass",
    "PassManager",
    "StageExecutor",
    "WorkflowOrchestrator",
    "WorkflowStatus",
    "ProgressReport",
    "ProgressEventType",
    "StageProgress",
]
