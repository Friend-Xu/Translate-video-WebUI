"""Workflow Preset definitions — Pipeline as Timeline Runtime bootstrap templates.

Each preset defines a Pass DAG that initializes a Timeline IR from source video.
Pipeline is NOT the system core here — it is a bootstrap executor for Timeline Runtime.

批次11 §阶段C: 每个 WorkflowPreset 新增 policy_fn 字段，委托到 core/ WorkflowPolicy
工厂方法，使 WebUI 可以直接通过 WorkflowOrchestrator 编排 Pipeline。
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Callable


class RuntimeState(str, enum.Enum):
    """Timeline Runtime lifecycle states."""

    UNINITIALIZED = "uninitialized"
    BOOTSTRAPPING = "bootstrapping"
    READY = "ready"
    COMPUTING = "computing"
    FAILED = "failed"
    COMPLETE = "complete"


@dataclass
class WorkflowPreset:
    """A named Pass DAG template that bootstraps a Timeline Runtime."""

    id: str
    name: str
    name_en: str
    description: str
    icon: str  # MUI icon component name
    passes: list[str]  # ordered pass IDs forming the DAG
    tags: list[str] = field(default_factory=list)
    config_defaults: dict = field(default_factory=dict)
    # 批次11 §阶段C: 指向 WorkflowPolicy 工厂方法
    policy_fn: Callable[[str], object] | None = None

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "name": self.name,
            "nameEn": self.name_en,
            "description": self.description,
            "icon": self.icon,
            "passes": self.passes,
            "tags": self.tags,
            "configDefaults": self.config_defaults,
        }
        if self.policy_fn is not None:
            d["hasPolicy"] = True
        return d


def _quick_preset(lang: str):
    from core.config.workflow_policy import WorkflowPolicy
    return WorkflowPolicy.quick_preset(lang)


def _default_preset(lang: str):
    from core.config.workflow_policy import WorkflowPolicy
    return WorkflowPolicy.default_preset(lang)


PRESETS: list[WorkflowPreset] = [
    WorkflowPreset(
        id="quick_sub_single",
        name="快速字幕",
        name_en="Quick Subtitles",
        description="单人视频快速提取字幕。跳过人声分离和说话人识别，仅 ASR → 翻译 → SRT，最快输出。",
        icon="SubtitlesRounded",
        passes=["media_validate", "asr", "semantic_merge", "translate", "srt_export"],
        tags=["单人", "仅字幕", "极速"],
        config_defaults={
            "skip_tts": True,
            "skip_demucs": True,
            "enable_speaker_diarization": False,
        },
        policy_fn=_quick_preset,
    ),
    WorkflowPreset(
        id="quick_sub_multi",
        name="快速字幕（多人）",
        name_en="Quick Subtitles (Multi)",
        description="多人视频字幕提取。人声分离 → 说话人识别 → ASR → 翻译 → SRT，可审查说话人标签。",
        icon="SubtitlesRounded",
        passes=["media_validate", "demucs", "asr", "speaker", "semantic_merge", "translate", "srt_export"],
        tags=["多人", "仅字幕", "说话人"],
        config_defaults={
            "skip_tts": True,
            "skip_demucs": False,
            "enable_speaker_diarization": True,
        },
        policy_fn=_quick_preset,
    ),
    WorkflowPreset(
        id="dub_single",
        name="一键成片",
        name_en="One-Click Dub",
        description="单人视频全自动配音。ASR → 翻译 → TTS → 导出，无审查暂停，一键输出成品。",
        icon="AutoAwesomeRounded",
        passes=["media_validate", "asr", "semantic_merge", "translate", "quality_check", "tts", "emotion", "srt_export", "export"],
        tags=["单人", "全自动", "TTS"],
        config_defaults={
            "full_pipeline": True,
            "skip_demucs": True,
            "enable_speaker_diarization": False,
        },
        policy_fn=_default_preset,
    ),
    WorkflowPreset(
        id="dub_multi",
        name="多说话人配音",
        name_en="Multi-Speaker Dub",
        description="多人视频完整配音。人声分离 → 说话人识别 → ASR → 翻译 → [审查] → TTS → 导出。翻译完成后暂停供审查修正。",
        icon="TheatersRounded",
        passes=["media_validate", "demucs", "asr", "speaker", "semantic_merge", "translate", "quality_check", "tts", "emotion", "srt_export", "export"],
        tags=["多人", "审查", "TTS"],
        config_defaults={
            "full_pipeline": True,
            "skip_demucs": False,
            "enable_speaker_diarization": True,
        },
        policy_fn=_default_preset,
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
