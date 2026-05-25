"""
Patch — runtime 层 mutation 原语

Patch 只追加到 TimelineEventState.patches，绝不修改 IR。
所有 patch 按 timestamp 排序执行，保证确定性。
"""
from __future__ import annotations
from dataclasses import dataclass
import time


@dataclass
class Patch:
    """Runtime 层状态修改原语。

    Patch 是纯数据，不包含任何执行逻辑。
    执行逻辑在 PatchEngine 中。
    """
    id: str                         # "patch_001"
    target_id: str                  # event_id — 目标事件
    op: str                         # merge | split | replace | propagate
    value: dict                     # 与 op 对应的 payload
    timestamp: float = 0.0
    author: str = "system"          # "system" | "user" | "ai"
    # v2.0 新增（对应 patch_log.schema.json §PatchEntry，向前端 TimelinePatchData 对齐）
    targets: list[str] | None = None  # 多目标事件 ID 列表
    reason: list[str] | None = None   # 变更原因描述
    score: float = 1.0                # AI 评分 [0,1]
    confidence: float = 1.0           # 置信度 [0,1]
    parent_version: str = ''          # 父版本标识
    idempotency_key: str = ''         # 幂等键

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()
