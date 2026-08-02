"""批次03验收: GlobalConfig.from_legacy_yaml() + PassManager configure() 注入"""
import pytest


class TestDeepMerge:
    def test_null_deletes_key(self):
        from core.runtime.config_resolver import deep_merge
        base = {"model": "turbo", "beam_size": 5}
        deep_merge(base, {"model": None})
        assert "model" not in base
        assert base["beam_size"] == 5

    def test_nested_recursive(self):
        from core.runtime.config_resolver import deep_merge
        base = {"gate": {"mode": "logic_gate", "threshold": 0.8}}
        deep_merge(base, {"gate": {"threshold": 0.9}})
        assert base["gate"]["mode"] == "logic_gate"
        assert base["gate"]["threshold"] == 0.9

    def test_leaf_override(self):
        from core.runtime.config_resolver import deep_merge
        base = {"model": "turbo", "device": "cuda"}
        deep_merge(base, {"model": "large-v3"})
        assert base == {"model": "large-v3", "device": "cuda"}

    def test_list_replacement(self):
        from core.runtime.config_resolver import deep_merge
        base = {"chain": ["a", "b", "c"]}
        deep_merge(base, {"chain": ["x"]})
        assert base["chain"] == ["x"]


class TestGlobalConfigBridge:
    def test_from_legacy_yaml_default(self):
        from core.config import GlobalConfig
        gc = GlobalConfig.from_legacy_yaml()
        t = gc.project.translation
        assert t["lang"] == "zh"

    def test_from_legacy_yaml_maps_fields(self):
        from core.config import GlobalConfig
        gc = GlobalConfig.from_legacy_yaml("config/translate.yaml")
        t = gc.project.translation
        assert isinstance(t["lang"], str)
        gate = t.get("gate", {})
        assert isinstance(gate.get("threshold_accept", 0.8), (int, float))

    def test_from_legacy_yaml_explicit_gate_section(self, tmp_path):
        """translate.yaml 显式 gate 段 → 阈值直接映射, 覆盖 semantic_threshold 映射"""
        from core.config import GlobalConfig
        p = tmp_path / "translate.yaml"
        p.write_text(
            "translate:\n"
            "  semantic_threshold: 0.7\n"
            "  gate:\n"
            "    mode: xcomet\n"
            "    threshold_accept: 0.52\n"
            "    threshold_reject: 0.24\n",
            encoding="utf-8",
        )
        gc = GlobalConfig.from_legacy_yaml(str(p))
        gate = gc.project.translation["gate"]
        assert gate["threshold_accept"] == 0.52
        assert gate["threshold_reject"] == 0.24
        assert gate["mode"] == "xcomet"

    def test_from_legacy_yaml_gate_without_section_keeps_mapping(self, tmp_path):
        """无显式 gate 段时, semantic_threshold 仍映射 threshold_accept (legacy 契约)"""
        from core.config import GlobalConfig
        p = tmp_path / "translate.yaml"
        p.write_text(
            "translate:\n"
            "  semantic_threshold: 0.65\n",
            encoding="utf-8",
        )
        gc = GlobalConfig.from_legacy_yaml(str(p))
        gate = gc.project.translation["gate"]
        assert gate["threshold_accept"] == 0.65


class TestPassManagerConfigure:
    def test_configure_called_before_apply(self):
        from core.engine.pass_manager import PassManager
        from core.engine.pass_base import TimelinePass
        from core.runtime.project_state import TimelineProjectState
        from core.ir.project import TimelineProjectIR
        from core.config.global_config import GlobalConfig
        from core.runtime.config_resolver import ConfigResolver

        calls = []

        class TestPass(TimelinePass):
            name = "test_p"
            def apply(self, s):
                calls.append("apply")
                return s
            def configure(self, cfg=None):
                calls.append(f"cfg:{bool(cfg)}")

        pm = PassManager()
        pm.register(TestPass())
        pm.set_config_resolver(ConfigResolver(GlobalConfig()))
        pm.run(TimelineProjectState(TimelineProjectIR({}, {})))
        assert calls == ["cfg:True", "apply"], f"Got: {calls}"
