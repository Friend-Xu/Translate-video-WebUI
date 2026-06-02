"""
Schema 契约测试 — timeline.schema.json v2.0 (批次7)
"""
import pytest
from core.testing.schema_validator import validate_json, assert_valid_timeline_v2
from core.runtime.synthesis import SynthesisEngine


_MIN_PROJECT = {"id": "proj", "source_video": "v.mp4", "source_lang": "en", "target_lang": "zh"}


@pytest.mark.schema
class TestTimelineSchemaV2:

    def test_minimal_valid(self):
        data = {
            "schema_version": "2.0", "project": _MIN_PROJECT,
            "events": [{"id": "evt_001", "start": 0.0, "end": 1.0, "text": "hello"}],
            "speakers": {}, "metadata": {},
        }
        ok, errs = validate_json(data, "timeline")
        assert ok, f"Should be valid: {errs}"

    def test_full_valid(self):
        data = {
            "schema_version": "2.0",
            "project": {"id": "proj", "source_video": "v.mp4", "source_lang": "en", "target_lang": "zh"},
            "events": [
                {"id": "evt_001", "start": 0.0, "end": 2.5, "text": "Hello world",
                 "speaker": "SPEAKER_00", "translation": "你好",
                 "confidence": 0.95, "source": "asr"},
            ],
            "speakers": {"SPEAKER_00": {"id": "SPEAKER_00", "name": "Speaker"}},
            "metadata": {},
        }
        ok, errs = validate_json(data, "timeline")
        assert ok, f"Should be valid: {errs}"

    def test_missing_required_id_fails(self):
        data = {
            "schema_version": "2.0", "project": _MIN_PROJECT,
            "events": [{"start": 0.0, "end": 1.0, "text": "hello"}],
            "speakers": {}, "metadata": {},
        }
        ok, _ = validate_json(data, "timeline")
        assert not ok

    def test_negative_start_fails(self):
        data = {
            "schema_version": "2.0", "project": _MIN_PROJECT,
            "events": [{"id": "e1", "start": -1.0, "end": 1.0, "text": "hello"}],
            "speakers": {}, "metadata": {},
        }
        ok, _ = validate_json(data, "timeline")
        assert not ok

    def test_invalid_review_status_fails(self):
        """schema enum for review_status rejects unknown values."""
        data = {
            "schema_version": "2.0", "project": _MIN_PROJECT,
            "events": [{"id": "e1", "start": 0.0, "end": 1.0, "text": "hello",
                        "review_status": "INVALID_STATUS"}],
            "speakers": {}, "metadata": {},
        }
        ok, _ = validate_json(data, "timeline")
        assert not ok

    def test_empty_events_valid(self):
        data = {"schema_version": "2.0", "project": _MIN_PROJECT, "events": [], "speakers": {}, "metadata": {}}
        ok, errs = validate_json(data, "timeline")
        assert ok, f"Empty events should be valid: {errs}"

    def test_speaker_valid(self):
        data = {
            "schema_version": "2.0", "project": _MIN_PROJECT, "events": [],
            "speakers": {"S1": {"id": "S1", "name": "Alice", "is_locked": True}},
            "metadata": {},
        }
        ok, errs = validate_json(data, "timeline")
        assert ok, f"Speaker should be valid: {errs}"

    def test_synthesis_output_valid(self, sample_project_state):
        engine = SynthesisEngine()
        rendered = engine.render_all(sample_project_state)
        speakers = engine.render_speakers(sample_project_state)
        data = {
            "schema_version": "2.0", "project": _MIN_PROJECT,
            "events": rendered,
            "speakers": {s["id"]: s for s in speakers},
            "metadata": {},
        }
        assert_valid_timeline_v2(data)
