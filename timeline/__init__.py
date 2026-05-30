"""
Timeline 模块 — AI Assisted Timeline Editing System

Timeline-first / Patch-driven / Verification-based architecture.

提供:
- TimelineIR / TimelineSegment / TimelineWord / SpeakerMapEntry — 核心数据结构
- JSON 序列化 / 反序列化 / 版本迁移
- 版本化 Pydantic schema (v1.1)
- Patch Engine (6 fixed opcodes, apply, planner, conflict detection)
- Rule Feature Extractor + Scoring Engine
- Speaker 三层模型 (Acoustic / Logical / Runtime)
- Recovery (undo, replay, snapshot, DAG)
- Safety Gate (validator)
- Public API layer

用法:
    from timeline import TimelineIR, TimelineSegment, TimelineWord
    from timeline import save_json, load_json, from_extract_result
    from timeline.api import generate_candidate_patches, apply_user_patch, undo_last_patch
"""

from .ir import TimelineIR, TimelineSegment, TimelineWord, SpeakerMapEntry
from .io import save_json, load_json, migrate
from .fusion import from_extract_result

__all__ = [
    "TimelineIR",
    "TimelineSegment",
    "TimelineWord",
    "SpeakerMapEntry",
    "save_json",
    "load_json",
    "migrate",
    "from_extract_result",
]
