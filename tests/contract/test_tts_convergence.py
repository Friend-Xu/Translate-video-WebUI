"""
TTS 收束契约测试 (架构收束 P4)

覆盖:
  - cli_bridge caption 键名映射 (caption_font → font, 与 VideoExportPass 消费一致)
  - cli_bridge tts 槽位桥 (engine/enable_emotion/cosyvoice)
  - CosyVoiceCompositePass configure (tts 槽位 → 构造参数)
  - VideoExportPass CaptionRenderer 全字段传参
  - patch_engine UPDATE_TTS_AUDIO 类型化槽位写入 (修复 TTSAudio.update 崩溃)
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from types import SimpleNamespace

from core.compat.cli_bridge import build_caption_config, apply_cli_slot_overrides
from core.config.global_config import GlobalConfig


class TestCaptionConfigBridge:
    def test_caption_font_maps_to_font(self):
        args = SimpleNamespace(caption_font="arial.ttf", caption_font_size=24,
                               caption_font_color="red")
        cfg = build_caption_config(args)
        assert cfg == {"font": "arial.ttf", "font_size": 24, "font_color": "red"}

    def test_extra_fields_mapped(self):
        args = SimpleNamespace(caption_font_size_mode="fixed",
                               caption_max_font_size=40,
                               caption_font_size_factor=0.03)
        cfg = build_caption_config(args)
        assert cfg["font_size_mode"] == "fixed"
        assert cfg["max_font_size"] == 40
        assert cfg["font_size_factor"] == 0.03

    def test_no_optimize_disables_optimization(self):
        args = SimpleNamespace(no_optimize_subtitles=True)
        cfg = build_caption_config(args)
        assert cfg["enable_subtitle_optimization"] is False

    def test_yaml_base_with_cli_override(self, tmp_path):
        yaml_path = tmp_path / "caption.yaml"
        yaml_path.write_text(
            "caption:\n  font: base.ttf\n  font_size: 12\n  max_lines: 2\n",
            encoding="utf-8",
        )
        args = SimpleNamespace(caption_config_path=str(yaml_path),
                               caption_font_size=24, caption_font=None,
                               caption_font_color=None, caption_stroke_width=None,
                               caption_stroke_color=None, caption_bg_color=None,
                               caption_alignment=None, caption_position=None,
                               caption_max_lines=None, caption_width_ratio=None,
                               caption_font_size_mode=None, caption_max_font_size=None,
                               caption_font_size_factor=None,
                               no_optimize_subtitles=False)
        cfg = build_caption_config(args)
        assert cfg["font"] == "base.ttf"      # yaml 底
        assert cfg["font_size"] == 24         # CLI 覆盖


class TestTtsSlotBridge:
    def test_engine_and_emotion(self):
        gcfg = GlobalConfig()
        apply_cli_slot_overrides(SimpleNamespace(engine="cosyvoice",
                                                 enable_emotion=True), gcfg)
        assert gcfg.project.tts["engine"] == "cosyvoice"
        assert gcfg.project.tts["enable_emotion"] is True

    def test_cosyvoice_version(self):
        gcfg = GlobalConfig()
        apply_cli_slot_overrides(SimpleNamespace(cosyvoice_model_version="v3"), gcfg)
        assert gcfg.project.tts["cosyvoice_model_version"] == "v3"


class TestCosyVoiceConfigure:
    def test_tts_slot_bridge(self):
        from core.passes.cosyvoice_composite_pass import CosyVoiceCompositePass
        p = CosyVoiceCompositePass(output_dir="/tmp")
        p.configure({"tts": {"cosyvoice_model_version": "v3",
                             "default_lang": "zh",
                             "fp16": False}})
        assert p.model_version == "v3"
        assert p.default_lang == "zh"
        assert p.fp16 is False


class TestUpdateTtsAudioTypedSlot:
    """UPDATE_TTS_AUDIO 写类型化 TTSAudio 槽 (实测 E2E 崩溃回归)"""

    def test_update_sets_fields(self):
        from core.runtime.patch import Patch, OpCode
        from core.runtime.patch_engine import PatchEngine
        from core.ir.project import TimelineProjectIR
        from core.ir.timeline_event import TimelineEventIR
        from core.runtime.project_state import TimelineProjectState

        ir = TimelineProjectIR(events={
            "evt_001": TimelineEventIR(id="evt_001", start=0.0, end=1.0,
                                       text_ref="hi", speaker_ref=None),
        })
        state = TimelineProjectState(ir)
        p = Patch(
            id="tts_evt_001", target_id="evt_001",
            op=OpCode.UPDATE_TTS_AUDIO,
            value={"audio_ref": "05_tts/evt_001_edge.wav", "duration": 1.2,
                   "engine": "edge"},
            author="system",
        )
        PatchEngine().apply(state, p)
        es = state.get_event("evt_001")
        assert es.tts.audio_ref == "05_tts/evt_001_edge.wav"
        assert es.tts.duration == 1.2
        assert es.tts.engine == "edge"


class TestVideoExportPassCaption:
    """VideoExportPass caption_config 全字段承载 (构造验证)"""

    def test_full_field_carriers(self):
        from core.passes.video_export_pass import VideoExportPass
        p = VideoExportPass(
            video_path="/tmp/v.mp4", output_dir="/tmp/out",
            workspace_dir="/tmp/ws",
            caption_config={"font_size_mode": "fixed", "max_font_size": 40,
                            "font_size_factor": 0.03,
                            "enable_subtitle_optimization": False},
        )
        assert p.caption_config["font_size_mode"] == "fixed"
        assert p.caption_config["max_font_size"] == 40
        assert p.caption_config["font_size_factor"] == 0.03
        assert p.caption_config["enable_subtitle_optimization"] is False
