"""
双写测试 — 宽松 + 严格双层策略

宽松测试 (test_dual_write_*): 记录已知差异，允许 status 为 "ok" 或 "diff"。
严格测试 (test_dual_write_*_must_be_ok): 语义等价的补丁必须返回 "ok"，
作为 CI 一致性 gate。如果当前实现无法达到，标记 xfail 并附 issue。
"""

import pytest
from timeline.patch.opcode import OpCode
from timeline.patch.model import TimelinePatch
from timeline.dual_write import dual_write_patch, _map_opcode


# ═══════════════════════════════════════════════════════════
# 宽松测试 — 记录已知差异，不硬性断言 "ok"
# ═══════════════════════════════════════════════════════════

class TestDualWrite:
    """宽松测试: 允许 "diff" 状态，用于发现未知差异"""

    def test_dual_write_ok(self, sample_timeline_ir):
        """SET_TRANSLATION: 允许 diff — 翻译字段在新旧 IR 中路径不同"""
        patch = TimelinePatch(
            patch_id="p1", opcode=OpCode.SET_TRANSLATION,
            targets=["seg_001"], payload={"translation": "hello world"},
        )
        result = dual_write_patch(sample_timeline_ir, patch)
        assert result["status"] in ("ok", "diff")

    def test_dual_write_retag(self, sample_timeline_ir):
        """RETAG_SPEAKER: 允许 diff — speaker 在新 IR 中通过 derivatives 表达"""
        patch = TimelinePatch(
            patch_id="p1", opcode=OpCode.RETAG_SPEAKER,
            targets=["seg_001"], payload={"new_speaker": "SPEAKER_99"},
        )
        result = dual_write_patch(sample_timeline_ir, patch)
        assert result["status"] in ("ok", "diff")

    def test_dual_write_with_project_ir(self, sample_timeline_ir):
        """预传入 project_ir: 允许 diff — 跳过 to_project_ir 内部调用"""
        from timeline.fusion import to_project_ir
        proj = to_project_ir(sample_timeline_ir)
        patch = TimelinePatch(
            patch_id="p1", opcode=OpCode.RETAG_SPEAKER,
            targets=["seg_001"], payload={"new_speaker": "SPEAKER_99"},
        )
        result = dual_write_patch(sample_timeline_ir, patch, project_ir=proj)
        assert result["status"] in ("ok", "diff")

    def test_dual_write_returns_diff_count(self, sample_timeline_ir):
        """验证返回结构包含 diff_count 和 diffs 字段"""
        patch = TimelinePatch(
            patch_id="p1", opcode=OpCode.RETAG_SPEAKER,
            targets=["seg_001"], payload={"new_speaker": "SPEAKER_99"},
        )
        result = dual_write_patch(sample_timeline_ir, patch)
        assert "diff_count" in result
        assert "diffs" in result


# ═══════════════════════════════════════════════════════════
# 严格测试 — 语义等价补丁必须返回 "ok"
# ═══════════════════════════════════════════════════════════

class TestDualWriteStrict:
    """严格测试: 断言 status == "ok"，CI 一致性 gate"""

    def test_dual_write_retag_speaker_must_be_ok(self, sample_timeline_ir):
        """RETAG_SPEAKER 语义明确等价 — 双写必须返回 ok"""
        patch = TimelinePatch(
            patch_id="p1", opcode=OpCode.RETAG_SPEAKER,
            targets=["seg_001"], payload={"new_speaker": "SPEAKER_99"},
        )
        result = dual_write_patch(sample_timeline_ir, patch)
        assert result["status"] == "ok", f"Expected ok, got {result['status']}: {result.get('diffs', [])}"

    def test_dual_write_split(self, sample_timeline_ir):
        """SPLIT: 允许 diff — 旧引擎按 word 拆分 text，新引擎保留 text_ref"""
        patch = TimelinePatch(
            patch_id="p1", opcode=OpCode.SPLIT,
            targets=["seg_001"], payload={"split_point": 1.0},
        )
        result = dual_write_patch(sample_timeline_ir, patch)
        assert result["status"] in ("ok", "diff")


# ═══════════════════════════════════════════════════════════
# OpCode 映射测试
# ═══════════════════════════════════════════════════════════

class TestOpcodeMapping:
    """_map_opcode 参数化测试 — 覆盖全部 6 种 OpCode"""

    @pytest.mark.parametrize("opcode_str, expected_op", [
        ("MERGE", "merge"),
        ("SPLIT", "segment_split"),
        ("RETAG_SPEAKER", "replace"),
        ("SET_TRANSLATION", "replace"),
        ("RELINK_WORDS", "propagate"),
        ("ANNOTATE", "replace"),
    ])
    def test_opcode_mapping(self, opcode_str, expected_op):
        """每种 OpCode 映射到正确的新引擎 op"""
        assert _map_opcode(opcode_str) == expected_op

    def test_unknown_opcode_fallback(self):
        """未知 opcode 回退为 replace"""
        assert _map_opcode("UNKNOWN_OP") == "replace"
