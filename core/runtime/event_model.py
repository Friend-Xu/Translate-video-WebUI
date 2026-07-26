"""
Event 数据模型 — 合并 IR + State 的单一工作模型 (数据结构重设计 Phase 1)

设计决策 (2026-07-27 用户确认, 见 memory/project_data_protocol_design):
- 取代 TimelineEventIR(frozen) + TimelineEventState(九槽位) 双对象
- Event 是可变工作模型: pipeline pass 作为生产者直接写字段;
  用户编辑走 Patch 留痕 (可撤销/审计), 不靠 frozen 强制不可变
- 字段分两层: 持久化字段 (to_dict → timeline.json) + EventRuntime (内存 only)
- 禁止兜底: from_dict 缺必填字段显式 raise, 不静默补默认值

semantic.embedding_ref 数据源 TBD (用户: 未实测不敢定), 现有 TTS 读取端保留。

本文件 Phase 1 仅为目标契约定义, 尚未替换 event_state.py / timeline_event.py。
"""
from __future__ import annotations
from dataclasses import dataclass, field

SCHEMA_VERSION_V3 = "3.0"

REVIEW_STATUSES = ("pending", "approved", "modified", "flagged")
EVENT_SOURCES = ("asr", "alignment", "manual", "imported")

# 句末/从句标点 (Phase 4 分段用, 在此统一定义避免多处散落)
SENTENCE_ENDERS = ("。", "！", "？", ".", "!", "?")
CLAUSE_BREAKS = ("，", "、", "；", ",", ";", ":", "：")


def _require(d: dict, key: str, ctx: str):
    """禁止兜底: 缺必填字段显式报错。"""
    if key not in d or d[key] is None:
        raise ValueError(f"{ctx}: 缺必填字段 '{key}' (数据={list(d.keys())})")
    return d[key]


def join_words(words: list["Word"], lang: str = "") -> str:
    """按语言规则从 words 派生 text。

    CJK (zh/ja/ko/yue) 词间无空格; 拉丁/其他词间单空格。
    whisper 词元已 strip, 故需语言感知拼接。
    """
    if not words:
        return ""
    cjk = lang.lower().split("-")[0] in ("zh", "ja", "ko", "yue", "cn")
    sep = "" if cjk else " "
    return sep.join(w.word for w in words).strip()


# ── 值对象 ─────────────────────────────────────────────────

@dataclass(frozen=True)
class Word:
    """词级时间戳 — ASR 产出的事实, 永不修改 (修改靠重跑 ASR)。"""
    word: str
    start: float
    end: float
    confidence: float | None = None

    def to_dict(self) -> dict:
        d = {"word": self.word, "start": self.start, "end": self.end}
        if self.confidence is not None:
            d["confidence"] = self.confidence
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Word":
        return cls(
            word=_require(d, "word", "Word"),
            start=float(_require(d, "start", "Word")),
            end=float(_require(d, "end", "Word")),
            confidence=d.get("confidence"),
        )


@dataclass
class Semantic:
    """语义嵌入 — TTS 零样本克隆用的声学语义向量 (数据源 TBD)。"""
    embedding_ref: str = ""

    def to_dict(self) -> dict:
        return {"embedding_ref": self.embedding_ref}

    @classmethod
    def from_dict(cls, d: dict | None) -> "Semantic":
        return cls(embedding_ref=(d or {}).get("embedding_ref", ""))


@dataclass
class Translation:
    """翻译 — 统一 dict, 禁 string/dict 双态。"""
    text: str = ""
    engine: str = ""
    quality_score: float | None = None
    similarity: float | None = None

    def to_dict(self) -> dict:
        d = {"text": self.text, "engine": self.engine}
        if self.quality_score is not None:
            d["quality_score"] = self.quality_score
        if self.similarity is not None:
            d["similarity"] = self.similarity
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Translation":
        return cls(
            text=d.get("text", ""),
            engine=d.get("engine", ""),
            quality_score=d.get("quality_score"),
            similarity=d.get("similarity"),
        )


@dataclass
class TTSAudio:
    """TTS 产出 — 只记最终胜出引擎的结果 (中间引擎状态在 EventRuntime)。"""
    audio_path: str = ""
    duration: float = 0.0
    engine: str = ""
    speed_factor: float = 1.0
    quality_score: float | None = None

    def to_dict(self) -> dict:
        d = {
            "audio_path": self.audio_path,
            "duration": self.duration,
            "engine": self.engine,
            "speed_factor": self.speed_factor,
        }
        if self.quality_score is not None:
            d["quality_score"] = self.quality_score
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "TTSAudio":
        return cls(
            audio_path=d.get("audio_path", ""),
            duration=float(d.get("duration", 0.0)),
            engine=d.get("engine", ""),
            speed_factor=float(d.get("speed_factor", 1.0)),
            quality_score=d.get("quality_score"),
        )


@dataclass
class Review:
    """审核 — 人工决策 + 门控 (gate_decision 从旧 provenance 迁入)。"""
    status: str = "pending"          # REVIEW_STATUSES
    flags: list[str] = field(default_factory=list)
    gate_decision: str | None = None  # "A"|"B"|"C" — orchestrator 路由依据
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "flags": list(self.flags),
            "gate_decision": self.gate_decision,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict | None) -> "Review":
        d = d or {}
        status = d.get("status", "pending")
        if status not in REVIEW_STATUSES:
            raise ValueError(f"Review: 非法 status '{status}' (合法={REVIEW_STATUSES})")
        return cls(
            status=status,
            flags=list(d.get("flags", [])),
            gate_decision=d.get("gate_decision"),
            notes=d.get("notes", ""),
        )


@dataclass
class Speaker:
    """说话人 — speakers 注册表项。"""
    id: str
    label: str = ""
    embedding_ref: str = ""
    confidence: float | None = None
    color: str = "#808080"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "embedding_ref": self.embedding_ref,
            "confidence": self.confidence,
            "color": self.color,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Speaker":
        return cls(
            id=_require(d, "id", "Speaker"),
            label=d.get("label", d.get("name", "")),
            embedding_ref=d.get("embedding_ref", "") or "",
            confidence=d.get("confidence"),
            color=d.get("color", "#808080"),
        )


# ── 运行时状态 (内存 only, 不持久化) ──────────────────────────

@dataclass
class EventRuntime:
    """事件运行时状态机 — 单次 pipeline 会议的中间状态, 跑完即弃。

    TTS 引擎链 (ChatTTS→OpenVoice→EdgeTTS) 靠 tts_status 传递"上一个失败"信号。
    一律不写入 timeline.json; reload 后为空, 靠 Event.tts 是否存在判断"已配音"。
    """
    tts_status: str = ""          # ""|needs_split|rejected|fallback_accepted|...
    generation_mode: str = ""     # ""|primary|fallback
    reject_reason: str = ""       # 各引擎失败原因 (当次诊断)
    engine_scores: dict = field(default_factory=dict)    # 中间引擎评分
    dirty_flags: dict = field(default_factory=dict)      # SlotDependencyGraph 传播
    config_versions: dict = field(default_factory=dict)  # patch_engine 配置版本


# ── Event (合并 IR + State 的单一工作模型) ───────────────────

@dataclass
class Event:
    """可变工作模型 — pipeline pass 直接写字段, 用户编辑走 Patch。

    持久化字段 (to_dict ↔ timeline.json events[]):
      id/start/end/text/source/lineage/speaker/confidence/words/semantic/
      translation/tts/review
    运行时字段 (不持久化):
      runtime (EventRuntime)
    """
    id: str
    start: float
    end: float
    text: str
    source: str = "asr"
    lineage: str = ""               # 分裂来源 id; 空 → __post_init__ 设为自身 id
    speaker: str | None = None
    confidence: float = 1.0
    words: list[Word] = field(default_factory=list)
    semantic: Semantic = field(default_factory=Semantic)
    translation: Translation | None = None
    tts: TTSAudio | None = None
    review: Review = field(default_factory=Review)
    runtime: EventRuntime = field(default_factory=EventRuntime, repr=False)

    def __post_init__(self):
        if self.start >= self.end:
            raise ValueError(
                f"Event {self.id}: start({self.start:.2f}) >= end({self.end:.2f}) — "
                "坏数据必须在 adapter 边界清洗, 不得进入模型 (禁止兜底)")
        if not self.lineage:
            self.lineage = self.id

    # ── 持久化 ────────────────────────────────────────────

    def to_dict(self) -> dict:
        """序列化为 timeline.json v3.0 的 event 项 (不含 runtime)。"""
        return {
            "id": self.id,
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "source": self.source,
            "lineage": self.lineage,
            "speaker": self.speaker,
            "confidence": self.confidence,
            "words": [w.to_dict() for w in self.words],
            "semantic": self.semantic.to_dict(),
            "translation": self.translation.to_dict() if self.translation else None,
            "tts": self.tts.to_dict() if self.tts else None,
            "review": self.review.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        """从 timeline.json v3.0 反序列化。缺必填字段显式 raise (禁止兜底)。

        words 缺失默认 [] (外部 SRT 导入场景), 由分段逻辑打 review flag,
        不在此崩 — 但 words 若存在则每个词必填 word/start/end。
        """
        words = [Word.from_dict(w) for w in d.get("words", [])]
        trans_raw = d.get("translation")
        tts_raw = d.get("tts")
        return cls(
            id=_require(d, "id", "Event"),
            start=float(_require(d, "start", "Event")),
            end=float(_require(d, "end", "Event")),
            text=_require(d, "text", "Event"),
            source=d.get("source", "asr"),
            lineage=d.get("lineage", ""),
            speaker=d.get("speaker"),
            confidence=float(d.get("confidence", 1.0)),
            words=words,
            semantic=Semantic.from_dict(d.get("semantic")),
            translation=Translation.from_dict(trans_raw) if isinstance(trans_raw, dict) else None,
            tts=TTSAudio.from_dict(tts_raw) if isinstance(tts_raw, dict) else None,
            review=Review.from_dict(d.get("review")),
        )

    def derive_text(self, lang: str = "") -> str:
        """从 words 重新派生 text (分段/合并后用)。"""
        return join_words(self.words, lang)


# ── Project ────────────────────────────────────────────────

@dataclass
class ProjectAudio:
    """项目级音频 (从旧 event 级 audio 槽上移)。"""
    vocals_path: str = ""
    bgm_path: str = ""
    sample_rate: int = 16000

    def to_dict(self) -> dict:
        return {
            "vocals_path": self.vocals_path,
            "bgm_path": self.bgm_path,
            "sample_rate": self.sample_rate,
        }

    @classmethod
    def from_dict(cls, d: dict | None) -> "ProjectAudio":
        d = d or {}
        return cls(
            vocals_path=d.get("vocals_path", ""),
            bgm_path=d.get("bgm_path", ""),
            sample_rate=int(d.get("sample_rate", 16000)),
        )


@dataclass
class Project:
    """项目容器 — timeline.json v3.0 的根。

    events 平铺按 start 排序, 不按说话人分组; speakers 是注册表。
    """
    id: str
    source_video: str
    source_lang: str
    target_lang: str
    created_at: str = ""
    audio: ProjectAudio = field(default_factory=ProjectAudio)
    speakers: dict[str, Speaker] = field(default_factory=dict)
    events: list[Event] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION_V3,
            "project": {
                "id": self.id,
                "source_video": self.source_video,
                "source_lang": self.source_lang,
                "target_lang": self.target_lang,
                "created_at": self.created_at,
                "audio": self.audio.to_dict(),
            },
            "events": [e.to_dict() for e in self.events],
            "speakers": {sid: s.to_dict() for sid, s in self.speakers.items()},
            "metadata": {
                "total_duration": max((e.end for e in self.events), default=0.0),
                "event_count": len(self.events),
                "speaker_count": len(self.speakers),
            },
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Project":
        proj = _require(d, "project", "Project")
        speakers = {
            sid: Speaker.from_dict({**s, "id": s.get("id", sid)})
            for sid, s in d.get("speakers", {}).items()
        }
        return cls(
            id=_require(proj, "id", "Project.project"),
            source_video=_require(proj, "source_video", "Project.project"),
            source_lang=_require(proj, "source_lang", "Project.project"),
            target_lang=_require(proj, "target_lang", "Project.project"),
            created_at=proj.get("created_at", ""),
            audio=ProjectAudio.from_dict(proj.get("audio")),
            speakers=speakers,
            events=[Event.from_dict(e) for e in _require(d, "events", "Project")],
        )
