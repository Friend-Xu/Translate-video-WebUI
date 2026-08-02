"""
SlotLevelDependencyGraph — 字段级依赖图 (定稿 §14, AC-DEP-01~04)

v2.0: 从槽位级升级为字段级粒度。
  - 修改 tts.config.speed_factor → 仅标记 TTS 脏 (AC-DEP-01)
  - 修改 asr.config.model → 级联标记 asr+translation+tts+emotion (AC-DEP-02)
  - RecomputeEngine 仅重算 dirty 事件 (AC-DEP-03)
"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.runtime.project_state import TimelineProjectState


class SlotLevelDependencyGraph:
    """字段级依赖图 — 精确计算配置变更的脏标记传播范围。"""

    SLOT_DOWNSTREAM: dict[str, set[str]] = {
        "audio":        {"asr", "speaker"},
        "asr":          {"asr", "translation", "tts", "emotion"},
        "speaker":      {"speaker", "tts"},
        "translation":  {"translation", "tts"},
        "tts":          {"tts"},
        "emotion":      {"emotion", "tts"},
        "review":       set(),
        "semantic":     {"semantic"},
        "runtime":      set(),
        "provenance":   set(),
    }

    # 字段 → 是否触发级联传播到下游槽位 (未列出的默认仅标记自身)
    CASCADE_FIELDS: dict[str, bool] = {
        "vad_threshold": True,
        "silence_handling": True,
        "model": True,
        "language": True,
        "compute_type": True,
        "clustering_threshold": True,
        "min_speakers": True,
        "max_speakers": True,
        "lang": True,
        "backend": True,
        "enabled": True,
        "fusion_strategy": True,
    }

    def propagate_dirty(
        self,
        event_id: str,
        changed_slot: str,
        state: "TimelineProjectState",
    ) -> set[tuple[str, str]]:
        """槽位级传播 (向后兼容)。推荐使用 propagate_dirty_fields()。"""
        return self._bfs_propagate(event_id, changed_slot, state, cascade=True)

    def propagate_dirty_fields(
        self,
        event_id: str,
        changed_slot: str,
        changed_field: str,
        state: "TimelineProjectState",
    ) -> set[tuple[str, str]]:
        """字段级脏标记传播 (AC-DEP-01, AC-DEP-02)。

        changed_field 在 CASCADE_FIELDS 中 → 级联传播到下游槽位。
        否则 → 仅标记自身槽位 (speed_factor 等 local-only 字段)。

        Returns:
            受影响的 (event_id, slot) 集合。
        """
        cascade = self.CASCADE_FIELDS.get(changed_field, False)
        return self._bfs_propagate(event_id, changed_slot, state, cascade=cascade)

    def is_cascade_field(self, field: str) -> bool:
        return self.CASCADE_FIELDS.get(field, False)

    def _bfs_propagate(
        self,
        event_id: str,
        changed_slot: str,
        state: "TimelineProjectState",
        cascade: bool = True,
    ) -> set[tuple[str, str]]:
        visited: set[tuple[str, str]] = set()

        if not cascade:
            es = state.get_event(event_id)
            if es is not None:
                es.runtime.dirty_flags[changed_slot] = True
            visited.add((event_id, changed_slot))
            return visited

        queue: list[tuple[str, str]] = [(event_id, changed_slot)]
        while queue:
            eid, slot = queue.pop(0)
            if (eid, slot) in visited:
                continue
            visited.add((eid, slot))
            es = state.get_event(eid)
            if es is not None:
                es.runtime.dirty_flags[slot] = True
            for downstream_slot in self.SLOT_DOWNSTREAM.get(slot, set()):
                if (eid, downstream_slot) not in visited:
                    queue.append((eid, downstream_slot))
        return visited

    def get_downstream_slots(self, slot: str) -> set[str]:
        return self.SLOT_DOWNSTREAM.get(slot, set())

    def get_full_downstream_chain(self, slot: str) -> set[str]:
        visited: set[str] = {slot}
        queue = [slot]
        while queue:
            s = queue.pop(0)
            for ds in self.SLOT_DOWNSTREAM.get(s, set()):
                if ds not in visited:
                    visited.add(ds)
                    queue.append(ds)
        return visited
