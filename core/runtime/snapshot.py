"""
SnapshotManager — 时间线快照系统 (Chapter 12 §12.8)

create / restore / replay_from. MAX_SNAPSHOTS=10.
"""
from __future__ import annotations
from dataclasses import dataclass
import time
from core.runtime.project_state import TimelineProjectState

MAX_SNAPSHOTS = 10


@dataclass
class TimelineSnapshot:
    snapshot_id: str
    timestamp: float
    event_states_snapshot: dict[str, dict]
    global_patches_count: int
    description: str = ""


class SnapshotManager:

    def __init__(self):
        self._snapshots: list[TimelineSnapshot] = []

    def create(self, state: TimelineProjectState, description: str = "") -> TimelineSnapshot:
        snap = TimelineSnapshot(
            snapshot_id=f"snap_{int(time.time() * 1000)}",
            timestamp=time.time(),
            event_states_snapshot={
                eid: {
                    "derivatives": {
                        # 类型化槽位序列化为 dict (Phase 3A)
                        k: (v.to_dict() if hasattr(v, "to_dict") else dict(v))
                        for k, v in es._data.items()
                    },
                    "patch_count": len(es.patches),  # 批次04 §四
                }
                for eid, es in state.event_states.items()
            },
            global_patches_count=len(state.global_patches),
            description=description,
        )
        self._snapshots.append(snap)
        if len(self._snapshots) > MAX_SNAPSHOTS:
            self._snapshots.pop(0)
        return snap

    def restore(self, state: TimelineProjectState, snapshot: TimelineSnapshot) -> TimelineProjectState:
        for eid, saved in snapshot.event_states_snapshot.items():
            es = state.get_event(eid)
            if es is None:
                continue
            # 兼容两种格式: 旧格式 {key: val, ...}，新格式 {"derivatives": {...}, "patch_count": N}
            derivs = saved.get("derivatives", saved) if isinstance(saved, dict) else {}
            es._data.clear()
            es._data.update(derivs)  # dict 形态由 _slot from_dict 迁移
            pc = saved.get("patch_count") if isinstance(saved, dict) else None
            if pc is not None and len(es.patches) > pc:
                es.patches = es.patches[:pc]
        return state

    def replay_from(self, state: TimelineProjectState, snapshot: TimelineSnapshot) -> TimelineProjectState:
        return self.restore(state, snapshot)

    @property
    def snapshot_count(self) -> int:
        return len(self._snapshots)

    def latest(self) -> TimelineSnapshot | None:
        return self._snapshots[-1] if self._snapshots else None
