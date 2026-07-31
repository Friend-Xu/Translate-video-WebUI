"""
TimelineEventState — 事件的运行时状态

持有 IR 引用（只读）+ 类型化槽位 + patches 链。
这是 zero-deepcopy 架构的关键：不复制 IR，只在 state 层叠加变更。

状态三层模型 (Chapter 2 §2.4):
  Raw State     — ir (TimelineEventIR), 不可变事实
  Derived State — asr/speaker/semantic/translation/tts/emotion, 引擎产出
  Decision State — review/runtime/provenance, 门控决策

Phase 3A: 槽位从 lazy dict 转正为类型化对象 (ASRData/SpeakerAssignment/
Translation/TTSAudio/EmotionData/Review/Semantic/EventRuntime)。
旧 dict 形态数据经 from_dict 迁移, 不丢失。
"""
from __future__ import annotations
from core.ir.timeline_event import TimelineEventIR
from core.runtime.patch import Patch
from core.runtime.event_model import (
    ASRData, SpeakerAssignment, Semantic, Translation, TTSAudio,
    EmotionData, Review, EventRuntime,
)


class TimelineEventState:
    """事件的运行时可变状态。

    - self.ir: 只读引用，绝不被修改 (Raw State)
    - self.<slot>: 类型化槽位访问 (Derived + Decision State)
    - self.patches: 用户/AI 补丁链，按 timestamp 排序
    """
    __slots__ = (
        "_ir",
        "_data",       # 槽位容器 (类型化对象 + provenance dict)
        "patches",     # list[Patch] — 变更日志
    )

    def __init__(self, ir: TimelineEventIR):
        self._ir = ir
        self._data: dict = {}
        self.patches: list[Patch] = []

    @property
    def ir(self) -> TimelineEventIR:
        return self._ir

    @property
    def id(self) -> str:
        return self.ir.id

    @property
    def start(self) -> float:
        return self.ir.start

    @property
    def end(self) -> float:
        return self.ir.end

    @property
    def speaker_ref(self) -> str | None:
        return self.ir.speaker_ref

    # ── 向后兼容：derivatives 属性 (Phase 3B 删除) ─────────

    @property
    def derivatives(self) -> dict:
        """向后兼容 — 返回槽位容器引用 (3B 消灭自由写后删除)。"""
        return self._data

    @derivatives.setter
    def derivatives(self, value: dict):
        self._data = value

    # ── 槽位容器 ──────────────────────────────────────────

    def _slot(self, name: str, cls):
        """类型化槽位访问 — 缺失创建空对象, 旧 dict 形态迁移为类型化对象。"""
        if name not in self._data:
            self._data[name] = cls()
        elif isinstance(self._data[name], dict):
            self._data[name] = cls.from_dict(self._data[name])
        return self._data[name]

    # ── 类型化槽位 (Derived State) ─────────────────────────

    @property
    def asr(self) -> ASRData:
        """{words, confidence, language, config}"""
        return self._slot("asr", ASRData)

    @property
    def speaker(self) -> SpeakerAssignment:
        """{speaker_id, embedding_ref, confidence, config}"""
        return self._slot("speaker", SpeakerAssignment)

    @property
    def semantic(self) -> Semantic:
        """{embedding_ref, config}"""
        return self._slot("semantic", Semantic)

    @property
    def translation(self) -> Translation:
        """{text, engine, quality_score, similarity, ppl_ratio, config}"""
        return self._slot("translation", Translation)

    @property
    def tts(self) -> TTSAudio:
        """{audio_ref, duration, engine, quality_score, speed_decision, config}"""
        return self._slot("tts", TTSAudio)

    @property
    def emotion(self) -> EmotionData:
        """{emotion, valence, arousal, dominance, confidence, intensity, ...} (Ch15)"""
        return self._slot("emotion", EmotionData)

    # ── 类型化槽位 (Decision State) ─────────────────────────

    @property
    def review(self) -> Review:
        """{review_status, flags, gate_decision, needs_human_review, notes, config}"""
        return self._slot("review", Review)

    @property
    def runtime(self) -> EventRuntime:
        """{tts_status, generation_mode, reject_reason, engine_scores, ...}"""
        return self._slot("runtime", EventRuntime)

    # ── 评分暂存 (自由 dict, 引擎专属 key) ─────────────────

    @property
    def provenance(self) -> dict:
        """引擎评分暂存 — gate/engine 已迁出 (Phase 3a), 仅剩评分 key。"""
        if "provenance" not in self._data:
            self._data["provenance"] = {}
        return self._data["provenance"]

    # ── mutation ────────────────────────────────────────────

    def add_patch(self, patch: Patch) -> None:
        """追加 patch 并保持 timestamp 排序"""
        self.patches.append(patch)
        self.patches.sort(key=lambda p: p.timestamp)
