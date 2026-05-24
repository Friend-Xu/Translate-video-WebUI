"""
Phase 8 — 安全阀门 + 快照恢复单元测试 (P2)

覆盖: gate_check, should_snapshot, create_snapshot, restore_from_snapshot, replay_from_snapshot
"""

import copy
import pytest
from timeline.patch.opcode import OpCode
from timeline.patch.model import TimelinePatch
from timeline.patch.apply import apply_patch
from timeline.safety.guard import gate_check, GateRejection
from timeline.recovery.snapshot import (
    should_snapshot, create_snapshot, restore_from_snapshot, replay_from_snapshot,
)


class TestGateCheck:
    """gate_check — 补丁应用前安全校验"""

    def test_unknown_opcode_raises(self, sample_timeline_dicts):
        p = TimelinePatch(patch_id="p1", opcode=OpCode.MERGE, targets=["seg_001"])
        # 用 MagicMock 模拟 opcode 为非 OpCode 枚举的字符串
        from unittest.mock import MagicMock
        p.opcode = MagicMock()
        p.opcode.value = "INVALID_OP"
        with pytest.raises(GateRejection, match="unknown_opcode"):
            gate_check(p, sample_timeline_dicts)

    def test_invalid_target_raises(self, sample_timeline_dicts):
        p = TimelinePatch(patch_id="p1", opcode=OpCode.MERGE, targets=["seg_999"])
        with pytest.raises(GateRejection, match="invalid_target"):
            gate_check(p, sample_timeline_dicts)

    def test_confidence_out_of_bounds_raises(self, sample_timeline_dicts):
        p = TimelinePatch(patch_id="p1", opcode=OpCode.MERGE,
                          targets=["seg_001"], confidence=1.5)
        with pytest.raises(GateRejection, match="invalid_confidence"):
            gate_check(p, sample_timeline_dicts)

    def test_negative_confidence_raises(self, sample_timeline_dicts):
        p = TimelinePatch(patch_id="p1", opcode=OpCode.MERGE,
                          targets=["seg_001"], confidence=-0.1)
        with pytest.raises(GateRejection):
            gate_check(p, sample_timeline_dicts)

    def test_valid_patch_passes(self, sample_timeline_dicts):
        p = TimelinePatch(patch_id="p1", opcode=OpCode.MERGE,
                          targets=["seg_001", "seg_002"], confidence=0.8)
        gate_check(p, sample_timeline_dicts)

    def test_confidence_zero_passes(self, sample_timeline_dicts):
        p = TimelinePatch(patch_id="p1", opcode=OpCode.MERGE,
                          targets=["seg_001", "seg_002"], confidence=0.0)
        gate_check(p, sample_timeline_dicts)

    def test_confidence_one_passes(self, sample_timeline_dicts):
        p = TimelinePatch(patch_id="p1", opcode=OpCode.MERGE,
                          targets=["seg_001", "seg_002"], confidence=1.0)
        gate_check(p, sample_timeline_dicts)


class TestSnapshot:
    """snapshot — 快照保存与恢复"""

    def test_should_snapshot_at_10(self):
        assert should_snapshot(10) is True
        assert should_snapshot(20) is True

    def test_should_not_snapshot_below_10(self):
        for n in [0, 1, 5, 9]:
            assert should_snapshot(n) is False

    def test_should_not_snapshot_at_11(self):
        assert should_snapshot(11) is False

    def test_create_snapshot(self, sample_timeline_dicts):
        p = TimelinePatch(patch_id="p1", opcode=OpCode.MERGE,
                          targets=["seg_001", "seg_002"])
        snap = create_snapshot(sample_timeline_dicts, [p])
        assert snap["patch_count"] == 1
        assert snap["last_patch_id"] == "p1"
        assert len(snap["timeline"]) == 3

    def test_create_snapshot_empty_patches(self, sample_timeline_dicts):
        snap = create_snapshot(sample_timeline_dicts, [])
        assert snap["last_patch_id"] is None

    def test_restore_from_snapshot(self, sample_timeline_dicts):
        snap = create_snapshot(sample_timeline_dicts, [])
        restored = restore_from_snapshot(snap)
        assert restored == sample_timeline_dicts

    def test_restore_is_deep_copy(self, sample_timeline_dicts):
        snap = create_snapshot(sample_timeline_dicts, [])
        restored = restore_from_snapshot(snap)
        restored[0]["text"] = "CHANGED"
        assert snap["timeline"][0]["text"] != "CHANGED"

    def test_replay_from_snapshot(self, sample_timeline_dicts):
        tl0 = copy.deepcopy(sample_timeline_dicts)
        p1 = TimelinePatch(patch_id="p1", opcode=OpCode.RETAG_SPEAKER,
                           targets=["seg_001"],
                           payload={"new_speaker": "SPEAKER_99"})
        tl1, _ = apply_patch(tl0, p1)
        snap = create_snapshot(tl1, [p1])  # snapshot 存储已应用 p1 的 timeline
        p2 = TimelinePatch(patch_id="p2", opcode=OpCode.SET_TRANSLATION,
                           targets=["seg_001"],
                           payload={"translation": "hello"})
        result = replay_from_snapshot(snap, [p1, p2])
        assert result[0]["speaker"] == "SPEAKER_99"
        assert result[0]["translation"] == "hello"
