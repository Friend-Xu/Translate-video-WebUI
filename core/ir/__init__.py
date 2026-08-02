"""core/ir — 纯不可变 IR 数据定义层

零外部依赖，零 Pydantic runtime，零 GPU 触发。
所有 dataclass 均为 frozen=True。
"""
from core.ir.timeline_event import TimelineEventIR
from core.ir.speaker import SpeakerNodeIR
from core.ir.project import TimelineProjectIR

__all__ = [
    "TimelineEventIR",
    "SpeakerNodeIR",
    "TimelineProjectIR",
]
