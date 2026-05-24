"""
SemanticMergePass — 合并同 speaker 的短间隔相邻事件

遍历 Timeline，将 speaker_ref 相同、时间间隔 < threshold 的事件合并。
通过 PatchEngine.merge 执行，不直接修改 IR。
"""
from __future__ import annotations
from core.engine.pass_base import TimelinePass
from core.runtime import TimelineProjectState, Patch, PatchEngine
from core.runtime.index import TimelineIndex


class SemanticMergePass(TimelinePass):
    """语义合并 — 同 speaker + 短间隔 + 无句末标点 → merge"""

    name = "semantic_merge"
    depends_on = ["asr_to_ir"]

    def __init__(self, gap_threshold: float = 0.3):
        self.gap_threshold = gap_threshold
        self._sentence_enders = {".", "。", "!", "！", "?", "？"}

    def apply(self, state: TimelineProjectState) -> TimelineProjectState:
        idx = TimelineIndex(state)
        engine = PatchEngine()
        merged_ids: set[str] = set()

        for i in range(len(idx.by_time) - 1):
            a, b = idx.by_time[i], idx.by_time[i + 1]
            if a.id in merged_ids or b.id in merged_ids:
                continue
            if a.speaker_ref != b.speaker_ref or a.speaker_ref is None:
                continue
            gap = b.start - a.end
            if gap > self.gap_threshold:
                continue
            a_text = a.ir.text_ref
            ends_sentence = a_text and a_text.strip()[-1] in self._sentence_enders
            if ends_sentence and gap > 0.15:
                continue

            patch = Patch(
                id=f"merge_{a.id}_{b.id}",
                target_id=a.id,
                op="merge",
                value={"target_ids": [a.id, b.id]},
                author="system",
            )
            engine.apply(state, patch)
            merged_ids.add(b.id)

        return state
