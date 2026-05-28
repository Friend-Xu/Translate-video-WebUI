"""批次12 §3.1: Pass 级别测试。

覆盖: ASRToIRPass, SRTExportPass
(LLMTranslationPass + TranslationQualityPass 需要真实 API key，推迟到集成测试)
"""
import os
import tempfile
import pytest
from core.passes.asr_to_ir_pass import ASRToIRPass
from core.passes.srt_export_pass import SRTExportPass
from core.ir import TimelineEventIR, SpeakerNodeIR, TimelineProjectIR
from core.runtime import TimelineProjectState, TimelineEventState


class TestASRToIRPass:
    """ASRToIRPass: segments → IR events。"""

    @pytest.fixture
    def sample_segments(self):
        return [
            {"start": 0.0, "end": 2.5, "text": "Hello world", "speaker": "SPK_1"},
            {"start": 2.5, "end": 5.0, "text": "Goodbye world", "speaker": "SPK_2"},
            {"start": 5.0, "end": 7.0, "text": "The end", "speaker": None},
        ]

    def test_segments_to_events(self, sample_segments):
        """segments 正确转换为 IR events"""
        pass_ = ASRToIRPass(segments=sample_segments)
        state = pass_.apply()

        assert len(state.event_states) == 3
        assert "evt_001" in state.event_states
        assert state.ir.events["evt_001"].start == 0.0
        assert state.ir.events["evt_001"].end == 2.5
        assert state.ir.events["evt_001"].text_ref == "Hello world"

    def test_speaker_assignments(self, sample_segments):
        """说话人正确映射到 IR speakers"""
        pass_ = ASRToIRPass(segments=sample_segments)
        state = pass_.apply()

        assert "SPK_1" in state.ir.speakers
        assert "SPK_2" in state.ir.speakers
        assert state.ir.events["evt_001"].speaker_ref == "SPK_1"

    def test_null_speaker_handled(self, sample_segments):
        """无说话人的 segment 正常处理"""
        pass_ = ASRToIRPass(segments=sample_segments)
        state = pass_.apply()
        assert state.ir.events["evt_003"].speaker_ref is None

    def test_empty_segments(self):
        """空 segments 返回空 state"""
        pass_ = ASRToIRPass(segments=[])
        state = pass_.apply()
        assert len(state.event_states) == 0

    def test_event_source_is_asr(self, sample_segments):
        """所有 event source 为 'asr'"""
        pass_ = ASRToIRPass(segments=sample_segments)
        state = pass_.apply()
        for es in state.event_states.values():
            evt = state.ir.events.get(es.id)
            assert evt is not None
            assert evt.source == "asr"

    def test_speaker_timeline_used(self, sample_segments):
        """speaker_timeline 参数传入后生效"""
        st = [("SPK_A", 0.0, 3.0, 0.9)]
        pass_ = ASRToIRPass(segments=sample_segments, speaker_timeline=st)
        state = pass_.apply()
        assert len(state.event_states) == 3


class TestSRTExportPass:
    """SRTExportPass: state → SRT 文件。"""

    @pytest.fixture
    def sample_state(self):
        ir = TimelineProjectIR(
            events={
                "evt_001": TimelineEventIR(
                    id="evt_001", start=0.0, end=2.5,
                    text_ref="Hello world", source="asr",
                ),
                "evt_002": TimelineEventIR(
                    id="evt_002", start=2.5, end=5.0,
                    text_ref="Goodbye world", source="asr",
                ),
            },
            speakers={},
        )
        state = TimelineProjectState(ir)
        state.event_states["evt_001"] = TimelineEventState(
            id="evt_001", derivatives={"translation": "Hello world"},
        )
        state.event_states["evt_002"] = TimelineEventState(
            id="evt_002", derivatives={"translation": "Goodbye world"},
        )
        return state

    def test_srt_output_format(self, sample_state):
        """SRT 输出格式正确"""
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "test.srt")
            pass_ = SRTExportPass(output_path=out)
            pass_.apply(sample_state)

            assert os.path.isfile(out)
            with open(out, "r", encoding="utf-8") as f:
                content = f.read()

            assert "Hello world" in content
            assert "00:00:00,000" in content
            assert "00:00:02,500" in content

    def test_srt_subtitle_numbering(self, sample_state):
        """SRT 字幕序号正确"""
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "test.srt")
            pass_ = SRTExportPass(output_path=out)
            pass_.apply(sample_state)

            with open(out, "r", encoding="utf-8") as f:
                content = f.read()

            blocks = content.strip().split("\n\n")
            assert len(blocks) == 2
            assert blocks[0].startswith("1\n")
            assert blocks[1].startswith("2\n")

    def test_srt_to_srt_time(self):
        """_to_srt_time 时间格式化正确"""
        from core.passes.srt_export_pass import SRTExportPass as SEP
        assert SEP._to_srt_time(0.0) == "00:00:00,000"
        assert SEP._to_srt_time(1.5) == "00:00:01,500"
        assert SEP._to_srt_time(3600.0) == "01:00:00,000"
        assert SEP._to_srt_time(3661.123) == "01:01:01,123"

    def test_srt_empty_output_path(self, sample_state):
        """空 output_path 不写文件但不出错"""
        pass_ = SRTExportPass(output_path="")
        result = pass_.apply(sample_state)
        assert result is not None
