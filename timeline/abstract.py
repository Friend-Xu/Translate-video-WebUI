"""
统一消费协议 — SegmentView + TimelineView Protocol

所有消费端（API、WebUI、CLI）只依赖这两个 Protocol，
不直接 import timeline.ir 或 core.ir，实现新旧 IR 的透明切换。

Strangler Fig Expand 阶段 —— 新旧 IR 适配到同一协议。
"""

from __future__ import annotations
from typing import Protocol, runtime_checkable


@runtime_checkable
class SegmentView(Protocol):
    """单个时间轴片段的只读视图 — 消费端唯一可见的 segment 接口"""

    id: str
    start: float
    end: float
    speaker: str | None
    text: str
    type: str

    @property
    def duration(self) -> float: ...


@runtime_checkable
class TimelineView(Protocol):
    """完整时间轴的只读视图 — 消费端唯一可见的 timeline 接口"""

    segments: list[SegmentView]
    speakers: list[dict]  # [{"id": "SPEAKER_00", "name": "主持人"}, ...]

    def to_dict(self) -> dict:
        """序列化为 WebUI JSON 格式"""
        ...

    def to_project_ir(self):
        """迁移到 core.ir.project.TimelineProjectIR (新引擎格式)"""
        ...
