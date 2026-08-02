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
    # 时间边界 (Phase 4: 旧 RESIZE 对等物)
    UPDATE_BOUNDS = "update_bounds"
    # Speaker 类
    ASSIGN_SPEAKER = "assign_speaker"
    MERGE_SPEAKERS = "merge_speakers"
    SPLIT_SEGMENT_BY_SPEAKER = "split_segment_by_speaker"
    # Speaker 注册表类 (P2 收敛: 注册表级操作统一走 patch)
    REGISTER_SPEAKER = "register_speaker"
    UPDATE_SPEAKER = "update_speaker"
    LOCK_SPEAKER = "lock_speaker"
    # TTS 类
    UPDATE_TTS_AUDIO = "update_tts_audio"
    # Translation 类
    UPDATE_TRANSLATION = "update_translation"
    # Emotion 类 (Ch15)
    UPDATE_EMOTION = "update_emotion"
    # 配置类 (v3.0 — 定稿 §10.5)
    SET_CONFIG = "set_config"
    OVERRIDE_CONFIG = "override_config"
    RESET_CONFIG = "reset_config"
    BATCH_SET_CONFIG = "batch_set_config"
    # 通用
    ANNOTATE = "annotate"
    # v1.0 向后兼容别名 — 现有 patch_engine 和 pass 使用
    MERGE = "merge"
    SPLIT = "split"
    REPLACE = "replace"


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
        if self.timestamp is None or abs(self.timestamp) < 1e-9:
            self.timestamp = time.time()

    def to_dict(self) -> dict:
        """序列化 (Phase 4: patch 链持久化用)。op 存小写字符串。"""
        return {
            "id": self.id,
            "target_id": self.target_id,
            "op": self.op.value,
            "value": self.value,
            "timestamp": self.timestamp,
            "author": self.author,
            "targets": self.targets,
            "reason": self.reason,
            "score": self.score,
            "confidence": self.confidence,
            "parent_version": self.parent_version,
            "idempotency_key": self.idempotency_key,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Patch":
        """从 to_dict 恢复。op 必须是 OpCode 已知值, 未知响亮报错 (禁止兜底)。"""
        op_raw = d.get("op", "")
        if isinstance(op_raw, OpCode):
            op = op_raw
        else:
            try:
                op = OpCode(str(op_raw).lower())
            except ValueError:
                raise ValueError(
                    f"Patch.from_dict: 未知 opcode '{op_raw}' "
                    f"(合法: {[o.value for o in OpCode]})"
                )
        return cls(
            id=d["id"],
            target_id=d.get("target_id", ""),
            op=op,
            value=d.get("value", {}),
            timestamp=d.get("timestamp", 0.0),
            author=d.get("author", "system"),
            targets=d.get("targets"),
            reason=d.get("reason"),
            score=d.get("score", 1.0),
            confidence=d.get("confidence", 1.0),
            parent_version=d.get("parent_version", ""),
            idempotency_key=d.get("idempotency_key", ""),
        )
