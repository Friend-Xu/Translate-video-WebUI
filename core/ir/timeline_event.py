"""
TimelineEventIR — 不可变时间轴事件（最小语义单元）

零外部依赖，frozen=True 禁止任何原地修改。
这是 IR 层的原子节点，只包含从 ASR/alignment 提取的原始数据。
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class TimelineEventIR:
    """不可变事件 — 时间轴的最小语义片段。

    所有字段在构造时锁定，任何修改尝试均抛出 FrozenInstanceError。
    不包含 translation、衍生数据、patch — 这些都是 runtime 层关注点。
    """
    id: str                         # "evt_001" — 稳定唯一标识
    start: float                    # 起始时间 (秒)
    end: float                      # 结束时间 (秒)
    speaker_ref: str | None         # → SpeakerNodeIR.id，或无
    text_ref: str                   # payload 文本引用（原始 ASR 文本）
    source: str = "asr"             # "asr" | "alignment" | "manual"

    def __post_init__(self):
        if self.start >= self.end:
            orig_end = self.end
            object.__setattr__(self, "end", self.start + 0.01)
            import logging
            logging.getLogger("core.ir").warning(
                "TimelineEventIR %s: start(%.2f) >= end(%.2f), auto-corrected to +10ms",
                self.id, self.start, orig_end)
