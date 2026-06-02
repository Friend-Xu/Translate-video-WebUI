"""
契约测试 — Pass I/O 验证 IR 引用和 event 一致性 (批次7)
"""
import pytest
import os
import tempfile
from core.passes import ASRToIRPass, SemanticMergePass, SRTExportPass
from core.runtime.synthesis import SynthesisEngine
from core.runtime.project_state import TimelineProjectState
from core.ir.project import TimelineProjectIR
from core.ir.timeline_event import TimelineEventIR
from core.ir.speaker import SpeakerNodeIR


@pytest.mark.schema
class TestPassIO:

    def _make_state(self) -> TimelineProjectState:
        evts = {
            "evt_001": TimelineEventIR(id="evt_001", start=0.0, end=1.0, speaker_ref="S1", text_ref="hello"),
            "evt_002": TimelineEventIR(id="evt_002", start=1.0, end=2.0, speaker_ref="S2", text_ref="world"),
        }
        spks = {"S1": SpeakerNodeIR(id="S1"), "S2": SpeakerNodeIR(id="S2")}
        return TimelineProjectState(TimelineProjectIR(events=evts, speakers=spks))

    def test_asr_to_ir_creates_events(self):
        segs = [
            {"start": 0.0, "end": 1.0, "text": "hello", "speaker": "S1"},
            {"start": 1.5, "end": 2.0, "text": "world", "speaker": "S2"},
        ]
        state = ASRToIRPass(segments=segs).apply()
        assert len(state.event_states) == 2

    def test_semantic_merge_preserves_ir_ref(self):
        state = self._make_state()
        ir_before = state.ir
        merged = SemanticMergePass(gap_threshold=0.3).apply(state)
        assert merged.ir is ir_before

    def test_srt_export_preserves_state(self):
        state = self._make_state()
        tmp = os.path.join(tempfile.gettempdir(), "test_contract.srt")
        try:
            result = SRTExportPass(output_path=tmp).apply(state)
            assert result.ir is state.ir
        finally:
            if os.path.isfile(tmp):
                os.unlink(tmp)

    def test_synthesis_after_passes(self):
        state = self._make_state()
        state.get_event("evt_001").translation["text"] = "ni hao"
        state.get_event("evt_002").translation["text"] = "shi jie"
        rendered = SynthesisEngine().render_all(state)
        assert len(rendered) == 2
