"""
双写基础设施 — 补丁同步应用到新旧 IR 并比对

Strangler Fig 关键组件：保证新旧系统行为等价。
差异不阻断，只记录 diff 日志。
"""

from __future__ import annotations
from timeline.ir import TimelineIR
from timeline.patch.model import TimelinePatch
from timeline.patch.apply import apply_patch


def dual_write_patch(
    old_ir: TimelineIR,
    patch: TimelinePatch,
    project_ir=None,
) -> dict:
    """应用 patch 到新旧两套 IR，比对结果。

    Returns:
        {"status": "ok"|"diff"|"error", "diff_count": int, "diffs": [...]}
    """
    # Step 1: apply to old IR
    old_segments = [s.to_dict() for s in old_ir.timeline]
    try:
        new_old_segments, old_diff = apply_patch(old_segments, patch)
    except Exception as e:
        return {"status": "error", "reason": f"old apply failed: {e}"}

    # Step 2: get or build project_ir
    if project_ir is None:
        from timeline.fusion import to_project_ir
        project_ir = to_project_ir(old_ir)

    # Step 3: apply to new IR via PatchEngine
    from core.runtime.patch import Patch as CorePatch
    from core.runtime.project_state import TimelineProjectState
    from core.runtime.patch_engine import PatchEngine

    state = TimelineProjectState(project_ir)
    engine = PatchEngine()

    core_target = _map_targets_to_new_ids(patch.targets, old_segments)
    core_patch = CorePatch(
        id=patch.patch_id,
        target_id=core_target[0] if core_target else patch.targets[0],
        op=_map_opcode(patch.opcode.value),
        value=_map_payload(patch.opcode.value, patch.payload),
    )

    result = engine.apply(state, core_patch)
    if result.get("status") != "applied":
        return {"status": "error", "reason": f"new apply failed: {result.get('reason')}"}

    # Step 4: compare
    from core.runtime.verify import _build_v2_output, _compare

    v2_output = _build_v2_output(_segments_from_state(state), None)
    old_output = _extract_old_from_segments(new_old_segments)
    diffs = _compare(old_output, v2_output)

    return {
        "status": "diff" if diffs else "ok",
        "diff_count": len(diffs),
        "diffs": diffs,
        "old_diff": old_diff,
        "new_result": result,
    }


def _map_targets_to_new_ids(targets: list[str], old_segments: list[dict]) -> list[str]:
    """to_project_ir 保留原始 segment ID，直接传递"""
    return list(targets)


def _map_opcode(op: str) -> str:
    """映射旧 OpCode 到新引擎 op 字符串"""
    mapping = {
        "MERGE": "merge", "SPLIT": "split",
        "RETAG_SPEAKER": "replace", "SET_TRANSLATION": "replace",
        "RELINK_WORDS": "propagate", "ANNOTATE": "replace",
    }
    return mapping.get(op, "replace")


def _map_payload(op: str, payload: dict) -> dict:
    """将旧 IR 的 patch payload 转换为新引擎期望的 value 格式。

    RETAG_SPEAKER: new_speaker → speaker (写入 derivatives.speaker，被 SynthesisEngine 叠加)
    SET_TRANSLATION: translation → translation (写入 derivatives.translation)
    ANNOTATE: key/value → annotation (写入 derivatives.annotation)
    MERGE/SPLIT/RELINK_WORDS: 保持原 payload 不变
    """
    if op == "RETAG_SPEAKER":
        return {"speaker": payload.get("new_speaker", payload.get("speaker", ""))}
    elif op == "SET_TRANSLATION":
        return {"translation": payload.get("translation", "")}
    elif op == "ANNOTATE":
        return {"annotation": {payload.get("key", ""): payload.get("value")}}
    else:
        return dict(payload)


def _segments_from_state(state) -> list[dict]:
    from core.runtime.synthesis import SynthesisEngine
    return SynthesisEngine().render_all(state)


def _extract_old_from_segments(segments: list[dict]) -> list[dict]:
    return [
        {
            "id": s.get("id", ""), "start": s.get("start", 0.0),
            "end": s.get("end", 0.0), "speaker": s.get("speaker"),
            "text": s.get("text", ""), "source": "asr",
        }
        for s in segments
    ]
