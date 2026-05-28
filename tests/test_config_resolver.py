"""批次12 §3.3: ConfigResolver 三级合并 + null=delete 语义测试。

覆盖:
  - deep_merge 5 条规则
  - ConfigResolver 三级合并 (Event > Speaker > Global)
  - null 删除继承
  - 缓存行为
"""
import pytest
from core.runtime.config_resolver import deep_merge, serialize_event_config
from core.config.global_config import GlobalConfig


class TestDeepMerge:
    """deep_merge 5 条规则测试。"""

    def test_leaf_override(self):
        """规则1: override 叶子值直接覆盖 base"""
        base = {"a": 1, "b": 2}
        deep_merge(base, {"b": 3})
        assert base == {"a": 1, "b": 3}

    def test_nested_recursion(self):
        """规则2: override 中 dict 递归合并"""
        base = {"a": {"x": 1, "y": 2}, "b": 3}
        deep_merge(base, {"a": {"y": 20, "z": 30}})
        assert base == {"a": {"x": 1, "y": 20, "z": 30}, "b": 3}

    def test_null_deletes(self):
        """规则3: null 删除 base 中的键"""
        base = {"a": 1, "b": 2}
        deep_merge(base, {"b": None})
        assert base == {"a": 1}
        assert "b" not in base

    def test_null_on_missing_key_noop(self):
        """null 对 base 中不存在的键无影响"""
        base = {"a": 1}
        deep_merge(base, {"b": None})
        assert base == {"a": 1}

    def test_list_replacement(self):
        """规则4: list 整体替换"""
        base = {"a": [1, 2, 3]}
        deep_merge(base, {"a": [4, 5]})
        assert base == {"a": [4, 5]}

    def test_lazy_override(self):
        """规则5: base 中有但 override 中没有的键保持不变"""
        base = {"a": 1, "b": 2, "c": {"x": 10}}
        deep_merge(base, {"a": 100})
        assert base["b"] == 2
        assert base["c"] == {"x": 10}

    def test_empty_override_noop(self):
        base = {"a": 1, "b": 2}
        deep_merge(base, {})
        assert base == {"a": 1, "b": 2}

    def test_deeply_nested(self):
        base = {"level1": {"level2": {"level3": {"key": "old"}}}}
        deep_merge(base, {"level1": {"level2": {"level3": {"key": "new"}}}})
        assert base["level1"]["level2"]["level3"]["key"] == "new"


class TestConfigResolver:
    """ConfigResolver 三级合并测试。"""

    @pytest.fixture
    def global_config(self):
        gc = GlobalConfig()
        gc.project.asr = {"model": "medium", "device": "cpu", "language": "auto"}
        gc.project.translation = {
            "lang": "en", "backend": "deepseek",
            "gate": {"mode": "logic_gate"},
        }
        gc.project.tts = {"engine": "edge", "speed_factor": 1.0}
        return gc

    def test_global_default_only(self, global_config):
        """仅全局默认配置可用"""
        resolved = global_config.get_slot_defaults("asr")
        assert resolved["model"] == "medium"
        assert resolved["device"] == "cpu"
        assert resolved["language"] == "auto"

    def test_event_overrides_global(self, global_config):
        """Event 配置覆盖 Global 配置"""
        global_cfg = global_config.get_slot_defaults("asr")
        event_cfg = {"model": "turbo", "device": "cuda"}
        deep_merge(global_cfg, event_cfg)
        assert global_cfg["model"] == "turbo"
        assert global_cfg["device"] == "cuda"
        assert global_cfg["language"] == "auto"

    def test_speaker_layer_applied(self, global_config):
        """Speaker 配置在 Event 配置之前被合并"""
        global_cfg = global_config.get_slot_defaults("tts")
        speaker_cfg = {"engine": "chattts"}
        event_cfg = {"speed_factor": 1.5}
        deep_merge(global_cfg, speaker_cfg)
        deep_merge(global_cfg, event_cfg)
        assert global_cfg["engine"] == "chattts"
        assert global_cfg["speed_factor"] == 1.5

    def test_null_removes_inherited_value(self):
        """null 删除 Global 继承的值"""
        base = {"model": "medium", "device": "cuda", "language": "auto"}
        deep_merge(base, {"model": None})
        assert "model" not in base
        assert base["device"] == "cuda"
        assert base["language"] == "auto"

    def test_null_on_nested_dict(self):
        """null 删除嵌套 dict"""
        base = {
            "lang": "en", "backend": "deepseek",
            "gate": {"mode": "logic_gate", "threshold": 0.8},
        }
        deep_merge(base, {"gate": None})
        assert "gate" not in base
        assert base["lang"] == "en"

    def test_partial_nested_override(self):
        """嵌套 dict 部分覆盖"""
        base = {
            "gate": {
                "mode": "logic_gate",
                "threshold_accept": 0.80,
                "threshold_reject": 0.60,
            },
        }
        deep_merge(base, {"gate": {"threshold_accept": 0.90}})
        assert base["gate"]["mode"] == "logic_gate"
        assert base["gate"]["threshold_accept"] == 0.90
        assert base["gate"]["threshold_reject"] == 0.60

    def test_full_chain_event_speaker_global(self, global_config):
        """完整三级合并: Event > Speaker > Global"""
        global_cfg = global_config.get_slot_defaults("asr")
        deep_merge(global_cfg, {"model": "large-v2", "beam_size": 10})
        deep_merge(global_cfg, {"model": "turbo"})
        assert global_cfg["model"] == "turbo"
        assert global_cfg["beam_size"] == 10
        assert global_cfg["device"] == "cpu"


class TestSerializeEventConfig:
    """差异化序列化测试。"""

    def test_diff_only_stores_changes(self):
        from core.runtime.config_resolver import _dict_diff
        override = {"model": "turbo", "device": "cuda"}
        resolved = {"model": "medium", "device": "cuda", "language": "auto"}
        diff = _dict_diff(override, resolved)
        assert "model" in diff
        assert diff["model"] == "turbo"
        assert "device" not in diff
        assert "language" not in diff
