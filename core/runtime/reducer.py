"""
TimelineReducer — 状态归约器 (Chapter 12 §12.4)

Patch 序列 → 当前状态的确定性归约器。
保证: 同一 patch sequence → 同一结果 (deterministic replay)。

与 PatchEngine 的关系:
  - PatchEngine: 单 patch 执行器 (apply one patch → diff)
  - Reducer: 多 patch 编排器 (apply sequence → final state)

Reducer 负责:
  - 按 timestamp 排序 patches
  - 生成 replay checkpoint
  - 计算状态间差异
"""
from __future__ import annotations
from core.runtime.patch import Patch
from core.runtime.patch_engine import PatchEngine
from core.runtime.project_state import TimelineProjectState
from core.ir.project import TimelineProjectIR


class TimelineReducer:
    """Patch 序列 → 当前状态的确定性归约器。

    Usage:
        reducer = TimelineReducer()
        final = reducer.reduce(state, patches)
        past_state = reducer.replay(state, patches, target_timestamp=1000.0)
    """

    def __init__(self):
        self._engine = PatchEngine()

    # ── public API ──────────────────────────────────────

    def reduce(
        self,
        state: TimelineProjectState,
        patches: list[Patch],
    ) -> TimelineProjectState:
        """按 timestamp 排序后顺序应用 patches，返回最终状态。"""
        sorted_patches = sorted(patches, key=lambda p: p.timestamp)
        for patch in sorted_patches:
            self._engine.apply(state, patch)
        return state

    def replay(
        self,
        state: TimelineProjectState,
        patches: list[Patch],
        target_timestamp: float | None = None,
    ) -> TimelineProjectState:
        """重放 patches 到指定时间戳（用于回滚到历史点）。

        如果 target_timestamp 为 None，重放全部。
        """
        sorted_patches = sorted(patches, key=lambda p: p.timestamp)
        for patch in sorted_patches:
            if target_timestamp is not None and patch.timestamp > target_timestamp:
                break
            self._engine.apply(state, patch)
        return state

    def replay_from_snapshot(
        self,
        ir: TimelineProjectIR,
        patches: list[Patch],
    ) -> TimelineProjectState:
        """从 IR 快照 + patch 序列重放，生成完整 state。"""
        state = TimelineProjectState(ir)
        return self.reduce(state, patches)

    def compute_diff(
        self,
        before: TimelineProjectState,
        after: TimelineProjectState,
    ) -> dict:
        """计算两个状态之间的差异。

        Returns:
            {event_count_delta, added_events, removed_events,
             modified_events: {event_id: {patches_added, derivatives_changed}},
             global_patches_delta}
        """
        before_ids = set(before.event_states.keys())
        after_ids = set(after.event_states.keys())

        added = list(after_ids - before_ids)
        removed = list(before_ids - after_ids)
        common = before_ids & after_ids

        modified = {}
        for eid in common:
            b_es = before.get_event(eid)
            a_es = after.get_event(eid)
            if b_es is None or a_es is None:
                continue
            patches_delta = len(a_es.patches) - len(b_es.patches)
            deriv_changed = [
                k for k in a_es.derivatives
                if k not in b_es.derivatives
                or b_es.derivatives.get(k) != a_es.derivatives.get(k)
            ]
            if patches_delta != 0 or deriv_changed:
                modified[eid] = {
                    "patches_added": patches_delta,
                    "derivatives_changed": deriv_changed,
                }

        return {
            "event_count_delta": len(after_ids) - len(before_ids),
            "added_events": added,
            "removed_events": removed,
            "modified_events": modified,
            "global_patches_delta": (
                len(after.global_patches) - len(before.global_patches)
            ),
        }
