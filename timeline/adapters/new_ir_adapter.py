"""
新 IR 适配器 — 将 core.runtime 合成结果包装为统一 TimelineView

基于 SynthesisEngine.render() 输出构建 SegmentView，
直接持有 TimelineProjectState 引用，to_project_ir() 零开销。
"""

from __future__ import annotations
from core.runtime.project_state import TimelineProjectState
from core.runtime.synthesis import SynthesisEngine


class NewSegmentView:
    """基于 SynthesisEngine.render() dict 输出的只读 SegmentView"""

    __slots__ = ("_data",)

    def __init__(self, data: dict):
        self._data = data

    @property
    def id(self) -> str:
        return self._data["id"]

    @property
    def start(self) -> float:
        return self._data["start"]

    @property
    def end(self) -> float:
        return self._data["end"]

    @property
    def speaker(self) -> str | None:
        return self._data.get("speaker")

    @property
    def text(self) -> str:
        return self._data.get("text", "")

    @property
    def type(self) -> str:
        return self._data.get("type", "speech")

    @property
    def duration(self) -> float:
        return self._data["end"] - self._data["start"]

    def to_dict(self) -> dict:
        return dict(self._data)


class NewTimelineView:
    """包装 TimelineProjectState + SynthesisEngine 为 TimelineView"""

    __slots__ = ("_state", "_synth", "_segments", "_speakers")

    def __init__(self, state: TimelineProjectState, synth: SynthesisEngine | None = None):
        self._state = state
        self._synth = synth or SynthesisEngine()
        rendered = self._synth.render_all(state)
        self._segments = [NewSegmentView(r) for r in rendered]
        self._speakers = self._synth.render_speakers(state)

    @property
    def segments(self) -> list[NewSegmentView]:
        return self._segments

    @property
    def speakers(self) -> list[dict]:
        return self._speakers

    def to_dict(self) -> dict:
        return {
            "segments": [s.to_dict() for s in self._segments],
            "speakers": self._speakers,
            "version": "2.0",
        }

    def to_project_ir(self):
        """零开销 — 直接返回持有的 TimelineProjectIR"""
        return self._state.ir
