"""test_dual_write — dual_write_patch 成功 + 差异场景"""
from timeline.patch.opcode import OpCode
from timeline.patch.model import TimelinePatch
from timeline.dual_write import dual_write_patch


class TestDualWrite:
    def test_dual_write_ok(self, sample_timeline_ir):
        patch = TimelinePatch(
            patch_id="p1", opcode=OpCode.SET_TRANSLATION,
            targets=["seg_001"], payload={"translation": "hello world"},
        )
        result = dual_write_patch(sample_timeline_ir, patch)
        assert result["status"] in ("ok", "diff")

    def test_dual_write_retag(self, sample_timeline_ir):
        patch = TimelinePatch(
            patch_id="p1", opcode=OpCode.RETAG_SPEAKER,
            targets=["seg_001"], payload={"new_speaker": "SPEAKER_99"},
        )
        result = dual_write_patch(sample_timeline_ir, patch)
        assert result["status"] in ("ok", "diff")

    def test_dual_write_with_project_ir(self, sample_timeline_ir):
        from timeline.fusion import to_project_ir
        proj = to_project_ir(sample_timeline_ir)
        patch = TimelinePatch(
            patch_id="p1", opcode=OpCode.RETAG_SPEAKER,
            targets=["seg_001"], payload={"new_speaker": "SPEAKER_99"},
        )
        result = dual_write_patch(sample_timeline_ir, patch, project_ir=proj)
        assert result["status"] in ("ok", "diff")

    def test_dual_write_returns_diff_count(self, sample_timeline_ir):
        patch = TimelinePatch(
            patch_id="p1", opcode=OpCode.RETAG_SPEAKER,
            targets=["seg_001"], payload={"new_speaker": "SPEAKER_99"},
        )
        result = dual_write_patch(sample_timeline_ir, patch)
        assert "diff_count" in result
        assert "diffs" in result
