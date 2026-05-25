"""
TimelineEventState — 事件的运行时状态

持有 IR 引用（只读）+ 九语义槽位 + patches 链。
这是 zero-deepcopy 架构的关键：不复制 IR，只在 state 层叠加变更。

状态三层模型 (Chapter 2 §2.4):
  Raw State     — ir (TimelineEventIR), 不可变事实
  Derived State — audio/asr/speaker/semantic/translation/tts, 引擎产出
  Decision State — review/runtime/provenance, 门控决策
"""
from __future__ import annotations
from core.ir.timeline_event import TimelineEventIR
from core.runtime.patch import Patch


class TimelineEventState:
    """事件的运行时可变状态。

    - self.ir: 只读引用，绝不被修改 (Raw State)
    - self.derivatives: 向后兼容属性，返回 _data 引用
    - self.<named_slot>: 九槽位结构化访问 (Derived + Decision State)
    - self.patches: 用户/AI 补丁链，按 timestamp 排序
    """
    __slots__ = (
        "_ir",
        "_data",       # 向后兼容：自由字典存储
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

    # ── 向后兼容：derivatives 属性 ──────────────────────────

    @property
    def derivatives(self) -> dict:
        """向后兼容 — 返回自由字典引用，支持读/写/update"""
        return self._data

    @derivatives.setter
    def derivatives(self, value: dict):
        self._data = value

    # ── 九语义槽位 (Derived State) ──────────────────────────

    @property
    def audio(self) -> dict:
        """{vocals_ref, bgm_ref, sample_rate, channels}"""
        if "audio" not in self._data:
            self._data["audio"] = {}
        return self._data["audio"]

    @property
    def asr(self) -> dict:
        """{words, confidence, language}"""
        if "asr" not in self._data:
            self._data["asr"] = {}
        return self._data["asr"]

    @property
    def speaker(self) -> dict:
        """{speaker_id, embedding_ref, confidence}"""
        if "speaker" not in self._data:
            self._data["speaker"] = {}
        return self._data["speaker"]

    @property
    def semantic(self) -> dict:
        """{embedding_ref, tokens, speech_rate_vector}"""
        if "semantic" not in self._data:
            self._data["semantic"] = {}
        return self._data["semantic"]

    @property
    def translation(self) -> dict:
        """{text, engine, score}"""
        if "translation" not in self._data:
            self._data["translation"] = {}
        return self._data["translation"]

    @property
    def tts(self) -> dict:
        """{audio_ref, duration, engine, quality_score}"""
        if "tts" not in self._data:
            self._data["tts"] = {}
        return self._data["tts"]

    @property
    def emotion(self) -> dict:
        """{valence, arousal, dominance, emotion_label, confidence, intensity} (Ch15)"""
        if "emotion" not in self._data:
            self._data["emotion"] = {}
        return self._data["emotion"]

    # ── 九语义槽位 (Decision State) ─────────────────────────

    @property
    def review(self) -> dict:
        """{flags, notes, needs_human_review}"""
        if "review" not in self._data:
            self._data["review"] = {}
        return self._data["review"]

    @property
    def runtime(self) -> dict:
        """{status, dirty, locked, generation_mode}"""
        if "runtime" not in self._data:
            self._data["runtime"] = {}
        return self._data["runtime"]

    @property
    def provenance(self) -> dict:
        """{engine, confidence, timestamp, gate_decision}"""
        if "provenance" not in self._data:
            self._data["provenance"] = {}
        return self._data["provenance"]

    # ── mutation ────────────────────────────────────────────

    def add_patch(self, patch: Patch) -> None:
        """追加 patch 并保持 timestamp 排序"""
        self.patches.append(patch)
        self.patches.sort(key=lambda p: p.timestamp)
