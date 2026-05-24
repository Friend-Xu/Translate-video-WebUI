"""
TimelineEventState — 事件的运行时状态

持有 IR 引用（只读）+ derivatives + patches 链。
这是 zero-deepcopy 架构的关键：不复制 IR，只在 state 层叠加变更。
"""
from __future__ import annotations
from core.ir.timeline_event import TimelineEventIR
from core.runtime.patch import Patch


class TimelineEventState:
    """事件的运行时可变状态。

    - self.ir: 只读引用，绝不被修改
    - self.derivatives: Pass 产出的衍生数据（translation, emotion, cps...）
    - self.patches: 用户/AI 补丁链，按 timestamp 排序
    """
    __slots__ = ("ir", "derivatives", "patches")

    def __init__(self, ir: TimelineEventIR):
        self.ir = ir
        self.derivatives: dict = {}
        self.patches: list[Patch] = []

    @property
    def id(self) -> str:
        return self.ir.id

    @property
    def start(self) -> float:
        return self.ir.start

    @property
    def end(self) -> float:
        return self.ir.end

    @property
    def speaker_ref(self) -> str | None:
        return self.ir.speaker_ref

    def add_patch(self, patch: Patch) -> None:
        """追加 patch 并保持 timestamp 排序"""
        self.patches.append(patch)
        self.patches.sort(key=lambda p: p.timestamp)
