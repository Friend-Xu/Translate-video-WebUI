"""core/runtime — 运行时状态层 + Patch 引擎 + Synthesis + Ch12 系统

- 零 deepcopy：通过 IR 只读引用 + dict 字面量合并实现
- Patch 只写 state，不改 IR
- Synthesis 纯函数组合渲染，5 层显式分层
- Ch12: Reducer / DependencyGraph / RecomputeEngine / Conflict / Rollback / Snapshot / PatchStore / GateValidator / PatchPlanner

v3.0: 全 14 OpCode PatchEngine + 完整回滚/快照/冲突消解/局部重算。
"""
from core.runtime.patch import Patch, OpCode
from core.runtime.event_state import TimelineEventState
from core.runtime.project_state import TimelineProjectState
from core.runtime.patch_engine import PatchEngine
from core.runtime.synthesis import SynthesisEngine
from core.runtime.reducer import TimelineReducer
from core.runtime.dependency_graph import DependencyGraph, DependencyEdge
from core.runtime.recompute import RecomputeEngine, RecomputeScope, RecomputeTask
from core.runtime.conflict import (
    ConflictDetector, ConflictResolver, Conflict, ConflictType,
)
from core.runtime.rollback import RollbackManager
from core.runtime.snapshot import SnapshotManager, TimelineSnapshot
from core.runtime.patch_store import PatchStore
from core.runtime.gate_validator import GateValidator, GateRejection
from core.runtime.patch_planner import PatchPlanner
from core.runtime.workspace import WorkspaceResolver

__all__ = [
    "Patch", "OpCode",
    "TimelineEventState", "TimelineProjectState",
    "PatchEngine", "SynthesisEngine",
    "TimelineReducer",
    "DependencyGraph", "DependencyEdge",
    "RecomputeEngine", "RecomputeScope", "RecomputeTask",
    "ConflictDetector", "ConflictResolver", "Conflict", "ConflictType",
    "RollbackManager",
    "SnapshotManager", "TimelineSnapshot",
    "PatchStore",
    "GateValidator", "GateRejection",
    "PatchPlanner",
    "WorkspaceResolver",
]
