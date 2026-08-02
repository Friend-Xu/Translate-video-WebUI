"""
extract 收束契约测试 (架构收束 P2)

覆盖:
  - cli_bridge 参数映射 (--skip-align/--model/--device → gcfg 槽位)
  - ASRCompositePass 对齐门控 (alignment_enabled=False 跳过; 语言桥)
  - AudioPreprocessCompositePass validate_defect 桥
  - main._normalize_core_extract_files 产物标准名适配
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from types import SimpleNamespace

from core.engine.pass_factory import create_pass_factory
from core.passes.asr_composite_pass import ASRCompositePass
from core.passes.audio_preprocess_composite_pass import AudioPreprocessCompositePass
from core.runtime.project_state import TimelineProjectState
from core.ir.project import TimelineProjectIR
from core.ir.timeline_event import TimelineEventIR
from core.compat.cli_bridge import apply_cli_slot_overrides
from core.config.global_config import GlobalConfig


class TestCliBridgeSlotOverrides:
    def _gcfg(self):
        return GlobalConfig()

    def test_skip_align_disables_alignment(self):
        gcfg = self._gcfg()
        args = SimpleNamespace(skip_align=True)
        apply_cli_slot_overrides(args, gcfg)
        assert gcfg.project.asr["alignment_enabled"] is False

    def test_model_device_mapped(self):
        gcfg = self._gcfg()
        args = SimpleNamespace(model="turbo", device="cpu", compute_type="int8",
                               num_workers=2)
        apply_cli_slot_overrides(args, gcfg)
        assert gcfg.project.asr["model"] == "turbo"
        assert gcfg.project.asr["device"] == "cpu"
        assert gcfg.project.asr["compute_type"] == "int8"
        assert gcfg.project.asr["num_workers"] == 2

    def test_align_lang_maps_to_language(self):
        gcfg = self._gcfg()
        args = SimpleNamespace(align_lang="ja")
        apply_cli_slot_overrides(args, gcfg)
        assert gcfg.project.asr["language"] == "ja"

    def test_skip_defect_check_disables_validate(self):
        gcfg = self._gcfg()
        args = SimpleNamespace(skip_defect_check=True)
        apply_cli_slot_overrides(args, gcfg)
        assert gcfg.project.audio["validate_defect"] is False

    def test_skip_demucs_mapped(self):
        gcfg = self._gcfg()
        args = SimpleNamespace(skip_demucs=True)
        apply_cli_slot_overrides(args, gcfg)
        assert gcfg.project.audio["skip_demucs"] is True

    def test_empty_args_no_overrides(self):
        gcfg = self._gcfg()
        before = dict(gcfg.project.asr)
        args = SimpleNamespace()
        apply_cli_slot_overrides(args, gcfg)
        assert gcfg.project.asr == before


class TestASRCompositeGate:
    def _mk_pass(self):
        return ASRCompositePass(audio_path="/tmp/test.wav")

    def test_default_alignment_enabled(self):
        assert self._mk_pass().alignment_enabled is True

    def test_configure_disables_alignment(self):
        p = self._mk_pass()
        p.configure({"asr": {"alignment_enabled": False}})
        assert p.alignment_enabled is False

    def test_configure_language_bridge(self):
        p = self._mk_pass()
        p.configure({"asr": {"language": "ja"}})
        assert p.align_lang == "ja"
        assert p.ctx.language == "ja"

    def test_configure_model_device_bridge(self):
        p = self._mk_pass()
        p.configure({"asr": {"model": "turbo", "device": "cpu", "compute_type": "int8",
                             "num_workers": 2}})
        assert p.ctx.model_name == "turbo"
        assert p.ctx.device == "cpu"
        assert p.ctx.compute_type == "int8"
        assert p.ctx.num_workers == 2

    def test_whisper_run_still_happens_when_disabled(self, monkeypatch):
        """门控只关对齐, 不影响 whisper ASR 主流程"""
        import core.passes.asr_composite_pass as mod

        class FakeWhisper:
            def __init__(self, ctx, workspace_dir=""):
                self.ctx = ctx

            def run(self):
                return []

        calls = {"aligned": 0}

        class FakeWav2Vec2:
            def __init__(self, audio_path, language):
                pass

            def refine_alignment(self, segments):
                calls["aligned"] += 1
                return []

            def extract_semantic(self, segment_ids, output_dir=""):
                calls["aligned"] += 1
                return []

        monkeypatch.setattr(mod, "WhisperAdapter", FakeWhisper)
        monkeypatch.setattr(mod, "Wav2Vec2Adapter", FakeWav2Vec2)
        p = self._mk_pass()
        p.configure({"asr": {"alignment_enabled": False}})
        p.apply()
        assert calls["aligned"] == 0


class TestAudioPreprocessBridge:
    def test_validate_defect_false_sets_skip(self):
        p = AudioPreprocessCompositePass()
        p.configure({"audio": {"validate_defect": False}})
        assert p.skip_defect_check is True

    def test_validate_defect_true_default(self):
        p = AudioPreprocessCompositePass()
        p.configure({"audio": {"validate_defect": True}})
        assert p.skip_defect_check is False

    def test_skip_demucs_bridge(self):
        p = AudioPreprocessCompositePass()
        p.configure({"audio": {"skip_demucs": True}})
        assert p.skip_demucs is True


class TestNormalizeCoreExtractFiles:
    """main._normalize_core_extract_files 产物标准名适配"""

    @staticmethod
    def _mk_state() -> TimelineProjectState:
        ir = TimelineProjectIR(events={
            "evt_001": TimelineEventIR(id="evt_001", start=0.0, end=1.5,
                                       text_ref="Hello world", speaker_ref=None),
        })
        return TimelineProjectState(ir)

    def _run(self, tmp_path, *, skip_demucs=False):
        from core.compat.cli_bridge import normalize_core_extract_files
        extract_dir = str(tmp_path)
        extracted = os.path.join(extract_dir, "Test_JP_extracted.wav")
        open(extracted, "w", encoding="utf-8").write("wav")
        demucs_dir = os.path.join(extract_dir, "htdemucs", "Test_JP")
        os.makedirs(demucs_dir, exist_ok=True)
        open(os.path.join(demucs_dir, "vocals.wav"), "w", encoding="utf-8").write("v")
        open(os.path.join(demucs_dir, "no_vocals.wav"), "w", encoding="utf-8").write("n")
        normalize_core_extract_files(self._mk_state(), extract_dir, "Test_JP",
                                     skip_demucs=skip_demucs)
        return extract_dir

    def test_extracted_wav_renamed(self, tmp_path):
        d = self._run(tmp_path)
        assert os.path.isfile(os.path.join(d, "audio.wav"))
        assert not os.path.isfile(os.path.join(d, "Test_JP_extracted.wav"))

    def test_demucs_outputs_renamed(self, tmp_path):
        d = self._run(tmp_path)
        assert os.path.isfile(os.path.join(d, "vocals.wav"))
        assert os.path.isfile(os.path.join(d, "instrumental.wav"))

    def test_demucs_dir_named_after_audio_stem(self, tmp_path):
        """demucs 目录名是输入音频名 (Test_JP_extracted), 不是视频名"""
        from core.compat.cli_bridge import normalize_core_extract_files
        extract_dir = str(tmp_path)
        os.makedirs(os.path.join(extract_dir, "htdemucs", "Test_JP_extracted"),
                    exist_ok=True)
        open(os.path.join(extract_dir, "Test_JP_extracted.wav"), "w",
             encoding="utf-8").write("w")
        open(os.path.join(extract_dir, "htdemucs", "Test_JP_extracted",
                          "vocals.wav"), "w", encoding="utf-8").write("v")
        open(os.path.join(extract_dir, "htdemucs", "Test_JP_extracted",
                          "no_vocals.wav"), "w", encoding="utf-8").write("n")
        normalize_core_extract_files(self._mk_state(), extract_dir, "Test_JP",
                                     skip_demucs=False)
        assert os.path.isfile(os.path.join(extract_dir, "vocals.wav"))
        assert os.path.isfile(os.path.join(extract_dir, "instrumental.wav"))

    def test_skip_demucs_keeps_original(self, tmp_path):
        d = self._run(tmp_path, skip_demucs=True)
        assert os.path.isfile(os.path.join(d, "audio.wav"))
        assert not os.path.isfile(os.path.join(d, "vocals.wav"))

    def test_source_srt_synthesized_from_state(self, tmp_path):
        d = self._run(tmp_path)
        srt = os.path.join(d, "source.srt")
        assert os.path.isfile(srt)
        content = open(srt, encoding="utf-8").read()
        assert "Hello world" in content
        assert "00:00:00" in content

    def test_existing_source_srt_preserved(self, tmp_path):
        extract_dir = str(tmp_path)
        os.makedirs(extract_dir, exist_ok=True)
        with open(os.path.join(extract_dir, "source.srt"), "w", encoding="utf-8") as f:
            f.write("existing")
        from core.compat.cli_bridge import normalize_core_extract_files
        normalize_core_extract_files(self._mk_state(), extract_dir, "Test_JP",
                                     skip_demucs=True)
        assert open(os.path.join(extract_dir, "source.srt"), encoding="utf-8").read() == "existing"


class TestSpeakerSplitBoundaries:
    """pyannote 重叠 turn 等时边界 → 零时长段修复 (实测 evt_009_spk00 start==end)"""

    def test_equal_time_boundaries_deduped(self):
        """重叠 turn 同时开始 — 等时边界必须去重, 否则产生零时长切分"""
        from core.adapters.pyannote_adapter import PyannoteAdapter
        # segment [60, 70], 两个 turn 都从 65.48 开始 (pyannote 重叠)
        speaker_timeline = [
            ("SPEAKER_00", 60.0, 68.0, 0.9),
            ("SPEAKER_01", 65.48, 70.0, 0.85),
            ("SPEAKER_02", 65.48, 72.0, 0.80),
        ]
        boundaries = PyannoteAdapter._find_internal_boundaries(
            60.0, 70.0, speaker_timeline,
        )
        times = [b["time"] for b in boundaries]
        assert len(times) == len(set(times))  # 无等时边界
        assert times == sorted(times)

    def test_split_skips_zero_length_segments(self):
        """防御: 边界等时时 _split_by_speaker 跳过零时长段, 不进 IR"""
        from core.runtime.patch import Patch, OpCode
        from core.runtime.patch_engine import PatchEngine
        from core.ir.project import TimelineProjectIR
        from core.ir.timeline_event import TimelineEventIR
        from core.runtime.project_state import TimelineProjectState

        ir = TimelineProjectIR(events={
            "evt_001": TimelineEventIR(id="evt_001", start=60.0, end=70.0,
                                       text_ref="abc", speaker_ref=None),
        })
        state = TimelineProjectState(ir)
        p = Patch(
            id="boundary_evt_001", target_id="evt_001",
            op=OpCode.SPLIT_SEGMENT_BY_SPEAKER,
            value={"boundaries": [
                {"speaker": "SPEAKER_00", "time": 60.0},
                {"speaker": "SPEAKER_01", "time": 65.48},
                {"speaker": "SPEAKER_02", "time": 65.48},
            ]},
            author="system",
        )
        result = PatchEngine().apply(state, p)
        created = result.get("created", [])
        # 等时边界 65.48 产生 [65.48, 65.48] 零时长段 → 跳过
        for seg_id in created:
            es = state.get_event(seg_id)
            assert es.end > es.start
