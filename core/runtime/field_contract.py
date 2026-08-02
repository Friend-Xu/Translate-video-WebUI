"""
字段级数据契约 — pass 的 READS/WRITES 声明显式化 (数据结构重设计 Phase 1)

高内聚低耦合: 每个 pass 声明自己读写哪些 (slot, field), 禁止"只保留我认识的
字段"式重建, 禁止越界读写其他 pass 的数据。

Phase 1 提供合法字段词表 + 声明基类 + 声明校验; Phase 3 迁移时逐 pass 添加
声明并接入运行时审计。
"""
from __future__ import annotations

# ── 合法字段词表 (以实测读写为准, 单一事实源) ──────────────

# Event 顶层持久化字段
EVENT_FIELDS = frozenset({
    "id", "start", "end", "text", "source", "lineage",
    "speaker", "confidence", "words",
})

# slot → 该 slot 的合法字段 (Phase 2: 按实测槽位契约图补全 —
#   tts 用 audio_ref (非 audio_path), review 用 review_status (非 status),
#   translation 加 ppl_ratio, 新增 asr/speaker/emotion/provenance)
SLOT_FIELDS: dict[str, frozenset[str]] = {
    "asr": frozenset({"words", "confidence", "language"}),
    "speaker": frozenset({"speaker_id", "confidence", "embedding_ref"}),
    "translation": frozenset({"text", "engine", "quality_score", "similarity",
                              "ppl_ratio"}),
    "tts": frozenset({"audio_ref", "duration", "engine", "quality_score",
                      "speed_decision", "emotion_hint"}),
    "semantic": frozenset({"embedding_ref"}),
    "emotion": frozenset({"emotion", "valence", "arousal", "dominance", "confidence",
                          "intensity", "translation_aligned", "drift_type",
                          "emotion_score", "gate_decision"}),
    "review": frozenset({"review_status", "flags", "gate_decision",
                         "needs_human_review", "notes"}),
    # runtime 是内存 only, 不持久化, 但仍是合法读写对象
    "runtime": frozenset({"tts_status", "generation_mode", "reject_reason",
                          "engine_scores", "dirty_flags", "config_versions"}),
    # provenance: 引擎评分暂存 (gate/engine 已迁出, Phase 3a 收窄)
    "provenance": frozenset({"confidence", "engine", "tts_score", "tts_score_detail",
                             "cosyvoice_score", "cosyvoice_detail",
                             "indextts_score", "indextts_detail",
                             "edge_tts_score", "edge_tts_detail",
                             "openvoice_score", "openvoice_detail",
                             "emotion_route", "translation_quality"}),
}

VALID_SLOTS = frozenset(SLOT_FIELDS.keys())


def validate_field_ref(slot: str, field: str) -> None:
    """校验 (slot, field) 引用是否合法。非法显式 raise (禁止兜底)。"""
    if slot == "event":
        if field not in EVENT_FIELDS:
            raise ValueError(f"非法 event 字段 '{field}' (合法={sorted(EVENT_FIELDS)})")
        return
    if slot not in SLOT_FIELDS:
        raise ValueError(f"非法 slot '{slot}' (合法={sorted(SLOT_FIELDS)} + 'event')")
    if field not in SLOT_FIELDS[slot]:
        raise ValueError(
            f"slot '{slot}' 无字段 '{field}' (合法={sorted(SLOT_FIELDS[slot])})")


class PassContract:
    """pass 字段契约基类。

    用法 (Phase 3 迁移时在各 pass 类上声明):
        class LLMTranslationPass(TimelinePass):
            READS = frozenset({("event", "text")})
            WRITES = frozenset({("translation", "text"),
                                ("translation", "engine")})

    声明即契约: apply() 只应读写声明内的字段。
    """
    READS: frozenset[tuple[str, str]] = frozenset()
    WRITES: frozenset[tuple[str, str]] = frozenset()

    @classmethod
    def validate_contract(cls) -> list[str]:
        """校验声明的 (slot, field) 引用全部合法。返回错误列表 (空 = 合法)。"""
        errors: list[str] = []
        for kind, refs in (("READS", cls.READS), ("WRITES", cls.WRITES)):
            for slot, field in refs:
                try:
                    validate_field_ref(slot, field)
                except ValueError as exc:
                    errors.append(f"{cls.__name__}.{kind}: {exc}")
        return errors

    @classmethod
    def assert_contract_valid(cls) -> None:
        errs = cls.validate_contract()
        if errs:
            raise ValueError("字段契约非法:\n" + "\n".join(errs))
