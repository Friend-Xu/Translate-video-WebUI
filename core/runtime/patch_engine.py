"""
PatchEngine — Patch 执行器

Patch 只写 runtime state，绝不修改 IR。
所有 op 实现为纯函数，返回 diff 而不修改入参。
"""
from __future__ import annotations
from core.runtime.patch import Patch
from core.runtime.event_state import TimelineEventState
from core.runtime.project_state import TimelineProjectState


class PatchEngine:
    """Patch 执行器 — 只作用 runtime state，不改 IR。

    apply() 接收 state + patch，修改 state 并返回 diff dict。
    """

    # ── public API ──────────────────────────────────────

    def apply(
        self, state: TimelineProjectState, patch: Patch
    ) -> dict:
        """执行一个 patch，返回 diff。修改 state 的 event_states。"""
        target = state.get_event(patch.target_id)
        if target is None:
            return {"status": "error", "reason": f"target not found: {patch.target_id}"}

        if patch.op == "replace":
            return self._replace(target, patch)
        elif patch.op == "merge":
            return self._merge(state, patch)
        elif patch.op == "split":
            return self._split(state, patch)
        elif patch.op == "propagate":
            return self._propagate(state, patch)
        else:
            return {"status": "error", "reason": f"unknown op: {patch.op}"}

    def apply_many(
        self, state: TimelineProjectState, patches: list[Patch]
    ) -> list[dict]:
        """批量执行 patches，返回 diffs 列表"""
        return [self.apply(state, p) for p in patches]

    # ── op implementations ──────────────────────────────

    def _replace(self, target: TimelineEventState, patch: Patch) -> dict:
        """replace: 合并 value dict 到 target.derivatives"""
        before = dict(target.derivatives)
        target.derivatives.update(patch.value)
        target.add_patch(patch)
        return {
            "status": "applied",
            "op": "replace",
            "target": patch.target_id,
            "before": before,
            "after": dict(target.derivatives),
        }

    def _merge(self, state: TimelineProjectState, patch: Patch) -> dict:
        """merge: 合并 target_ids 中的事件到一个"""
        ids = patch.value.get("target_ids", [patch.target_id])
        if len(ids) < 2:
            return {"status": "error", "reason": "merge requires >= 2 targets"}
        primary = state.get_event(ids[0])
        if primary is None:
            return {"status": "error", "reason": f"primary not found: {ids[0]}"}
        merged_ids = ids[1:]
        primary.derivatives["_merged_from"] = merged_ids
        primary.derivatives["_merged_end"] = max(
            primary.end,
            max(
                (state.get_event(mid).end if state.get_event(mid) else 0)
                for mid in merged_ids
            ),
        )
        primary.add_patch(patch)
        return {
            "status": "applied",
            "op": "merge",
            "primary": ids[0],
            "merged": merged_ids,
        }

    def _split(self, state: TimelineProjectState, patch: Patch) -> dict:
        """split: 在指定时间点切分事件"""
        split_at = patch.value.get("at", 0.0)
        target = state.get_event(patch.target_id)
        if target is None:
            return {"status": "error", "reason": f"target not found: {patch.target_id}"}
        target.derivatives["_split_at"] = split_at
        target.add_patch(patch)
        return {
            "status": "applied",
            "op": "split",
            "target": patch.target_id,
            "split_at": split_at,
        }

    def _propagate(self, state: TimelineProjectState, patch: Patch) -> dict:
        """propagate: 将变更传播到其他事件"""
        propagated_to = patch.value.get("to_ids", [])
        key = patch.value.get("key", "")
        val = patch.value.get("val")
        for eid in propagated_to:
            es = state.get_event(eid)
            if es:
                es.derivatives[key] = val
        target = state.get_event(patch.target_id)
        if target:
            target.add_patch(patch)
        return {
            "status": "applied",
            "op": "propagate",
            "from": patch.target_id,
            "to": propagated_to,
        }
