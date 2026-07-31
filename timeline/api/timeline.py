"""
Timeline API — AI Patch 建议 (Phase 4 收敛后精简版)

写路径 (apply/undo/log) 已迁移到 core PatchEngine + timeline_io (GUI/patch_adapter)。
仅保留只读的 generate_candidate_patches (AI 建议, diarization/load 与 patch/generate 端点用)。
"""
from __future__ import annotations

import os, json
from timeline.patch.planner import plan as planner_plan
from timeline.rules.extractor import extract_signals, extract_segment_signals
from timeline.scorer.scorer import score_all


def _load_timeline_segments(timeline_path: str) -> tuple[list[dict], dict]:
    """统一读 timeline.json，返回 (events_list, full_v2_dict)。

    自动检测 v1/v2 格式。v1: {audio_id, timeline:[], speaker_map:{}}。
    v2: {schema_version, events:[], speakers:{}, ...} — 直接返回。
    """
    import json as _json
    with open(timeline_path, "r", encoding="utf-8") as f:
        data = _json.load(f)
    if "schema_version" in data and data["schema_version"] == "2.0":
        return data.get("events", []), data
    # 旧格式: 转换为 events 列表（不建 speaker 映射）
    events = []
    for seg in data.get("timeline", []):
        trans = seg.get("translation", "")
        if isinstance(trans, dict):
            trans = trans.get("text", "") or ""
        events.append({
            "id": seg.get("id", ""),
            "start": seg.get("start", 0),
            "end": seg.get("end", 0),
            "text": seg.get("text", ""),
            "translation": trans,
            "speaker": seg.get("speaker"),
            "overlap": seg.get("overlap", False),
            "words": seg.get("words", []),
        })
    return events, data


def generate_candidate_patches(timeline_path: str) -> dict:
    """Generate AI-suggested patches. Read-only, no modification."""
    segments, _ = _load_timeline_segments(timeline_path)
    pair_signals = extract_signals(segments)
    seg_signals = [extract_segment_signals(s) for s in segments]
    scores = score_all(pair_signals, seg_signals)
    patches = planner_plan(segments, pair_signals, scores)
    result = {"patches": [p.to_dict() for p in patches], "high": [], "medium": [], "low": []}
    for p in patches:
        result[p.confidence_label].append(p.to_dict())
    return result
