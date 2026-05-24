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

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()
