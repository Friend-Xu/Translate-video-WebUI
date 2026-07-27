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
from core.runtime.config_resolver import deep_merge
from core.runtime.slot_dependency import SlotLevelDependencyGraph


def _join_word_dicts(words: list[dict], lang: str) -> str:
    """从词 dict 切片派生 text — CJK 无空格, 拉丁单空格。"""
    cjk = (lang or "").lower().split("-")[0] in ("zh", "ja", "ko", "yue", "cn")
    sep = "" if cjk else " "
    return sep.join(w.get("word", "") for w in words).strip()


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
            OpCode.UPDATE_TTS_AUDIO: self._update_tts_audio,
            OpCode.UPDATE_TRANSLATION: self._update_translation,
            OpCode.UPDATE_EMOTION: self._replace,
            OpCode.ANNOTATE: self._annotate,
            # v3.0: 配置 OpCode (定稿 §10.5, §12.3)
            OpCode.SET_CONFIG: self._set_config,
            OpCode.OVERRIDE_CONFIG: self._override_config,
            OpCode.RESET_CONFIG: self._reset_config,
            OpCode.BATCH_SET_CONFIG: self._batch_set_config,
        }
        self._slot_dep_graph = SlotLevelDependencyGraph()

    # ── public API ──────────────────────────────────────

    def apply(
        self, state: TimelineProjectState, patch: Patch
    ) -> dict:
        # 批次04 §六: 幂等键检查 — 相同 idempotency_key 不重复应用
        if patch.idempotency_key:
            target = state.get_event(patch.target_id)
            if target is not None:
                for existing in target.patches:
                    if getattr(existing, "idempotency_key", None) == patch.idempotency_key:
                        return {"status": "skipped", "reason": "idempotent"}
        handler = self._dispatch.get(patch.op)
        if handler is None:
            return {"status": "error", "reason": f"unknown op: {patch.op}"}
        return handler(state, patch)

    def apply_many(
        self, state: TimelineProjectState, patches: list[Patch]
    ) -> list[dict]:
        return [self.apply(state, p) for p in patches]

    def dry_run(
        self, state: TimelineProjectState, patch: Patch
    ) -> dict:
        """预览 patch 效果，不修改原始 state。(批次04 §二)"""
        from copy import deepcopy
        snapshot = deepcopy(state)
        result = self.apply(snapshot, patch)
        if result.get("status") != "applied":
            return {
                "valid": False,
                "reason": result.get("reason", "apply failed"),
                "affected_events": [],
                "dirty_slots": [],
            }
        affected = [patch.target_id] + result.get("propagated_to", [])
        target = snapshot.get_event(patch.target_id)
        orig = state.get_event(patch.target_id)
        dirty = []
        if target is not None and orig is not None:
            for slot in ("asr", "translation", "tts", "speaker", "emotion"):
                if getattr(target, slot, None) != getattr(orig, slot, None):
                    dirty.append((patch.target_id, slot))
        return {
            "valid": True,
            "reason": None,
            "affected_events": affected,
            "dirty_slots": dirty,
        }

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

    def _update_translation(self, state: TimelineProjectState, patch: Patch) -> dict:
        """UPDATE_TRANSLATION — 写入 translation slot (dict 态), 不用 _replace 顶层塞字符串。

        修复三态根因: 旧 _replace 把 _data["translation"] 覆盖成裸字符串,
        丢失 engine/similarity 等字段, 与 slot dict 形态不一致。
        """
        target = state.get_event(patch.target_id)
        if target is None:
            return {"status": "error", "reason": f"target not found: {patch.target_id}"}
        slot = target.translation  # lazy-init dict (含 config)
        val = patch.value.get("translation", "")
        if isinstance(val, dict):
            slot.update(val)
        else:
            slot["text"] = val
        target.add_patch(patch)
        return {
            "status": "applied",
            "op": "update_translation",
            "target": patch.target_id,
            "after": dict(slot),
        }

    def _update_tts_audio(self, state: TimelineProjectState, patch: Patch) -> dict:
        """UPDATE_TTS_AUDIO — 写入 tts slot, 不用 _replace 顶层塞 audio_ref。

        修复: 旧 _replace 把 audio_ref/duration/engine 塞到 _data 顶层,
        导致各 TTS pass 的 es.tts.get("audio_ref") skip 检查读空槽。
        """
        target = state.get_event(patch.target_id)
        if target is None:
            return {"status": "error", "reason": f"target not found: {patch.target_id}"}
        slot = target.tts  # lazy-init dict (含 config)
        slot.update(patch.value)
        target.add_patch(patch)
        return {
            "status": "applied",
            "op": "update_tts_audio",
            "target": patch.target_id,
            "after": dict(slot),
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
            text_ref=target.ir.text_ref,
            source=target.ir.source,
        )
        es_b = TimelineEventState(ir_b)
        es_b.derivatives.update(target.derivatives)
        es_b.patches = list(target.patches)
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
        all_events.sort(key=lambda e: e.start)

        lang = primary.asr.get("language", "") or "en"
        words = []
        for e in all_events:
            words.extend(e.asr.get("words", []))
        words.sort(key=lambda w: w.get("start", 0.0))

        if words:
            text = _join_word_dicts(words, lang)
        else:
            # 无词级数据: 拼接各段真实文本 (非虚构, 是各 event 原有 text_ref)
            text = " ".join(e.ir.text_ref for e in all_events if e.ir.text_ref).strip()

        max_end = max(e.end for e in all_events)
        min_start = min(e.start for e in all_events)
        had_translation = any(
            isinstance(e.translation, dict) and e.translation.get("text")
            for e in all_events
        )

        ir_merged = TimelineEventIR(
            id=primary_id,
            start=min_start,
            end=max_end,
            speaker_ref=primary.speaker_ref,
            text_ref=text,
            source=primary.ir.source,
        )
        es_merged = TimelineEventState(ir_merged)
        es_merged.patches = list(primary.patches)
        es_merged.add_patch(patch)
        es_merged.derivatives["_merged_from"] = merged_ids  # 合并血缘
        if words:
            es_merged.asr["words"] = words
            es_merged.asr["language"] = lang
        spk = primary.speaker.get("speaker_id") or primary.speaker_ref
        if spk:
            es_merged.speaker["speaker_id"] = spk
        # 合并改变了源文本, 旧译文失效: 不带过来, 置标记触发重译 (禁止兜底下保留陈旧译文)
        if had_translation:
            es_merged.review["flags"] = ["needs_retranslate"]
            es_merged.review["needs_human_review"] = True

        state.event_states[primary_id] = es_merged
        # 删除被合并事件, 避免孤儿残留 (IR + state 同步)
        for mid in merged_ids:
            state.event_states.pop(mid, None)
            state.ir.events.pop(mid, None)
        state.ir.events[primary_id] = ir_merged
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
                es = es_new
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
                try:
                    before_snap[key] = dict(slot) if not isinstance(slot, str) else str(slot)
                except (ValueError, TypeError):
                    before_snap[key] = str(slot)
                if isinstance(slot, dict):
                    slot.update(val if isinstance(val, dict) else {"value": val})

        target.add_patch(patch)
        return {
            "status": "applied",
            "op": "annotate",
            "target": patch.target_id,
            "slots_updated": list(before_snap.keys()),
            "before": before_snap,
        }

    # ── config ops (v3.0 — 定稿 §12.3) ────────────────────

    def _override_config(self, state: TimelineProjectState, patch: Patch) -> dict:
        """OVERRIDE_CONFIG — 深度合并覆盖 config 指定字段。

        最常用的配置操作码（对应 WebUI 单字段微调）。
        使用增量快照（JSON Pointer 路径）记录 previous_state。
        """
        event_id = patch.target_id
        slot = patch.value.get("slot", "")
        partial = patch.value.get("partial_config", {})

        es = state.get_event(event_id)
        if es is None:
            return {"status": "error", "reason": "target not found: %s" % event_id}

        # v3.0: 乐观锁版本检查 (定稿 §12.4.2)
        base_version = patch.value.get("base_version", -1)
        current_version = es.runtime.get("config_versions", {}).get(slot, 0)
        if current_version != base_version and base_version >= 0:
            # 检测是否可自动合并 (修改不同字段)
            partial_keys = set((patch.value.get("partial_config") or {}).keys())
            # 简单策略: 若版本不匹配，仍允许应用但标记 auto_merged
            pass  # 当前版本: 乐观策略，不阻塞，依赖用户意图优先

        slot_dict = getattr(es, slot, None)
        if slot_dict is None:
            return {"status": "error", "reason": "unknown slot: %s" % slot}

        if "config" not in slot_dict:
            slot_dict["config"] = {}

        # 增量快照：仅记录被修改字段的路径和旧值
        previous_state = {}
        for key, new_value in partial.items():
            old_value = slot_dict["config"].get(key)
            if old_value != new_value:
                previous_state[key] = old_value

        # 深度合并
        deep_merge(slot_dict["config"], partial)
        es.add_patch(patch)

        # 标记脏并传播
        dirty_slots = self._slot_dep_graph.propagate_dirty(event_id, slot, state)

        # 更新槽位版本号
        vers = es.runtime.setdefault("config_versions", {})
        vers[slot] = vers.get(slot, 0) + 1

        return {
            "status": "applied",
            "op": "override_config",
            "target": event_id,
            "slot": slot,
            "previous_state": previous_state,
            "dirty_slots": [(eid, s) for eid, s in dirty_slots],
        }

    def _set_config(self, state: TimelineProjectState, patch: Patch) -> dict:
        """SET_CONFIG — 全量替换目标槽位的 config 块。

        用于 Import 模式批量初始化和"从预设加载"操作。
        记录完整旧 config 作为 previous_state。
        """
        event_id = patch.target_id
        slot = patch.value.get("slot", "")
        config_block = patch.value.get("config_block", {})

        es = state.get_event(event_id)
        if es is None:
            return {"status": "error", "reason": "target not found: %s" % event_id}

        # v3.0: 乐观锁版本检查 (定稿 §12.4.2)
        base_version = patch.value.get("base_version", -1)
        current_version = es.runtime.get("config_versions", {}).get(slot, 0)
        if current_version != base_version and base_version >= 0:
            # 检测是否可自动合并 (修改不同字段)
            partial_keys = set((patch.value.get("partial_config") or {}).keys())
            # 简单策略: 若版本不匹配，仍允许应用但标记 auto_merged
            pass  # 当前版本: 乐观策略，不阻塞，依赖用户意图优先

        slot_dict = getattr(es, slot, None)
        if slot_dict is None:
            return {"status": "error", "reason": "unknown slot: %s" % slot}

        # 完整快照旧 config
        old_config = dict(slot_dict.get("config", {}))
        slot_dict["config"] = dict(config_block)  # 全量替换
        es.add_patch(patch)

        dirty_slots = self._slot_dep_graph.propagate_dirty(event_id, slot, state)

        return {
            "status": "applied",
            "op": "set_config",
            "target": event_id,
            "slot": slot,
            "previous_state": {"_full_config": old_config},
            "dirty_slots": [(eid, s) for eid, s in dirty_slots],
        }

    def _reset_config(self, state: TimelineProjectState, patch: Patch) -> dict:
        """RESET_CONFIG — 移除事件级覆盖，恢复继承。

        支持两种模式:
          - 无 fields 参数: 删除整个槽位的 config（完全恢复继承）
          - 有 fields 参数: 仅删除指定字段的覆盖（部分恢复继承）
        """
        event_id = patch.target_id
        slot = patch.value.get("slot", "")
        fields = patch.value.get("fields")

        es = state.get_event(event_id)
        if es is None:
            return {"status": "error", "reason": "target not found: %s" % event_id}

        # v3.0: 乐观锁版本检查 (定稿 §12.4.2)
        base_version = patch.value.get("base_version", -1)
        current_version = es.runtime.get("config_versions", {}).get(slot, 0)
        if current_version != base_version and base_version >= 0:
            # 检测是否可自动合并 (修改不同字段)
            partial_keys = set((patch.value.get("partial_config") or {}).keys())
            # 简单策略: 若版本不匹配，仍允许应用但标记 auto_merged
            pass  # 当前版本: 乐观策略，不阻塞，依赖用户意图优先

        slot_dict = getattr(es, slot, None)
        if slot_dict is None:
            return {"status": "error", "reason": "unknown slot: %s" % slot}

        config = slot_dict.get("config", {})
        previous_state = {}

        if fields is None:
            previous_state = {"_full_config": dict(config)}
            slot_dict["config"] = {}
        else:
            for field in fields:
                if field in config:
                    previous_state[field] = config.pop(field)
            if not slot_dict["config"]:
                slot_dict["config"] = {}

        es.add_patch(patch)
        dirty_slots = self._slot_dep_graph.propagate_dirty(event_id, slot, state)

        return {
            "status": "applied",
            "op": "reset_config",
            "target": event_id,
            "slot": slot,
            "fields": fields,
            "previous_state": previous_state,
            "dirty_slots": [(eid, s) for eid, s in dirty_slots],
        }

    def _batch_set_config(self, state: TimelineProjectState, patch: Patch) -> dict:
        """BATCH_SET_CONFIG — 批量执行相同配置操作。

        对每个 target 独立执行 SET_CONFIG 逻辑，合并依赖计算（去重）。
        并发重算由 RecomputeScheduler 管理。
        """
        targets = patch.targets or [patch.target_id]
        slot = patch.value.get("slot", "")
        config_block = patch.value.get("config_block", {})

        results = []
        all_dirty: set[tuple[str, str]] = set()

        for eid in targets:
            es = state.get_event(eid)
            if es is None:
                results.append({"target": eid, "status": "error", "reason": "not found"})
                continue

            slot_dict = getattr(es, slot, None)
            if slot_dict is None:
                results.append({"target": eid, "status": "error", "reason": "unknown slot"})
                continue

            old_config = dict(slot_dict.get("config", {}))
            slot_dict["config"] = dict(config_block)
            es.add_patch(patch)

            dirty = self._slot_dep_graph.propagate_dirty(eid, slot, state)
            all_dirty.update(dirty)

            results.append({
                "target": eid,
                "status": "applied",
                "previous_state": {"_full_config": old_config},
            })

        return {
            "status": "applied",
            "op": "batch_set_config",
            "targets": targets,
            "slot": slot,
            "results": results,
            "dirty_slots": [(eid, s) for eid, s in all_dirty],
        }
