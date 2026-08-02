"""
SpeakerNodeIR — 不可变说话人节点

说话人从字符串标签升级为独立实体，通过 speaker_ref 与事件关联。
v2.1: 新增 embedding/confidence/profile 字段以承载 pyannote + voice cloning 输出。
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class SpeakerNodeIR:
    """不可变说话人节点 — 声学身份的稳定表示。

    不与 LogicSpeaker（可重命名）或 RuntimeSpeaker（TTS 映射）混淆。
    """
    id: str                         # "SPEAKER_00" — 来自 diarization 的稳定 ID
    name: str | None = None         # 显示名，None 表示未命名
    # v2.0 (speaker_map.schema.json §SpeakerMapping)
    voice_id: str | None = None     # 绑定的 TTS 声线 ID
    engine: str | None = None       # 绑定的 TTS 引擎 (speaker/bind, T5.2)
    voice_profile: dict | None = None  # 说话人级 voice profile (speaker/bind, T5.2)
    color: str | None = None        # UI 轨道颜色 (#RRGGBB)
    is_locked: bool = False         # 禁止自动合并/拆分
    # v2.1: speaker identity 字段 (Chapter 4 §4.4)
    embedding_ref: str | None = None  # speaker embedding 存储路径
    gender_prob: float | None = None  # 性别概率 [0,1]
    voice_style: str | None = None    # "neutral" | "energetic" | "calm" | "authoritative"
    confidence: float | None = None   # pyannote diarization 置信度 [0,1]
    # v3.0: 说话人级配置覆盖 (定稿 §8.3, §10.4)
    config: dict | None = None       # 说话人级 config，如 {"tts": {"engine": "cosyvoice"}}
