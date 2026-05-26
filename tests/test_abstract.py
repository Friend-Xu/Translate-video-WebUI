"""test_abstract — Protocol 定义验证"""
from timeline.abstract import SegmentView, TimelineView
from timeline.adapters.old_ir_adapter import OldSegmentView, OldTimelineView
from timeline.adapters.new_ir_adapter import NewSegmentView, NewTimelineView


class TestProtocol:
    def test_old_segment_view_is_segment_view(self):
        from timeline.ir import TimelineSegment
        seg = TimelineSegment(id="s1", start=0.0, end=1.0, text="Hello")
        v = OldSegmentView(seg)
        assert isinstance(v, SegmentView)

    def test_old_timeline_view_is_timeline_view(self, sample_timeline_ir):
        v = OldTimelineView(sample_timeline_ir)
        assert isinstance(v, TimelineView)

    def test_new_segment_view_is_segment_view(self):
        v = NewSegmentView({"id": "e1", "start": 0.0, "end": 1.0, "speaker": "S1",
                            "text": "Hello", "source": "asr"})
        assert isinstance(v, SegmentView)

    def test_new_timeline_view_is_timeline_view(self, sample_project):
        from core.runtime.project_state import TimelineProjectState
        state = TimelineProjectState(sample_project)
        v = NewTimelineView(state)
        assert isinstance(v, TimelineView)

    def test_duration_property(self):
        from timeline.ir import TimelineSegment
        seg = TimelineSegment(id="s1", start=0.0, end=2.5)
        v = OldSegmentView(seg)
        assert v.duration == 2.5

    def test_segment_view_has_required_attrs(self):
        from timeline.ir import TimelineSegment
        seg = TimelineSegment(id="s1", start=0.0, end=1.0, text="Hello", speaker="S1")
        v = OldSegmentView(seg)
        assert v.id == "s1"
        assert v.start == 0.0
        assert v.end == 1.0
        assert v.text == "Hello"
        assert v.type == "speech"
