"""
断点续传模块 — ResumeManager

从原 `SrtTxtToAudio` 中保存/恢复进度的逻辑提取。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set


@dataclass
class ResumeState:
    """断点续传状态"""
    processed_pairs: Set[tuple] = field(default_factory=set)
    over_time_audio_list: List[str] = field(default_factory=list)
    error_subtitles: List[Dict[str, Any]] = field(default_factory=list)
    last_count: int = 0
    total_subs: int = 0

    def to_dict(self) -> dict:
        return {
            "processed_pairs": list(self.processed_pairs),
            "over_time_audio_list": self.over_time_audio_list,
            "error_subtitles": self.error_subtitles,
            "last_count": self.last_count,
            "total_subs": self.total_subs,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ResumeState":
        state = cls()
        state.processed_pairs = set(tuple(p) for p in data.get("processed_pairs", []))
        state.over_time_audio_list = data.get("over_time_audio_list", [])
        state.error_subtitles = data.get("error_subtitles", [])
        state.last_count = data.get("last_count", 0)
        state.total_subs = data.get("total_subs", 0)
        return state


class ResumeManager:
    """断点续传管理器。

    提供保存和加载处理进度的功能，支持多条流水线共享。
    """

    def __init__(self, state_path: str = "file/resume_state.json"):
        self.state_path = state_path
        self.state = self._load()

    def _load(self) -> ResumeState:
        if os.path.isfile(self.state_path):
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return ResumeState.from_dict(data)
            except (json.JSONDecodeError, Exception) as e:
                print(f"断点续传状态加载失败: {e}，从头开始")
        return ResumeState()

    def save(self):
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(self.state.to_dict(), f, ensure_ascii=False, indent=2)

    def mark_processed(self, start: int, end: int):
        self.state.processed_pairs.add((start, end))

    def is_processed(self, start: int, end: int) -> bool:
        return (start, end) in self.state.processed_pairs

    def add_error(self, start: int, end: int, text: str, error: str):
        self.state.error_subtitles.append({
            "start": start,
            "end": end,
            "text": text,
            "error": error,
        })

    def reset(self):
        self.state = ResumeState()
        if os.path.isfile(self.state_path):
            os.remove(self.state_path)
