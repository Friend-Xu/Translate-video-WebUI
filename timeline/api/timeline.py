"""
TASK 15 — Timeline API Layer

Public API for patch-driven timeline editing.
Bridges Patch Engine with FastAPI/WebUI.
"""
from __future__ import annotations

import os, json
from timeline.patch.model import TimelinePatch
from timeline.patch.apply import apply_patch
from timeline.patch.conflict import is_safe_to_apply
from timeline.patch.planner import plan as planner_plan
from timeline.rules.extractor import extract_signals, extract_segment_signals
from timeline.scorer.scorer import score_all
from timeline.safety.guard import gate_check
from timeline.recovery.replay import undo_last
from timeline.recovery.snapshot import create_snapshot, should_snapshot
from timeline.io import load_json as load_timeline, save_json as save_timeline


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


def _save_timeline_segments(events: list[dict], full_data: dict, timeline_path: str):
    """写回 timeline.json，保持原格式。"""
    import json as _json
    if "schema_version" in full_data and full_data["schema_version"] == "2.0":
        full_data["events"] = events
    else:
        timeline = []
        for evt in events:
            timeline.append({
                "id": evt.get("id", ""), "type": "speech",
                "start": evt.get("start", 0), "end": evt.get("end", 0),
                "text": evt.get("text", ""), "translation": evt.get("translation", ""),
                "speaker": evt.get("speaker"), "overlap": evt.get("overlap", False),
                "words": evt.get("words", []),
            })
        full_data["timeline"] = timeline
    with open(timeline_path, "w", encoding="utf-8") as f:
        _json.dump(full_data, f, ensure_ascii=False, indent=2)


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


def apply_user_patch(
    timeline_path: str, patch_dict: dict, patch_log_path: str | None = None,
) -> dict:
    """Apply a single patch: validate → apply → log."""
    patch = TimelinePatch.from_dict(patch_dict)
    segments, full_data = _load_timeline_segments(timeline_path)
    existing = _load_patch_log(patch_log_path) if patch_log_path else []

    safe, reason = is_safe_to_apply(patch, existing, segments)
    if not safe:
        return {"status": "rejected", "reason": reason}

    acoustic = {s["id"]: s.get("speaker") for s in segments if s.get("speaker")}
    gate_check(patch, segments, acoustic)

    patch.parent_version = _hash_segments(segments)
    new_segments, diff = apply_patch(segments, patch)
    _save_timeline_segments(new_segments, full_data, timeline_path)

    if patch_log_path:
        existing.append(patch)
        _save_patch_log(existing, patch_log_path)

    if should_snapshot(len(existing)):
        snap = create_snapshot(new_segments, existing)
        snap_path = timeline_path.replace("timeline.json", "timeline_snapshot.json")
        with open(snap_path, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=2)

    return {"status": "applied", "patch_id": patch.patch_id, "diff": diff}


def undo_last_patch(
    source_timeline_path: str, working_timeline_path: str, patch_log_path: str,
) -> dict:
    source_segs, _ = _load_timeline_segments(source_timeline_path)
    existing = _load_patch_log(patch_log_path)
    if not existing:
        return {"status": "no_patches"}
    reverted = undo_last(source_segs, existing)
    if reverted is None:
        return {"status": "error"}
    removed = existing.pop()
    _save_patch_log(existing, patch_log_path)
    _, full_data = _load_timeline_segments(working_timeline_path)
    _save_timeline_segments(reverted, full_data, working_timeline_path)
    return {"status": "undone", "patch_id": removed.patch_id}


def get_patch_log(patch_log_path: str) -> list[dict]:
    return [p.to_dict() for p in _load_patch_log(patch_log_path)]


def _load_patch_log(path: str) -> list[TimelinePatch]:
    if not path or not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [TimelinePatch.from_dict(d) for d in json.load(f)]


def _save_patch_log(patches: list[TimelinePatch], path: str):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([p.to_dict() for p in patches], f, ensure_ascii=False, indent=2)


def _hash_segments(segments: list[dict]) -> str:
    import hashlib
    keys = ("id", "start", "end", "speaker", "text")
    raw = json.dumps([{k: s[k] for k in keys if k in s} for s in segments],
                     sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


# ── Migration Router ──────────────────────────────────────

class TimelineMigrationRouter:
    """Strangler Fig 渐进迁移路由 — feature flag 控制新旧 IR 切换。

    Usage:
        router = TimelineMigrationRouter()
        view = router.get_view(workspace_path, use_new_ir=False)
    """

    def __init__(self, new_ir_ratio: float = 0.0):
        self._ratio = max(0.0, min(1.0, new_ir_ratio))

    @property
    def ratio(self) -> float:
        return self._ratio

    def get_view(self, workspace: str, use_new_ir: bool = False):
        """获取统一 TimelineView — 根据 feature flag 返回旧或新视图。"""
        if use_new_ir:
            return self._new_view(workspace)

        import hashlib
        if self._ratio >= 1.0:
            return self._new_view(workspace)
        if self._ratio <= 0.0:
            return self._old_view(workspace)

        h = int(hashlib.md5(workspace.encode()).hexdigest()[:8], 16)
        if (h % 100) / 100.0 < self._ratio:
            return self._new_view(workspace)
        return self._old_view(workspace)

    def _old_view(self, workspace: str):
        from timeline.adapters.old_ir_adapter import OldTimelineView

        tl_path = os.path.join(workspace, "01_extract", "timeline.json")
        if not os.path.isfile(tl_path):
            raise FileNotFoundError(f"timeline.json 不存在: {tl_path}")

        tl = load_timeline(tl_path)
        return OldTimelineView(tl)

    def _new_view(self, workspace: str):
        from timeline.adapters.new_ir_adapter import NewTimelineView
        from timeline.fusion import to_project_ir

        tl_path = os.path.join(workspace, "01_extract", "timeline.json")
        if not os.path.isfile(tl_path):
            raise FileNotFoundError(f"timeline.json 不存在: {tl_path}")

        tl = load_timeline(tl_path)
        project_ir = to_project_ir(tl)
        from core.runtime.project_state import TimelineProjectState
        state = TimelineProjectState(project_ir)
        return NewTimelineView(state)
