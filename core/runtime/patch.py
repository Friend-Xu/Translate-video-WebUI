"""
Patch — runtime 层 mutation 原语

Patch 只追加到 TimelineEventState.patches，绝不修改 IR。
所有 patch 按 timestamp 排序执行，保证确定性。

v2.1: OpCode 枚举约束 patch 操作类型，同时继承 str 保证向后兼容。
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
import time


class OpCode(str, Enum):
    """Patch 操作码 — 继承 str 保证与现有字符串比较向后兼容。"""
    # v2.1 新操作码
    SEGMENT_INSERT = "segment_insert"
    SEGMENT_SPLIT = "segment_split"
    SEGMENT_MERGE = "segment_merge"
    # ASR 类
    UPDATE_TRANSCRIPTION = "update_transcription"
    REFINE_ALIGNMENT = "refine_alignment"
    # Speaker 类
    ASSIGN_SPEAKER = "assign_speaker"
    MERGE_SPEAKERS = "merge_speakers"
    SPLIT_SEGMENT_BY_SPEAKER = "split_segment_by_speaker"
    # TTS 类
    UPDATE_TTS_AUDIO = "update_tts_audio"
    # Translation 类
    UPDATE_TRANSLATION = "update_translation"
    # Emotion 类 (Ch15)
    UPDATE_EMOTION = "update_emotion"
    # 通用
    ANNOTATE = "annotate"
    # v1.0 向后兼容别名 — 现有 patch_engine 和 pass 使用
    MERGE = "merge"
    SPLIT = "split"
    REPLACE = "replace"
    PROPAGATE = "propagate"


@dataclass
class Patch:
    """Runtime 层状态修改原语。

    Patch 是纯数据，不包含任何执行逻辑。
    执行逻辑在 PatchEngine 中。
    """
    PROTOCOL_VERSION = "2.0"  # Patch 协议版本

    id: str                         # "patch_001"
    target_id: str                  # event_id — 目标事件
    op: OpCode                      # 操作码 (OpCode 枚举，兼容 str)
    value: dict                     # 与 op 对应的 payload
    timestamp: float = 0.0
    author: str = "system"          # "system" | "user" | "ai"
    # v2.0 (patch_log.schema.json §PatchEntry)
    targets: list[str] | None = None  # 多目标事件 ID 列表
    reason: list[str] | None = None   # 变更原因描述
    score: float = 1.0                # AI 评分 [0,1]
    confidence: float = 1.0           # 置信度 [0,1]
    parent_version: str = ''          # 父版本标识
    idempotency_key: str = ''         # 幂等键

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()
