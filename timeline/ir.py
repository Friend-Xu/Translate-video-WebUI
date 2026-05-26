"""
Timeline IR — 统一时间轴中间表示

TimelineWord → TimelineSegment → TimelineIR

规范参考: 计划开发/Translate-video-WebUI_统一时间轴工程化改造计划书.md

- word 是最小语义单位
- speaker 是逻辑实体，可重命名、可合并
- overlap 必须显式表达
- Timeline IR 版本化，便于后续迁移
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TimelineWord:
    """词级时间戳单元 — 最细粒度的语义+时间信息"""
    word: str
    start: float
    end: float
    score: float = 1.0
    speaker: str | None = None

    def to_dict(self) -> dict:
        d: dict = {"word": self.word, "start": self.start, "end": self.end}
        if self.score != 1.0:
            d["score"] = self.score
        if self.speaker is not None:
            d["speaker"] = self.speaker
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "TimelineWord":
        return cls(
            word=d["word"],
            start=d["start"],
            end=d["end"],
            score=d.get("score", 1.0),
            speaker=d.get("speaker"),
        )


@dataclass
class TimelineSegment:
    """有起止时间的语义片段 — Timeline IR 的核心单元"""
    id: str                                    # "seg_001"
    type: str = "speech"                       # speech / silence / music
    speaker: str | None = None                 # "SPEAKER_00"
    start: float = 0.0
    end: float = 0.0
    text: str = ""
    translation: str = ""                      # 翻译后回写
    overlap: bool = False                      # 是否与其他 segment 时间重叠
    words: list[TimelineWord] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict:
        d: dict = {
            "id": self.id,
            "type": self.type,
            "start": self.start,
            "end": self.end,
            "text": self.text,
        }
        if self.speaker is not None:
            d["speaker"] = self.speaker
        if self.translation:
            d["translation"] = self.translation
        if self.overlap:
            d["overlap"] = True
        if self.words:
            d["words"] = [w.to_dict() for w in self.words]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "TimelineSegment":
        words = [TimelineWord.from_dict(w) for w in d.get("words", [])]
        return cls(
            id=d["id"],
            type=d.get("type", "speech"),
            speaker=d.get("speaker"),
            start=d.get("start", 0.0),
            end=d.get("end", 0.0),
            text=d.get("text", ""),
            translation=d.get("translation", ""),
            overlap=d.get("overlap", False),
            words=words,
        )


@dataclass
class SpeakerMapEntry:
    """说话人元信息"""
    alias: str = ""                            # 显示名如 "主持人"
    voice_id: str = ""                         # TTS voice 如 "edge_zh_female_01"

    def to_dict(self) -> dict:
        d: dict = {}
        if self.alias:
            d["alias"] = self.alias
        if self.voice_id:
            d["voice_id"] = self.voice_id
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "SpeakerMapEntry":
        return cls(
            alias=d.get("alias", ""),
            voice_id=d.get("voice_id", ""),
        )


@dataclass
class TimelineIR:
    """统一时间轴中间表示 — 系统唯一的语义中间层"""
    audio_id: str                              # 视频 stem
    version: str = "1.0"
    timeline: list[TimelineSegment] = field(default_factory=list)
    speaker_map: dict[str, SpeakerMapEntry] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)  # lang, duration, sample_rate, ...

    @property
    def speakers(self) -> list[str]:
        """返回 timeline 中出现过的所有 speaker ID（排序）"""
        seen: set[str] = set()
        for seg in self.timeline:
            if seg.speaker:
                seen.add(seg.speaker)
        return sorted(seen)

    @property
    def total_duration(self) -> float:
        if not self.timeline:
            return 0.0
        return max(seg.end for seg in self.timeline)

    def to_dict(self) -> dict:
        d: dict = {
            "audio_id": self.audio_id,
            "version": self.version,
            "timeline": [seg.to_dict() for seg in self.timeline],
        }
        if self.speaker_map:
            d["speaker_map"] = {k: v.to_dict() for k, v in self.speaker_map.items()}
        if self.metadata:
            d["metadata"] = self.metadata
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "TimelineIR":
        speaker_map = {}
        for k, v in d.get("speaker_map", {}).items():
            speaker_map[k] = SpeakerMapEntry.from_dict(v)
        return cls(
            audio_id=d["audio_id"],
            version=d.get("version", "1.0"),
            timeline=[TimelineSegment.from_dict(s) for s in d.get("timeline", [])],
            speaker_map=speaker_map,
            metadata=d.get("metadata", {}),
        )
