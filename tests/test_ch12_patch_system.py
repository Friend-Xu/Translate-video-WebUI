"""
Chapter 12 — Patch 系统、Reducer 与局部重算机制 测试

覆盖: PatchEngine v2, Reducer, DependencyGraph, RecomputeEngine,
      Conflict, Rollback, Snapshot, PatchStore, GateValidator, PatchPlanner
"""
import os
import tempfile
import pytest
from core.ir.timeline_event import TimelineEventIR
from core.ir.project import TimelineProjectIR
from core.runtime.patch import Patch, OpCode
from core.runtime.project_state import TimelineProjectState
from core.runtime.patch_engine import PatchEngine
from core.runtime.reducer import TimelineReducer
from core.runtime.dependency_graph import DependencyGraph, DependencyEdge
from core.runtime.recompute import RecomputeEngine, RecomputeScope, RecomputeTask
from core.runtime.conflict import (
    ConflictDetector, ConflictResolver, Conflict, ConflictType,
)
from core.runtime.rollback import RollbackManager
from core.runtime.snapshot import SnapshotManager
from core.runtime.patch_store import PatchStore
from core.runtime.gate_validator import GateValidator
from core.runtime.patch_planner import PatchPlanner


# ═══════════ PatchEngine v2 ═══════════

class TestPatchEngineV2:

    @pytest.fixture
    def engine(self):
        return PatchEngine()

    @pytest.fixture
    def state(self, sample_project):
        return TimelineProjectState(sample_project)

    def test_seg_insert_creates_event(self, engine, state):
        p = Patch(id="p1", target_id="evt_new", op=OpCode.SEGMENT_INSERT,
                  value={"start": 0.0, "end": 2.0, "text": "hello"})
        diff = engine.apply(state, p)
        assert diff["status"] == "applied"
        es = state.get_event("evt_new")
        assert es is not None
        assert es.start == 0.0
        assert es.end == 2.0

    def test_seg_insert_invalid_time(self, engine, state):
        p = Patch(id="p1", target_id="evt_bad", op=OpCode.SEGMENT_INSERT,
                  value={"start": 5.0, "end": 2.0})
        assert engine.apply(state, p)["status"] == "error"

    def test_seg_split_creates_two(self, engine, state):
        p = Patch(id="p1", target_id="evt_001", op=OpCode.SEGMENT_SPLIT,
                  value={"at": 1.0, "new_id": "evt_001_b"})
        diff = engine.apply(state, p)
        assert diff["status"] == "applied"
        assert state.get_event("evt_001").end == 1.0
        assert state.get_event("evt_001_b") is not None

    def test_seg_split_out_of_range(self, engine, state):
        p = Patch(id="p1", target_id="evt_001", op=OpCode.SEGMENT_SPLIT,
                  value={"at": 999.0})
        assert engine.apply(state, p)["status"] == "error"

    def test_seg_merge_two(self, engine, state):
        p = Patch(id="p1", target_id="evt_001", op=OpCode.SEGMENT_MERGE,
                  value={"target_ids": ["evt_001", "evt_002"]})
        diff = engine.apply(state, p)
        assert diff["status"] == "applied"

    def test_seg_merge_requires_2(self, engine, state):
        p = Patch(id="p1", target_id="evt_001", op=OpCode.SEGMENT_MERGE,
                  value={"target_ids": ["evt_001"]})
        assert engine.apply(state, p)["status"] == "error"

    def test_refine_alignment(self, engine, state):
        p = Patch(id="p1", target_id="evt_001", op=OpCode.REFINE_ALIGNMENT,
                  value={"word_timestamps": [{"word": "hi", "start": 0.0, "end": 0.5}]})
        assert engine.apply(state, p)["status"] == "applied"
        assert state.get_event("evt_001").asr.words != []

    def test_assign_speaker(self, engine, state):
        p = Patch(id="p1", target_id="evt_001", op=OpCode.ASSIGN_SPEAKER,
                  value={"speaker_id": "SPK_X", "confidence": 0.95})
        assert engine.apply(state, p)["status"] == "applied"
        assert state.get_event("evt_001").speaker.speaker_id == "SPK_X"

    def test_merge_speakers(self, engine, state):
        p = Patch(id="p1", target_id="SPK_00", op=OpCode.MERGE_SPEAKERS,
                  value={"from_ids": ["SPK_01"], "into_id": "SPK_00"})
        assert engine.apply(state, p)["status"] == "applied"

    def test_annotate_writes_slots(self, engine, state):
        p = Patch(id="p1", target_id="evt_001", op=OpCode.ANNOTATE,
                  value={"runtime": {"status": "done"}})
        assert engine.apply(state, p)["status"] == "applied"
        assert state.get_event("evt_001").runtime.status == "done"

    def test_annotate_rejects_removed_audio_slot(self, engine, state):
        """audio 槽已上移项目级 (Phase 3b), 不再接受 per-event ANNOTATE (Phase 2 契约对齐)。

        slot_map 从 field_contract 生成, 未知 slot 静默跳过 (兼容旧 patch 文件)。
        """
        p = Patch(id="p1", target_id="evt_001", op=OpCode.ANNOTATE,
                  value={"audio": {"sample_rate": 16000}, "runtime": {"status": "done"}})
        assert engine.apply(state, p)["status"] == "applied"
        es = state.get_event("evt_001")
        assert "audio" not in es._data          # audio key 被跳过, 不创建死槽
        assert es.runtime.status == "done"   # 合法槽位正常写入

    def test_annotate_global(self, engine, state):
        p = Patch(id="p1", target_id="__g__", op=OpCode.ANNOTATE,
                  value={"_global": True, "msg": "ckpt"})
        diff = engine.apply(state, p)
        assert diff["status"] == "applied"
        assert diff["scope"] == "global"


# ═══════════ Reducer ═══════════

class TestReducer:

    @pytest.fixture
    def reducer(self):
        return TimelineReducer()

    @pytest.fixture
    def state(self, sample_project):
        return TimelineProjectState(sample_project)

    def test_reduce_deterministic(self, reducer, state):
        p1 = Patch(id="p1", target_id="evt_001", op=OpCode.REPLACE,
                   value={"review": {"notes": "first"}}, timestamp=100)
        p2 = Patch(id="p2", target_id="evt_001", op=OpCode.REPLACE,
                   value={"review": {"notes": "second"}}, timestamp=200)
        reducer.reduce(state, [p1, p2])
        assert state.get_event("evt_001").review.notes == "second"

    def test_replay_to_timestamp(self, reducer, state):
        p1 = Patch(id="p1", target_id="evt_001", op=OpCode.REPLACE,
                   value={"review": {"notes": "first"}}, timestamp=100)
        p2 = Patch(id="p2", target_id="evt_001", op=OpCode.REPLACE,
                   value={"review": {"notes": "second"}}, timestamp=200)
        reducer.replay(state, [p1, p2], target_timestamp=150)
        assert state.get_event("evt_001").review.notes == "first"

    def test_compute_diff(self, reducer, state):
        before = TimelineProjectState(state.ir)
        after = TimelineProjectState(state.ir)
        PatchEngine().apply(after, Patch(id="p1", target_id="evt_001", op=OpCode.REPLACE,
                                         value={"review": {"notes": "changed"}}))
        diff = reducer.compute_diff(before, after)
        assert "evt_001" in diff["modified_events"]

    def test_reduce_empty(self, reducer, state):
        assert reducer.reduce(state, []) is state

    def test_sorts_by_timestamp(self, reducer, state):
        p2 = Patch(id="p2", target_id="evt_001", op=OpCode.REPLACE,
                   value={"review": {"notes": "last"}}, timestamp=200)
        p1 = Patch(id="p1", target_id="evt_001", op=OpCode.REPLACE,
                   value={"review": {"notes": "first"}}, timestamp=100)
        reducer.reduce(state, [p2, p1])
        # 按 timestamp 排序应用 → p1(100) 先, p2(200) 后 → 最终 "last"
        assert state.get_event("evt_001").review.notes == "last"

    def test_replay_from_snapshot(self, reducer, sample_project):
        p = Patch(id="p1", target_id="evt_001", op=OpCode.REPLACE,
                  value={"review": {"notes": "snap"}}, timestamp=100)
        st = reducer.replay_from_snapshot(sample_project, [p])
        assert st.get_event("evt_001").review.notes == "snap"


# ═══════════ DependencyGraph ═══════════

class TestDependencyGraph:

    @pytest.fixture
    def graph(self):
        return DependencyGraph()

    @pytest.fixture
    def state(self, sample_project):
        return TimelineProjectState(sample_project)

    def test_build_temporal(self, graph, state):
        graph.build(state)
        assert "evt_002" in graph.get_downstream("evt_001", depth=1)

    def test_get_upstream(self, graph, state):
        graph.build(state)
        assert "evt_001" in graph.get_upstream("evt_002", depth=1)

    def test_invalidate_cascade(self, graph, state):
        graph.build(state)
        cascaded = graph.invalidate("evt_001", max_depth=2)
        assert graph.is_invalidated("evt_001")
        assert "evt_002" in cascaded

    def test_clear_invalidation(self, graph, state):
        graph.build(state)
        graph.invalidate("evt_001")
        graph.clear_invalidation()
        assert not graph.is_invalidated("evt_001")

    def test_affected_range(self, graph, state):
        graph.build(state)
        affected = graph.get_affected_range("evt_002", upstream_depth=1, downstream_depth=1)
        assert "evt_001" in affected
        assert "evt_003" in affected

    def test_pruned(self, graph, state):
        graph.build(state)
        pruned = graph.pruned(max_depth=1)
        assert len(pruned.get_downstream("evt_001", depth=5)) <= 2

    def test_empty_state(self, graph):
        empty = TimelineProjectState(TimelineProjectIR(events={}, speakers={}))
        graph.build(empty)
        assert len(graph.edges) == 0


# ═══════════ RecomputeEngine ═══════════

class TestRecomputeEngine:

    @pytest.fixture
    def graph(self):
        return DependencyGraph()

    @pytest.fixture
    def engine(self, graph):
        return RecomputeEngine(graph)

    def test_plan_minimal(self, engine):
        tasks = engine.plan(["evt_001"], strategy="minimal", trigger="tts_replace")
        assert len(tasks) == 1
        assert tasks[0].scope == RecomputeScope.SEGMENT

    def test_plan_window(self, engine, graph, sample_project):
        st = TimelineProjectState(sample_project)
        graph.build(st)
        tasks = engine.plan(["evt_002"], strategy="window", trigger="speaker_reassign")
        assert len(tasks) == 1
        assert tasks[0].scope == RecomputeScope.WINDOW

    def test_estimate_cost(self, engine):
        tasks = [RecomputeTask(["a", "b"], RecomputeScope.WINDOW, "test", 0)]
        cost = engine.estimate_cost(tasks)
        assert cost["segment_count"] == 2

    def test_estimate_cost_empty(self, engine):
        assert engine.estimate_cost([])["segment_count"] == 0

    def test_merge_tasks(self, engine):
        t1 = RecomputeTask(["a"], RecomputeScope.SEGMENT, "test", 0)
        t2 = RecomputeTask(["b"], RecomputeScope.SEGMENT, "test", 0)
        merged = engine.merge_tasks([t1, t2])
        assert len(merged) == 1


# ═══════════ Conflict ═══════════

class TestConflictDetector:

    @pytest.fixture
    def d(self):
        return ConflictDetector()

    def test_overwrite(self, d):
        p1 = Patch("p1", "evt_001", OpCode.UPDATE_TRANSCRIPTION, {"text": "A"})
        p2 = Patch("p2", "evt_001", OpCode.UPDATE_TRANSCRIPTION, {"text": "B"})
        conflicts = d.detect([p1, p2])
        assert len(conflicts) == 1
        assert conflicts[0].conflict_type == ConflictType.OVERWRITE

    def test_identity(self, d):
        p1 = Patch("p1", "evt_001", OpCode.ASSIGN_SPEAKER, {"speaker_id": "A"})
        p2 = Patch("p2", "evt_001", OpCode.ASSIGN_SPEAKER, {"speaker_id": "B"})
        conflicts = d.detect([p1, p2])
        assert len(conflicts) == 1
        assert conflicts[0].conflict_type == ConflictType.IDENTITY

    def test_no_conflict(self, d):
        p1 = Patch("p1", "evt_001", OpCode.REFINE_ALIGNMENT, {"w": []})
        p2 = Patch("p2", "evt_002", OpCode.ASSIGN_SPEAKER, {"speaker_id": "X"})
        assert len(d.detect([p1, p2])) == 0

    def test_is_safe(self, d, sample_project):
        st = TimelineProjectState(sample_project)
        ok, _ = d.is_safe_to_apply(Patch("p1", "evt_001", OpCode.REPLACE, {}), st)
        assert ok

    def test_is_safe_missing(self, d, sample_project):
        st = TimelineProjectState(sample_project)
        ok, _ = d.is_safe_to_apply(Patch("p1", "noex", OpCode.REPLACE, {}), st)
        assert not ok


class TestConflictResolver:

    @pytest.fixture
    def r(self):
        return ConflictResolver()

    def test_rule_priority(self, r):
        p1 = Patch("p_a", "e1", OpCode.UPDATE_TRANSCRIPTION, {"t": "A"}, author="whisper")
        p2 = Patch("p_b", "e1", OpCode.UPDATE_TTS_AUDIO, {"a": "b"}, author="edge_tts")
        c = Conflict(ConflictType.OVERWRITE, p1, p2, "e1", "test")
        kept = r.resolve([c], "rule")
        assert kept[0].author == "whisper"

    def test_confidence(self, r):
        p1 = Patch("p_a", "e1", OpCode.REPLACE, {"review": {"notes": "x"}}, confidence=0.9)
        p2 = Patch("p_b", "e1", OpCode.REPLACE, {"review": {"notes": "x2"}}, confidence=0.3)
        c = Conflict(ConflictType.OVERWRITE, p1, p2, "e1", "test")
        kept = r.resolve([c], "confidence")
        assert kept[0].id == "p_a"

    def test_range_union(self, r):
        # conflict 解析不经过 PatchEngine, value 可为任意范围字段
        p1 = Patch("p_a", "e1", OpCode.REPLACE, {"start": 0.0, "end": 5.0})
        p2 = Patch("p_b", "e1", OpCode.REPLACE, {"start": 3.0, "end": 8.0})
        c = Conflict(ConflictType.TEMPORAL, p1, p2, "", "overlap")
        kept = r.resolve([c], "range")
        assert kept[0].value["end"] == 8.0


# ═══════════ Snapshot ═══════════

class TestSnapshotManager:

    @pytest.fixture
    def mgr(self):
        return SnapshotManager()

    @pytest.fixture
    def state(self, sample_project):
        return TimelineProjectState(sample_project)

    def test_roundtrip(self, mgr, state):
        state.get_event("evt_001").meta["k"] = "before"
        snap = mgr.create(state, "test")
        state.get_event("evt_001").meta["k"] = "after"
        mgr.restore(state, snap)
        assert state.get_event("evt_001").meta["k"] == "before"

    def test_latest(self, mgr, state):
        assert mgr.latest() is None
        mgr.create(state, "first")
        assert mgr.latest().description == "first"

    def test_description(self, mgr, state):
        snap = mgr.create(state, "after ASR")
        assert snap.description == "after ASR"


# ═══════════ Rollback ═══════════

class TestRollbackManager:

    @pytest.fixture
    def mgr(self):
        return RollbackManager(TimelineReducer(), SnapshotManager(), DependencyGraph())

    @pytest.fixture
    def state(self, sample_project):
        return TimelineProjectState(sample_project)

    def test_rollback_segment(self, mgr, state):
        eng = PatchEngine()
        eng.apply(state, Patch("p1", "evt_001", OpCode.REPLACE, {"review": {"notes": "v1"}}, timestamp=100))
        eng.apply(state, Patch("p2", "evt_001", OpCode.REPLACE, {"review": {"notes": "v2"}}, timestamp=200))
        mgr.rollback_segment(state, "evt_001", 0)
        assert state.get_event("evt_001").review.notes == "v1"
        assert len(state.get_event("evt_001").patches) == 1

    def test_get_versions(self, mgr, state):
        PatchEngine().apply(state, Patch("p1", "evt_001", OpCode.REPLACE, {}, timestamp=100))
        versions = mgr.get_segment_versions(state, "evt_001")
        assert len(versions) == 1
        assert versions[0]["patch_id"] == "p1"

    def test_versions_missing(self, mgr, state):
        assert mgr.get_segment_versions(state, "nonexistent") == []

    def test_reverse_patch(self, mgr, state):
        eng = PatchEngine()
        eng.apply(state, Patch("p1", "evt_001", OpCode.REPLACE, {"review": {"notes": "a1"}}, timestamp=100))
        eng.apply(state, Patch("p2", "evt_001", OpCode.REPLACE, {"review": {"notes": "a2"}}, timestamp=200))
        rev = mgr.compute_reverse_patch(state.get_event("evt_001").patches[1], state)
        assert rev is not None
        assert rev.value["review"]["notes"] == "a1"

    def test_reverse_patch_first_returns_undo(self, mgr, state):
        eng = PatchEngine()
        eng.apply(state, Patch("p1", "evt_001", OpCode.REPLACE, {"review": {"notes": "a1"}}, timestamp=100))
        rev = mgr.compute_reverse_patch(state.get_event("evt_001").patches[0], state)
        assert rev is not None
        assert rev.op == OpCode.REPLACE

    def test_rollback_out_of_range(self, mgr, state):
        assert mgr.rollback_segment(state, "evt_001", 99) is state


# ═══════════ PatchStore ═══════════

class TestPatchStore:

    @pytest.fixture
    def store(self):
        return PatchStore()

    def test_flush_load(self, store):
        store.append(Patch("p1", "evt_001", OpCode.REPLACE, {"text": "hi"}, confidence=0.9))
        with tempfile.TemporaryDirectory() as d:
            store.persist_dir = d
            fp = store.flush()
            assert os.path.exists(fp)
            loaded = PatchStore().load(fp)
            assert len(loaded) == 1
            assert loaded[0].id == "p1"

    def test_merge_adjacent(self, store):
        p1 = Patch("p1", "evt_001", OpCode.REPLACE, {"a": 1}, timestamp=100)
        p2 = Patch("p2", "evt_001", OpCode.REPLACE, {"b": 2}, timestamp=200)
        p3 = Patch("p3", "evt_002", OpCode.REPLACE, {"c": 3}, timestamp=300)
        c = store.compress([p1, p2, p3], "merge_adjacent")
        assert len(c) == 2
        assert c[0].value.get("b") == 2

    def test_keep_latest(self, store):
        p1 = Patch("p1", "evt_001", OpCode.REPLACE, {"v": 1}, timestamp=100)
        p2 = Patch("p2", "evt_001", OpCode.REPLACE, {"v": 2}, timestamp=200)
        c = store.compress([p1, p2], "keep_latest")
        assert len(c) == 1
        assert c[0].value["v"] == 2

    def test_keep_checkpoints(self, store):
        p1 = Patch("p1", "evt_A", OpCode.SEGMENT_INSERT, {"start": 0, "end": 1}, timestamp=100)
        p2 = Patch("p2", "evt_B", OpCode.REPLACE, {"x": 1}, timestamp=200)
        p3 = Patch("p3", "evt_B", OpCode.REPLACE, {"x": 2}, timestamp=300)
        c = store.compress([p1, p2, p3], "keep_checkpoints")
        assert any(p.op == OpCode.SEGMENT_INSERT for p in c)

    def test_get_history(self, store):
        store.append(Patch("p1", "evt_001", OpCode.REPLACE, {}))
        store.append(Patch("p2", "evt_002", OpCode.REPLACE, {}))
        assert len(store.get_history("evt_001")) == 1


# ═══════════ GateValidator ═══════════

class TestGateValidator:

    @pytest.fixture
    def v(self):
        return GateValidator()

    @pytest.fixture
    def state(self, sample_project):
        return TimelineProjectState(sample_project)

    def test_valid_passes(self, v, state):
        assert v.validate(Patch("p1", "evt_001", OpCode.REPLACE, {}), state) == []

    def test_missing_target(self, v, state):
        r = v.validate(Patch("p1", "noex", OpCode.REPLACE, {}), state)
        assert any(x.reason == "target_not_found" for x in r)

    def test_seg_insert_no_target_ok(self, v, state):
        r = v.validate(Patch("p1", "new_s", OpCode.SEGMENT_INSERT, {"start": 0, "end": 1}), state)
        assert not any(x.reason == "target_not_found" for x in r)

    def test_invalid_confidence(self, v, state):
        r = v.validate(Patch("p1", "evt_001", OpCode.REPLACE, {}, confidence=1.5), state)
        assert any(x.reason == "invalid_confidence" for x in r)

    def test_missing_field(self, v, state):
        r = v.validate(Patch("p1", "evt_001", OpCode.SEGMENT_SPLIT, {}), state)
        assert any(x.reason == "missing_field" for x in r)

    def test_duplicate_idempotency(self, v, state):
        PatchEngine().apply(state, Patch("ex", "evt_001", OpCode.REPLACE, {}, idempotency_key="k1"))
        r = v.validate(Patch("dup", "evt_001", OpCode.REPLACE, {}, idempotency_key="k1"), state)
        assert any(x.reason == "duplicate_idempotency" for x in r)


# ═══════════ PatchPlanner ═══════════

class TestPatchPlanner:

    @pytest.fixture
    def planner(self):
        return PatchPlanner()

    @pytest.fixture
    def state(self, sample_project):
        return TimelineProjectState(sample_project)

    def test_accept(self, planner, state):
        patches = planner.plan({"evt_001": {"accept": True, "score": 0.9, "engine": "cosyvoice"}}, state)
        assert len(patches) == 1
        assert patches[0].value["provenance"]["gate_decision"] == "accept"

    def test_downgrade(self, planner, state):
        patches = planner.plan({"evt_001": {"downgrade": True, "score": 0.3}}, state)
        assert len(patches) == 1
        assert patches[0].op == OpCode.UPDATE_TTS_AUDIO

    def test_manual_review(self, planner, state):
        patches = planner.plan({"evt_001": {"manual_review": True, "reason": "low"}}, state)
        assert patches[0].value["review"]["flags"] == ["needs_human_review"]

    def test_repair(self, planner, state):
        patches = planner.plan({"evt_001": {"repair": True}}, state)
        assert patches[0].value["runtime"]["status"] == "repairing"

    def test_empty(self, planner, state):
        assert planner.plan({}, state) == []
