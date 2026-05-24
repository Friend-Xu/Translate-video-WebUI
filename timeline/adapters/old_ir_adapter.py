"""
旧 IR 适配器 — 将 timeline.ir.TimelineIR 包装为统一 TimelineView

实现 timeline.abstract 中的 SegmentView 和 TimelineView Protocol。
提供 to_project_ir() 桥接到新引擎。
"""

from __future__ import annotations
from timeline.ir import TimelineSegment, TimelineIR


class OldSegmentView:
    """包装 timeline.ir.TimelineSegment 为只读 SegmentView"""

    __slots__ = ("_seg",)

    def __init__(self, segment: TimelineSegment):
        self._seg = segment

    @property
    def id(self) -> str:
        return self._seg.id

    @property
    def start(self) -> float:
        return self._seg.start

    @property
    def end(self) -> float:
        return self._seg.end

    @property
    def speaker(self) -> str | None:
        return self._seg.speaker

    @property
    def text(self) -> str:
        return self._seg.text

    @property
    def type(self) -> str:
        return self._seg.type

    @property
    def duration(self) -> float:
        return self._seg.duration

    def to_dict(self) -> dict:
        return self._seg.to_dict()


class OldTimelineView:
    """包装 timeline.ir.TimelineIR 为 TimelineView"""

    __slots__ = ("_ir", "_segments", "_speakers")

    def __init__(self, ir: TimelineIR):
        self._ir = ir
        self._segments = [OldSegmentView(seg) for seg in ir.timeline]
        self._speakers = self._build_speakers()

    @property
    def segments(self) -> list[OldSegmentView]:
        return self._segments

    @property
    def speakers(self) -> list[dict]:
        return self._speakers

    def _build_speakers(self) -> list[dict]:
        result = []
        for spk_id, entry in self._ir.speaker_map.items():
            result.append({
                "id": spk_id,
                "name": entry.alias or spk_id,
                "voice_id": entry.voice_id,
            })
        for spk_id in self._ir.speakers:
            if spk_id not in self._ir.speaker_map:
                result.append({"id": spk_id, "name": spk_id})
        return result

    def to_dict(self) -> dict:
        return self._ir.to_dict()

    def to_project_ir(self):
        """旧 IR → 新 IR (core.ir.project.TimelineProjectIR)"""
        from timeline.fusion import to_project_ir
        return to_project_ir(self._ir)
