"""
normalize_v1_timeline 契约测试 — v1→v2 一次性迁移 (架构收束 P1)

验证迁移产出与旧 server._load_timeline_v2 迁移分支等价:
  - v2 输入幂等 (不迁移)
  - v1 字段映射 (translation dict/str, words score→confidence, speaker_map, metadata)
  - 备份 + 原子覆写
  - 非 v1/v2 文件显式报错 (禁止兜底)
"""
import json
import os
import pytest
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from tools.normalize_v1_timeline import normalize_data, normalize_file, is_v1, is_v2  # noqa: E402


def _v1_fixture() -> dict:
    return {
        "audio_id": "Test_JP",
        "version": "1.0",
        "timeline": [
            {
                "id": "seg_001", "type": "speech",
                "start": 0.0, "end": 2.5, "text": "こんにちは",
                "speaker": "SPEAKER_00",
                "translation": {"text": "你好"},
                "words": [
                    {"word": "こんにちは", "start": 0.0, "end": 2.5, "score": 0.95},
                    {"word": "missing", "start": 0.0, "end": 0.5},
                ],
            },
            {
                "id": "seg_002", "type": "speech",
                "start": 3.0, "end": 5.0, "text": "世界",
                "translation": "世界",
                "speaker": "SPEAKER_01",
                "words": [],
            },
        ],
        "speaker_map": {
            "SPEAKER_00": {"alias": "主持人", "voice_id": "edge_zh_female_01"},
            "SPEAKER_01": {"alias": "嘉宾"},
        },
        "metadata": {"lang": "ja", "duration": 5.0},
    }


class TestV1Detection:
    def test_is_v2(self):
        assert is_v2({"schema_version": "2.0"})
        assert not is_v2({"version": "1.0"})

    def test_is_v1(self):
        assert is_v1({"timeline": []})
        assert not is_v1({"events": []})
        assert not is_v1({})


class TestNormalizeData:
    def test_v2_passthrough(self):
        data = {"schema_version": "2.0", "events": []}
        assert normalize_data(data) is data

    def test_not_timeline_raises(self):
        with pytest.raises(ValueError, match="既不是 v2"):
            normalize_data({"foo": "bar"})

    def test_events_mapping(self):
        out = normalize_data(_v1_fixture())
        assert out["schema_version"] == "2.0"
        assert len(out["events"]) == 2

        e0 = out["events"][0]
        assert e0["id"] == "seg_001"
        assert e0["text"] == "こんにちは"
        assert e0["translation"] == "你好"          # dict → text
        assert e0["speaker"] == "SPEAKER_00"
        assert e0["source"] == "asr"
        assert e0["review_status"] == "pending"
        assert e0["words"][0]["confidence"] == 0.95  # score → confidence
        assert e0["words"][1]["confidence"] is None   # 无 score 不编造

        e1 = out["events"][1]
        assert e1["translation"] == "世界"          # str 原样

    def test_speakers_mapping(self):
        out = normalize_data(_v1_fixture())
        assert out["speakers"]["SPEAKER_00"]["name"] == "主持人"
        assert out["speakers"]["SPEAKER_00"]["voice_id"] == "edge_zh_female_01"
        assert out["speakers"]["SPEAKER_01"]["name"] == "嘉宾"
        assert out["speakers"]["SPEAKER_01"]["voice_id"] is None

    def test_metadata_mapping(self):
        out = normalize_data(_v1_fixture())
        assert out["metadata"]["total_duration"] == 5.0
        assert out["metadata"]["event_count"] == 2
        assert out["metadata"]["speaker_count"] == 2
        assert out["project"]["source_lang"] == "ja"

    def test_duration_fallback_to_max_end(self):
        data = _v1_fixture()
        del data["metadata"]["duration"]
        out = normalize_data(data)
        assert out["metadata"]["total_duration"] == 5.0

    def test_empty_v1(self):
        data = {"audio_id": "x", "version": "1.0", "timeline": []}
        out = normalize_data(data)
        assert out["events"] == []
        assert out["metadata"]["total_duration"] == 0


class TestNormalizeFile:
    def test_v2_idempotent(self, tmp_path):
        path = tmp_path / "timeline.json"
        data = {"schema_version": "2.0", "events": []}
        path.write_text(json.dumps(data), encoding="utf-8")
        assert normalize_file(str(path)) is False
        assert json.loads(path.read_text(encoding="utf-8")) == data

    def test_v1_migrates_with_backup(self, tmp_path):
        path = tmp_path / "timeline.json"
        path.write_text(json.dumps(_v1_fixture()), encoding="utf-8")
        assert normalize_file(str(path)) is True

        out = json.loads(path.read_text(encoding="utf-8"))
        assert out["schema_version"] == "2.0"
        assert len(out["events"]) == 2

        bak = json.loads((tmp_path / "timeline.json.v1.bak").read_text(encoding="utf-8"))
        assert bak["version"] == "1.0"

    def test_invalid_raises(self, tmp_path):
        path = tmp_path / "timeline.json"
        path.write_text(json.dumps({"garbage": True}), encoding="utf-8")
        with pytest.raises(ValueError):
            normalize_file(str(path))
