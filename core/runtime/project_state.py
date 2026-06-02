"""
TimelineProjectState — 项目级运行时状态

持有 TimelineProjectIR 引用 + 全部 event_states + 全局 patches。
整个 pipeline 唯一可变容器。
"""
from __future__ import annotations
from enum import Enum
from core.ir.project import TimelineProjectIR
from core.runtime.event_state import TimelineEventState
from core.runtime.patch import Patch


class RuntimeState(Enum):
    """Timeline Runtime 生命周期状态（设计文档 §7 生命周期管理）。

    DRAFT      — 输入已建档，尚未跑完 bootstrap
    PROCESSING — 正在执行 stage，仍可能发生结构性变化
    REVIEWABLE — bootstrap 已结束，timeline 可审阅/可 patch/可校验
    FROZEN     — 通过校验，准备进入 export，工作区进入归档态
    EXPORTING  — 正在执行 TTS + 视频合成
    COMPLETED  — 导出完成
    FAILED     — 执行失败，需人工介入
    CANCELLED  — 用户取消
    """
    DRAFT = "draft"
    PROCESSING = "processing"
    REVIEWABLE = "reviewable"
    FROZEN = "frozen"
    EXPORTING = "exporting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TimelineProjectState:
    """项目级运行时可变状态。

    IR 引用只读。所有变更通过 event_states 和 global_patches 记录。
    """
    __slots__ = ("ir", "event_states", "global_patches", "global_config")

    def __init__(self, ir: TimelineProjectIR):
        self.ir = ir
        self.event_states: dict[str, TimelineEventState] = {
            eid: TimelineEventState(evt) for eid, evt in ir.events.items()
        }
        self.global_patches: list[Patch] = []
        self.global_config = None  # GlobalConfig | None — 项目级全局配置

    def get_event(self, event_id: str) -> TimelineEventState | None:
        return self.event_states.get(event_id)

    def sorted_events(self) -> list[TimelineEventState]:
        """按 start 时间排序的事件状态列表"""
        return sorted(self.event_states.values(), key=lambda es: es.start)

    def add_global_patch(self, patch: Patch) -> None:
        self.global_patches.append(patch)
        self.global_patches.sort(key=lambda p: p.timestamp)

    def get_global_audio_ref(self) -> str | None:
        """从 global_patches 中提取 vocals_ref 或 audio_ref（由 LOAD stage 写入）。
        vocals_ref 优先，用于 speaker diarization。"""
        result = None
        for p in self.global_patches:
            if p.op.name == "ANNOTATE":
                v = p.value
                if v.get("vocals_ref", ""):
                    result = v["vocals_ref"]
                elif v.get("audio_ref", "") and result is None:
                    result = v["audio_ref"]
        return result

    def get_global_bgm_ref(self) -> str | None:
        """从 global_patches 中提取 bgm_ref（Demucs 分离的背景乐）。"""
        for p in self.global_patches:
            if p.op.name == "ANNOTATE":
                bgm = p.value.get("bgm_ref", "")
                if bgm:
                    return bgm
        return None
