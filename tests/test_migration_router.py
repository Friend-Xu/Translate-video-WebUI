"""test_migration_router — feature flag 灰度切换"""
import os
import json
import pytest
from timeline.api.timeline import TimelineMigrationRouter


class TestMigrationRouter:
    def test_default_ratio_zero(self):
        router = TimelineMigrationRouter()
        assert router.ratio == 0.0

    def test_custom_ratio(self):
        router = TimelineMigrationRouter(new_ir_ratio=0.5)
        assert router.ratio == 0.5

    def test_ratio_clamped(self):
        assert TimelineMigrationRouter(new_ir_ratio=2.0).ratio == 1.0
        assert TimelineMigrationRouter(new_ir_ratio=-1.0).ratio == 0.0

    def test_get_view_old(self, tmp_path):
        workspace = str(tmp_path)
        os.makedirs(os.path.join(workspace, "01_extract"))
        _write_timeline(workspace)
        from timeline.adapters.old_ir_adapter import OldTimelineView
        view = TimelineMigrationRouter().get_view(workspace, use_new_ir=False)
        assert isinstance(view, OldTimelineView)

    def test_get_view_new(self, tmp_path):
        workspace = str(tmp_path)
        os.makedirs(os.path.join(workspace, "01_extract"))
        _write_timeline(workspace)
        from timeline.adapters.new_ir_adapter import NewTimelineView
        view = TimelineMigrationRouter().get_view(workspace, use_new_ir=True)
        assert isinstance(view, NewTimelineView)

    def test_get_view_full_migration(self, tmp_path):
        workspace = str(tmp_path)
        os.makedirs(os.path.join(workspace, "01_extract"))
        _write_timeline(workspace)
        from timeline.adapters.new_ir_adapter import NewTimelineView
        view = TimelineMigrationRouter(new_ir_ratio=1.0).get_view(workspace)
        assert isinstance(view, NewTimelineView)

    def test_get_view_ratio_zero_default(self, tmp_path):
        workspace = str(tmp_path)
        os.makedirs(os.path.join(workspace, "01_extract"))
        _write_timeline(workspace)
        from timeline.adapters.old_ir_adapter import OldTimelineView
        view = TimelineMigrationRouter(new_ir_ratio=0.0).get_view(workspace)
        assert isinstance(view, OldTimelineView)

    def test_get_view_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            TimelineMigrationRouter().get_view(str(tmp_path))


def _write_timeline(workspace: str):
    data = {
        "audio_id": "test", "version": "1.0",
        "timeline": [
            {"id": "seg_001", "type": "speech", "speaker": "SPEAKER_00",
             "start": 0.0, "end": 2.5, "text": "Hello world", "overlap": False},
            {"id": "seg_002", "type": "speech", "speaker": "SPEAKER_01",
             "start": 3.0, "end": 5.0, "text": "How are you", "overlap": False},
        ],
        "speaker_map": {}, "metadata": {},
    }
    path = os.path.join(workspace, "01_extract", "timeline.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
