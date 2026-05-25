"""
PatchEngine — Patch 执行器 (v3.0 — 全 OpCode 支持)

Patch 只写 runtime state，绝不修改 IR。
所有 op 实现为纯函数，返回 diff 而不修改入参。

v3.0 (Ch12): 全 14 OpCode 支持 — SEGMENT_INSERT/SPLIT/MERGE,
  UPDATE_TRANSCRIPTION/TRANSLATION/TTS_AUDIO, REFINE_ALIGNMENT,
  ASSIGN_SPEAKER/MERGE_SPEAKERS/SPLIT_SEGMENT_BY_SPEAKER, ANNOTATE.
"""
from __future__ import annotations
from core.runtime.patch import Patch, OpCode
from core.runtime.event_state import TimelineEventState
from core.runtime.project_state import TimelineProjectState
from core.ir.timeline_event import TimelineEventIR


class PatchEngine:
    """Patch 执行器 — 只作用 runtime state，不改 IR。

    apply() 接收 state + patch，修改 state 并返回 diff dict。
    通过 _OP_DISPATCH dict 分发到各 handler。
    """

    def __init__(self):
        self._dispatch = {
            OpCode.REPLACE: self._replace,
            OpCode.MERGE: self._merge,
            OpCode.SPLIT: self._split,
            OpCode.PROPAGATE: self._propagate,
            OpCode.SEGMENT_INSERT: self._seg_insert,
            OpCode.SEGMENT_SPLIT: self._seg_split,
            OpCode.SEGMENT_MERGE: self._seg_merge,
            OpCode.UPDATE_TRANSCRIPTION: self._replace,
            OpCode.REFINE_ALIGNMENT: self._refine_alignment,
            OpCode.ASSIGN_SPEAKER: self._assign_speaker,
            OpCode.MERGE_SPEAKERS: self._merge_speakers,
            OpCode.SPLIT_SEGMENT_BY_SPEAKER: self._split_by_speaker,
            OpCode.UPDATE_TTS_AUDIO: self._replace,
            OpCode.UPDATE_TRANSLATION: self._replace,
            OpCode.UPDATE_EMOTION: self._replace,
            OpCode.ANNOTATE: self._annotate,
        }

    # ── public API ──────────────────────────────────────

    def apply(
        self, state: TimelineProjectState, patch: Patch
    ) -> dict:
        handler = self._dispatch.get(patch.op)
        if handler is None:
            return {"status": "error", "reason": f"unknown op: {patch.op}"}
        return handler(state, patch)

    def apply_many(
        self, state: TimelineProjectState, patches: list[Patch]
    ) -> list[dict]:
        return [self.apply(state, p) for p in patches]

    # ── legacy ops ──────────────────────────────────────

    def _replace(self, state: TimelineProjectState, patch: Patch) -> dict:
        target = state.get_event(patch.target_id)
        if target is None:
            return {"status": "error", "reason": f"target not found: {patch.target_id}"}
        before = dict(target.derivatives)
        target.derivatives.update(patch.value)
        target.add_patch(patch)
        return {
            "status": "applied",
            "op": "replace",
            "target": patch.target_id,
            "before": before,
            "after": dict(target.derivatives),
        }

    def _merge(self, state: TimelineProjectState, patch: Patch) -> dict:
        ids = patch.value.get("target_ids", [patch.target_id])
        if len(ids) < 2:
            return {"status": "error", "reason": "merge requires >= 2 targets"}
        primary = state.get_event(ids[0])
        if primary is None:
            return {"status": "error", "reason": f"primary not found: {ids[0]}"}
        merged_ids = ids[1:]
        primary.derivatives["_merged_from"] = merged_ids
        primary.derivatives["_merged_end"] = max(
            primary.end,
            max(
                (state.get_event(mid).end if state.get_event(mid) else 0)
                for mid in merged_ids
            ),
        )
        primary.add_patch(patch)
        return {
            "status": "applied",
            "op": "merge",
            "primary": ids[0],
            "merged": merged_ids,
        }

    def _split(self, state: TimelineProjectState, patch: Patch) -> dict:
        split_at = patch.value.get("at", 0.0)
        target = state.get_event(patch.target_id)
        if target is None:
            return {"status": "error", "reason": f"target not found: {patch.target_id}"}
        target.derivatives["_split_at"] = split_at
        target.add_patch(patch)
        return {
            "status": "applied",
            "op": "split",
            "target": patch.target_id,
            "split_at": split_at,
        }

    def _propagate(self, state: TimelineProjectState, patch: Patch) -> dict:
        propagated_to = patch.value.get("to_ids", [])
        key = patch.value.get("key", "")
        val = patch.value.get("val")
        for eid in propagated_to:
            es = state.get_event(eid)
            if es:
                es.derivatives[key] = val
        target = state.get_event(patch.target_id)
        if target:
            target.add_patch(patch)
        return {
            "status": "applied",
            "op": "propagate",
            "from": patch.target_id,
            "to": propagated_to,
        }

    # ── structural ops ──────────────────────────────────

    def _seg_insert(self, state: TimelineProjectState, patch: Patch) -> dict:
        start = patch.value.get("start", 0.0)
        end = patch.value.get("end", 0.0)
        text = patch.value.get("text", "")
        speaker_ref = patch.value.get("speaker_ref")
        source = patch.value.get("source", "vad")

        if start >= end:
            return {"status": "error", "reason": f"invalid time range: {start}-{end}"}

        ir = TimelineEventIR(
            id=patch.target_id,
            start=start,
            end=end,
            speaker_ref=speaker_ref,
            text_ref=text,
            source=source,
        )
        es = TimelineEventState(ir)
        es.add_patch(patch)
        state.event_states[patch.target_id] = es
        return {
            "status": "applied",
            "op": "segment_insert",
            "target": patch.target_id,
            "start": start,
            "end": end,
        }

    def _seg_split(self, state: TimelineProjectState, patch: Patch) -> dict:
        split_at = patch.value.get("at", 0.0)
        target = state.get_event(patch.target_id)
        if target is None:
            return {"status": "error", "reason": f"target not found: {patch.target_id}"}
        if split_at <= target.start or split_at >= target.end:
            return {
                "status": "error",
                "reason": f"split point {split_at} outside [{target.start}, {target.end}]",
            }

        new_id = patch.value.get("new_id", f"{patch.target_id}_b")

        ir_b = TimelineEventIR(
            id=new_id,
            start=split_at,
            end=target.end,
            speaker_ref=target.speaker_ref,
            text_ref="",
            source=target.ir.source,
        )
        es_b = TimelineEventState(ir_b)
        es_b.derivatives.update(target.derivatives)
        es_b.derivatives["_split_from"] = patch.target_id

        ir_a = TimelineEventIR(
            id=patch.target_id,
            start=target.start,
            end=split_at,
            speaker_ref=target.speaker_ref,
            text_ref=target.ir.text_ref,
            source=target.ir.source,
        )
        es_a = TimelineEventState(ir_a)
        es_a.derivatives.update(target.derivatives)
        es_a.derivatives["_split_at"] = split_at
        es_a.patches = list(target.patches)
        es_a.add_patch(patch)

        state.event_states[patch.target_id] = es_a
        state.event_states[new_id] = es_b
        return {
            "status": "applied",
            "op": "segment_split",
            "target": patch.target_id,
            "new_id": new_id,
            "split_at": split_at,
        }

    def _seg_merge(self, state: TimelineProjectState, patch: Patch) -> dict:
        ids = patch.value.get("target_ids", patch.targets or [patch.target_id])
        if len(ids) < 2:
            return {"status": "error", "reason": "segment_merge requires >= 2 targets"}

        primary_id = ids[0]
        primary = state.get_event(primary_id)
        if primary is None:
            return {"status": "error", "reason": f"primary not found: {primary_id}"}

        merged_ids = ids[1:]
        all_events = [primary]
        for mid in merged_ids:
            evt = state.get_event(mid)
            if evt:
                all_events.append(evt)

        max_end = max(e.end for e in all_events)
        primary.derivatives["_merged_from"] = merged_ids
        primary.derivatives["_merged_end"] = max_end

        ir_merged = TimelineEventIR(
            id=primary_id,
            start=primary.start,
            end=max_end,
            speaker_ref=primary.speaker_ref,
            text_ref=primary.ir.text_ref,
            source=primary.ir.source,
        )
        es_merged = TimelineEventState(ir_merged)
        es_merged.derivatives.update(primary.derivatives)
        es_merged.patches = list(primary.patches)
        es_merged.add_patch(patch)

        state.event_states[primary_id] = es_merged
        return {
            "status": "applied",
            "op": "segment_merge",
            "primary": primary_id,
            "merged": merged_ids,
            "max_end": max_end,
        }

    # ── ASR ops ─────────────────────────────────────────

    def _refine_alignment(self, state: TimelineProjectState, patch: Patch) -> dict:
        target = state.get_event(patch.target_id)
        if target is None:
            return {"status": "error", "reason": f"target not found: {patch.target_id}"}
        before = dict(target.derivatives.get("alignment", {}))
        current = target.derivatives.get("alignment", {})
        current.update(patch.value)
        target.derivatives["alignment"] = current
        target.add_patch(patch)
        return {
            "status": "applied",
            "op": "refine_alignment",
            "target": patch.target_id,
            "before": before,
            "after": dict(current),
        }

    # ── Speaker ops ─────────────────────────────────────

    def _assign_speaker(self, state: TimelineProjectState, patch: Patch) -> dict:
        target = state.get_event(patch.target_id)
        if target is None:
            return {"status": "error", "reason": f"target not found: {patch.target_id}"}

        speaker_id = patch.value.get("speaker_id", "")
        confidence = patch.value.get("confidence", 1.0)
        embedding_ref = patch.value.get("embedding_ref")

        before_speaker = dict(target.speaker)
        before_ref = target.ir.speaker_ref

        target.speaker["speaker_id"] = speaker_id
        target.speaker["confidence"] = confidence
        if embedding_ref:
            target.speaker["embedding_ref"] = embedding_ref

        ir_new = TimelineEventIR(
            id=target.ir.id,
            start=target.start,
            end=target.end,
            speaker_ref=speaker_id or None,
            text_ref=target.ir.text_ref,
            source=target.ir.source,
        )
        es_new = TimelineEventState(ir_new)
        es_new.derivatives.update(target.derivatives)
        es_new.patches = list(target.patches)
        es_new.add_patch(patch)
        state.event_states[target.ir.id] = es_new

        return {
            "status": "applied",
            "op": "assign_speaker",
            "target": patch.target_id,
            "speaker_id": speaker_id,
            "before_speaker_ref": before_ref,
            "before_speaker_slot": before_speaker,
        }

    def _merge_speakers(self, state: TimelineProjectState, patch: Patch) -> dict:
        from_ids = patch.value.get("from_ids", [])
        into_id = patch.value.get("into_id", patch.target_id)
        remapped = 0

        for es in state.event_states.values():
            if es.speaker_ref in from_ids:
                ir_new = TimelineEventIR(
                    id=es.ir.id,
                    start=es.start,
                    end=es.end,
                    speaker_ref=into_id,
                    text_ref=es.ir.text_ref,
                    source=es.ir.source,
                )
                es_new = TimelineEventState(ir_new)
                es_new.derivatives.update(es.derivatives)
                es_new.patches = list(es.patches)
                state.event_states[es.ir.id] = es_new
                remapped += 1
            if es.speaker.get("speaker_id") in from_ids:
                es.speaker["speaker_id"] = into_id

        state.add_global_patch(patch)
        return {
            "status": "applied",
            "op": "merge_speakers",
            "from_ids": from_ids,
            "into_id": into_id,
            "remapped_events": remapped,
        }

    def _split_by_speaker(self, state: TimelineProjectState, patch: Patch) -> dict:
        target = state.get_event(patch.target_id)
        if target is None:
            return {"status": "error", "reason": f"target not found: {patch.target_id}"}

        boundaries = patch.value.get("boundaries", [])
        if len(boundaries) < 2:
            return {"status": "error", "reason": "need at least 2 boundaries"}

        created = []
        for i, bnd in enumerate(boundaries):
            seg_id = f"{patch.target_id}_spk{i:02d}"
            spk = bnd.get("speaker", "")
            t_start = bnd.get("time", target.start)
            t_end = boundaries[i + 1]["time"] if i + 1 < len(boundaries) else target.end

            ir = TimelineEventIR(
                id=seg_id,
                start=t_start,
                end=t_end,
                speaker_ref=spk or None,
                text_ref="",
                source=target.ir.source,
            )
            es = TimelineEventState(ir)
            es.speaker["speaker_id"] = spk
            es.derivatives["_split_from"] = patch.target_id
            es.add_patch(patch)
            state.event_states[seg_id] = es
            created.append(seg_id)

        return {
            "status": "applied",
            "op": "split_segment_by_speaker",
            "original": patch.target_id,
            "created": created,
            "boundary_count": len(boundaries),
        }

    # ── generic ops ─────────────────────────────────────

    def _annotate(self, state: TimelineProjectState, patch: Patch) -> dict:
        target = state.get_event(patch.target_id)
        if target is None:
            if patch.value.get("_global"):
                state.add_global_patch(patch)
                return {
                    "status": "applied",
                    "op": "annotate",
                    "target": patch.target_id,
                    "scope": "global",
                }
            return {"status": "error", "reason": f"target not found: {patch.target_id}"}

        slot_map = {
            "audio": target.audio,
            "asr": target.asr,
            "speaker": target.speaker,
            "semantic": target.semantic,
            "translation": target.translation,
            "tts": target.tts,
            "review": target.review,
            "runtime": target.runtime,
            "provenance": target.provenance,
        }

        before_snap = {}
        for key, val in patch.value.items():
            if key.startswith("_"):
                continue
            slot = slot_map.get(key)
            if slot is not None:
                before_snap[key] = dict(slot)
                slot.update(val if isinstance(val, dict) else {"value": val})

        target.add_patch(patch)
        return {
            "status": "applied",
            "op": "annotate",
            "target": patch.target_id,
            "slots_updated": list(before_snap.keys()),
            "before": before_snap,
        }
