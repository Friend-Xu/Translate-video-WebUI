"""
TimelineProjectIR — 不可变项目容器

events 和 speakers 以 dict 索引，O(1) 按 ID 查找。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from core.ir.timeline_event import TimelineEventIR
from core.ir.speaker import SpeakerNodeIR


@dataclass(frozen=True)
class TimelineProjectIR:
    """不可变项目容器 — 整个时间轴的编译时快照。

    events:  event_id → TimelineEventIR
    speakers: speaker_id → SpeakerNodeIR
    """
    events: dict[str, TimelineEventIR] = field(default_factory=dict)
    speakers: dict[str, SpeakerNodeIR] = field(default_factory=dict)

    @property
    def event_list(self) -> list[TimelineEventIR]:
        """按 start 时间排序的事件列表"""
        return sorted(self.events.values(), key=lambda e: e.start)

    @property
    def total_duration(self) -> float:
        if not self.events:
            return 0.0
        return max(e.end for e in self.events.values())
