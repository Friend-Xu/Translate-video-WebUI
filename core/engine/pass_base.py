"""
TimelinePass — Pass 抽象基类

每个 Pass 是纯函数变换：state_in → state_out。
不修改入参 IR，只通过 state 层操作。
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from core.runtime.project_state import TimelineProjectState


class TimelinePass(ABC):
    """Pass 抽象基类。

    Usage:
        class MyPass(TimelinePass):
            name = "my_pass"
            depends_on = ["asr_to_ir"]

            def apply(self, state):
                return state
    """
    name: str = ""
    depends_on: list[str] = []

    @abstractmethod
    def apply(self, state: TimelineProjectState) -> TimelineProjectState:
        """执行 pass 变换。接收 state，返回 state。"""
        ...
