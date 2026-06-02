"""core/ir — 纯不可变 IR 数据定义层

零外部依赖，零 Pydantic runtime，零 GPU 触发。
所有 dataclass 均为 frozen=True。

v2.1: 新增 TimelineIR 中间层 + 版本常量。
"""
from core.ir.timeline_event import TimelineEventIR
from core.ir.speaker import SpeakerNodeIR
from core.ir.project import TimelineProjectIR
from core.ir.timeline import TimelineIR

__all__ = [
    "TimelineEventIR",
    "SpeakerNodeIR",
    "TimelineProjectIR",
    "TimelineIR",
]
