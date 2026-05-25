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
                eid: dict(es.derivatives)
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
        for eid, derivs in snapshot.event_states_snapshot.items():
            es = state.get_event(eid)
            if es:
                es.derivatives.clear()
                es.derivatives.update(derivs)
        return state

    def replay_from(self, state: TimelineProjectState, snapshot: TimelineSnapshot) -> TimelineProjectState:
        return self.restore(state, snapshot)

    @property
    def snapshot_count(self) -> int:
        return len(self._snapshots)

    def latest(self) -> TimelineSnapshot | None:
        return self._snapshots[-1] if self._snapshots else None
