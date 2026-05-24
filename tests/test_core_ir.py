"""
Phase 2 — 核心 IR 数据模型单元测试 (P0)

覆盖: TimelineEventIR, SpeakerNodeIR, TimelineProjectIR
"""

import pytest
from dataclasses import FrozenInstanceError
from core.ir.timeline_event import TimelineEventIR
from core.ir.speaker import SpeakerNodeIR
from core.ir.project import TimelineProjectIR


# ═══════════════════════════════════════════════════════════
# TimelineEventIR
# ═══════════════════════════════════════════════════════════

class TestTimelineEventIR:
    """TimelineEventIR — frozen dataclass, 5 字段"""

    def test_construct_normal(self):
        evt = TimelineEventIR(
            id="evt_001", start=0.0, end=2.5,
            speaker_ref="SPEAKER_00", text_ref="Hello world",
        )
        assert evt.id == "evt_001"
        assert evt.start == 0.0
        assert evt.end == 2.5
        assert evt.speaker_ref == "SPEAKER_00"
        assert evt.text_ref == "Hello world"

    def test_source_default(self):
        evt = TimelineEventIR(id="e1", start=0.0, end=1.0, speaker_ref=None, text_ref="test")
        assert evt.source == "asr"

    def test_source_custom(self):
        evt = TimelineEventIR(id="e1", start=0.0, end=1.0, speaker_ref=None, text_ref="t", source="manual")
        assert evt.source == "manual"

    def test_speaker_ref_none(self):
        evt = TimelineEventIR(id="e1", start=0.0, end=1.0, speaker_ref=None, text_ref="t")
        assert evt.speaker_ref is None

    def test_start_ge_end_raises(self):
        with pytest.raises(ValueError, match="start"):
            TimelineEventIR(id="e1", start=2.0, end=2.0, speaker_ref=None, text_ref="t")

    def test_start_gt_end_raises(self):
        with pytest.raises(ValueError):
            TimelineEventIR(id="e1", start=5.0, end=1.0, speaker_ref=None, text_ref="t")

    def test_frozen_immutable(self):
        evt = TimelineEventIR(id="e1", start=0.0, end=1.0, speaker_ref=None, text_ref="t")
        with pytest.raises(FrozenInstanceError):
            evt.start = 10.0  # type: ignore

    def test_equality(self):
        a = TimelineEventIR(id="e1", start=0.0, end=1.0, speaker_ref=None, text_ref="t")
        b = TimelineEventIR(id="e1", start=0.0, end=1.0, speaker_ref=None, text_ref="t")
        c = TimelineEventIR(id="e2", start=0.0, end=1.0, speaker_ref=None, text_ref="t")
        assert a == b
        assert a != c

    def test_start_zero_boundary(self):
        evt = TimelineEventIR(id="e1", start=0.0, end=1.0, speaker_ref=None, text_ref="t")
        assert evt.start == 0.0

    def test_tiny_duration(self):
        """极小 duration (1e-10) 合法"""
        evt = TimelineEventIR(id="e1", start=0.0, end=1e-10, speaker_ref=None, text_ref="t")
        assert evt.end - evt.start == 1e-10

    def test_negative_start(self):
        """start 为负数合法（不抛异常，由上层校验）"""
        evt = TimelineEventIR(id="e1", start=-1.0, end=5.0, speaker_ref=None, text_ref="t")
        assert evt.start == -1.0


# ═══════════════════════════════════════════════════════════
# SpeakerNodeIR
# ═══════════════════════════════════════════════════════════

class TestSpeakerNodeIR:
    """SpeakerNodeIR — frozen dataclass, 2 字段"""

    def test_construct_with_name(self):
        spk = SpeakerNodeIR(id="SPEAKER_00", name="主持人")
        assert spk.id == "SPEAKER_00"
        assert spk.name == "主持人"

    def test_construct_without_name(self):
        spk = SpeakerNodeIR(id="SPEAKER_01")
        assert spk.id == "SPEAKER_01"
        assert spk.name is None

    def test_name_default_none(self):
        spk = SpeakerNodeIR(id="S1")
        assert spk.name is None

    def test_frozen_immutable(self):
        spk = SpeakerNodeIR(id="S1", name="test")
        with pytest.raises(FrozenInstanceError):
            spk.name = "changed"  # type: ignore

    def test_equality(self):
        a = SpeakerNodeIR(id="S1", name="A")
        b = SpeakerNodeIR(id="S1", name="A")
        c = SpeakerNodeIR(id="S2", name="A")
        assert a == b
        assert a != c

    def test_name_none_equality(self):
        a = SpeakerNodeIR(id="S1")
        b = SpeakerNodeIR(id="S1")
        assert a == b


# ═══════════════════════════════════════════════════════════
# TimelineProjectIR
# ═══════════════════════════════════════════════════════════

class TestTimelineProjectIR:
    """TimelineProjectIR — frozen dataclass, events + speakers dict"""

    def test_empty_project(self):
        proj = TimelineProjectIR()
        assert proj.event_list == []
        assert proj.total_duration == 0.0
        assert proj.events == {}
        assert proj.speakers == {}

    def test_event_list_sorted_by_start(self, sample_events, sample_speakers):
        proj = TimelineProjectIR(events=sample_events, speakers=sample_speakers)
        ordered = proj.event_list
        assert len(ordered) == 3
        assert ordered[0].id == "evt_001"  # start=0.0
        assert ordered[1].id == "evt_002"  # start=3.0
        assert ordered[2].id == "evt_003"  # start=5.5

    def test_event_list_out_of_order_input(self):
        """输入顺序与 start 不一致时，event_list 仍按 start 排序"""
        e2 = TimelineEventIR(id="e2", start=3.0, end=5.0, speaker_ref=None, text_ref="b")
        e1 = TimelineEventIR(id="e1", start=0.0, end=2.0, speaker_ref=None, text_ref="a")
        proj = TimelineProjectIR(events={"e2": e2, "e1": e1})
        assert proj.event_list[0].id == "e1"
        assert proj.event_list[1].id == "e2"

    def test_total_duration(self, sample_events, sample_speakers):
        proj = TimelineProjectIR(events=sample_events, speakers=sample_speakers)
        assert proj.total_duration == 8.0

    def test_total_duration_single_event(self):
        evt = TimelineEventIR(id="e1", start=1.0, end=3.5, speaker_ref=None, text_ref="t")
        proj = TimelineProjectIR(events={"e1": evt})
        assert proj.total_duration == 3.5

    def test_events_dict_index(self, sample_project):
        evt = sample_project.events["evt_001"]
        assert evt.text_ref == "Hello world"

    def test_speakers_dict_index(self, sample_project):
        spk = sample_project.speakers["SPEAKER_00"]
        assert spk.name == "主持人"

    def test_frozen_immutable(self, sample_project):
        with pytest.raises(FrozenInstanceError):
            sample_project.events = {}  # type: ignore
