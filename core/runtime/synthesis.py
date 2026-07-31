"""
SynthesisEngine — 纯函数组合渲染 (Chapter 2 §2.4)

按 5 层优先级组合最终输出:
  Layer 1: Raw State     — ir 字段 (不可变事实)
  Layer 2-4: Derivatives — _data 全量 (Derived + Decision State)
  Layer 5: Patches       — replace 类操作 (最高优先级覆盖)

全程 dict 字面量，不修改任何入参。
"""
from __future__ import annotations
from core.runtime.event_state import TimelineEventState
from core.runtime.project_state import TimelineProjectState
from core.runtime.patch import OpCode


class SynthesisEngine:
    """纯函数渲染器 — 零 deepcopy，零 side-effect。

    渲染逻辑：
    1. 从 IR 字段构建基础 dict (Raw State)
    2. 合并 derivatives (Derived + Decision State)
    3. 按时序叠加 patches 中的 replace 类操作
    """

    _PATCH_OPS = (
        OpCode.REPLACE, OpCode.UPDATE_TRANSCRIPTION, OpCode.UPDATE_TTS_AUDIO,
        OpCode.UPDATE_TRANSLATION,
    )

    # ── public API ──────────────────────────────────────

    def render(self, event_state: TimelineEventState) -> dict:
        """5 层渲染：Raw → Derivatives → Patches"""
        ir = event_state.ir
        # Layer 1: Raw State (from IR — 不可变事实)
        result = {
            "id": ir.id,
            "start": ir.start,
            "end": ir.end,
            "speaker": ir.speaker_ref,
            "text": ir.text_ref,
            "source": ir.source,
        }
        # Layer 2-4: Derived + Decision State (from _data 槽位容器)
        # 类型化槽位 (Phase 3A) → to_dict; meta 血缘不进入渲染输出
        for key, value in event_state._data.items():
            if key == "meta":
                continue
            result[key] = value.to_dict() if hasattr(value, "to_dict") else value
        # Layer 5: Patches (sorted — 最高优先级覆盖)
        for p in event_state.patches:
            if p.op in self._PATCH_OPS:
                result.update(p.value)
        return result

    def render_all(self, state: TimelineProjectState) -> list[dict]:
        """渲染项目中全部事件"""
        return [self.render(es) for es in state.sorted_events()]

    def render_speakers(self, state: TimelineProjectState) -> list[dict]:
        """渲染说话人列表（含 v2.1 新字段）"""
        speakers = []
        for spk_id, spk in state.ir.speakers.items():
            entry = {
                "id": spk_id,
                "name": spk.name,
            }
            if spk.voice_id:
                entry["voice_id"] = spk.voice_id
            if spk.color:
                entry["color"] = spk.color
            if spk.is_locked:
                entry["is_locked"] = True
            if spk.embedding_ref:
                entry["embedding_ref"] = spk.embedding_ref
            if spk.gender_prob is not None:
                entry["gender_prob"] = spk.gender_prob
            if spk.voice_style:
                entry["voice_style"] = spk.voice_style
            if spk.confidence is not None:
                entry["confidence"] = spk.confidence
            speakers.append(entry)
        return speakers
