"""
Phase 3 — Runtime 引擎单元测试 (P0)

覆盖: Patch, PatchEngine, SynthesisEngine, TimelineEventState, TimelineProjectState
"""

import pytest
from core.ir.timeline_event import TimelineEventIR
from core.ir.project import TimelineProjectIR
from core.runtime.patch import Patch
from core.runtime.event_state import TimelineEventState
from core.runtime.project_state import TimelineProjectState
from core.runtime.patch_engine import PatchEngine
from core.runtime.synthesis import SynthesisEngine


# ═══════════════════════════════════════════════════════════
# Patch
# ═══════════════════════════════════════════════════════════

class TestPatch:
    """Patch — runtime 层 mutation 原语"""

    def test_construct_normal(self):
        p = Patch(id="patch_001", target_id="evt_001", op="replace",
                  value={"speaker": "SPEAKER_00"})
        assert p.id == "patch_001"
        assert p.target_id == "evt_001"
        assert p.op == "replace"
        assert p.value == {"speaker": "SPEAKER_00"}

    def test_timestamp_auto_set(self):
        p = Patch(id="p1", target_id="e1", op="replace", value={})
        assert p.timestamp > 0.0

    def test_timestamp_custom(self):
        p = Patch(id="p1", target_id="e1", op="replace", value={}, timestamp=100.0)
        assert p.timestamp == 100.0

    def test_author_default_system(self):
        p = Patch(id="p1", target_id="e1", op="replace", value={})
        assert p.author == "system"

    def test_author_custom(self):
        p = Patch(id="p1", target_id="e1", op="replace", value={}, author="user")
        assert p.author == "user"

    def test_author_ai(self):
        p = Patch(id="p1", target_id="e1", op="replace", value={}, author="ai")
        assert p.author == "ai"


# ═══════════════════════════════════════════════════════════
# TimelineEventState
# ═══════════════════════════════════════════════════════════

class TestTimelineEventState:
    """TimelineEventState — 事件运行时状态"""

    def test_holds_ir_reference(self):
        ir = TimelineEventIR(id="e1", start=0.0, end=1.0, speaker_ref=None, text_ref="hello")
        es = TimelineEventState(ir)
        assert es.ir is ir
        assert es.id == "e1"
        assert es.start == 0.0
        assert es.end == 1.0
        assert es.speaker_ref is None

    def test_derivatives_initially_empty(self):
        ir = TimelineEventIR(id="e1", start=0.0, end=1.0, speaker_ref=None, text_ref="x")
        es = TimelineEventState(ir)
        assert es._data == {}

    def test_patches_initially_empty(self):
        ir = TimelineEventIR(id="e1", start=0.0, end=1.0, speaker_ref=None, text_ref="x")
        es = TimelineEventState(ir)
        assert es.patches == []

    def test_add_patch_sorted_by_timestamp(self):
        ir = TimelineEventIR(id="e1", start=0.0, end=1.0, speaker_ref=None, text_ref="x")
        es = TimelineEventState(ir)
        p2 = Patch(id="p2", target_id="e1", op="replace", value={}, timestamp=200.0)
        p1 = Patch(id="p1", target_id="e1", op="replace", value={}, timestamp=100.0)
        p3 = Patch(id="p3", target_id="e1", op="replace", value={}, timestamp=150.0)
        es.add_patch(p2)
        es.add_patch(p1)
        es.add_patch(p3)
        assert [p.id for p in es.patches] == ["p1", "p3", "p2"]


# ═══════════════════════════════════════════════════════════
# TimelineProjectState
# ═══════════════════════════════════════════════════════════

class TestTimelineProjectState:
    """TimelineProjectState — 项目级运行时状态"""

    def test_construct_from_ir(self, sample_project):
        state = TimelineProjectState(sample_project)
        assert state.ir is sample_project
        assert len(state.event_states) == 3

    def test_get_event(self, sample_project):
        state = TimelineProjectState(sample_project)
        es = state.get_event("evt_001")
        assert es is not None
        assert es.id == "evt_001"
        assert es.ir.text_ref == "Hello world"

    def test_get_event_missing(self, sample_project):
        state = TimelineProjectState(sample_project)
        assert state.get_event("nonexistent") is None

    def test_sorted_events(self, sample_project):
        state = TimelineProjectState(sample_project)
        sorted_es = state.sorted_events()
        assert [es.id for es in sorted_es] == ["evt_001", "evt_002", "evt_003"]

    def test_add_global_patch(self, sample_project):
        state = TimelineProjectState(sample_project)
        p = Patch(id="gp1", target_id="evt_001", op="replace", value={})
        state.add_global_patch(p)
        assert len(state.global_patches) == 1
        assert state.global_patches[0].id == "gp1"


# ═══════════════════════════════════════════════════════════
# PatchEngine
# ═══════════════════════════════════════════════════════════

class TestPatchEngine:
    """PatchEngine — Patch 执行器"""

    @pytest.fixture
    def engine(self):
        return PatchEngine()

    @pytest.fixture
    def state(self, sample_project):
        return TimelineProjectState(sample_project)

    # ── replace ──

    def test_replace_merges_value(self, engine, state):
        p = Patch(id="p1", target_id="evt_001", op="replace",
                  value={"translation": "hello"})
        diff = engine.apply(state, p)
        assert diff["status"] == "applied"
        assert diff["op"] == "replace"
        es = state.get_event("evt_001")
        assert es.translation.text == "hello"

    def test_replace_target_not_found(self, engine, state):
        p = Patch(id="p1", target_id="evt_999", op="replace", value={})
        diff = engine.apply(state, p)
        assert diff["status"] == "error"
        assert "not found" in diff["reason"]

    def test_replace_records_before_after(self, engine, state):
        es = state.get_event("evt_001")
        es.translation.text = "old"
        p = Patch(id="p1", target_id="evt_001", op="replace",
                  value={"translation": {"text": "new"}})
        diff = engine.apply(state, p)
        assert diff["before"]["translation"]["text"] == "old"
        assert es.translation.text == "new"

    # ── merge ──

    def test_merge_two_events(self, engine, state):
        p = Patch(id="p1", target_id="evt_001", op="merge",
                  value={"target_ids": ["evt_001", "evt_002"]})
        diff = engine.apply(state, p)
        assert diff["status"] == "applied"
        assert diff["op"] == "merge"
        es = state.get_event("evt_001")
        assert es.meta["merged_from"] == ["evt_002"]

    def test_merge_requires_2_targets(self, engine, state):
        p = Patch(id="p1", target_id="evt_001", op="merge",
                  value={"target_ids": ["evt_001"]})
        diff = engine.apply(state, p)
        assert diff["status"] == "error"
        assert ">= 2" in diff["reason"]

    def test_merge_primary_not_found(self, engine, state):
        p = Patch(id="p1", target_id="evt_999", op="merge",
                  value={"target_ids": ["evt_999", "evt_001"]})
        diff = engine.apply(state, p)
        assert diff["status"] == "error"

    def test_merge_sets_merged_end(self, engine, state):
        p = Patch(id="p1", target_id="evt_001", op="merge",
                  value={"target_ids": ["evt_001", "evt_003"]})
        engine.apply(state, p)
        es = state.get_event("evt_001")
        assert es.meta["merged_end"] == 8.0

    # ── split ──

    def test_split_records_split_point(self, engine, state):
        p = Patch(id="p1", target_id="evt_001", op="split",
                  value={"at": 1.0})
        diff = engine.apply(state, p)
        assert diff["status"] == "applied"
        assert diff["op"] == "split"
        assert diff["split_at"] == 1.0
        es = state.get_event("evt_001")
        assert es.meta["split_at"] == 1.0

    def test_split_target_not_found(self, engine, state):
        p = Patch(id="p1", target_id="evt_999", op="split",
                  value={"at": 1.0})
        diff = engine.apply(state, p)
        assert diff["status"] == "error"

    # ── propagate (op 已删, Phase 3B 无生产调用方) ──

    def test_propagate_op_rejected(self, engine, state):
        """PROPAGATE 已从 dispatch 移除 — 未知 op 响亮报错。"""
        p = Patch(id="p1", target_id="evt_001", op="propagate",
                  value={"to_ids": ["evt_002"], "key": "mood", "val": "happy"})
        diff = engine.apply(state, p)
        assert diff["status"] == "error"

    # ── unknown op ──

    def test_unknown_op(self, engine, state):
        p = Patch(id="p1", target_id="evt_001", op="invalid_op", value={})
        diff = engine.apply(state, p)
        assert diff["status"] == "error"
        assert "unknown op" in diff["reason"]

    # ── apply_many ──

    def test_apply_many(self, engine, state):
        p1 = Patch(id="p1", target_id="evt_001", op="replace",
                   value={"review": {"notes": "a"}})
        p2 = Patch(id="p2", target_id="evt_002", op="replace",
                   value={"review": {"notes": "b"}})
        diffs = engine.apply_many(state, [p1, p2])
        assert len(diffs) == 2
        assert all(d["status"] == "applied" for d in diffs)
        assert state.get_event("evt_001").review.notes == "a"
        assert state.get_event("evt_002").review.notes == "b"

    def test_apply_many_empty(self, engine, state):
        diffs = engine.apply_many(state, [])
        assert diffs == []


# ═══════════════════════════════════════════════════════════
# SynthesisEngine
# ═══════════════════════════════════════════════════════════

class TestSynthesisEngine:
    """SynthesisEngine — 纯函数渲染器"""

    @pytest.fixture
    def engine(self):
        return SynthesisEngine()

    @pytest.fixture
    def state(self, sample_project):
        return TimelineProjectState(sample_project)

    def test_render_returns_basic_fields(self, engine, state):
        es = state.get_event("evt_001")
        result = engine.render(es)
        assert result["id"] == "evt_001"
        assert result["start"] == 0.0
        assert result["end"] == 2.5
        assert result["speaker"] == "SPEAKER_00"
        assert result["text"] == "Hello world"
        assert result["source"] == "asr"

    def test_render_merges_derivatives(self, engine, state):
        es = state.get_event("evt_001")
        es.translation.text = "hello"
        es.emotion.emotion = "neutral"
        result = engine.render(es)
        assert result["translation"]["text"] == "hello"
        assert result["emotion"]["emotion"] == "neutral"

    def test_render_derivatives_override_ir(self, engine, state):
        """derivatives 覆盖同名字段"""
        es = state.get_event("evt_001")
        es.translation.text = "Modified text"
        result = engine.render(es)
        assert result["translation"]["text"] == "Modified text"

    def test_render_applies_replace_patches(self, engine, state):
        es = state.get_event("evt_001")
        p = Patch(id="p1", target_id="evt_001", op="replace",
                  value={"translation": {"text": "patched"}})
        es.add_patch(p)
        result = engine.render(es)
        assert result["translation"]["text"] == "patched"

    def test_render_patches_override_derivatives(self, engine, state):
        """patches 在 derivatives 之后叠加，后者覆盖前者"""
        es = state.get_event("evt_001")
        es.translation.text = "from_deriv"
        p = Patch(id="p1", target_id="evt_001", op="replace",
                  value={"translation": {"text": "from_patch"}})
        es.add_patch(p)
        result = engine.render(es)
        assert result["translation"]["text"] == "from_patch"

    def test_render_non_replace_patches_not_applied(self, engine, state):
        """非 replace 的 patches 不叠加到渲染输出"""
        es = state.get_event("evt_001")
        p = Patch(id="p1", target_id="evt_001", op="split", value={"at": 1.0})
        es.add_patch(p)
        result = engine.render(es)
        assert "meta" not in result

    def test_render_all(self, engine, state):
        results = engine.render_all(state)
        assert len(results) == 3
        ids = [r["id"] for r in results]
        assert ids == ["evt_001", "evt_002", "evt_003"]

    def test_render_speaker_stays_str_when_slot_set(self, engine, state):
        """E2E 修复: speaker 槽位 (dict) 不得覆盖基础字段 (ir.speaker_ref, str)。

        preprocess/llm_translation 用 {r["speaker"]} 集合 + dict key,
        speaker 变 dict 会 unhashable 崩溃。
        """
        es = state.get_event("evt_001")
        es.speaker.speaker_id = "SPEAKER_00"
        result = engine.render(es)
        assert isinstance(result["speaker"], str)
        assert result["speaker"] == "SPEAKER_00"

    def test_render_all_empty_state(self, engine):
        ir = TimelineProjectIR()
        state = TimelineProjectState(ir)
        assert engine.render_all(state) == []

    def test_render_speakers(self, engine, state):
        speakers = engine.render_speakers(state)
        assert len(speakers) == 2
        ids = {s["id"] for s in speakers}
        assert ids == {"SPEAKER_00", "SPEAKER_01"}

    def test_render_speakers_empty(self, engine):
        ir = TimelineProjectIR()
        state = TimelineProjectState(ir)
        assert engine.render_speakers(state) == []

    def test_patches_sorted_by_timestamp_in_render(self, engine, state):
        """多 patch 按 timestamp 顺序叠加"""
        es = state.get_event("evt_001")
        p_early = Patch(id="p1", target_id="evt_001", op="replace",
                        value={"translation": {"text": "red"}}, timestamp=100.0)
        p_late = Patch(id="p2", target_id="evt_001", op="replace",
                       value={"translation": {"text": "blue"}}, timestamp=200.0)
        es.add_patch(p_late)
        es.add_patch(p_early)
        result = engine.render(es)
        assert result["translation"]["text"] == "blue"

    def test_speaker_ref_none_in_render(self, engine):
        """speaker_ref 为 None 时，render 的 speaker 为 None"""
        ir = TimelineEventIR(id="e1", start=0.0, end=1.0, speaker_ref=None, text_ref="x")
        es = TimelineEventState(ir)
        result = engine.render(es)
        assert result["speaker"] is None
