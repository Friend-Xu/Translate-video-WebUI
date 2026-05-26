"""
TimelineIndex — 多维 O(1) 索引

Pass 执行期间频繁按 speaker/time/id 查找，避免每次 O(n) 遍历。
"""
from __future__ import annotations
from core.runtime.project_state import TimelineProjectState
from core.runtime.event_state import TimelineEventState


class TimelineIndex:
    """O(1) 多维查找索引。"""

    def __init__(self, state: TimelineProjectState):
        self.by_id: dict[str, TimelineEventState] = state.event_states
        self.by_speaker: dict[str, list[TimelineEventState]] = {}
        self.by_time: list[TimelineEventState] = state.sorted_events()
        self._build_speaker_index(state)

    def _build_speaker_index(self, state: TimelineProjectState) -> None:
        for es in state.event_states.values():
            spk = es.speaker_ref
            if spk:
                self.by_speaker.setdefault(spk, []).append(es)

    def events_in_range(
        self, start: float, end: float
    ) -> list[TimelineEventState]:
        """返回 [start, end] 内的所有 events"""
        return [e for e in self.by_time if e.start < end and e.end > start]

    def adjacent(
        self, event_id: str
    ) -> tuple[TimelineEventState | None, TimelineEventState | None]:
        """返回前一个和后一个 event"""
        evt = self.by_id.get(event_id)
        if evt is None:
            return None, None
        for i, e in enumerate(self.by_time):
            if e.id == event_id:
                prev_evt = self.by_time[i - 1] if i > 0 else None
                next_evt = self.by_time[i + 1] if i < len(self.by_time) - 1 else None
                return prev_evt, next_evt
        return None, None
