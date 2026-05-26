"""test_old_adapter — OldTimelineView 包装正确性"""
from timeline.adapters.old_ir_adapter import OldTimelineView, OldSegmentView


class TestOldSegmentView:
    def test_basic(self, sample_timeline_ir):
        seg = sample_timeline_ir.timeline[0]
        v = OldSegmentView(seg)
        assert v.id == "seg_001"
        assert v.start == 0.0
        assert v.end == 2.5
        assert v.speaker == "SPEAKER_00"
        assert v.text == "Hello world"
        assert v.type == "speech"
        assert v.duration == 2.5

    def test_to_dict(self, sample_timeline_ir):
        seg = sample_timeline_ir.timeline[0]
        v = OldSegmentView(seg)
        d = v.to_dict()
        assert d["id"] == "seg_001"


class TestOldTimelineView:
    def test_segments(self, sample_timeline_ir):
        v = OldTimelineView(sample_timeline_ir)
        assert len(v.segments) == 3
        assert v.segments[0].text == "Hello world"

    def test_speakers(self, sample_timeline_ir):
        v = OldTimelineView(sample_timeline_ir)
        assert len(v.speakers) >= 2
        ids = {s["id"] for s in v.speakers}
        assert "SPEAKER_00" in ids

    def test_to_dict(self, sample_timeline_ir):
        v = OldTimelineView(sample_timeline_ir)
        d = v.to_dict()
        assert d["audio_id"] == "test_audio"

    def test_to_project_ir(self, sample_timeline_ir):
        v = OldTimelineView(sample_timeline_ir)
        proj = v.to_project_ir()
        assert len(proj.events) == 3
        assert proj.total_duration == 8.0
