"""
SpeakerNodeIR — 不可变说话人节点

说话人从字符串标签升级为独立实体，通过 speaker_ref 与事件关联。
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
