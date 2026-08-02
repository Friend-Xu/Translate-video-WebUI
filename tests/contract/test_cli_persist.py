"""
契约测试 — CLI 翻译切默认 (main.py step_translate_core)

锁死: core 翻译完成后 persist v2 到 01_extract/timeline.json (唯一事实源),
GUI 编辑可读 CLI 产物译文; 02_translate/timeline_v2.json (SRT 桥接) 并存。
"""
import json
import os
import pytest

from core.ir.timeline_event import TimelineEventIR
from core.ir.speaker import SpeakerNodeIR
from core.ir.project import TimelineProjectIR
from core.runtime.project_state import TimelineProjectState
from core.runtime.timeline_io import persist_state, load_state


def _translated_state() -> TimelineProjectState:
    evts = {
        "evt_001": TimelineEventIR(id="evt_001", start=0.0, end=1.5,
                                   speaker_ref="SPK_01",
                                   text_ref="こんにちは"),
    }
    spks = {"SPK_01": SpeakerNodeIR(id="SPK_01", name="SPK_01")}
    state = TimelineProjectState(TimelineProjectIR(events=evts, speakers=spks))
    state.get_event("evt_001").translation.text = "你好"
    state.get_event("evt_001").translation.engine = "deepseek"
    state.get_event("evt_001").asr.words = [
        {"word": "こんにちは", "start": 0.0, "end": 1.5, "confidence": 0.95},
    ]
    return state


@pytest.mark.contract
class TestCliCorePersist:
    def test_translation_persists_to_01_extract(self, tmp_path):
        """step_translate_core 的 persist 语义: 译文落 01_extract/timeline.json v2。"""
        ws = str(tmp_path / "test_video_project")
        state = _translated_state()
        persist_state(state, ws, "test_video.mp4", "ja",
                      project_id="test_video_project")

        tl_path = os.path.join(ws, "01_extract", "timeline.json")
        assert os.path.isfile(tl_path)
        with open(tl_path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["schema_version"] == "2.0"
        assert data["project"]["source_video"] == "test_video.mp4"

        reloaded = load_state(tl_path)
        es = reloaded.get_event("evt_001")
        assert es.translation.text == "你好"
        assert es.translation.engine == "deepseek"

    def test_gui_load_path_reads_cli_output(self, tmp_path):
        """GUI 加载路径 (diarization/load 读 01_extract/timeline.json) 读到 CLI 译文。"""
        ws = str(tmp_path / "test_video_project")
        persist_state(_translated_state(), ws, "test_video.mp4", "ja",
                      project_id="test_video_project")
        tl_path = os.path.join(ws, "01_extract", "timeline.json")
        with open(tl_path, encoding="utf-8") as f:
            data = json.load(f)
        # GUI _load_timeline_v2 的读取形态
        events = data.get("events", [])
        assert events[0]["translation"]["text"] == "你好"
