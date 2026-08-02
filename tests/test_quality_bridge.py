"""契约测试 — P5-A/P5-B: 翻译引擎卡片对齐 + 日志端点

锁死结论:
  1. verification_mode 映射到 translation.quality_strategy (tvw.py 真实消费键)
  2. semantic_threshold 映射到 gate.semantic_threshold (logic_gate 策略真读的键)
  3. 死参数 (gate_beta/gate_gamma/quality_gate/enable_glossary) 不再映射 — 走 env 桥
  4. list_strategies 懒加载返回 core 注册表真实策略 (logic_gate + xcomet)
  5. SentenceTranslator max_tokens/top_p 经 env 注入; 并发优先 LLM_CONCURRENCY
  6. 术语表 env 桥: GLOSSARY_FILES 覆盖词典列表, GLOSSARY_ENABLED=0 禁用
  7. /api/logs/recent: workspace pipeline.log 优先, 否则 server 日志尾部
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from GUI import server  # noqa: E402


class TestP5QualityStrategyMap:
    def test_verification_mode_maps_to_quality_strategy(self):
        ov = server._pipeline_cfg_to_slot_overrides({"verification_mode": "xcomet"})
        assert ov["translation"]["quality_strategy"] == "xcomet"

    def test_semantic_threshold_maps_to_gate_semantic(self):
        """P5-A 键错位修复: 策略读 gate.semantic_threshold, 不再写 threshold_accept。"""
        ov = server._pipeline_cfg_to_slot_overrides({"semantic_threshold": 0.85})
        assert ov["translation"]["gate"]["semantic_threshold"] == 0.85
        assert "threshold_accept" not in ov["translation"]["gate"]

    def test_dead_keys_no_longer_mapped(self):
        """gate_beta/gate_gamma/quality_gate/enable_glossary 无消费端, 不再假装映射。"""
        ov = server._pipeline_cfg_to_slot_overrides({
            "gate_beta": 0.5, "gate_gamma": 0.4,
            "quality_gate": True, "enable_glossary": True,
        })
        assert ov == {}


class TestP5ListStrategies:
    def test_lazy_loads_registry(self):
        from core.quality.protocol import list_strategies
        strategies = list_strategies()
        assert strategies == ["logic_gate", "xcomet"]
        assert "joint_formula" not in strategies


class TestP5TranslatorParams:
    def test_max_tokens_top_p_from_env(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
        monkeypatch.setenv("LLM_MAX_TOKENS", "8000")
        monkeypatch.setenv("LLM_TOP_P", "0.95")
        from pipeline.translation_llm import SentenceTranslator
        t = SentenceTranslator.from_config(config_path="nonexistent.yaml")
        assert t.max_tokens == 8000
        assert t.top_p == 0.95

    def test_concurrency_env_priority(self, monkeypatch):
        monkeypatch.setenv("LLM_CONCURRENCY", "5")
        from core.passes.llm_translation_pass import LLMTranslationPass
        assert LLMTranslationPass._concurrency_from_config() == 5


class TestP5GlossaryEnv:
    def test_glossary_files_env_overrides_yaml(self, monkeypatch, tmp_path):
        dict_dir = tmp_path / "terms"
        dict_dir.mkdir()
        (dict_dir / "custom.json").write_text(json.dumps({"terms": {"GPU": "显卡"}}), encoding="utf-8")
        monkeypatch.setenv("GLOSSARY_FILES", "custom.json")
        from pipeline.translation_bible import load_manual_glossary
        cfg = {"terms_dict": {"enabled": True, "dict_dir": str(dict_dir), "default_dict": []}}
        assert load_manual_glossary(cfg) == {"GPU": "显卡"}

    def test_glossary_disabled_env(self, monkeypatch, tmp_path):
        dict_dir = tmp_path / "terms"
        dict_dir.mkdir()
        (dict_dir / "a.json").write_text(json.dumps({"terms": {"X": "Y"}}), encoding="utf-8")
        monkeypatch.setenv("GLOSSARY_ENABLED", "0")
        from pipeline.translation_bible import load_manual_glossary
        cfg = {"terms_dict": {"enabled": True, "dict_dir": str(dict_dir), "default_dict": ["a.json"]}}
        assert load_manual_glossary(cfg) == {}


class TestP5LogsRecent:
    def test_returns_server_log_tail(self, monkeypatch, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        (log_dir / "server.log").write_text("\n".join(f"line{i}" for i in range(50)), encoding="utf-8")
        monkeypatch.setattr(server, "LOG_DIR", log_dir)
        resp = asyncio.run(server.logs_recent(limit=10))
        assert resp["source"] == "server"
        assert len(resp["lines"]) == 10
        assert resp["total"] == 50

    def test_workspace_log_preferred(self, monkeypatch, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        (log_dir / "server.log").write_text("server-line", encoding="utf-8")
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "pipeline.log").write_text("ws-line", encoding="utf-8")
        monkeypatch.setattr(server, "LOG_DIR", log_dir)
        resp = asyncio.run(server.logs_recent(workspace=str(ws)))
        assert resp["source"] == "workspace"
        assert resp["lines"] == ["ws-line"]
