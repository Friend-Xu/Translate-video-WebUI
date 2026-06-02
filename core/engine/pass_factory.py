"""
Pass 工厂 — 将 WorkflowPolicy 中的 Pass 名称映射为实例。(批次02 §四)

用法:
    factory = create_pass_factory(translate_fn=my_translate, segments=segs, ...)
    pass_instance = factory("llm_translation")  # → LLMTranslationPass 实例

设计原则:
  - 闭包注入运行时依赖（LLM API key、SRT 路径等），保持依赖反转
  - 对未知 Pass 名称抛出 ValueError 并列出可用 Pass
  - ORPHAN Pass (TranslationQualityPass, EdgeTTSCompositePass) 一并注册
"""
from __future__ import annotations
from typing import Callable

from core.engine.pass_base import TimelinePass
from core.passes.asr_to_ir_pass import ASRToIRPass
from core.passes.asr_composite_pass import ASRCompositePass
from core.passes.audio_preprocess_composite_pass import AudioPreprocessCompositePass
from core.passes.semantic_merge_pass import SemanticMergePass
from core.passes.speaker_composite_pass import SpeakerCompositePass
from core.passes.llm_translation_pass import LLMTranslationPass
from core.passes.translation_quality_pass import TranslationQualityPass
from core.passes.emotion_composite_pass import EmotionCompositePass
from core.passes.srt_export_pass import SRTExportPass
from core.passes.video_export_pass import VideoExportPass
from core.passes.tts_composite_pass import TTSCompositePass
from core.passes.cosyvoice_composite_pass import CosyVoiceCompositePass
from core.passes.edge_tts_composite_pass import EdgeTTSCompositePass
from core.passes.indextts_composite_pass import IndexTTSCompositePass
from core.passes.openvoice_composite_pass import OpenVoiceCompositePass

# 所有已知 Pass 名称 → 构造函数（不含运行时参数）
_PASS_REGISTRY: dict[str, type] = {
    # LOAD stage
    "media_validate": AudioPreprocessCompositePass,
    "media_validator": AudioPreprocessCompositePass,
    "demucs": AudioPreprocessCompositePass,
    "audio_preprocess": AudioPreprocessCompositePass,
    # EXTRACT stage
    "asr": ASRCompositePass,
    "asr_to_ir": ASRToIRPass,
    "speaker": SpeakerCompositePass,
    "speaker_composite": SpeakerCompositePass,
    "semantic_merge": SemanticMergePass,
    # TRANSLATE stage
    "translate": LLMTranslationPass,
    "llm_translation": LLMTranslationPass,
    "quality_check": TranslationQualityPass,
    "translation_quality": TranslationQualityPass,
    # TTS stage
    "tts": TTSCompositePass,
    "tts_composite": TTSCompositePass,
    "emotion": EmotionCompositePass,
    "emotion_composite": EmotionCompositePass,
    # EXPORT stage
    "srt_export": SRTExportPass,
    "video_export": VideoExportPass,
    # Individual engine passes
    "cosyvoice_composite": CosyVoiceCompositePass,
    "edge_tts_composite": EdgeTTSCompositePass,
    "indextts_composite": IndexTTSCompositePass,
    "openvoice_composite": OpenVoiceCompositePass,
}

_RUNTIME_ARGS: dict[str, list[str]] = {
    "media_validate": ["video_path", "output_dir"],
    "media_validator": ["video_path", "output_dir"],
    "demucs": ["video_path", "output_dir", "skip_demucs"],
    "audio_preprocess": ["video_path", "output_dir"],
    "asr_to_ir": ["segments", "speaker_timeline"],
    "asr": ["audio_path", "workspace_dir"],
    "speaker": ["vocals_path", "output_dir", "num_speakers"],
    "speaker_composite": ["vocals_path", "output_dir", "num_speakers"],
    "translate": ["translate_fn"],
    "llm_translation": ["translate_fn"],
    "quality_check": ["quality_strategy"],
    "translation_quality": ["quality_strategy"],
    "srt_export": ["output_path"],
    "video_export": ["video_path", "output_dir", "workspace_dir", "caption_config"],
    "tts": ["output_dir"],
    "tts_composite": ["output_dir"],
    "emotion": ["workspace_dir"],
    "emotion_composite": ["workspace_dir"],
    "cosyvoice_composite": ["output_dir"],
    "edge_tts_composite": ["output_dir"],
}

AVAILABLE_PASS_NAMES = sorted(_PASS_REGISTRY.keys())


def create_pass_factory(
    translate_fn: Callable[[str], str] | None = None,
    segments: list | None = None,
    speaker_timeline: list | None = None,
    output_path: str = "",
    engine: str = "chattts",
    video_path: str = "",
    audio_path: str = "",
    output_dir: str = "",
    workspace_dir: str = "",
    quality_strategy = None,
    num_workers: int = 1,
    enable_speaker_diarization: bool = False,
    num_speakers: int = 0,
    enable_emotion: bool = False,
    verification_mode: str | None = None,
    skip_demucs: bool = False,
    caption_config: dict | None = None,
) -> Callable[[str], TimelinePass | None]:
    """通过闭包注入运行时依赖，返回 Pass 工厂函数。"""

    _runtime = {
        "segments": segments,
        "speaker_timeline": speaker_timeline,
        "translate_fn": translate_fn,
        "output_path": output_path,
        "engine": engine,
        "video_path": video_path,
        "audio_path": audio_path,
        "output_dir": output_dir,
        "workspace_dir": workspace_dir,
        "quality_strategy": quality_strategy,
        "num_workers": num_workers,
        "enable_speaker_diarization": enable_speaker_diarization,
        "num_speakers": num_speakers,
        "enable_emotion": enable_emotion,
        "verification_mode": verification_mode,
        "skip_demucs": skip_demucs,
        "caption_config": caption_config,
    }

    def _factory(name: str) -> TimelinePass | None:
        # Engine-based routing for generic tts/tts_composite → specific engine pass
        if name in ("tts", "tts_composite"):
            engine_name = _runtime.get("engine", "chattts")
            engine_map = {
                "chattts": "tts_composite",
                "edge": "edge_tts_composite",
                "cosyvoice": "cosyvoice_composite",
                "indextts": "indextts_composite",
                "openvoice": "openvoice_composite",
            }
            name = engine_map.get(engine_name, "tts_composite")
        cls = _PASS_REGISTRY.get(name)
        if cls is None:
            available = ", ".join(AVAILABLE_PASS_NAMES)
            raise ValueError(
                f"未知 Pass 名称: '{name}'。可用 Pass: {available}"
            )
        arg_names = _RUNTIME_ARGS.get(name, [])
        kwargs = {k: _runtime[k] for k in arg_names if k in _runtime}
        try:
            return cls(**kwargs)
        except TypeError as e:
            raise TypeError(
                f"Pass '{name}' ({cls.__name__}) 实例化失败: {e}"
            ) from e

    return _factory
