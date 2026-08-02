"""
TimelineProjectIR — 不可变项目容器

events 和 speakers 以 dict 索引，O(1) 按 ID 查找。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from core.ir.timeline_event import TimelineEventIR
from core.ir.speaker import SpeakerNodeIR
from core.ir.version import SCHEMA_VERSION, IR_VERSION


@dataclass(frozen=True)
class TimelineProjectIR:
    """不可变项目容器 — 整个时间轴的编译时快照。

    events:  event_id → TimelineEventIR
    speakers: speaker_id → SpeakerNodeIR
    """
    events: dict[str, TimelineEventIR] = field(default_factory=dict)
    speakers: dict[str, SpeakerNodeIR] = field(default_factory=dict)
    # v2.1: 全局元信息
    schema_version: str = SCHEMA_VERSION
    ir_version: str = IR_VERSION
    source_video: str | None = None
    audio_sample_rate: int | None = None
    language: str | None = None
    # 翻译引擎重构 Step 2: 预处理产出的翻译圣经 (TranslationBible.to_dict())
    translation_bible: dict = field(default_factory=dict)

    @property
    def event_list(self) -> list[TimelineEventIR]:
        """按 start 时间排序的事件列表"""
        return sorted(self.events.values(), key=lambda e: e.start)

    @property
    def total_duration(self) -> float:
        if not self.events:
            return 0.0
        return max(e.end for e in self.events.values())
