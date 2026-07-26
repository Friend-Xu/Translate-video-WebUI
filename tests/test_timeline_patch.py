"""
Phase 5 — 补丁系统单元测试 (P1)

覆盖: TimelinePatch 模型, apply_patch (6 种 OpCode), apply_patch_chain
"""

import copy
import pytest
from timeline.patch.opcode import OpCode, is_valid_opcode, PAYLOAD_SCHEMA
from timeline.patch.model import TimelinePatch
from timeline.patch.apply import apply_patch, apply_patch_chain


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


class TestApplyPatch:
    """apply_patch — 补丁执行 (6 种 OpCode)"""

    # ── MERGE ──

    def test_merge_two_segments(self, sample_timeline_dicts):
        tl = copy.deepcopy(sample_timeline_dicts)
        p = TimelinePatch(patch_id="p1", opcode=OpCode.MERGE,
                          targets=["seg_001", "seg_002"])
        new_tl, diff = apply_patch(tl, p)
        assert len(new_tl) == 2
        assert new_tl[0]["id"] == "seg_001"
        assert new_tl[0]["end"] == 5.0
        assert new_tl[0]["text"] == "Hello world How are you"
        assert diff["op"] == "merge"

    def test_merge_requires_2_targets(self, sample_timeline_dicts):
        tl = copy.deepcopy(sample_timeline_dicts)
        p = TimelinePatch(patch_id="p1", opcode=OpCode.MERGE, targets=["seg_001"])
        new_tl, diff = apply_patch(tl, p)
        assert "error" in diff
        assert len(new_tl) == 3

    def test_merge_multiple_segments(self, sample_timeline_dicts):
        tl = copy.deepcopy(sample_timeline_dicts)
        p = TimelinePatch(patch_id="p1", opcode=OpCode.MERGE,
                          targets=["seg_001", "seg_002", "seg_003"])
        new_tl, _ = apply_patch(tl, p)
        assert len(new_tl) == 1

    # ── SPLIT ──

    def test_split_at_point(self, sample_timeline_dicts):
        tl = copy.deepcopy(sample_timeline_dicts)
        p = TimelinePatch(patch_id="p1", opcode=OpCode.SPLIT,
                          targets=["seg_001"], payload={"split_point": 1.0})
        new_tl, diff = apply_patch(tl, p)
        assert len(new_tl) == 4
        assert new_tl[0]["end"] == 1.0
        assert new_tl[1]["start"] == 1.0
        assert diff["op"] == "split"

    def test_split_requires_exactly_1_target(self, sample_timeline_dicts):
        tl = copy.deepcopy(sample_timeline_dicts)
        p = TimelinePatch(patch_id="p1", opcode=OpCode.SPLIT,
                          targets=["seg_001", "seg_002"])
        _, diff = apply_patch(tl, p)
        assert "error" in diff

    def test_split_default_midpoint(self, sample_timeline_dicts):
        tl = copy.deepcopy(sample_timeline_dicts)
        p = TimelinePatch(patch_id="p1", opcode=OpCode.SPLIT,
                          targets=["seg_001"], payload={})
        new_tl, _ = apply_patch(tl, p)
        assert len(new_tl) == 4
        assert new_tl[0]["end"] == pytest.approx(1.25)

    # ── RETAG_SPEAKER ──

    def test_retag_speaker(self, sample_timeline_dicts):
        tl = copy.deepcopy(sample_timeline_dicts)
        p = TimelinePatch(patch_id="p1", opcode=OpCode.RETAG_SPEAKER,
                          targets=["seg_001"],
                          payload={"new_speaker": "SPEAKER_99"})
        new_tl, diff = apply_patch(tl, p)
        assert new_tl[0]["speaker"] == "SPEAKER_99"
        assert diff["op"] == "retag"

    def test_retag_updates_word_speakers(self, sample_timeline_dicts):
        tl = copy.deepcopy(sample_timeline_dicts)
        p = TimelinePatch(patch_id="p1", opcode=OpCode.RETAG_SPEAKER,
                          targets=["seg_001"],
                          payload={"new_speaker": "SPEAKER_99"})
        new_tl, _ = apply_patch(tl, p)
        for w in new_tl[0]["words"]:
            assert w["speaker"] == "SPEAKER_99"

    # ── SET_TRANSLATION ──

    def test_set_translation(self, sample_timeline_dicts):
        tl = copy.deepcopy(sample_timeline_dicts)
        p = TimelinePatch(patch_id="p1", opcode=OpCode.SET_TRANSLATION,
                          targets=["seg_001"],
                          payload={"translation": "hello"})
        new_tl, diff = apply_patch(tl, p)
        assert new_tl[0]["translation"] == "hello"
        assert diff["op"] == "set_translation"

    # ── RELINK_WORDS ──

    def test_relink_words(self, sample_timeline_dicts):
        tl = copy.deepcopy(sample_timeline_dicts)
        p = TimelinePatch(patch_id="p1", opcode=OpCode.RELINK_WORDS,
                          targets=["seg_001"],
                          payload={"word_mapping": {"world": "seg_002"}})
        new_tl, diff = apply_patch(tl, p)
        assert diff["op"] == "relink_words"
        seg1_words = [w["word"] for w in new_tl[0]["words"]]
        assert "world" not in seg1_words

    # ── ANNOTATE ──

    def test_annotate(self, sample_timeline_dicts):
        tl = copy.deepcopy(sample_timeline_dicts)
        p = TimelinePatch(patch_id="p1", opcode=OpCode.ANNOTATE,
                          targets=["seg_001"],
                          payload={"key": "verified", "value": True})
        new_tl, diff = apply_patch(tl, p)
        assert new_tl[0]["annotations"]["verified"] is True
        assert diff["op"] == "annotate"

    # ── Non-destructive ──

    def test_original_not_mutated(self, sample_timeline_dicts):
        tl = copy.deepcopy(sample_timeline_dicts)
        original = copy.deepcopy(tl)
        p = TimelinePatch(patch_id="p1", opcode=OpCode.RETAG_SPEAKER,
                          targets=["seg_001"],
                          payload={"new_speaker": "CHANGED"})
        apply_patch(tl, p)
        assert tl == original

    # ── Idempotency ──

    def test_same_patch_twice_same_result(self, sample_timeline_dicts):
        tl = copy.deepcopy(sample_timeline_dicts)
        p = TimelinePatch(patch_id="p1", opcode=OpCode.RETAG_SPEAKER,
                          targets=["seg_001"],
                          payload={"new_speaker": "SPEAKER_99"})
        r1, _ = apply_patch(tl, p)
        r2, _ = apply_patch(tl, p)
        assert r1 == r2

    # ── apply_patch_chain ──

    def test_apply_patch_chain(self, sample_timeline_dicts):
        tl = copy.deepcopy(sample_timeline_dicts)
        p1 = TimelinePatch(patch_id="p1", opcode=OpCode.RETAG_SPEAKER,
                           targets=["seg_001"],
                           payload={"new_speaker": "SPEAKER_99"})
        p2 = TimelinePatch(patch_id="p2", opcode=OpCode.SET_TRANSLATION,
                           targets=["seg_001"],
                           payload={"translation": "hello"})
        final, diffs = apply_patch_chain(tl, [p1, p2])
        assert len(diffs) == 2
        assert final[0]["speaker"] == "SPEAKER_99"
        assert final[0]["translation"] == "hello"

    def test_apply_patch_chain_empty(self, sample_timeline_dicts):
        tl = copy.deepcopy(sample_timeline_dicts)
        final, diffs = apply_patch_chain(tl, [])
        assert final == tl
        assert diffs == []
