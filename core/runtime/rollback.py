"""
RollbackManager — 三级回滚管理 (Chapter 12 §12.8.2)

Level 1: segment → 回退单个 segment patches 到指定版本
Level 2: window → 回退受影响范围的连续片段
Level 3: global → 从快照恢复整个 state
"""
from __future__ import annotations
from core.runtime.patch import Patch
from core.runtime.project_state import TimelineProjectState
from core.runtime.reducer import TimelineReducer
from core.runtime.snapshot import SnapshotManager, TimelineSnapshot
from core.runtime.dependency_graph import DependencyGraph


class RollbackManager:
    """三级回滚。

    Version Stack: patches[i] → version i+1
    回滚 = 截断 patches 到 target_version
    """

    def __init__(self, reducer: TimelineReducer, snapshots: SnapshotManager,
                 dep_graph: DependencyGraph):
        self.reducer = reducer
        self.snapshots = snapshots
        self.dep_graph = dep_graph

    def rollback_segment(self, state: TimelineProjectState, segment_id: str,
                         target_version: int) -> TimelineProjectState:
        """回退单个 segment 到指定版本 (0-indexed)。(批次04 §三)"""
        es = state.get_event(segment_id)
        if es is None or target_version < 0 or target_version >= len(es.patches):
            return state
        kept = es.patches[:target_version + 1]
        es.patches = kept
        es.derivatives.clear()
        for p in kept:
            from core.runtime.config_resolver import deep_merge as _dm
            _dm(es.derivatives, p.value)
        self.dep_graph.invalidate(segment_id)
        return state

    def get_segment_versions(self, state: TimelineProjectState,
                             segment_id: str) -> list[dict]:
        es = state.get_event(segment_id)
        if es is None:
            return []
        return [
            {"version": i, "patch_id": p.id, "op": str(p.op),
             "timestamp": p.timestamp, "author": p.author,
             "confidence": p.confidence}
            for i, p in enumerate(es.patches)
        ]

    def rollback_window(self, state: TimelineProjectState,
                        center_segment_id: str, window_size: int = 2,
                        target_timestamp: float | None = None,
                        ) -> TimelineProjectState:
        affected = self.dep_graph.get_affected_range(
            center_segment_id,
            upstream_depth=window_size,
            downstream_depth=window_size,
        )
        for seg_id in affected:
            es = state.get_event(seg_id)
            if es is None:
                continue
            kept = [p for p in es.patches
                    if target_timestamp is None or p.timestamp <= target_timestamp]
            es.patches = kept
            es.derivatives.clear()
            for p in kept:
                from core.runtime.config_resolver import deep_merge as _dm
                _dm(es.derivatives, p.value)
        return state

    def rollback_global(self, state: TimelineProjectState,
                        snapshot_id: str) -> TimelineProjectState | None:
        for s in self.snapshots._snapshots:
            if s.snapshot_id == snapshot_id:
                return self.snapshots.restore(state, s)
        return None

    def compute_reverse_patch(self, patch: Patch,
                              state: TimelineProjectState) -> Patch | None:
        target = state.get_event(patch.target_id)
        if target is None:
            return None
        idx = None
        for i, p in enumerate(target.patches):
            if p.id == patch.id:
                idx = i
                break
        if idx is None:
            return None
        # idx=0 允许：生成空 value 的逆向 patch，支持回退到初始状态 (批次04 §三)
        prev = {}
        for p in target.patches[:idx]:
            prev.update(p.value)
        import time as _time
        return Patch(
            id=f"undo_{patch.id}", target_id=patch.target_id,
            op=patch.op, value=prev, author="system",
            reason=[f"undo {patch.id}"], parent_version=patch.id,
        )
