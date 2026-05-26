"""test_config — TimelineConfig 单元测试"""
import pytest
from timeline.config import TimelineConfig


class TestTimelineConfig:
    def test_default_values(self):
        cfg = TimelineConfig()
        assert cfg.MIN_CONFIDENCE == 0.7
        assert cfg.MAX_GAP_SECONDS == 1.0
        assert cfg.MERGE_SAME_SPEAKER_THRESHOLD == 0.8
        assert cfg.SPLIT_SILENCE_THRESHOLD == 2.0

    def test_load_no_file(self, tmp_path):
        cfg = TimelineConfig.load(config_path=str(tmp_path / "nonexistent.yaml"))
        assert cfg.MIN_CONFIDENCE == 0.7

    def test_load_valid_yaml(self, tmp_path):
        import yaml
        path = tmp_path / "timeline.yaml"
        with open(path, "w") as f:
            yaml.dump({"MIN_CONFIDENCE": 0.85, "MAX_GAP_SECONDS": 2.0}, f)

        cfg = TimelineConfig.load(config_path=str(path))
        assert cfg.MIN_CONFIDENCE == 0.85
        assert cfg.MAX_GAP_SECONDS == 2.0
        assert cfg.MERGE_SAME_SPEAKER_THRESHOLD == 0.8

    def test_load_invalid_yaml(self, tmp_path):
        path = tmp_path / "timeline.yaml"
        with open(path, "w") as f:
            f.write(": invalid yaml :::")

        cfg = TimelineConfig.load(config_path=str(path))
        assert cfg.MIN_CONFIDENCE == 0.7

    def test_load_non_dict_yaml(self, tmp_path):
        import yaml
        path = tmp_path / "timeline.yaml"
        with open(path, "w") as f:
            yaml.dump([1, 2, 3], f)

        cfg = TimelineConfig.load(config_path=str(path))
        assert cfg.MIN_CONFIDENCE == 0.7

    def test_get_method(self):
        assert TimelineConfig.get("MIN_CONFIDENCE") == 0.7
        assert TimelineConfig.get("NONEXISTENT", "fallback") == "fallback"
        assert TimelineConfig.get("NONEXISTENT") is None
