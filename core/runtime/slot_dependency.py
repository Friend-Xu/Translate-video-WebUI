"""
SlotLevelDependencyGraph — 槽位级依赖图 (定稿 §12.2)

扩展自 DependencyGraph，支持字段级粒度的脏标记传播。
修改 tts.config.speed_factor 仅标记 TTS 脏，不触发无意义的重翻译。
"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.runtime.project_state import TimelineProjectState


class SlotLevelDependencyGraph:
    """槽位级依赖图 — 精确计算配置变更的脏标记传播范围。

    与 DependencyGraph 的区别:
      DependencyGraph 基于段间关系 (temporal/speaker/semantic)，
      是粗粒度模型。SlotLevelDependencyGraph 回答的问题是：
      "修改事件 A 的 asr.config.model，哪些下游需要重算？"

    答案: asr 自身 + translation + tts + emotion — 全部级联。
    而修改 tts.config.speed_factor → 仅 tts 自身。
    """

    # 槽位 → 下游槽位 的声明式映射
    SLOT_DOWNSTREAM: dict[str, set[str]] = {
        "audio":        {"asr", "speaker"},
        "asr":          {"asr", "translation", "tts", "emotion"},
        "speaker":      {"speaker", "tts"},
        "translation":  {"translation", "tts"},
        "tts":          {"tts"},              # 仅自身！这是关键优化
        "emotion":      {"emotion", "tts"},
        "review":       set(),               # review 变更不影响计算
        "semantic":     {"semantic"},
        "runtime":      set(),
        "provenance":   set(),
    }

    def propagate_dirty(
        self,
        event_id: str,
        changed_slot: str,
        state: "TimelineProjectState",
    ) -> set[tuple[str, str]]:
        """传播脏标记到受影响的下游槽位。

        Returns:
            受影响的 (event_id, slot) 集合。
        """
        visited: set[tuple[str, str]] = set()
        queue: list[tuple[str, str]] = [(event_id, changed_slot)]

        while queue:
            eid, slot = queue.pop(0)
            if (eid, slot) in visited:
                continue
            visited.add((eid, slot))

            es = state.get_event(eid)
            if es is not None:
                es.runtime.setdefault("dirty_flags", {})[slot] = True

            for downstream_slot in self.SLOT_DOWNSTREAM.get(slot, set()):
                if (eid, downstream_slot) not in visited:
                    queue.append((eid, downstream_slot))

        return visited

    def get_downstream_slots(self, slot: str) -> set[str]:
        """获取某槽位的直接下游槽位集合。"""
        return self.SLOT_DOWNSTREAM.get(slot, set())

    def get_full_downstream_chain(self, slot: str) -> set[str]:
        """获取某槽位的完整下游链（含自身）。"""
        visited: set[str] = {slot}
        queue = [slot]
        while queue:
            s = queue.pop(0)
            for ds in self.SLOT_DOWNSTREAM.get(s, set()):
                if ds not in visited:
                    visited.add(ds)
                    queue.append(ds)
        return visited
