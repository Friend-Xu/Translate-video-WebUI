"""
Phase 5 — 补丁系统单元测试 (P1) — Phase 4 裁剪: apply 已退役, 保留 opcode/model
"""

import copy
import pytest
from timeline.patch.opcode import OpCode, is_valid_opcode, PAYLOAD_SCHEMA
from timeline.patch.model import TimelinePatch


class TestOpCode:
    """OpCode 枚举 — 7 种固定 opcode"""

    def test_all_seven_values(self):
        values = {o.value for o in OpCode}
        assert values == {"MERGE", "SPLIT", "RETAG_SPEAKER", "SET_TRANSLATION",
                          "RELINK_WORDS", "ANNOTATE", "RESIZE"}

    def test_is_valid_opcode(self):
        assert is_valid_opcode("MERGE") is True
        assert is_valid_opcode("UNKNOWN") is False

    def test_payload_schema_has_all_opcodes(self):
        for op in OpCode:
            assert op in PAYLOAD_SCHEMA


class TestTimelinePatch:
    """TimelinePatch — 补丁模型"""

    def test_construct_normal(self):
        p = TimelinePatch(
            patch_id="patch_001", opcode=OpCode.MERGE,
            targets=["seg_001", "seg_002"],
        )
        assert p.patch_id == "patch_001"
        assert p.opcode == OpCode.MERGE
        assert p.targets == ["seg_001", "seg_002"]

    def test_defaults_auto_filled(self):
        p = TimelinePatch(patch_id="p1", opcode=OpCode.MERGE, targets=["s1", "s2"])
        assert p.timestamp != ""
        assert p.idempotency_key != ""
        assert p.author == "system"

    def test_to_dict_and_from_dict_roundtrip(self):
        p = TimelinePatch(
            patch_id="p1", opcode=OpCode.RETAG_SPEAKER,
            targets=["seg_001"], payload={"new_speaker": "SPEAKER_99"},
            reason=["Mistake"], score=0.85, confidence=0.9, author="user",
        )
        d = p.to_dict()
        p2 = TimelinePatch.from_dict(d)
        assert p2.patch_id == p.patch_id
        assert p2.opcode == p.opcode
        assert p2.targets == p.targets
        assert p2.payload == p.payload
        assert p2.score == p.score
        assert p2.confidence == p.confidence
        assert p2.author == p.author

    def test_confidence_label_high(self):
        p = TimelinePatch(patch_id="p1", opcode=OpCode.MERGE, targets=["a", "b"],
                          confidence=0.95)
        assert p.confidence_label == "high"

    def test_confidence_label_medium(self):
        p = TimelinePatch(patch_id="p1", opcode=OpCode.MERGE, targets=["a", "b"],
                          confidence=0.75)
        assert p.confidence_label == "medium"

    def test_confidence_label_low(self):
        p = TimelinePatch(patch_id="p1", opcode=OpCode.MERGE, targets=["a", "b"],
                          confidence=0.5)
        assert p.confidence_label == "low"

    def test_confidence_label_boundary_high(self):
        p = TimelinePatch(patch_id="p1", opcode=OpCode.MERGE, targets=["a", "b"],
                          confidence=0.91)
        assert p.confidence_label == "high"

    def test_confidence_label_boundary_medium(self):
        p = TimelinePatch(patch_id="p1", opcode=OpCode.MERGE, targets=["a", "b"],
                          confidence=0.70)
        assert p.confidence_label == "medium"

    def test_idempotency_key_deterministic(self):
        p1 = TimelinePatch(patch_id="a", opcode=OpCode.MERGE,
                           targets=["s1", "s2"], payload={"x": 1})
        p2 = TimelinePatch(patch_id="b", opcode=OpCode.MERGE,
                           targets=["s1", "s2"], payload={"x": 1})
        assert p1.idempotency_key == p2.idempotency_key

    def test_idempotency_key_different_for_different_input(self):
        p1 = TimelinePatch(patch_id="a", opcode=OpCode.MERGE, targets=["s1", "s2"])
        p2 = TimelinePatch(patch_id="b", opcode=OpCode.MERGE, targets=["s3", "s4"])
        assert p1.idempotency_key != p2.idempotency_key

    def test_from_dict_with_string_opcode(self):
        d = {"patch_id": "p1", "opcode": "MERGE", "targets": ["a", "b"]}
        p = TimelinePatch.from_dict(d)
        assert p.opcode == OpCode.MERGE

