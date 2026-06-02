"""tests/test_patch_engine_config.py — Patch Engine config OpCode tests
AC-PE-01 ~ AC-PE-05 (定稿 §12.8). TDD: all FAIL before Batch B implementation.
"""
from __future__ import annotations
import pytest
from core.runtime.patch import Patch, OpCode
from core.runtime.project_state import TimelineProjectState
from core.runtime.patch_engine import PatchEngine
from core.ir.timeline_event import TimelineEventIR
from core.ir.speaker import SpeakerNodeIR
from core.ir.project import TimelineProjectIR

@pytest.fixture
def simple_state():
    events = {
        "evt_001": TimelineEventIR(id="evt_001", start=0.0, end=2.5, speaker_ref="SPEAKER_00", text_ref="Hello"),
        "evt_002": TimelineEventIR(id="evt_002", start=3.0, end=5.0, speaker_ref="SPEAKER_01", text_ref="World"),
        "evt_003": TimelineEventIR(id="evt_003", start=5.5, end=8.0, speaker_ref="SPEAKER_00", text_ref="Test"),
    }
    speakers = {"SPEAKER_00": SpeakerNodeIR(id="SPEAKER_00", name="A"), "SPEAKER_01": SpeakerNodeIR(id="SPEAKER_01", name="B")}
    return TimelineProjectState(TimelineProjectIR(events=events, speakers=speakers))

@pytest.fixture
def patch_engine():
    return PatchEngine()

class TestOverrideIncrementalSnapshot:
    def test_override_records_previous_state(self, simple_state, patch_engine):
        patch = Patch(id="p001", target_id="evt_001", op=OpCode.OVERRIDE_CONFIG, value={"slot": "tts", "partial_config": {"speed_factor": 1.5}}, author="user", confidence=1.0)
        result = patch_engine.apply(simple_state, patch)
        assert result["status"] == "applied"
        assert result["op"] == "override_config"
        prev = result.get("previous_state", {})
        # v3.0: previous_state records previous RAW config (None when key absent)
        assert prev.get("speed_factor") is None

    def test_override_only_dirties_target_slot(self, simple_state, patch_engine):
        patch = Patch(id="p002", target_id="evt_001", op=OpCode.OVERRIDE_CONFIG, value={"slot": "tts", "partial_config": {"speed_factor": 1.5}}, author="user")
        result = patch_engine.apply(simple_state, patch)
        dirty = result.get("dirty_slots", [])
        has_tts = any("tts" in str(d) for d in dirty)
        has_tr = any("translation" in str(d) for d in dirty)
        assert has_tts
        assert not has_tr

class TestConfigUndo:
    def test_undo_restores_value(self, simple_state, patch_engine):
        es = simple_state.get_event("evt_001")
        p1 = Patch(id="u010", target_id="evt_001", op=OpCode.OVERRIDE_CONFIG, value={"slot": "tts", "partial_config": {"speed_factor": 1.5}}, author="user")
        r1 = patch_engine.apply(simple_state, p1)
        prev = r1.get("previous_state", {})
        undo = Patch(id="undo010", target_id="evt_001", op=OpCode.OVERRIDE_CONFIG, value={"slot": "tts", "partial_config": prev}, author="undo")
        patch_engine.apply(simple_state, undo)
        # v3.0: undo restores previous RAW config (None). ConfigResolver handles null→inherit.
        assert es.tts["config"].get("speed_factor") is None

class TestSchemaReject:
    def test_reject_invalid_enum(self, simple_state, patch_engine):
        p = Patch(id="bad1", target_id="evt_001", op=OpCode.OVERRIDE_CONFIG, value={"slot": "tts_routing", "partial_config": {"engine": "invalid_xyz"}}, author="user")
        assert patch_engine.apply(simple_state, p)["status"] != "applied"

class TestBulkPatches:
    def test_60_patches(self, simple_state, patch_engine):
        for i in range(60):
            p = Patch(id="bulk_%03d" % i, target_id="evt_001", op=OpCode.OVERRIDE_CONFIG, value={"slot": "tts", "partial_config": {"speed_factor": 1.0 + i * 0.01}}, author="system")
            assert patch_engine.apply(simple_state, p)["status"] == "applied"
        assert len(simple_state.get_event("evt_001").patches) == 60

class TestResetConfig:
    def test_reset_full(self, simple_state, patch_engine):
        es = simple_state.get_event("evt_001")
        patch_engine.apply(simple_state, Patch(id="s1", target_id="evt_001", op=OpCode.OVERRIDE_CONFIG, value={"slot": "tts", "partial_config": {"engine": "edge"}}, author="user"))
        patch_engine.apply(simple_state, Patch(id="r1", target_id="evt_001", op=OpCode.RESET_CONFIG, value={"slot": "tts"}, author="user"))
        assert es.tts["config"] == {}

class TestBatchSetConfig:
    def test_batch_multi(self, simple_state, patch_engine):
        patch_engine.apply(simple_state, Patch(id="b1", target_id="evt_001", op=OpCode.BATCH_SET_CONFIG, targets=["evt_001", "evt_002"], value={"slot": "translation", "config_block": {"lang": "ja"}}, author="user"))
        for eid in ["evt_001", "evt_002"]:
            assert simple_state.get_event(eid).translation["config"].get("lang") == "ja"
