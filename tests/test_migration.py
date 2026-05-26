"""test_migration — to_project_ir / from_project_ir 双向等价"""
from timeline.fusion import to_project_ir, from_project_ir


class TestMigration:
    def test_to_project_ir_events(self, sample_timeline_ir):
        proj = to_project_ir(sample_timeline_ir)
        assert len(proj.events) == 3
        assert proj.total_duration == 8.0

    def test_to_project_ir_speakers(self, sample_timeline_ir):
        proj = to_project_ir(sample_timeline_ir)
        assert "SPEAKER_00" in proj.speakers
        assert proj.speakers["SPEAKER_00"].name == "主持人"

    def test_to_project_ir_text_preserved(self, sample_timeline_ir):
        proj = to_project_ir(sample_timeline_ir)
        texts = {e.text_ref for e in proj.events.values()}
        assert "Hello world" in texts

    def test_roundtrip(self, sample_timeline_ir):
        proj = to_project_ir(sample_timeline_ir)
        ir2 = from_project_ir(proj)
        assert len(ir2.timeline) == 3
        assert ir2.timeline[0].text == "Hello world"

    def test_roundtrip_speakers(self, sample_timeline_ir):
        proj = to_project_ir(sample_timeline_ir)
        ir2 = from_project_ir(proj)
        assert "SPEAKER_00" in ir2.speakers

    def test_empty_timeline(self):
        from timeline.ir import TimelineIR
        proj = to_project_ir(TimelineIR(audio_id="empty"))
        assert len(proj.events) == 0

    def test_from_project_ir_empty(self):
        from core.ir.project import TimelineProjectIR
        ir = from_project_ir(TimelineProjectIR())
        assert ir.timeline == []

    def test_speaker_without_name(self):
        from timeline.ir import TimelineIR, TimelineSegment
        ir = TimelineIR(
            audio_id="test",
            timeline=[TimelineSegment(id="s1", speaker="S1", start=0.0, end=1.0, text="Hi")],
        )
        proj = to_project_ir(ir)
        assert proj.speakers["S1"].name is None
