"""Workflow Preset definitions — Pipeline as Timeline Runtime bootstrap templates.

Each preset defines a Pass DAG that initializes a Timeline IR from source video.
Pipeline is NOT the system core here — it is a bootstrap executor for Timeline Runtime.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class RuntimeState(str, enum.Enum):
    """Timeline Runtime lifecycle states.

    UNINITIALIZED  workspace created, no pipeline run yet
    BOOTSTRAPPING  pipeline subprocess running, initializing Timeline IR
    READY          Timeline IR loaded, user can interactively edit
    COMPUTING      local pass recompute in progress (patch / selective rerun)
    FAILED         bootstrap or pass failed, recoverable
    COMPLETE       final export rendered
    """

    UNINITIALIZED = "uninitialized"
    BOOTSTRAPPING = "bootstrapping"
    READY = "ready"
    COMPUTING = "computing"
    FAILED = "failed"
    COMPLETE = "complete"


@dataclass
class WorkflowPreset:
    """A named Pass DAG template that bootstraps a Timeline Runtime.

    Each preset is a pre-configured set of passes with default config values.
    Users select a preset in the Hub, then customize in the Bootstrap Wizard.
    """

    id: str
    name: str  # display name (Chinese)
    name_en: str  # display name (English)
    description: str
    icon: str  # MUI icon component name
    passes: list[str]  # ordered pass IDs forming the DAG
    tags: list[str] = field(default_factory=list)
    config_defaults: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "nameEn": self.name_en,
            "description": self.description,
            "icon": self.icon,
            "passes": self.passes,
            "tags": self.tags,
            "configDefaults": self.config_defaults,
        }


# ── Pass ID reference (maps to core/passes/ module names) ──────────────
# asr              → ASRCompositePass (whisper + wav2vec2 alignment)
# speaker          → SpeakerCompositePass (pyannote + clustering)
# translate        → LLMTranslationPass (DeepSeek/OpenAI API)
# tts              → TTSCompositePass (EdgeTTS / ChatTTS / CosyVoice)
# srt_export       → SRTExportPass
# demucs           → AudioPreprocessCompositePass (Demucs vocal separation)
# media_validate   → MediaValidatorAdapter (C2 defect check)
# semantic_merge   → SemanticMergePass
# quality_check    → TranslationQualityPass (MiniLM + PPL scoring)
# emotion          → EmotionCompositePass

PRESETS: list[WorkflowPreset] = [
    WorkflowPreset(
        id="quick_subtitle",
        name="快速字幕",
        name_en="Quick Subtitle",
        description="仅提取和翻译字幕，不生成 TTS 语音。适合快速获得双语字幕文件。",
        icon="SubtitlesRounded",
        passes=["media_validate", "asr", "semantic_merge", "translate", "srt_export"],
        tags=["轻量", "无TTS", "最快"],
        config_defaults={
            "skip_tts": True,
            "skip_demucs": True,
            "compute_type": "int8",
        },
    ),
    WorkflowPreset(
        id="cinema_dub",
        name="影院配音",
        name_en="Cinema Dub",
        description="完整管线：人声分离 → ASR → 说话人识别 → 翻译 → TTS 合成 → 字幕渲染 → 最终合成。适合影视级配音。",
        icon="TheatersRounded",
        passes=[
            "media_validate", "demucs", "asr", "speaker",
            "semantic_merge", "translate", "quality_check",
            "tts", "emotion", "srt_export",
        ],
        tags=["完整管线", "高质量", "TTS"],
        config_defaults={
            "skip_demucs": False,
            "enable_speaker_diarization": True,
            "compute_type": "float16",
        },
    ),
    WorkflowPreset(
        id="translate_only",
        name="仅翻译字幕",
        name_en="Translate Only",
        description="基于已有 SRT 字幕文件进行翻译，不重新提取音频。适合已有字幕的视频。",
        icon="TranslateRounded",
        passes=["translate", "quality_check", "srt_export"],
        tags=["无ASR", "仅翻译", "最快"],
        config_defaults={
            "skip_extract": True,
            "skip_tts": True,
            "skip_demucs": True,
        },
    ),
    WorkflowPreset(
        id="podcast_cleanup",
        name="播客清理",
        name_en="Podcast Cleanup",
        description="多说话人识别 + 翻译，不生成 TTS。适合播客、访谈类多说话人内容。",
        icon="PodcastsRounded",
        passes=[
            "media_validate", "demucs", "asr", "speaker",
            "semantic_merge", "translate", "srt_export",
        ],
        tags=["多说话人", "无TTS", "播客"],
        config_defaults={
            "skip_tts": True,
            "enable_speaker_diarization": True,
            "skip_demucs": False,
        },
    ),
]


def get_presets() -> list[dict]:
    """Return all workflow presets as serializable dicts."""
    return [p.to_dict() for p in PRESETS]


def get_preset(preset_id: str) -> WorkflowPreset | None:
    """Look up a single preset by ID."""
    for p in PRESETS:
        if p.id == preset_id:
            return p
    return None
