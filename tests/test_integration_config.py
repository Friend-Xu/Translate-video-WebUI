"""tests/test_integration_config.py — 端到端集成测试 (Phase 7, 定稿 §13.2)."""
from __future__ import annotations
import pytest

class TestConfigE2E:
    """End-to-end: IR store -> Patch apply -> Config resolve -> Adapter inject."""

    def test_full_config_flow(self):
        from core.config.global_config import GlobalConfig
        from core.runtime.config_resolver import ConfigResolver, deep_merge
        from core.runtime.patch import Patch, OpCode
        from core.runtime.patch_engine import PatchEngine
        from core.runtime.project_state import TimelineProjectState
        from core.ir.timeline_event import TimelineEventIR
        from core.ir.speaker import SpeakerNodeIR
        from core.ir.project import TimelineProjectIR

        # Setup
        events = {"evt_001": TimelineEventIR(id="evt_001", start=0.0, end=2.5, speaker_ref="SPK_A", text_ref="Hi")}
        speakers = {"SPK_A": SpeakerNodeIR(id="SPK_A", name="Alice", config={"tts": {"engine": "cosyvoice"}})}
        ir = TimelineProjectIR(events=events, speakers=speakers)
        state = TimelineProjectState(ir)
        gc = GlobalConfig()
        resolver = ConfigResolver(gc)
        engine = PatchEngine()

        # Step 1: Resolve TTS config — should get speaker-level engine
        resolved = resolver.resolve_event_config("evt_001", "tts", state)
        assert resolved["engine"] == "cosyvoice"

        # Step 2: Apply OVERRIDE_CONFIG — event-level override
        patch = Patch(id="p1", target_id="evt_001", op=OpCode.OVERRIDE_CONFIG,
                      value={"slot": "tts", "partial_config": {"speed_factor": 1.8}}, author="user", confidence=1.0)
        result = engine.apply(state, patch)
        assert result["status"] == "applied"
        # v3.0: previous_state records the RAW config before override (None when key absent)
        assert result.get("previous_state", {}).get("speed_factor") is None

        # Step 3: Resolve again — event override should win
        resolved2 = resolver.resolve_event_config("evt_001", "tts", state)
        assert resolved2["speed_factor"] == 1.8
        assert resolved2["engine"] == "cosyvoice"

        # Step 4: RESET_CONFIG — remove speed_factor override
        reset = Patch(id="r1", target_id="evt_001", op=OpCode.RESET_CONFIG,
                      value={"slot": "tts", "fields": ["speed_factor"]}, author="user")
        engine.apply(state, reset)
        resolved3 = resolver.resolve_event_config("evt_001", "tts", state)
        assert resolved3["speed_factor"] == 1.0  # back to global default

    def test_undo_chain(self):
        from core.runtime.config_resolver import deep_merge
        from core.runtime.snapshot_manager import generate_undo_patch
        from core.runtime.patch import Patch, OpCode

        original = Patch(id="orig", target_id="evt_001", op=OpCode.OVERRIDE_CONFIG,
                         value={"slot": "tts", "partial_config": {"speed_factor": 0.5}}, author="user")
        prev_state = {"speed_factor": 1.0}
        undo = generate_undo_patch(original, prev_state)
        assert undo.op == OpCode.OVERRIDE_CONFIG
        assert undo.value["partial_config"] == prev_state
        assert undo.author == "undo"

    def test_slot_dependency_graph(self):
        from core.runtime.slot_dependency import SlotLevelDependencyGraph
        from core.runtime.project_state import TimelineProjectState
        from core.ir.timeline_event import TimelineEventIR
        from core.ir.project import TimelineProjectIR

        events = {"evt_001": TimelineEventIR(id="evt_001", start=0.0, end=1.0, text_ref="X", speaker_ref=None)}
        state = TimelineProjectState(TimelineProjectIR(events=events))

        sdg = SlotLevelDependencyGraph()
        dirty = sdg.propagate_dirty("evt_001", "tts", state)
        dirty_slots = {s for _, s in dirty}
        assert "tts" in dirty_slots
        assert "translation" not in dirty_slots  # tts change does NOT dirty translation

        dirty2 = sdg.propagate_dirty("evt_001", "asr", state)
        dirty_slots2 = {s for _, s in dirty2}
        assert "translation" in dirty_slots2  # asr change DOES dirty translation
        assert "tts" in dirty_slots2

    def test_schema_validation(self):
        import os
        from core.config.schema_loader import SchemaLoader
        schema_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "schemas", "ir_v2")
        loader = SchemaLoader(schema_dir)
        ok1, _ = loader.validate("tts_routing", {"engine": "cosyvoice", "speed_factor": 1.2})
        assert ok1
        ok2, err = loader.validate("tts_routing", {"engine": "invalid_xyz"})
        assert not ok2
