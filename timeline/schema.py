"""
TASK 00 — Freeze IR Schema v1.1
Pydantic models for Timeline IR validation.
Version locked, no extra fields allowed.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator
from typing import Optional

IR_VERSION = "1.1"


class WordSchema(BaseModel):
    """词级时间戳 schema"""
    word: str
    start: float
    end: float
    score: float = 1.0
    speaker: Optional[str] = None

    model_config = {"extra": "forbid"}


class SegmentSchema(BaseModel):
    """Timeline segment schema"""
    id: str                                     # "seg_001"
    type: str = "speech"                        # speech / silence / music
    speaker: Optional[str] = None               # "SPEAKER_00"
    start: float
    end: float
    text: str = ""
    translation: str = ""
    overlap: bool = False
    words: list[WordSchema] = Field(default_factory=list)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def time_positive(self):
        assert self.start < self.end, f"{self.id}: start({self.start}) >= end({self.end})"
        return self

    @model_validator(mode="after")
    def words_monotonic(self):
        if not self.words:
            return self
        prev_end = self.words[0].start
        for w in self.words:
            assert w.start <= w.end, f"{self.id}/word '{w.word}': start({w.start}) > end({w.end})"
            assert w.start >= prev_end - 0.01, \
                f"{self.id}/word '{w.word}': start({w.start}) < prev({prev_end})"
            prev_end = w.end
        return self


class SpeakerMapEntrySchema(BaseModel):
    """说话人元信息 schema"""
    alias: str = ""
    voice_id: str = ""

    model_config = {"extra": "forbid"}


class TimelineIRSchema(BaseModel):
    """Timeline IR v1.1 — frozen schema"""
    audio_id: str
    version: str = IR_VERSION
    timeline: list[SegmentSchema] = Field(default_factory=list)
    speaker_map: dict[str, SpeakerMapEntrySchema] = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def timeline_monotonic(self):
        return self
