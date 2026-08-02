"""
短时长碎片合并契约测试 (架构收束补丁 — Json_Convert_Srt min_duration 约束等价物)

SemanticMergePass 阶段二: 事件时长 < min_duration → 合并到相邻目标。
覆盖: 同 speaker / split_from 回源 / 边界段 / 间隔过大保留 / 链式 / 单事件 / 阶段一回归。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest

from core.ir.project import TimelineProjectIR
from core.ir.timeline_event import TimelineEventIR
from core.runtime.project_state import TimelineProjectState
from core.passes.semantic_merge_pass import SemanticMergePass


def _mk_state(events: list[dict]) -> TimelineProjectState:
    ir = TimelineProjectIR(events={
        e["id"]: TimelineEventIR(
            id=e["id"], start=e["start"], end=e["end"],
            text_ref=e.get("text", ""), speaker_ref=e.get("speaker"),
        )
        for e in events
    })
    state = TimelineProjectState(ir)
    for e in events:
        if e.get("split_from"):
            state.get_event(e["id"]).meta["split_from"] = e["split_from"]
    return state


def _ids(state) -> set[str]:
    return set(state.event_states.keys())


class TestShortFragmentMerge:
    def test_same_speaker_fragment_merged(self):
        """同 speaker 短碎片 → 合并到相邻, 碎片消失"""
        st = _mk_state([
            {"id": "a", "start": 0.0, "end": 4.0, "text": "长句内容", "speaker": "S1"},
            {"id": "b", "start": 4.2, "end": 5.0, "text": "短句", "speaker": "S1"},
        ])
        SemanticMergePass().apply(st)
        assert "b" not in _ids(st)
        es = st.get_event("a")
        assert es.end == 5.0
        assert "短句" in es.ir.text_ref

    def test_split_from_fragment_returns_to_source(self):
        """说话人拆分产物 (meta.split_from) → 合并回源事件"""
        st = _mk_state([
            {"id": "evt_004", "start": 10.0, "end": 20.0, "text": "主句", "speaker": "S1"},
            {"id": "evt_004_spk00", "start": 10.0, "end": 10.8, "text": "",
             "speaker": "S2", "split_from": "evt_004"},
        ])
        SemanticMergePass().apply(st)
        assert "evt_004_spk00" not in _ids(st)
        assert st.get_event("evt_004") is not None

    def test_first_event_fragment_merges_to_next(self):
        """开头短段 → 合并到后一个"""
        st = _mk_state([
            {"id": "a", "start": 0.0, "end": 0.9, "text": "短", "speaker": "S1"},
            {"id": "b", "start": 1.0, "end": 5.0, "text": "长句", "speaker": "S2"},
        ])
        SemanticMergePass().apply(st)
        assert "a" not in _ids(st)
        assert st.get_event("b") is not None

    def test_isolated_fragment_kept_when_gap_too_large(self):
        """孤悬短段 (间隔 > max_gap) 不合并 — 宁缺毋滥"""
        st = _mk_state([
            {"id": "a", "start": 0.0, "end": 4.0, "text": "长句", "speaker": "S1"},
            {"id": "b", "start": 20.0, "end": 20.8, "text": "孤悬", "speaker": "S1"},
        ])
        SemanticMergePass().apply(st)
        assert "b" in _ids(st)

    def test_chain_merge_until_min_duration(self):
        """链式: 合并后目标仍短 → 继续合并到更早事件"""
        st = _mk_state([
            {"id": "a", "start": 0.0, "end": 6.0, "text": "长句甲", "speaker": "S1"},
            {"id": "b", "start": 6.2, "end": 7.0, "text": "中句", "speaker": "S1"},
            {"id": "c", "start": 7.2, "end": 7.6, "text": "短句", "speaker": "S1"},
        ])
        SemanticMergePass().apply(st)
        # b (0.8s) 合并到 a 或 c; 若 b 并入 a 后 a 足够长, c 单独并入 a/b
        assert "c" not in _ids(st) or "b" not in _ids(st)
        for eid in _ids(st):
            es = st.get_event(eid)
            assert (es.end - es.start) >= 1.5

    def test_single_event_untouched(self):
        st = _mk_state([
            {"id": "a", "start": 0.0, "end": 0.8, "text": "短", "speaker": "S1"},
        ])
        SemanticMergePass().apply(st)
        assert _ids(st) == {"a"}

    def test_diff_speaker_uses_nearest(self):
        """无同 speaker 相邻 → 最近相邻合并 (间隔合法)"""
        st = _mk_state([
            {"id": "a", "start": 0.0, "end": 4.0, "text": "长句", "speaker": "S1"},
            {"id": "b", "start": 4.2, "end": 5.0, "text": "碎片", "speaker": "S2"},
        ])
        SemanticMergePass().apply(st)
        assert "b" not in _ids(st)

    def test_stage_one_still_works(self):
        """阶段一 (同 speaker 短间隔合并) 回归"""
        st = _mk_state([
            {"id": "a", "start": 0.0, "end": 2.0, "text": "你好", "speaker": "S1"},
            {"id": "b", "start": 2.1, "end": 4.0, "text": "世界", "speaker": "S1"},
        ])
        SemanticMergePass().apply(st)
        assert "b" not in _ids(st)

    def test_normal_duration_untouched(self):
        """正常时长事件不受影响"""
        st = _mk_state([
            {"id": "a", "start": 0.0, "end": 3.0, "text": "正常", "speaker": "S1"},
            {"id": "b", "start": 3.5, "end": 6.0, "text": "正常二", "speaker": "S1"},
        ])
        SemanticMergePass().apply(st)
        assert _ids(st) == {"a", "b"}

    def test_overlapping_fragment_merged(self):
        """重叠短碎片 (说话人重叠) 也合并"""
        st = _mk_state([
            {"id": "a", "start": 0.0, "end": 5.0, "text": "长句", "speaker": "S1"},
            {"id": "b", "start": 1.0, "end": 1.5, "text": "重叠", "speaker": "S1"},
        ])
        SemanticMergePass().apply(st)
        assert "b" not in _ids(st)
