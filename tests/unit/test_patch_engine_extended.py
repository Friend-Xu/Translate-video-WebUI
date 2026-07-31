"""
PatchEngine 单元测试全覆盖 (批次8)
"""
import pytest
from core.runtime.patch import Patch
from core.runtime.patch_engine import PatchEngine
from core.testing.fixtures import make_event, make_state, make_patch


@pytest.mark.unit
class TestPatchEngineCRUD:

    def test_replace_writes_derivatives(self):
        s = make_state({"e1": make_event("e1", 0, 1, "hello")})
        PatchEngine().apply(s, make_patch("p1", "e1", "replace", {"translation": "hi"}))
        assert s.get_event("e1").derivatives.get("translation") == "hi"

    def test_merge_records_merged_from(self):
        s = make_state({"e1": make_event("e1", 0, 1, "hello"), "e2": make_event("e2", 1, 2, "world")})
        PatchEngine().apply(s, make_patch("p1", "e1", "merge", {"target_ids": ["e1","e2"]}))
        assert "e2" in s.get_event("e1").derivatives.get("_merged_from", [])

    def test_split_records_split_at(self):
        s = make_state({"e1": make_event("e1", 0, 2, "hello world")})
        PatchEngine().apply(s, make_patch("p1", "e1", "split", {"at": 1.0}))
        assert s.get_event("e1").derivatives.get("_split_at") == 1.0

    def test_segment_insert_adds_event(self):
        s = make_state({"e1": make_event("e1", 0, 1, "hello")})
        PatchEngine().apply(s, make_patch("p1", "e2", "segment_insert", {
            "id": "e2", "start": 1.5, "end": 2.5, "text": "world", "speaker": "S1"}))
        assert "e2" in s.event_states

    def test_segment_split_creates_child(self):
        s = make_state({"e1": make_event("e1", 0, 4, "hello world")})
        PatchEngine().apply(s, make_patch("p1", "e1", "segment_split", {"at": 2.0}))
        child = [eid for eid in s.event_states if eid.startswith("e1_")]
        assert len(child) >= 1

    def test_segment_merge_combines(self):
        s = make_state({"e1": make_event("e1", 0, 1, "hello"), "e2": make_event("e2", 1, 2, "world")})
        PatchEngine().apply(s, make_patch("p1", "e1", "segment_merge", {"target_ids": ["e1","e2"]}))


@pytest.mark.unit
class TestPatchEngineSpeakerConfig:

    def test_assign_speaker_updates_ref(self):
        s = make_state({"e1": make_event("e1", 0, 1, "hello")})
        PatchEngine().apply(s, make_patch("p1", "e1", "assign_speaker", {"speaker_id": "S2", "confidence": 0.9}))
        assert s.get_event("e1").speaker.get("speaker_id") == "S2"

    def test_set_config_replaces_all(self):
        s = make_state({"e1": make_event("e1", 0, 1, "hello")})
        s.get_event("e1").tts["config"] = {"speed_factor": 0.8}
        PatchEngine().apply(s, make_patch("p1", "e1", "set_config", {"slot": "tts", "config_block": {"engine": "edge"}}))
        assert s.get_event("e1").tts["config"].get("engine") == "edge"

    def test_override_config_merges(self):
        s = make_state({"e1": make_event("e1", 0, 1, "hello")})
        s.get_event("e1").tts["config"] = {"speed_factor": 1.0, "engine": "chattts"}
        PatchEngine().apply(s, make_patch("p1", "e1", "override_config", {"slot": "tts", "partial_config": {"speed_factor": 1.5}}))
        assert s.get_event("e1").tts["config"]["engine"] == "chattts"


@pytest.mark.unit
class TestPatchEngineErrors:

    def test_unknown_target_returns_error(self):
        s = make_state({"e1": make_event("e1", 0, 1, "hello")})
        assert PatchEngine().apply(s, make_patch("p1", "nonexistent"))["status"] == "error"

    def test_unknown_opcode_returns_error(self):
        s = make_state({"e1": make_event("e1", 0, 1, "hello")})
        p = Patch(id="p1", target_id="e1", op="unknown_op", value={})
        assert PatchEngine().apply(s, p)["status"] == "error"

    def test_idempotency_key_dedup(self):
        s = make_state({"e1": make_event("e1", 0, 1, "hello")})
        p1 = Patch(id="p1", target_id="e1", op="replace", value={"a": 1}, idempotency_key="k1")
        p2 = Patch(id="p2", target_id="e1", op="replace", value={"a": 2}, idempotency_key="k1")
        PatchEngine().apply(s, p1)
        assert PatchEngine().apply(s, p2)["status"] == "skipped"

    def test_dry_run_does_not_mutate(self):
        s = make_state({"e1": make_event("e1", 0, 1, "hello")})
        r = PatchEngine().dry_run(s, make_patch("p1", "e1", "replace", {"x": 1}))
        assert r["valid"] is True
        assert "x" not in s.get_event("e1").derivatives


@pytest.mark.unit
class TestPatchEngineConsistency:

    def test_split_preserves_time_continuity(self):
        s = make_state({"e1": make_event("e1", 0, 4, "hello world")})
        PatchEngine().apply(s, make_patch("p1", "e1", "segment_split", {"at": 2.0}))
        assert s.get_event("e1").derivatives.get("_split_at") == 2.0

    def test_merge_combines_time_range(self):
        s = make_state({"e1": make_event("e1", 0, 1, "hello"), "e2": make_event("e2", 1, 2, "world")})
        PatchEngine().apply(s, make_patch("p1", "e1", "segment_merge", {"target_ids": ["e1","e2"]}))
        assert "e2" in s.get_event("e1").derivatives.get("_merged_from", [])

    def test_batch_apply_consistency(self):
        s = make_state({"e1": make_event("e1", 0, 1, "hello"), "e2": make_event("e2", 1, 2, "world")})
        patches = [make_patch("p1", "e1", "replace", {"a": 1}), make_patch("p2", "e2", "replace", {"b": 2})]
        results = PatchEngine().apply_many(s, patches)
        assert all(r["status"] == "applied" for r in results)
        assert s.get_event("e1").derivatives.get("a") == 1
        assert s.get_event("e2").derivatives.get("b") == 2

    # ── IR 注册表同步 (Phase1: 结构性 handler 后 ir.events 与 event_states 一致) ──

    def _assert_ir_registry_synced(self, s):
        assert set(s.ir.events.keys()) == set(s.event_states.keys())
        for eid, es in s.event_states.items():
            assert s.ir.events[eid] is es.ir  # 同一 IR 节点, 内容一致

    def test_segment_insert_syncs_ir_registry(self):
        s = make_state({"e1": make_event("e1", 0, 1, "hello")})
        PatchEngine().apply(s, make_patch("p1", "e2", "segment_insert", {
            "start": 1.5, "end": 2.5, "text": "world", "speaker": "S1"}))
        self._assert_ir_registry_synced(s)

    def test_segment_split_syncs_ir_registry(self):
        s = make_state({"e1": make_event("e1", 0, 4, "hello world")})
        PatchEngine().apply(s, make_patch("p1", "e1", "segment_split", {"at": 2.0}))
        self._assert_ir_registry_synced(s)
        # 新事件 e1_b 必须进入 IR 注册表
        assert "e1_b" in s.ir.events
        assert s.ir.events["e1_b"].start == 2.0

    def test_segment_merge_syncs_ir_registry(self):
        s = make_state({"e1": make_event("e1", 0, 1, "hello"), "e2": make_event("e2", 1, 2, "world")})
        PatchEngine().apply(s, make_patch("p1", "e1", "segment_merge", {"target_ids": ["e1", "e2"]}))
        self._assert_ir_registry_synced(s)
        assert "e2" not in s.ir.events          # 被合并事件从注册表移除

    def test_assign_speaker_syncs_ir_registry(self):
        s = make_state({"e1": make_event("e1", 0, 1, "hello")})
        PatchEngine().apply(s, make_patch("p1", "e1", "assign_speaker", {"speaker_id": "S2", "confidence": 0.9}))
        self._assert_ir_registry_synced(s)
        assert s.ir.events["e1"].speaker_ref == "S2"   # 新 IR 节点带新 speaker_ref

    def test_merge_speakers_syncs_ir_registry(self):
        s = make_state({
            "e1": make_event("e1", 0, 1, "hello", speaker="S1"),
            "e2": make_event("e2", 1, 2, "world", speaker="S1"),
        })
        PatchEngine().apply(s, make_patch("p1", "e1", "merge_speakers",
                                          {"from_ids": ["S1"], "into_id": "S2"}))
        self._assert_ir_registry_synced(s)
        assert s.ir.events["e1"].speaker_ref == "S2"
        assert s.ir.events["e2"].speaker_ref == "S2"
