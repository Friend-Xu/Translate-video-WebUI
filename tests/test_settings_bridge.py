"""契约测试 — P2 设置桥 (settings 差异层 → GlobalConfig / CLI / 环境变量)

锁死结论:
  1. _pipeline_cfg_to_slot_overrides: 前端 snake_case 键 → 槽位 dict,
     嵌套路径 (gate.mode) 展开, 自动语义值 (source_lang=auto / max_speakers=0) 跳过
  2. GlobalConfig.apply_slot_overrides: 深度合并进槽位默认, 未知槽位忽略,
     嵌套不覆盖同层其它字段
  3. SentenceTranslator.from_config: 环境变量覆盖 yaml (优先级: env > yaml > 默认)
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from GUI import server  # noqa: E402


class TestSlotOverrideMap:
    def test_basic_mapping(self):
        cfg = {"demucs_model": "htdemucs_ft", "clustering_threshold": 0.7}
        ov = server._pipeline_cfg_to_slot_overrides(cfg)
        assert ov == {
            "audio": {"demucs_model": "htdemucs_ft"},
            "speaker": {"clustering_threshold": 0.7},
        }

    def test_nested_path_expands(self):
        cfg = {"semantic_threshold": 0.75, "gate_beta": 0.5}
        ov = server._pipeline_cfg_to_slot_overrides(cfg)
        assert ov["translation"]["gate"]["threshold_accept"] == 0.75
        assert ov["translation"]["gate"]["beta"] == 0.5

    def test_skip_auto_semantics(self):
        """source_lang=auto / max_speakers=0 交给引擎自动检测, 不映射。"""
        cfg = {"source_lang": "auto", "max_speakers": 0, "clustering_threshold": 0.7}
        ov = server._pipeline_cfg_to_slot_overrides(cfg)
        assert "asr" not in ov or "language" not in ov.get("asr", {})
        assert "max_speakers" not in ov.get("speaker", {})

    def test_target_lang_not_in_slot_map(self):
        """target_lang 走 --lang CLI, 不进槽位覆盖 (避免双通道)。"""
        ov = server._pipeline_cfg_to_slot_overrides({"target_lang": "en"})
        assert ov == {}

    def test_skip_null_and_missing(self):
        ov = server._pipeline_cfg_to_slot_overrides({"speed_factor": None})
        assert ov == {}


class TestApplySlotOverrides:
    def test_merges_into_defaults(self):
        from core.config.global_config import GlobalConfig
        gc = GlobalConfig()
        gc.apply_slot_overrides({"translation": {"gate": {"threshold_accept": 0.75}}})
        assert gc.project.translation["gate"]["threshold_accept"] == 0.75
        # 同层其它默认字段保留
        assert gc.project.translation["gate"]["mode"] == "xcomet"

    def test_unknown_field_written(self):
        """引擎专属参数直接写入槽位 (SchemaLoader 负责校验)。"""
        from core.config.global_config import GlobalConfig
        gc = GlobalConfig()
        gc.apply_slot_overrides({"tts": {"chattts_speaker_seed": 42}})
        assert gc.project.tts["chattts_speaker_seed"] == 42

    def test_unknown_slot_ignored(self):
        from core.config.global_config import GlobalConfig
        gc = GlobalConfig()
        before = dict(gc.project.tts)
        gc.apply_slot_overrides({"nosuchslot": {"a": 1}})
        assert gc.project.tts == before


class TestTranslationEnvBridge:
    def test_env_overrides_config(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
        monkeypatch.setenv("LLM_MODEL", "env-model")
        monkeypatch.setenv("LLM_TEMPERATURE", "0.7")
        from pipeline.translation_llm import SentenceTranslator
        t = SentenceTranslator.from_config(config_path="nonexistent.yaml")
        assert t._api_key == "env-key"
        assert t.model == "env-model"
        assert t.temperature == 0.7

    def test_env_missing_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
        monkeypatch.delenv("LLM_MODEL", raising=False)
        from pipeline.translation_llm import DEFAULT_MODEL, SentenceTranslator
        t = SentenceTranslator.from_config(config_path="nonexistent.yaml")
        assert t.model == DEFAULT_MODEL
