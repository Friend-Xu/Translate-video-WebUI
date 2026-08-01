"""
契约测试 — Phase 4 GUI 编辑路径收敛

锁死:
  - Patch 序列化往返 (to_dict/from_dict, op 存 value 非枚举 repr)
  - 旧前端契约 → core Patch 适配映射 (patch_adapter)
  - undo 重放: pristine bak + PatchEngine 重放链 (消灭旧系统静默 no-op)
  - UPDATE_BOUNDS (旧 RESIZE 对等物) 改事件边界
"""
import os
import shutil
import pytest

from core.ir.timeline_event import TimelineEventIR
from core.ir.speaker import SpeakerNodeIR
from core.ir.project import TimelineProjectIR
from core.runtime.project_state import TimelineProjectState
from core.runtime.patch import Patch, OpCode
from core.runtime.patch_engine import PatchEngine
from core.runtime.timeline_io import persist_state, load_state
from GUI.patch_adapter import (legacy_to_core, core_to_legacy, load_chain,
                               save_chain, UnsupportedPatchError)


def _state(n_events: int = 4, speakers: int = 2) -> TimelineProjectState:
    """合成 state: n 个事件 + speakers 注册表 (带外观字段)。"""
    evts = {
        f"evt_{i:03d}": TimelineEventIR(id=f"evt_{i:03d}", start=i * 2.0,
                                        end=i * 2.0 + 1.5,
                                        speaker_ref=f"SPK_{i % speakers:02d}",
                                        text_ref=f"text {i}")
        for i in range(n_events)
    }
    spks = {f"SPK_{i:02d}": SpeakerNodeIR(id=f"SPK_{i:02d}", name=f"spk{i}",
                                          voice_id=f"v{i}", color="#123456")
            for i in range(speakers)}
    return TimelineProjectState(TimelineProjectIR(events=evts, speakers=spks))


@pytest.mark.contract
class TestPatchSerialization:
    def test_to_dict_op_is_value(self):
        """op 存 value ('segment_merge'), 不是枚举 repr ('OpCode.SEGMENT_MERGE')。"""
        p = Patch(id="p1", target_id="e1", op=OpCode.SEGMENT_MERGE, value={})
        assert p.to_dict()["op"] == "segment_merge"

    def test_roundtrip(self):
        p = Patch(id="p1", target_id="e1", op=OpCode.ASSIGN_SPEAKER,
                  value={"speaker_id": "SPK_01"}, timestamp=123.0,
                  author="user", targets=["e1", "e2"], reason=["r"],
                  score=0.9, confidence=0.8, parent_version="v1",
                  idempotency_key="k1")
        p2 = Patch.from_dict(p.to_dict())
        assert p2.id == p.id and p2.op == p.op and p2.value == p.value
        assert p2.timestamp == 123.0 and p2.idempotency_key == "k1"

    def test_unknown_op_loud(self):
        with pytest.raises(ValueError):
            Patch.from_dict({"id": "p", "op": "nope", "value": {}})


@pytest.mark.contract
class TestLegacyAdapter:
    def test_merge_mapping(self):
        p = legacy_to_core({"patch_id": "m1", "opcode": "MERGE",
                            "targets": ["a", "b"], "payload": {},
                            "idempotency_key": "k"})
        assert p.op == OpCode.SEGMENT_MERGE
        assert p.value == {"target_ids": ["a", "b"]}
        assert p.idempotency_key == "k"

    def test_split_mapping(self):
        p = legacy_to_core({"patch_id": "s1", "opcode": "SPLIT",
                            "targets": ["a"], "payload": {"split_point": 1.5}})
        assert p.op == OpCode.SEGMENT_SPLIT
        assert p.value == {"at": 1.5}

    def test_retag_mapping(self):
        p = legacy_to_core({"patch_id": "r1", "opcode": "RETAG_SPEAKER",
                            "targets": ["a"], "payload": {"new_speaker": "SPK_9"}})
        assert p.op == OpCode.ASSIGN_SPEAKER
        assert p.value == {"speaker_id": "SPK_9"}

    def test_set_translation_mapping(self):
        p = legacy_to_core({"patch_id": "t1", "opcode": "SET_TRANSLATION",
                            "targets": ["a"], "payload": {"translation": "你好"}})
        assert p.op == OpCode.UPDATE_TRANSLATION
        assert p.value == {"translation": "你好"}

    def test_resize_mapping(self):
        p = legacy_to_core({"patch_id": "z1", "opcode": "RESIZE",
                            "targets": ["a"],
                            "payload": {"new_start": 1.0, "new_end": 2.5}})
        assert p.op == OpCode.UPDATE_BOUNDS
        assert p.value == {"start": 1.0, "end": 2.5}

    def test_annotate_deleted_maps_to_review_flags(self):
        p = legacy_to_core({"patch_id": "d1", "opcode": "ANNOTATE",
                            "targets": ["a"],
                            "payload": {"key": "deleted", "value": True}})
        assert p.op == OpCode.ANNOTATE
        assert p.value == {"review": {"flags": ["deleted"]}}

    def test_speaker_ops_mapped_to_core(self):
        """P2 收敛: speaker 操作统一走 patch — 映射到注册表级 opcode。"""
        cases = [
            # (前端 opcode, payload, targets, 期望 core op, value 关键字段)
            ("ASSIGN_SPEAKER", {"new_speaker": "SPK_B"}, ["evt_001"],
             OpCode.ASSIGN_SPEAKER, {"speaker_id": "SPK_B"}),
            ("MERGE_SPEAKERS", {"source": "SPK_A", "target": "SPK_B"}, ["SPK_A"],
             OpCode.MERGE_SPEAKERS, {"from_ids": ["SPK_A"], "into_id": "SPK_B"}),
            ("CREATE_SPEAKER", {"display_name": "新角色"}, ["SPK_NEW"],
             OpCode.REGISTER_SPEAKER, {"speaker_id": "SPK_NEW", "display_name": "新角色"}),
            ("RENAME_SPEAKER", {"newName": "主角", "color": "#FF0000"}, ["SPK_A"],
             OpCode.UPDATE_SPEAKER, {"speaker_id": "SPK_A", "name": "主角", "color": "#FF0000"}),
            ("LOCK_SPEAKER", {"speaker": "SPK_A"}, ["SPK_A"],
             OpCode.LOCK_SPEAKER, {"speaker_id": "SPK_A", "locked": True}),
        ]
        for opcode, payload, targets, expect_op, expect_value in cases:
            p = legacy_to_core({"patch_id": "x", "opcode": opcode,
                                "targets": targets, "payload": payload})
            assert p.op == expect_op, opcode
            for k, v in expect_value.items():
                assert p.value.get(k) == v, f"{opcode} value.{k}"

    def test_merge_speakers_missing_target_rejected(self):
        with pytest.raises(UnsupportedPatchError):
            legacy_to_core({"patch_id": "x", "opcode": "MERGE_SPEAKERS",
                            "targets": ["SPK_A"], "payload": {"source": "SPK_A"}})

    def test_timeline_edit_ops_mapped_to_core(self):
        """P3-A: timeline 编辑假 draft 补映射 — 不再降级 ANNOTATE 静默零写入。"""
        cases = [
            ("MOVE_EVENT", {"start": 1.0, "end": 3.0}, ["evt_001"],
             OpCode.UPDATE_BOUNDS, {"start": 1.0, "end": 3.0}),
            ("TRIM_START", {"start": 0.5}, ["evt_001"],
             OpCode.UPDATE_BOUNDS, {"start": 0.5, "end": None}),
            ("TRIM_END", {"end": 4.0}, ["evt_001"],
             OpCode.UPDATE_BOUNDS, {"start": None, "end": 4.0}),
            ("SPLIT_EVENT", {"splitTime": 1.5}, ["evt_001"],
             OpCode.SEGMENT_SPLIT, {"at": 1.5}),
            ("MERGE_PREV", {"mergeTarget": "evt_000"}, ["evt_001"],
             OpCode.SEGMENT_MERGE, {"target_ids": ["evt_001", "evt_000"]}),
            ("MERGE_NEXT", {"mergeTarget": "evt_002"}, ["evt_001"],
             OpCode.SEGMENT_MERGE, {"target_ids": ["evt_001", "evt_002"]}),
            ("APPLY_AI_SUGGESTION", {"translation": "AI 译文"}, ["evt_001"],
             OpCode.UPDATE_TRANSLATION, {"translation": "AI 译文"}),
            ("RETRIGGER", {}, ["evt_001"],
             OpCode.ANNOTATE, {"review": {"flags": ["needs_retranslate"],
                                          "needs_human_review": True}}),
        ]
        for opcode, payload, targets, expect_op, expect_value in cases:
            p = legacy_to_core({"patch_id": "x", "opcode": opcode,
                                "targets": targets, "payload": payload})
            assert p.op == expect_op, opcode
            assert p.value == expect_value, opcode

    def test_merge_prev_missing_target_rejected(self):
        with pytest.raises(UnsupportedPatchError):
            legacy_to_core({"patch_id": "x", "opcode": "MERGE_PREV",
                            "targets": ["evt_001"], "payload": {}})

    def test_unknown_opcode_rejected(self):
        with pytest.raises(UnsupportedPatchError):
            legacy_to_core({"patch_id": "x", "opcode": "RELINK_WORDS",
                            "targets": ["a"], "payload": {}})

    def test_legacy_iso_timestamp(self):
        p = legacy_to_core({"patch_id": "t", "opcode": "MERGE",
                            "targets": ["a", "b"], "payload": {},
                            "timestamp": "2026-07-26T23:44:27.411Z"})
        assert p.timestamp > 0

    def test_core_to_legacy_display_opcodes(self):
        for core_op, legacy_label in [
            (OpCode.SEGMENT_MERGE, "MERGE"),
            (OpCode.SEGMENT_SPLIT, "SPLIT"),
            (OpCode.ASSIGN_SPEAKER, "ASSIGN_SPEAKER"),
            (OpCode.UPDATE_TRANSLATION, "SET_TRANSLATION"),
            (OpCode.UPDATE_BOUNDS, "RESIZE"),
            (OpCode.MERGE_SPEAKERS, "MERGE_SPEAKERS"),
            (OpCode.REGISTER_SPEAKER, "CREATE_SPEAKER"),
            (OpCode.UPDATE_SPEAKER, "RENAME_SPEAKER"),
            (OpCode.LOCK_SPEAKER, "LOCK_SPEAKER"),
        ]:
            p = Patch(id="p", target_id="e", op=core_op, value={})
            assert core_to_legacy(p)["opcode"] == legacy_label


@pytest.mark.contract
class TestPatchChain:
    def test_mixed_chain_roundtrip(self, tmp_path):
        """新旧格式混合链统一读取 (旧链是历史数据)。"""
        chain_path = str(tmp_path / "timeline_patches.json")
        legacy = {"patch_id": "old_1", "opcode": "RETAG_SPEAKER",
                  "targets": ["e1"], "payload": {"new_speaker": "SPK_1"},
                  "timestamp": "2026-07-26T23:44:27.411Z"}
        new = Patch(id="new_1", target_id="e2", op=OpCode.SEGMENT_MERGE,
                    value={"target_ids": ["e2", "e3"]})
        save_chain([Patch.from_dict(new.to_dict())], chain_path)  # 新格式
        with open(chain_path, "r", encoding="utf-8") as f:
            import json
            raw = json.load(f)
        raw.insert(0, legacy)  # 前面插旧条目
        with open(chain_path, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)

        chain = load_chain(chain_path)
        assert [p.id for p in chain] == ["old_1", "new_1"]
        assert chain[0].op == OpCode.ASSIGN_SPEAKER
        assert chain[1].op == OpCode.SEGMENT_MERGE

    def test_save_chain_then_load(self, tmp_path):
        chain_path = str(tmp_path / "timeline_patches.json")
        ps = [Patch(id="a", target_id="e1", op=OpCode.ASSIGN_SPEAKER,
                    value={"speaker_id": "SPK_1"}),
              Patch(id="b", target_id="e2", op=OpCode.UPDATE_TRANSLATION,
                    value={"translation": "hi"})]
        save_chain(ps, chain_path)
        assert [p.id for p in load_chain(chain_path)] == ["a", "b"]


@pytest.mark.contract
class TestUpdateBounds:
    def test_resize_event(self):
        state = _state(2)
        patch = Patch(id="r", target_id="evt_001", op=OpCode.UPDATE_BOUNDS,
                      value={"start": 0.5, "end": 3.0})
        result = PatchEngine().apply(state, patch)
        assert result["status"] == "applied"
        es = state.get_event("evt_001")
        assert es.start == 0.5 and es.end == 3.0
        # IR 注册表同步
        assert state.ir.events["evt_001"].start == 0.5

    def test_invalid_range_rejected(self):
        state = _state(2)
        patch = Patch(id="r", target_id="evt_001", op=OpCode.UPDATE_BOUNDS,
                      value={"start": 5.0, "end": 3.0})
        result = PatchEngine().apply(state, patch)
        assert result["status"] == "error"

    def test_resize_survives_persist(self, tmp_path):
        ws = str(tmp_path / "ws")
        state = _state(2)
        tl = persist_state(state, ws, "v.mp4", "en")
        PatchEngine().apply(state, Patch(
            id="r", target_id="evt_001", op=OpCode.UPDATE_BOUNDS,
            value={"start": 0.5, "end": 3.0}))
        persist_state(state, ws, "v.mp4", "en")
        reloaded = load_state(tl)
        assert reloaded.get_event("evt_001").end == 3.0


@pytest.mark.contract
class TestTimelineEditOps:
    """P3-A: timeline 编辑 opcode (前端假 draft) 经 adapter 全链路应用。"""

    def test_trim_start_partial_bounds(self):
        """TRIM_START 只给 start — 部分边界更新, end 保持。"""
        state = _state(2)
        p = legacy_to_core({"patch_id": "t1", "opcode": "TRIM_START",
                            "targets": ["evt_001"],
                            "payload": {"start": 0.5}})
        assert p.op == OpCode.UPDATE_BOUNDS
        r = PatchEngine().apply(state, p)
        assert r["status"] == "applied"
        es = state.get_event("evt_001")
        assert es.start == 0.5 and es.end == 3.5

    def test_trim_end_partial_bounds(self):
        """TRIM_END 只给 end — start 保持。"""
        state = _state(2)
        p = legacy_to_core({"patch_id": "t2", "opcode": "TRIM_END",
                            "targets": ["evt_001"], "payload": {"end": 3.2}})
        assert PatchEngine().apply(state, p)["status"] == "applied"
        es = state.get_event("evt_001")
        assert es.start == 2.0 and es.end == 3.2

    def test_split_event_applied(self):
        """SPLIT_EVENT → SEGMENT_SPLIT: 事件数 +1, 边界正确。"""
        state = _state(2)
        p = legacy_to_core({"patch_id": "s1", "opcode": "SPLIT_EVENT",
                            "targets": ["evt_001"],
                            "payload": {"splitTime": 2.5}})
        r = PatchEngine().apply(state, p)
        assert r["status"] == "applied"
        assert len(state.ir.events) == 3
        assert state.get_event("evt_001").end == 2.5
        assert state.get_event("evt_001_b").start == 2.5

    def test_merge_prev_applied(self):
        """MERGE_PREV → SEGMENT_MERGE: 合并进前事件, 事件数 -1。"""
        state = _state(3)
        p = legacy_to_core({"patch_id": "m1", "opcode": "MERGE_PREV",
                            "targets": ["evt_001"],
                            "payload": {"mergeTarget": "evt_000"}})
        assert p.op == OpCode.SEGMENT_MERGE
        assert p.targets == ["evt_001", "evt_000"]
        r = PatchEngine().apply(state, p)
        assert r["status"] == "applied"
        assert len(state.ir.events) == 2
        assert state.get_event("evt_001").start == 0.0

    def test_retrigger_marks_needs_retranslate(self):
        """RETRIGGER → ANNOTATE review 槽: needs_retranslate 标记落盘。"""
        state = _state(2)
        p = legacy_to_core({"patch_id": "r1", "opcode": "RETRIGGER",
                            "targets": ["evt_001"], "payload": {}})
        r = PatchEngine().apply(state, p)
        assert r["status"] == "applied"
        es = state.get_event("evt_001")
        assert "needs_retranslate" in es.review.flags
        assert es.review.needs_human_review is True

    def test_apply_ai_suggestion_updates_translation(self):
        """APPLY_AI_SUGGESTION → UPDATE_TRANSLATION: 译文真实写入。"""
        state = _state(2)
        p = legacy_to_core({"patch_id": "a1", "opcode": "APPLY_AI_SUGGESTION",
                            "targets": ["evt_001"],
                            "payload": {"translation": "AI 建议译文"}})
        r = PatchEngine().apply(state, p)
        assert r["status"] == "applied"
        assert state.get_event("evt_001").translation.text == "AI 建议译文"

    def test_review_flags_survive_persist(self, tmp_path):
        """RETRIGGER 的 needs_retranslate 标记必须落盘 (此前 persist 丢 review 槽)。"""
        ws = str(tmp_path / "ws")
        state = _state(2)
        tl = persist_state(state, ws, "v.mp4", "en")
        PatchEngine().apply(state, Patch(
            id="r1", target_id="evt_001", op=OpCode.ANNOTATE,
            value={"review": {"flags": ["needs_retranslate"],
                              "needs_human_review": True}}))
        persist_state(state, ws, "v.mp4", "en")
        reloaded = load_state(tl)
        es = reloaded.get_event("evt_001")
        assert "needs_retranslate" in es.review.flags
        assert es.review.needs_human_review is True
        # 磁盘上也必须有 review 块 (不只内存)
        with open(tl, "r", encoding="utf-8") as f:
            import json
            raw = json.load(f)
        ev = next(e for e in raw["events"] if e["id"] == "evt_001")
        assert "needs_retranslate" in (ev.get("review") or {}).get("flags", [])




@pytest.mark.contract
class TestUndoReplay:
    """undo = pristine bak + PatchEngine 重放链[:-1] (server 端点逻辑)。"""

    def _setup(self, tmp_path):
        ws = str(tmp_path / "ws")
        extract = os.path.join(ws, "01_extract")
        os.makedirs(extract, exist_ok=True)
        state = _state(4, 2)
        tl = persist_state(state, ws, "v.mp4", "en")
        return ws, extract, tl

    def _replay_undo(self, extract, tl, log_path):
        """复刻 server undo 端点: bak → load → 重放链[:-1] → persist → save_chain。"""
        from core.runtime.timeline_io import persist_state
        bak = tl + ".bak"
        assert os.path.isfile(bak), "undo 需要 pristine bak"
        st0 = load_state(bak)
        engine = PatchEngine()
        chain = load_chain(log_path)
        removed = chain.pop()
        for p in chain:
            r = engine.apply(st0, p)
            assert r["status"] == "applied", r
        persist_state(st0, os.path.dirname(extract), "v.mp4", "en")
        save_chain(chain, log_path)
        return removed

    def test_undo_restores_merged_events(self, tmp_path):
        """MERGE 后 undo: 事件数恢复, 链回退。"""
        ws, extract, tl = self._setup(tmp_path)
        log_path = os.path.join(extract, "timeline_patches.json")

        # apply merge (与 server 一致: 链空时建 bak)
        state = load_state(tl)
        merge = Patch(id="m1", target_id="evt_000", op=OpCode.SEGMENT_MERGE,
                      value={"target_ids": ["evt_000", "evt_001"]})
        r = PatchEngine().apply(state, merge)
        assert r["status"] == "applied"
        bak = tl + ".bak"
        chain = []
        if not chain and not os.path.isfile(bak):
            shutil.copy2(tl, bak)
        chain.append(merge)
        save_chain(chain, log_path)
        persist_state(state, ws, "v.mp4", "en")
        assert len(load_state(tl).ir.events) == 3

        removed = self._replay_undo(extract, tl, log_path)
        assert removed.id == "m1"
        assert len(load_state(tl).ir.events) == 4
        assert load_chain(log_path) == []

    def test_undo_multi_level(self, tmp_path):
        """两级 undo: 逐条回退都能恢复对应状态。"""
        ws, extract, tl = self._setup(tmp_path)
        log_path = os.path.join(extract, "timeline_patches.json")
        state = load_state(tl)
        chain = []
        engine = PatchEngine()

        for i, (tid, spk) in enumerate([("evt_000", "SPK_09"), ("evt_001", "SPK_09")]):
            p = Patch(id=f"a{i}", target_id=tid, op=OpCode.ASSIGN_SPEAKER,
                      value={"speaker_id": spk})
            assert engine.apply(state, p)["status"] == "applied"
            chain.append(p)
        if not os.path.isfile(tl + ".bak"):
            shutil.copy2(tl, tl + ".bak")
        save_chain(chain, log_path)
        persist_state(state, ws, "v.mp4", "en")

        # undo 一次: evt_001 回到 SPK_01, evt_000 仍 SPK_09
        self._replay_undo(extract, tl, log_path)
        s = load_state(tl)
        assert s.get_event("evt_000").ir.speaker_ref == "SPK_09"
        assert s.get_event("evt_001").ir.speaker_ref == "SPK_01"

        # undo 第二次: 全部恢复
        self._replay_undo(extract, tl, log_path)
        s = load_state(tl)
        assert s.get_event("evt_000").ir.speaker_ref == "SPK_00"
        assert s.get_event("evt_001").ir.speaker_ref == "SPK_01"


@pytest.mark.contract
class TestSpeakerEditConvergence:
    """speaker 编辑只写 timeline.json (上游数据不污染), 注册表合并修复。"""

    def test_merge_speakers_persist(self, tmp_path):
        ws = str(tmp_path / "ws")
        state = _state(4, 2)
        tl = persist_state(state, ws, "v.mp4", "en")
        patch = Patch(id="ms", target_id="SPK_00", op=OpCode.MERGE_SPEAKERS,
                      value={"from_ids": ["SPK_01"], "into_id": "SPK_00"})
        assert PatchEngine().apply(state, patch)["status"] == "applied"
        persist_state(state, ws, "v.mp4", "en")
        reloaded = load_state(tl)
        for eid in ("evt_000", "evt_001"):
            assert reloaded.get_event(eid).ir.speaker_ref == "SPK_00"

    def test_speaker_appearance_fields_survive(self, tmp_path):
        """voice_id/color 经 persist/load 不丢失 (修复旧实现清空为 None)。"""
        ws = str(tmp_path / "ws")
        state = _state(4, 2)
        tl = persist_state(state, ws, "v.mp4", "en")
        reloaded = load_state(tl)
        node = reloaded.ir.speakers["SPK_00"]
        assert node.voice_id == "v0"
        assert node.color == "#123456"
        assert node.name == "spk0"
