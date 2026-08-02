"""契约测试 — /api/config 差异层语义 (P1)

锁死结论:
  1. POST 增量 deep_merge, 不再整体替换 settings.json["pipeline"] → 单键 POST
     不会清掉其它设置 (GlossaryManager 数据丢失回归)
  2. POST null = 删除该键 (恢复默认) — 与 core/runtime/config_resolver.py deep_merge 一致
  3. GET 返回 {config: 默认+差异合并, defaults: 系统默认, overridden: 被覆盖键列表}
  4. 旧数据中的 null 残留自动过滤, 不进 merged/overridden
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from GUI import server  # noqa: E402


@pytest.fixture
def cfg_path(tmp_path, monkeypatch):
    """隔离 settings.json 到临时目录。"""
    tmp = tmp_path / "settings.json"
    monkeypatch.setattr(server, "SETTINGS_PATH", tmp)
    return tmp


def _write(cfg_path: Path, data: dict) -> None:
    cfg_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _read(cfg_path: Path) -> dict:
    return json.loads(cfg_path.read_text(encoding="utf-8"))


def _get() -> dict:
    return asyncio.run(server.get_config())


def _post(cfg: dict) -> dict:
    return asyncio.run(server.post_config(cfg))


class TestConfigDiffLayer:
    def test_get_empty_returns_defaults(self, cfg_path):
        resp = _get()
        assert set(resp) == {"config", "defaults", "overridden", "quality_strategies"}
        assert resp["config"] == resp["defaults"]
        assert resp["overridden"] == []

    def test_post_single_key_merges(self, cfg_path):
        _post({"config": {"tts_engine": "edge"}})
        resp = _get()
        assert resp["config"]["tts_engine"] == "edge"
        assert resp["overridden"] == ["tts_engine"]
        # 未覆盖的默认键仍取系统默认
        assert resp["config"]["target_lang"] == resp["defaults"]["target_lang"]

    def test_post_does_not_wipe_existing_keys(self, cfg_path):
        """数据丢失回归: GlossaryManager 单键 POST 不得清掉其它设置。"""
        _post({"config": {"tts_engine": "edge", "target_lang": "en"}})
        _post({"config": {"glossary_files": "a.json"}})
        resp = _get()
        assert resp["config"]["tts_engine"] == "edge"
        assert resp["config"]["target_lang"] == "en"
        assert resp["config"]["glossary_files"] == "a.json"
        assert resp["overridden"] == ["tts_engine", "target_lang", "glossary_files"]

    def test_post_null_restores_default(self, cfg_path):
        _post({"config": {"tts_engine": "edge"}})
        _post({"config": {"tts_engine": None}})
        resp = _get()
        assert resp["config"]["tts_engine"] == resp["defaults"]["tts_engine"]
        assert "tts_engine" not in resp["overridden"]
        # 磁盘差异层键已删除
        assert "tts_engine" not in _read(cfg_path)["pipeline"]

    def test_post_bare_body_compat(self, cfg_path):
        """旧调用方直接 POST config 对象 (无 config 包装) 仍兼容。"""
        _post({"tts_engine": "edge"})
        resp = _get()
        assert resp["config"]["tts_engine"] == "edge"

    def test_post_overrides_previous_value(self, cfg_path):
        _post({"config": {"tts_engine": "edge"}})
        _post({"config": {"tts_engine": "cosyvoice"}})
        resp = _get()
        assert resp["config"]["tts_engine"] == "cosyvoice"
        assert resp["overridden"] == ["tts_engine"]

    def test_get_filters_stale_nulls(self, cfg_path):
        """旧数据里的 null 残留不进入 merged/overridden。"""
        _write(cfg_path, {"pipeline": {"tts_engine": None, "target_lang": "en"}})
        resp = _get()
        assert resp["config"]["tts_engine"] == resp["defaults"]["tts_engine"]
        assert resp["overridden"] == ["target_lang"]
