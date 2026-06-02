"""
Naming Registry — Adapter/Pass/Gate 统一命名注册表 (定稿 §3.1, GAP-3.1-1)

所有通过名称反射加载的组件必须在此注册。命名规范:
  - Adapter: snake_case + "_adapter" 后缀
  - Pass:    snake_case (无强制后缀)
  - Gate:    snake_case + "_gate" 后缀
"""
from __future__ import annotations
from enum import Enum


class AdapterRegistry(str, Enum):
    WHISPER = "whisper_adapter"
    WAV2VEC2 = "wav2vec2_adapter"
    PYANNOTE = "pyannote_adapter"
    CHAT_TTS = "chattts_adapter"
    COSY_VOICE = "cosyvoice_adapter"
    EDGE_TTS = "edge_tts_adapter"
    INDEX_TTS = "indextts_adapter"
    OPEN_VOICE = "openvoice_adapter"
    DEMUCS = "demucs_adapter"
    MEDIA_VALIDATOR = "media_validator_adapter"
    VAD_BOUNDARY = "vad_boundary_adapter"
    MINILM = "minilm_adapter"
    PPL = "ppl_adapter"
    EMOTION_RECOGNIZER = "emotion_recognizer_adapter"


class PassRegistry(str, Enum):
    AUDIO_PREPROCESS = "audio_preprocess"
    ASR_COMPOSITE = "asr_composite"
    ASR_TO_IR = "asr_to_ir"
    SEMANTIC_MERGE = "semantic_merge"
    SPEAKER_COMPOSITE = "speaker_composite"
    LLM_TRANSLATION = "llm_translation"
    TRANSLATION_QUALITY = "translation_quality"
    TTS_COMPOSITE = "tts_composite"
    COSY_VOICE_TTS = "cosyvoice_composite"
    EDGE_TTS = "edge_tts_composite"
    INDEX_TTS = "indextts_composite"
    OPEN_VOICE = "openvoice_composite"
    EMOTION_COMPOSITE = "emotion_composite"
    SRT_EXPORT = "srt_export"


class GateRegistry(str, Enum):
    TEXT_GATE = "text_gate"
    EMOTION_GATE = "emotion_gate"


def resolve_adapter(name: str) -> str | None:
    try:
        return AdapterRegistry(name).value
    except ValueError:
        for m in AdapterRegistry:
            if m.value == name:
                return m.value
        return None


def resolve_pass(name: str) -> str | None:
    try:
        return PassRegistry(name).value
    except ValueError:
        for m in PassRegistry:
            if m.value == name:
                return m.value
        return None


def resolve_gate(name: str) -> str | None:
    try:
        return GateRegistry(name).value
    except ValueError:
        for m in GateRegistry:
            if m.value == name:
                return m.value
        return None


def validate_name(category: str, name: str) -> bool:
    registry = {"adapter": AdapterRegistry, "pass": PassRegistry, "gate": GateRegistry}.get(category)
    if registry is None:
        return False
    try:
        registry(name)
        return True
    except ValueError:
        return any(m.value == name for m in registry)
