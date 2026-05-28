"""
AudioPreprocessCompositePass — 音频前置层统一编排 (Chapter 10 §10.1-10.9)

编织 MediaValidatorAdapter + DemucsAdapter + VADBoundaryAdapter。
这是整个系统最前置的 pass——所有下游引擎依赖它提供的干净音频。

依赖: []（无依赖，前置层）

编排顺序:
  1. MediaValidatorAdapter.diagnose() → ANNOTATE (defect info)
  2. MediaValidatorAdapter.repair_and_extract() → ANNOTATE (audio_ref)
  3. DemucsAdapter.separate() → ANNOTATE (vocals_ref, bgm_ref)
  4. VADBoundaryAdapter.detect_boundaries() → [SEGMENT_INSERT, ...]
"""
from __future__ import annotations
from core.engine.pass_base import TimelinePass
from core.runtime.project_state import TimelineProjectState
from core.runtime.patch_engine import PatchEngine
from core.adapters.media_validator_adapter import (
    MediaValidatorAdapter, AudioDefectContext,
)
from core.adapters.demucs_adapter import DemucsAdapter, DemucsContext
from core.adapters.vad_boundary_adapter import VADBoundaryAdapter, VADBoundaryContext


class AudioPreprocessCompositePass(TimelinePass):
    """音频前置层完整编排。

    四步时序:
      Step 1: 缺陷诊断 → defect_status, defect_type, needs_repair
      Step 2: 音频提取 + C2 修复 → audio_ref, sample_rate, channels
      Step 3: Demucs 人声分离 → vocals_ref, bgm_ref
      Step 4: VAD 边界检测 → SEGMENT_INSERT patches
    """

    name = "audio_preprocess"
    depends_on = []  # 无依赖，前置层

    def __init__(self, video_path: str = "",
                 output_dir: str = "",
                 skip_demucs: bool = False,
                 skip_defect_check: bool = False,
                 skip_vad: bool = False,
                 sample_rate: int = 16000,
                 channels: int = 1):
        self.video_path = video_path
        self.output_dir = output_dir
        self.skip_demucs = skip_demucs
        self.skip_defect_check = skip_defect_check
        self.skip_vad = skip_vad
        self.sample_rate = sample_rate
        self.channels = channels
        self._resolved_config: dict | None = None

    def configure(self, resolved_config: dict | None = None) -> None:
        cfg = resolved_config or {}
        self._resolved_config = cfg
        if "skip_demucs" in cfg:
            self.skip_demucs = cfg["skip_demucs"]

    def apply(self, state: TimelineProjectState) -> TimelineProjectState:
        engine = PatchEngine()
        video_path = self.video_path or getattr(state.ir, 'source_video', '')

        if not video_path:
            return state

        import os

        # Ensure output directory exists
        out_dir = self.output_dir or os.path.join(os.path.dirname(video_path) or ".", "")
        os.makedirs(os.path.join(out_dir, "01_extract"), exist_ok=True)

        # Step 1: 缺陷诊断
        if not self.skip_defect_check:
            defect_ctx = AudioDefectContext(
                video_path=video_path,
                sample_rate=self.sample_rate,
                channels=self.channels,
            )
            validator = MediaValidatorAdapter()
            patch = validator.diagnose(defect_ctx)
            engine.apply(state, patch)

            # Step 2: 音频提取 + C2 修复
            audio_path = os.path.join(
                self.output_dir or os.path.dirname(video_path) or ".",
                "01_extract",
                f"{os.path.splitext(os.path.basename(video_path))[0]}_extracted.wav",
            )
            defect_ctx.output_audio_path = audio_path
            patch = validator.repair_and_extract(defect_ctx)
            engine.apply(state, patch)

        # Step 3: Demucs 人声分离
        vocals_ref = ""
        bgm_ref = ""
        if not self.skip_demucs:
            demucs_input = audio_path if 'audio_path' in dir() else video_path
            demucs_ctx = DemucsContext(
                audio_path=demucs_input,
                output_dir=self.output_dir or os.path.dirname(video_path) or ".",
            )
            demucs = DemucsAdapter()
            patch = demucs.separate(demucs_ctx)
            engine.apply(state, patch)
            vocals_ref = patch.value.get("vocals_ref", "")
            bgm_ref = patch.value.get("bgm_ref", "")

        # Step 4: VAD 边界检测
        if not self.skip_vad:
            vad_audio = vocals_ref or (audio_path if 'audio_path' in dir() else video_path)
            vad_ctx = VADBoundaryContext(audio_path=vad_audio)
            vad = VADBoundaryAdapter()
            patches = vad.detect_boundaries(vad_ctx)
            for p in patches:
                engine.apply(state, p)

        return state
