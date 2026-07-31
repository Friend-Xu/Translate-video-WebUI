"""
ConfigResolver 三级合并测试 (批次10)
"""
import pytest
from core.config.global_config import GlobalConfig
from core.config import SLOT_DEFAULTS
from core.runtime.config_resolver import ConfigResolver
from core.runtime.project_state import TimelineProjectState
from core.ir.project import TimelineProjectIR
from core.ir.timeline_event import TimelineEventIR


@pytest.mark.unit
class TestConfigResolver:

    def _make_state(self):
        evts = {"evt_001": TimelineEventIR(id="evt_001", start=0.0, end=1.0, speaker_ref=None, text_ref="hi")}
        return TimelineProjectState(TimelineProjectIR(events=evts))

    def test_global_defaults(self):
        resolved = ConfigResolver(GlobalConfig()).resolve_event_config("evt_001", "tts", self._make_state())
        assert "engine" in resolved
        assert resolved["engine"] == "chattts"

    def test_event_override(self):
        state = self._make_state()
        state.get_event("evt_001").tts.config = {"speed_factor": 1.5}
        resolved = ConfigResolver(GlobalConfig()).resolve_event_config("evt_001", "tts", state)
        assert resolved["speed_factor"] == 1.5
        assert resolved["engine"] == "chattts"

    def test_null_deletion(self):
        state = self._make_state()
        state.get_event("evt_001").tts.config = {"engine": None}
        resolved = ConfigResolver(GlobalConfig()).resolve_event_config("evt_001", "tts", state)
        assert resolved["engine"] == "chattts"  # null restores global default

    def test_slots_count(self):
        assert len(SLOT_DEFAULTS) == 10

    def test_translation_lang(self):
        resolved = ConfigResolver(GlobalConfig()).resolve_event_config("evt_001", "translation", self._make_state())
        assert "lang" in resolved
