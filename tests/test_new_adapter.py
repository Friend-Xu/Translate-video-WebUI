"""test_new_adapter — NewTimelineView 基于 core.runtime"""
from timeline.adapters.new_ir_adapter import NewTimelineView, NewSegmentView


class TestNewSegmentView:
    def test_basic(self):
        v = NewSegmentView({"id": "e1", "start": 0.0, "end": 2.5,
                            "speaker": "SPEAKER_00", "text": "Hello", "source": "asr"})
        assert v.id == "e1"
        assert v.start == 0.0
        assert v.end == 2.5
        assert v.speaker == "SPEAKER_00"
        assert v.text == "Hello"
        assert v.duration == 2.5

    def test_to_dict(self):
        v = NewSegmentView({"id": "e1", "start": 0.0, "end": 1.0,
                            "text": "Hi", "source": "asr"})
        d = v.to_dict()
        assert d["id"] == "e1"


class TestNewTimelineView:
    def test_segments(self, sample_project):
        from core.runtime.project_state import TimelineProjectState
        state = TimelineProjectState(sample_project)
        v = NewTimelineView(state)
        assert len(v.segments) == 3
        assert "evt_001" in {s.id for s in v.segments}

    def test_speakers(self, sample_project):
        from core.runtime.project_state import TimelineProjectState
        state = TimelineProjectState(sample_project)
        v = NewTimelineView(state)
        assert len(v.speakers) == 2

    def test_to_dict(self, sample_project):
        from core.runtime.project_state import TimelineProjectState
        state = TimelineProjectState(sample_project)
        v = NewTimelineView(state)
        d = v.to_dict()
        assert d["version"] == "2.0"
        assert len(d["segments"]) == 3

    def test_to_project_ir_zero_overhead(self, sample_project):
        from core.runtime.project_state import TimelineProjectState
        state = TimelineProjectState(sample_project)
        v = NewTimelineView(state)
        assert v.to_project_ir() is state.ir
