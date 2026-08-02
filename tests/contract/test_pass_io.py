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

    def test_semantic_merge_actually_merges(self):
        """Phase1 空壳修复: SEGMENT_MERGE 结构性合并 — 同 speaker 短间隔事件合一。

        旧实现用 legacy MERGE (只写 _merged_from 标注), 合并无实际效果。
        """
        evts = {
            "evt_001": TimelineEventIR(id="evt_001", start=0.0, end=1.0, speaker_ref="S1", text_ref="hello"),
            "evt_002": TimelineEventIR(id="evt_002", start=1.2, end=2.0, speaker_ref="S1", text_ref="world"),
        }
        state = TimelineProjectState(TimelineProjectIR(events=evts))
        # ASR pass 写入的 words + language (segment_merge 从 words 派生 text)
        for es in state.event_states.values():
            es.asr.language = "en"
            es.asr.words = [
                {"word": w, "start": es.start + i * 0.05, "end": es.start + (i + 1) * 0.05}
                for i, w in enumerate(("hello" if es.id == "evt_001" else "world").split())
            ]

        SemanticMergePass(gap_threshold=0.3).apply(state)

        # 两个事件合并为一个: evt_002 被删除, 文本从 words 派生
        assert "evt_002" not in state.event_states
        assert "evt_002" not in state.ir.events
        assert len(state.event_states) == 1
        es = state.get_event("evt_001")
        assert es.ir.end == 2.0                # 时间范围取并集
        assert "hello world" in es.ir.text_ref  # words 合并派生
        assert es.ir.speaker_ref == "S1"

    def test_semantic_merge_no_merge_across_speakers(self):
        """不同 speaker 不合并 (即使间隔小于阈值; 段长均 >= min_duration, 阶段二不触发)。"""
        evts = {
            "evt_001": TimelineEventIR(id="evt_001", start=0.0, end=2.5, speaker_ref="S1", text_ref="hello"),
            "evt_002": TimelineEventIR(id="evt_002", start=2.7, end=4.5, speaker_ref="S2", text_ref="world"),
        }
        state = TimelineProjectState(TimelineProjectIR(events=evts))
        SemanticMergePass(gap_threshold=0.3).apply(state)
        assert len(state.event_states) == 2

    def test_semantic_merge_marks_old_translation_stale(self):
        """合并改变源文本 → 旧译文失效置 flag (禁止兜底下保留陈旧译文)。"""
        evts = {
            "evt_001": TimelineEventIR(id="evt_001", start=0.0, end=1.0, speaker_ref="S1", text_ref="hello"),
            "evt_002": TimelineEventIR(id="evt_002", start=1.2, end=2.0, speaker_ref="S1", text_ref="world"),
        }
        state = TimelineProjectState(TimelineProjectIR(events=evts))
        for es in state.event_states.values():
            es.translation.text = "旧译文"
        SemanticMergePass(gap_threshold=0.3).apply(state)
        es = state.get_event("evt_001")
        assert "needs_retranslate" in es.review.flags
        assert es.review.needs_human_review is True

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
        state.get_event("evt_001").translation.text = "ni hao"
        state.get_event("evt_002").translation.text = "shi jie"
        rendered = SynthesisEngine().render_all(state)
        assert len(rendered) == 2
