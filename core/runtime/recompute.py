"""
RecomputeEngine — 局部重算引擎 (Chapter 12 §12.5)

核心职责:
  1. 接收 invalidated segment IDs
  2. 计算最优重算范围
  3. 生成优先级排序的重算队列
  4. 合并连续重算请求以减 batch 开销
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from core.runtime.dependency_graph import DependencyGraph


class RecomputeScope(Enum):
    SEGMENT = "segment"
    WINDOW = "window"
    FULL = "full"


@dataclass
class RecomputeTask:
    segment_ids: list[str]
    scope: RecomputeScope
    reason: str
    priority: int = 0
    invalidated_by: str = ""


_TRIGGER_MAP: dict[str, tuple[RecomputeScope, int, int]] = {
    "asr_transcription": (RecomputeScope.WINDOW, 0, 1),
    "speaker_reassign": (RecomputeScope.WINDOW, 0, 2),
    "tts_replace": (RecomputeScope.SEGMENT, 1, 0),
    "alignment_fix": (RecomputeScope.SEGMENT, 1, 0),
    "speaker_drift": (RecomputeScope.WINDOW, 0, 3),
    "translation_retranslate": (RecomputeScope.WINDOW, 2, 1),
    "vad_resegment": (RecomputeScope.FULL, 0, 0),
}


class RecomputeEngine:
    """局部重算引擎。"""

    def __init__(self, dep_graph: DependencyGraph):
        self.dep_graph = dep_graph

    def plan(
        self, invalidated: list[str],
        strategy: str = "minimal",
        trigger: str = "asr_transcription",
    ) -> list[RecomputeTask]:
        if not invalidated:
            return []
        scope, priority, window = _TRIGGER_MAP.get(
            trigger, (RecomputeScope.SEGMENT, 1, 0),
        )
        if strategy == "window" or scope == RecomputeScope.WINDOW:
            return self._plan_window(invalidated, trigger, priority, window or 2)
        if strategy == "safe":
            return self._plan_safe(invalidated, trigger, priority)
        return self._plan_minimal(invalidated, trigger, priority)

    def _plan_minimal(self, invalidated, reason, priority):
        tasks = [
            RecomputeTask(
                segment_ids=[sid], scope=RecomputeScope.SEGMENT,
                reason=reason, priority=priority, invalidated_by=sid,
            )
            for sid in invalidated
        ]
        return sorted(tasks, key=lambda t: (t.priority, t.segment_ids[0]))

    def _plan_window(self, invalidated, reason, priority, window_size):
        all_ids: set[str] = set()
        for sid in invalidated:
            affected = self.dep_graph.get_affected_range(
                sid, upstream_depth=window_size, downstream_depth=window_size,
            )
            all_ids.update(affected)
        return [RecomputeTask(
            segment_ids=sorted(all_ids), scope=RecomputeScope.WINDOW,
            reason=reason, priority=priority,
            invalidated_by=",".join(invalidated),
        )]

    def _plan_safe(self, invalidated, reason, priority):
        tasks = self._plan_window(invalidated, reason, priority, 2)
        for task in tasks:
            for sid in task.segment_ids:
                downstream = self.dep_graph.get_downstream(sid, depth=2)
                if downstream:
                    cascaded = self.dep_graph.invalidate(sid, max_depth=2)
                    if len(cascaded) > len(downstream) * 0.5:
                        task.scope = RecomputeScope.FULL
                        break
        return tasks

    def estimate_cost(self, tasks: list[RecomputeTask]) -> dict:
        if not tasks:
            return {"segment_count": 0, "task_count": 0, "scope": "none"}
        all_segs: set[str] = set()
        for t in tasks:
            all_segs.update(t.segment_ids)
        scope = "full" if any(t.scope == RecomputeScope.FULL for t in tasks) else (
            "window" if any(t.scope == RecomputeScope.WINDOW for t in tasks) else "segment"
        )
        return {
            "segment_count": len(all_segs),
            "task_count": len(tasks),
            "scope": scope,
        }

    def merge_tasks(self, tasks: list[RecomputeTask]) -> list[RecomputeTask]:
        if len(tasks) <= 1:
            return tasks
        sorted_tasks = sorted(tasks, key=lambda t: (t.priority, t.segment_ids[0]))
        merged = []
        current = sorted_tasks[0]
        for task in sorted_tasks[1:]:
            if (
                task.scope == current.scope
                and task.priority == current.priority
                and task.reason == current.reason
            ):
                combined = list(set(current.segment_ids + task.segment_ids))
                current = RecomputeTask(
                    segment_ids=sorted(combined),
                    scope=RecomputeScope.WINDOW,
                    reason=current.reason,
                    priority=current.priority,
                    invalidated_by=f"{current.invalidated_by},{task.invalidated_by}",
                )
            else:
                merged.append(current)
                current = task
        merged.append(current)
        return merged
