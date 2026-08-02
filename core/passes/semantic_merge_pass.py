"""
SemanticMergePass — 合并同 speaker 的短间隔相邻事件

遍历 Timeline，将 speaker_ref 相同、时间间隔 < threshold 的事件合并。
通过 PatchEngine.merge 执行，不直接修改 IR。

第二阶段 (架构收束补丁): 短时长碎片合并 — Json_Convert_Srt min_duration
约束的等价物 (实测说话人拆分产生 0.19s 空文本碎片 + 分段短句闪屏)。
"""
from __future__ import annotations
from core.engine.pass_base import TimelinePass
from core.runtime import TimelineProjectState, Patch, PatchEngine
from core.runtime.index import TimelineIndex


class SemanticMergePass(TimelinePass):
    """语义合并 — 同 speaker + 短间隔 + 无句末标点 → merge;
    短时长碎片 (< min_duration) → 合并到相邻目标。"""

    name = "semantic_merge"
    # 依赖 speaker_composite: 阶段二短碎片合并需要说话人拆分 (SPLIT_BY_SPEAKER
    # 产生 _spk00 碎片) 完成之后运行 — 拓扑排序保证, 不靠列表顺序
    depends_on: list[str] = ["speaker_composite"]

    def __init__(self, gap_threshold: float = 0.3,
                 min_duration: float = 1.5, max_gap: float = 5.0):
        self.gap_threshold = gap_threshold
        self.min_duration = min_duration
        self.max_gap = max_gap
        self._sentence_enders = {".", "。", "!", "！", "?", "？"}

    def apply(self, state: TimelineProjectState) -> TimelineProjectState:
        idx = TimelineIndex(state)
        engine = PatchEngine()
        merged_ids: set[str] = set()

        # ── 阶段一: 同 speaker 短间隔合并 (原有) ──
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
                # SEGMENT_MERGE (结构性合并): words 合并 + 文本从 words 派生 +
                # 旧译文失效标记。旧 MERGE 只写 _merged_from 标注, 合并无实际效果
                # (Phase1: 空壳修复)。
                op="segment_merge",
                value={"target_ids": [a.id, b.id]},
                author="system",
            )
            engine.apply(state, patch)
            merged_ids.add(b.id)

        # ── 阶段二: 短时长碎片合并 (min_duration 约束) ──
        self._merge_short_fragments(state)

        return state

    # ── 阶段二: 短时长碎片 ─────────────────────────────

    def _merge_short_fragments(self, state: TimelineProjectState) -> None:
        """事件时长 < min_duration → 合并到相邻目标事件。

        目标优先级:
          1. split_from 血缘 (说话人拆分产物 _spk00 碎片 → 回源)
          2. 同 speaker 相邻 (前/后, 选间隔小者)
          3. 最近相邻 (前/后, 间隔 <= max_gap)

        迭代直到无新合并 — 合并后目标仍短时继续 (链式)。
        孤悬短段 (间隔 > max_gap) 不合并 — 宁缺毋滥, 不扭曲时间轴。
        """
        engine = PatchEngine()
        for _ in range(10):
            events = sorted(state.event_states.values(), key=lambda e: e.start)
            if len(events) < 2:
                return
            changed = False
            for es in events:
                if (es.end - es.start) >= self.min_duration:
                    continue
                target_id = self._pick_target(state, es, events)
                if target_id is None or target_id == es.id:
                    continue
                patch = Patch(
                    id=f"dur_merge_{es.id}_{target_id}",
                    target_id=target_id,
                    op="segment_merge",
                    value={"target_ids": [target_id, es.id]},
                    author="system",
                )
                engine.apply(state, patch)
                changed = True
                break  # 事件集已变, 重新排序扫描
            if not changed:
                break

    def _pick_target(self, state: TimelineProjectState, es,
                     events: list) -> str | None:
        """选合并目标: split_from > 同 speaker 相邻 > 最近相邻 (间隔 <= max_gap)。"""
        # 1. 说话人拆分产物回源 (meta["split_from"] 由 _split_by_speaker 写入)
        split_from = es.meta.get("split_from")
        if split_from and state.get_event(split_from) is not None:
            return split_from

        # 2/3. 相邻候选 (前/后)
        candidates: list = []
        for i, e in enumerate(events):
            if e.id == es.id:
                if i > 0:
                    candidates.append(events[i - 1])
                if i + 1 < len(events):
                    candidates.append(events[i + 1])
                break
        if not candidates:
            return None

        def _gap(c) -> float:
            return max(c.start, es.start) - min(c.end, es.end)

        same_spk = [c for c in candidates if c.speaker_ref == es.speaker_ref]
        pool = same_spk if same_spk else candidates
        best, best_gap = None, None
        for c in pool:
            g = _gap(c)
            if g > self.max_gap:
                continue
            if best is None or g < best_gap:
                best, best_gap = c.id, g
        return best
