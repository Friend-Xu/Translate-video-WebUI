"""
SynthesisEngine — 纯函数组合渲染

替代 deepcopy + mutate 模式。
从 IR 字段 + derivatives + patches 组合最终输出，
全程 dict 字面量，不修改任何入参。
"""
from __future__ import annotations
from core.runtime.event_state import TimelineEventState
from core.runtime.project_state import TimelineProjectState


class SynthesisEngine:
    """纯函数渲染器 — 零 deepcopy，零 side-effect。

    渲染逻辑：
    1. 从 IR 字段构建基础 dict
    2. 合并 derivatives
    3. 按时序叠加 patches 中的 replace 值
    """

    # ── public API ──────────────────────────────────────

    def render(self, event_state: TimelineEventState) -> dict:
        """渲染单个事件为最终 dict 输出"""
        ir = event_state.ir
        result = {
            "id": ir.id,
            "start": ir.start,
            "end": ir.end,
            "speaker": ir.speaker_ref,
            "text": ir.text_ref,
            "source": ir.source,
        }
        # Layer 2: derivatives
        result.update(event_state.derivatives)
        # Layer 3: patches (sorted by timestamp)
        for p in event_state.patches:
            if p.op == "replace":
                result.update(p.value)
        return result

    def render_all(self, state: TimelineProjectState) -> list[dict]:
        """渲染项目中全部事件"""
        return [self.render(es) for es in state.sorted_events()]

    def render_speakers(self, state: TimelineProjectState) -> list[dict]:
        """渲染说话人列表"""
        speakers = []
        for spk_id, spk in state.ir.speakers.items():
            speakers.append({
                "id": spk_id,
                "name": spk.name,
            })
        return speakers
