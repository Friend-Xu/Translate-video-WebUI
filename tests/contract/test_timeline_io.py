"""
契约测试 — timeline_io persist/load 互逆 (数据结构重设计 Phase 2)

锁死数据破坏 bug: bootstrap 写入的译文, 经 export reload 后必须仍在,
不得被空槽 {"config": {}} 覆盖销毁。
"""
import os
import pytest
from core.ir.timeline_event import TimelineEventIR
from core.ir.speaker import SpeakerNodeIR
from core.ir.project import TimelineProjectIR
from core.runtime.project_state import TimelineProjectState
from core.runtime.timeline_io import persist_state, load_state


def _bootstrap_state() -> TimelineProjectState:
    """模拟 bootstrap 后的 state: 有 words + 真中文译文 + speaker。"""
    evts = {
        "evt_001": TimelineEventIR(id="evt_001", start=0.0, end=12.3,
                                   speaker_ref="spk_01",
                                   text_ref="Today guys, we're looking at mods."),
        "evt_002": TimelineEventIR(id="evt_002", start=12.5, end=20.0,
                                   speaker_ref="spk_02",
                                   text_ref="And the next one is great."),
    }
    spks = {"spk_01": SpeakerNodeIR(id="spk_01"), "spk_02": SpeakerNodeIR(id="spk_02")}
    state = TimelineProjectState(TimelineProjectIR(events=evts, speakers=spks))

    # 模拟 ASR pass 写 words
    state.get_event("evt_001").asr.words = [
        {"word": "Today", "start": 0.0, "end": 0.3, "confidence": 0.98},
        {"word": "guys,", "start": 0.35, "end": 0.6, "confidence": 0.97},
    ]
    # 模拟 translation pass 写真译文 (类型化, engine 归 translation.engine, Phase 3a)
    state.get_event("evt_001").translation.text = "各位朋友,今天我们来看模组。"
    state.get_event("evt_001").translation.engine = "deepseek"
    state.get_event("evt_001").translation.quality_score = 0.85
    state.get_event("evt_001").translation.similarity = 0.92
    state.get_event("evt_001").provenance["confidence"] = 0.95
    return state


@pytest.mark.schema
class TestPersistLoadRoundtrip:
    def test_translation_survives_export_reload(self, tmp_path):
        """核心回归: bootstrap 的译文经 reload 不得丢失 (修复毁译文 bug)。"""
        ws = str(tmp_path / "test_project")
        state = _bootstrap_state()
        tl = persist_state(state, ws, "test.mp4", "en")

        reloaded = load_state(tl)
        es = reloaded.get_event("evt_001")
        assert es is not None
        # TTS pass 读取路径: es.translation.text
        assert es.translation.text == "各位朋友,今天我们来看模组。"
        assert es.translation.engine == "deepseek"

    def test_words_survive_roundtrip(self, tmp_path):
        ws = str(tmp_path / "test_project")
        state = _bootstrap_state()
        tl = persist_state(state, ws, "test.mp4", "en")

        reloaded = load_state(tl)
        words = reloaded.get_event("evt_001").asr.words
        assert len(words) == 2
        assert words[0]["word"] == "Today"

    def test_speaker_survives_roundtrip(self, tmp_path):
        ws = str(tmp_path / "test_project")
        state = _bootstrap_state()
        tl = persist_state(state, ws, "test.mp4", "en")

        reloaded = load_state(tl)
        assert reloaded.get_event("evt_001").ir.speaker_ref == "spk_01"
        assert reloaded.get_event("evt_002").ir.speaker_ref == "spk_02"
        assert "spk_01" in reloaded.ir.speakers

    def test_events_sorted_by_start(self, tmp_path):
        ws = str(tmp_path / "test_project")
        state = _bootstrap_state()
        tl = persist_state(state, ws, "test.mp4", "en")
        reloaded = load_state(tl)
        starts = [es.start for es in reloaded.sorted_events()]
        assert starts == sorted(starts)

    def test_load_missing_file_raises(self, tmp_path):
        """禁止兜底: 文件缺失显式 raise, 不返回空 state。"""
        with pytest.raises(FileNotFoundError):
            load_state(str(tmp_path / "nonexistent" / "timeline.json"))

    def test_load_missing_required_field_raises(self, tmp_path):
        """禁止兜底: event 缺 text 显式 raise。"""
        import json
        bad = tmp_path / "timeline.json"
        bad.write_text(json.dumps({
            "schema_version": "3.0",
            "project": {"id": "p", "source_video": "v", "source_lang": "en", "target_lang": "zh"},
            "events": [{"id": "e1", "start": 0.0, "end": 1.0}],  # 缺 text
            "speakers": {},
        }), encoding="utf-8")
        with pytest.raises(ValueError, match="text"):
            load_state(str(bad))

    def test_load_v1_extract_format_raises(self, tmp_path):
        """E2E 修复: v1 提取格式 (timeline.ir) 无 events 键, 显式报错而非静默空 state。

        静默空 state 会让 orchestrator 误判"无事件"并重跑 ASR。
        """
        import json
        v1 = tmp_path / "timeline.json"
        v1.write_text(json.dumps({
            "version": "1.0", "audio_id": "x",
            "timeline": [], "speaker_map": {}, "metadata": {},
        }), encoding="utf-8")
        with pytest.raises(ValueError, match="v1"):
            load_state(str(v1))

    def test_v2_string_translation_normalized(self, tmp_path):
        """兼容 v2: translation 为 string 时归一为 dict, reload 后 TTS 可读。"""
        import json
        v2 = tmp_path / "timeline.json"
        v2.write_text(json.dumps({
            "schema_version": "2.0",
            "project": {"id": "p", "source_video": "v", "source_lang": "en", "target_lang": "zh"},
            "events": [{"id": "e1", "start": 0.0, "end": 1.0, "text": "hello",
                        "translation": "你好"}],
            "speakers": {},
        }), encoding="utf-8")
        reloaded = load_state(str(v2))
        assert reloaded.get_event("e1").translation.text == "你好"

    def test_speaker_voice_binding_survives_roundtrip(self, tmp_path):
        """speaker/bind 收敛: engine/voice_profile 注册表字段 persist/load 往返。"""
        import json
        ws = str(tmp_path / "test_project")
        evts = {"evt_001": TimelineEventIR(
            id="evt_001", start=0.0, end=1.5, speaker_ref="SPK_01", text_ref="hi")}
        state = TimelineProjectState(TimelineProjectIR(
            events=evts,
            speakers={"SPK_01": SpeakerNodeIR(
                id="SPK_01", name="SPK_01", engine="cosyvoice",
                voice_id="speaker_v2_01", voice_profile={"spk": "v2", "lang": "zh"})},
        ))
        tl = persist_state(state, ws, "test.mp4", "ja")

        with open(tl, encoding="utf-8") as f:
            data = json.load(f)
        spk = data["speakers"]["SPK_01"]
        assert spk["engine"] == "cosyvoice"
        assert spk["voice_profile"] == {"spk": "v2", "lang": "zh"}

        reloaded = load_state(tl)
        node = reloaded.ir.speakers["SPK_01"]
        assert node.engine == "cosyvoice"
        assert node.voice_profile == {"spk": "v2", "lang": "zh"}
