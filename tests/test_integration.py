"""
Phase 9 — 集成测试 (P0-P1)

5 个关键场景: Fusion, IR→Patch→Synthesis, dual_write_verify, idempotency, chain
"""

import copy
import json
import os
from core.ir import TimelineProjectIR
from core.runtime import TimelineProjectState, SynthesisEngine, PatchEngine
from core.runtime.patch import Patch
from timeline.fusion import from_extract_result
from timeline.patch.opcode import OpCode
from timeline.patch.model import TimelinePatch
from timeline.patch.apply import apply_patch, apply_patch_chain


class TestIntegration:
    """端到端集成测试"""

    # ── 场景 1: Pipeline → Fusion → TimelineIR ──

    def test_pipeline_to_fusion(self, sample_asr_segments, sample_speaker_timeline):
        ir = from_extract_result(
            sample_asr_segments, speaker_timeline=sample_speaker_timeline,
            audio_id="integration_test", metadata={"lang": "en"},
        )
        assert ir.audio_id == "integration_test"
        assert ir.version == "1.0"
        assert len(ir.timeline) == 3
        assert ir.timeline[0].speaker == "SPEAKER_00"
        assert ir.timeline[1].speaker == "SPEAKER_01"
        assert ir.metadata["lang"] == "en"

    # ── 场景 2: IR → Patch → Synthesis ──

    def test_ir_to_patch_to_synthesis(self, sample_project):
        state = TimelineProjectState(sample_project)
        engine = PatchEngine()
        synth = SynthesisEngine()

        p = Patch(id="p1", target_id="evt_001", op="replace",
                  value={"speaker": "SPEAKER_MODIFIED"})
        engine.apply(state, p)

        results = synth.render_all(state)
        evt1 = next(r for r in results if r["id"] == "evt_001")
        assert evt1["speaker"] == "SPEAKER_MODIFIED"

    # ── 场景 3: 双写比对验证 ──

    def test_dual_write_verify_ok(self, sample_asr_segments, sample_speaker_timeline,
                                   sample_timeline_ir, tmp_path):
        from core.runtime.verify import dual_write_verify

        result = dual_write_verify(
            old_timeline=sample_timeline_ir,
            segments=sample_asr_segments,
            speaker_timeline=sample_speaker_timeline,
            output_dir=str(tmp_path),
        )
        assert result["status"] == "ok"
        assert result["diff_count"] == 0
        assert os.path.isfile(result["diff_file"])
        assert os.path.isfile(result["v2_file"])

    def test_dual_write_verify_output_files(self, sample_asr_segments,
                                              sample_speaker_timeline,
                                              sample_timeline_ir, tmp_path):
        from core.runtime.verify import dual_write_verify

        result = dual_write_verify(
            old_timeline=sample_timeline_ir,
            segments=sample_asr_segments,
            speaker_timeline=sample_speaker_timeline,
            output_dir=str(tmp_path),
        )
        with open(result["v2_file"], "r", encoding="utf-8") as f:
            v2_data = json.load(f)
        assert v2_data["version"] == "2.0"
        assert len(v2_data["events"]) == 3

    # ── 场景 4: 补丁幂等性 ──

    def test_patch_idempotency(self, sample_timeline_dicts):
        tl = copy.deepcopy(sample_timeline_dicts)
        p = TimelinePatch(patch_id="p1", opcode=OpCode.MERGE,
                          targets=["seg_001", "seg_002"])
        r1, d1 = apply_patch(tl, p)
        r2, d2 = apply_patch(tl, p)
        assert r1 == r2
        assert d1 == d2

    # ── 场景 5: 补丁链式应用 ──

    def test_patch_chain_merge_retag_translate(self, sample_timeline_dicts):
        tl = copy.deepcopy(sample_timeline_dicts)
        patches = [
            TimelinePatch(patch_id="p1", opcode=OpCode.MERGE,
                          targets=["seg_001", "seg_002"]),
            TimelinePatch(patch_id="p2", opcode=OpCode.RETAG_SPEAKER,
                          targets=["seg_001"],
                          payload={"new_speaker": "SPEAKER_99"}),
            TimelinePatch(patch_id="p3", opcode=OpCode.SET_TRANSLATION,
                          targets=["seg_001"],
                          payload={"translation": "hello world"}),
        ]
        final, diffs = apply_patch_chain(tl, patches)
        assert len(diffs) == 3
        assert len(final) == 2
        assert final[0]["speaker"] == "SPEAKER_99"
        assert final[0]["translation"] == "hello world"

    def test_patch_chain_split_then_retag(self, sample_timeline_dicts):
        tl = copy.deepcopy(sample_timeline_dicts)
        patches = [
            TimelinePatch(patch_id="p1", opcode=OpCode.SPLIT,
                          targets=["seg_001"],
                          payload={"split_point": 1.0}),
            TimelinePatch(patch_id="p2", opcode=OpCode.RETAG_SPEAKER,
                          targets=["seg_001a"],
                          payload={"new_speaker": "SPEAKER_NEW"}),
        ]
        final, diffs = apply_patch_chain(tl, patches)
        assert len(diffs) == 2
        assert len(final) == 4
        seg_a = next(s for s in final if s["id"] == "seg_001a")
        assert seg_a["speaker"] == "SPEAKER_NEW"
