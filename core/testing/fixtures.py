"""
测试数据工厂 — 最小化 ProjectState / Patch / Event 构造 (设计文档 §6.3)
"""
from __future__ import annotations
from core.ir.timeline_event import TimelineEventIR
from core.ir.speaker import SpeakerNodeIR
from core.ir.project import TimelineProjectIR
from core.runtime.project_state import TimelineProjectState
from core.runtime.patch import Patch

MINIMAL_3_EVENT_SEGMENTS = [
    {"start": 0.0, "end": 1.5, "text": "Hello world", "speaker": "SPEAKER_00"},
    {"start": 2.0, "end": 3.0, "text": "How are you", "speaker": "SPEAKER_00"},
    {"start": 3.5, "end": 5.0, "text": "I am fine thank you", "speaker": "SPEAKER_01"},
]


def make_event(id: str, start: float, end: float, text: str, speaker: str | None = None):
    return TimelineEventIR(id=id, start=start, end=end, speaker_ref=speaker, text_ref=text)


def make_project(events: dict, speakers: dict | None = None) -> TimelineProjectIR:
    return TimelineProjectIR(events=events, speakers=speakers or {})


def make_state(events: dict, speakers: dict | None = None) -> TimelineProjectState:
    return TimelineProjectState(make_project(events, speakers))


def make_patch(id: str, target: str, op: str = "replace", value: dict | None = None):
    return Patch(id=id, target_id=target, op=op, value=value or {}, author="test")
