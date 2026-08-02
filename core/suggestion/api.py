"""
suggestion.api — AI 建议入口 (迁移自 timeline/api/timeline.py)

只读: 只消费 timeline.json (v2 唯一事实源), 不修改任何状态。
v1 格式已随 extract_subtitles 退役 — 显式报错 (架构收束, 禁止兜底)。
"""
from __future__ import annotations

import json
import os

from core.suggestion.signal import extract_signals, extract_segment_signals
from core.suggestion.scorer import score_all
from core.suggestion.planner import plan


def _load_timeline_events(timeline_path: str) -> list[dict]:
    """统一读 v2 timeline.json, 返回 events 列表。"""
    with open(timeline_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if data.get("schema_version") != "2.0":
        raise ValueError(
            f"timeline.json 不是 v2 格式 (schema_version={data.get('schema_version')!r})。"
            "旧 v1 工作区请先运行: python tools/normalize_v1_timeline.py --root <目录>"
        )
    events = data.get("events", [])
    if not isinstance(events, list):
        raise ValueError(f"timeline.json events 字段不是列表: {type(events).__name__}")
    return events


def generate_candidate_patches(timeline_path: str) -> dict:
    """Generate AI-suggested patches. Read-only, no modification."""
    segments = _load_timeline_events(timeline_path)
    pair_signals = extract_signals(segments)
    seg_signals = [extract_segment_signals(s) for s in segments]
    scores = score_all(pair_signals, seg_signals)
    patches = plan(segments, pair_signals, scores)
    result = {"patches": [p.to_dict() for p in patches], "high": [], "medium": [], "low": []}
    for p in patches:
        result[p.confidence_label].append(p.to_dict())
    return result
