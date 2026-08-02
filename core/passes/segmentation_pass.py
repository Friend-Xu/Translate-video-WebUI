"""
SegmentationPass — 标点感知 IR 重分段 (数据结构重设计 Phase 4)

在 EXTRACT 阶段 speaker 之后运行: 把 ASR 产出的长批 (merge_max_dur~45s)
重分段为句级 event, 让 translation/TTS 读到干净句子, 而非整段 41s blob。

复用 pipeline/segmentation 的 候选切点+约束切分 引擎 (移植自旧 SRT 处理器),
词级计时, 跨说话人不切, 缺词/硬切置 review_flag 进人工 (禁止兜底)。

这是生产者 pass — 按既定决策直接写字段, 不走 Patch (Patch 仅用户编辑)。
处于 EXTRACT (bootstrap), 尚无任何用户 patch 指向这些 event, 故按时间序
重排 ID (evt_001..N) 是安全的; patch 层的 split/merge ID 顺延是另一套机制。
"""
from __future__ import annotations
from core.engine.pass_base import TimelinePass
from core.ir.timeline_event import TimelineEventIR
from core.runtime.project_state import TimelineProjectState
from core.runtime.event_state import TimelineEventState
from pipeline.segmentation import segment_event_stream


class SegmentationPass(TimelinePass):
    """ASR 长批 → 句级 event (speaker 之后, translation 之前)。

    依赖的事件 speaker 字段由 asr (完整链) 或 asr_to_ir (注入产物) 提供;
    不声明 depends_on — 跨 stage 顺序由 stage_order 保证, 同 stage 顺序由
    passes 列表声明 (CLI 链无 speaker_composite pass, 声明它会锁死完整链)。
    """

    name = "segmentation"

    def __init__(self, language: str = ""):
        self.language = language

    def apply(self, state: TimelineProjectState) -> TimelineProjectState:
        events = state.sorted_events()
        if not events:
            return state

        lang = self._resolve_language(state, events)
        stream = [self._to_stream_dict(es) for es in events]
        segments = segment_event_stream(stream, lang)

        self._rebuild_state(state, segments)
        return state

    # ── internal ──────────────────────────────────────────

    def _resolve_language(self, state: TimelineProjectState, events) -> str:
        if self.language:
            return self.language
        if state.ir.language:
            return state.ir.language
        for es in events:
            lg = es.asr.language
            if lg:
                return lg
        return "en"

    @staticmethod
    def _to_stream_dict(es) -> dict:
        speaker = es.speaker.speaker_id or es.ir.speaker_ref
        return {
            "id": es.id,
            "start": es.start,
            "end": es.end,
            "text": es.ir.text_ref,
            "words": es.asr.words,
            "speaker": speaker,
        }

    def _rebuild_state(self, state: TimelineProjectState, segments) -> None:
        new_events: dict[str, TimelineEventIR] = {}
        new_states: dict[str, TimelineEventState] = {}

        for i, seg in enumerate(segments, 1):
            eid = f"evt_{i:03d}"
            ir = TimelineEventIR(
                id=eid,
                start=seg.start,
                end=seg.end,
                speaker_ref=seg.speaker,
                text_ref=seg.text,
                source="asr",
            )
            es = TimelineEventState(ir)
            if seg.words:
                es.asr.words = seg.words
                confs = [w.get("confidence") for w in seg.words
                         if isinstance(w.get("confidence"), (int, float))]
                if confs:
                    es.asr.confidence = sum(confs) / len(confs)
            if seg.speaker:
                es.speaker.speaker_id = seg.speaker
            es.provenance["engine"] = "segmentation"
            if seg.flag:
                es.review.flags = [seg.flag]
                es.review.needs_human_review = True
            new_events[eid] = ir
            new_states[eid] = es

        state.ir.events.clear()
        state.ir.events.update(new_events)
        state.event_states.clear()
        state.event_states.update(new_states)
