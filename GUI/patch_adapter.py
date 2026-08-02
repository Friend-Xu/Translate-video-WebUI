"""patch_adapter.py — 旧 WebUI patch 契约 ↔ core Patch 适配 (Phase 4)

前端契约 (useAppStore.patchDraftToApiFormat) 仍用旧词表:
  MERGE / SPLIT / RETAG_SPEAKER / SET_TRANSLATION / RESIZE / ANNOTATE
写路径统一走 core PatchEngine 后, 这里做薄映射。

未知/未迁移操作响亮报错 (UnsupportedPatchError), 不静默降级。
"""
from __future__ import annotations
import json
import os

from core.runtime.patch import Patch, OpCode


class UnsupportedPatchError(ValueError):
    """前端契约中无 core 对等语义的操作 — 显式拒绝而非静默跳过。"""


_LEGACY_TO_OP: dict[str, OpCode] = {
    "MERGE": OpCode.SEGMENT_MERGE,
    "SPLIT": OpCode.SEGMENT_SPLIT,
    "RETAG_SPEAKER": OpCode.ASSIGN_SPEAKER,
    "SET_TRANSLATION": OpCode.UPDATE_TRANSLATION,
    "RESIZE": OpCode.UPDATE_BOUNDS,
    "ANNOTATE": OpCode.ANNOTATE,
    "UPDATE_TRANSCRIPTION": OpCode.UPDATE_TRANSCRIPTION,
    "UPDATE_TRANSLATION": OpCode.UPDATE_TRANSLATION,
    "UPDATE_BOUNDS": OpCode.UPDATE_BOUNDS,
    # P2 收敛: speaker 操作统一走 patch (此前 ANNOTATE 承载/拒绝)
    "ASSIGN_SPEAKER": OpCode.ASSIGN_SPEAKER,
    "MERGE_SPEAKERS": OpCode.MERGE_SPEAKERS,
    "CREATE_SPEAKER": OpCode.REGISTER_SPEAKER,
    "RENAME_SPEAKER": OpCode.UPDATE_SPEAKER,
    "BIND_VOICE": OpCode.UPDATE_SPEAKER,
    "LOCK_SPEAKER": OpCode.LOCK_SPEAKER,
    # P3-A 收敛: timeline 编辑假 draft 补映射 (此前降级 ANNOTATE 静默零写入)
    "MOVE_EVENT": OpCode.UPDATE_BOUNDS,
    "TRIM_START": OpCode.UPDATE_BOUNDS,
    "TRIM_END": OpCode.UPDATE_BOUNDS,
    "SPLIT_EVENT": OpCode.SEGMENT_SPLIT,
    "MERGE_PREV": OpCode.SEGMENT_MERGE,
    "MERGE_NEXT": OpCode.SEGMENT_MERGE,
    "APPLY_AI_SUGGESTION": OpCode.UPDATE_TRANSLATION,
    # 局部重算: core 无 LLM 重翻通道, 唯一诚实落点是 needs_retranslate 标记
    "RETRIGGER": OpCode.ANNOTATE,
}

# log 显示用: core op → 前端认识的旧词表 (pass_trace KNOWN_PASS_ORDER 大写匹配)
_OP_TO_LEGACY: dict[OpCode, str] = {
    OpCode.SEGMENT_MERGE: "MERGE",
    OpCode.SEGMENT_SPLIT: "SPLIT",
    OpCode.ASSIGN_SPEAKER: "ASSIGN_SPEAKER",
    OpCode.UPDATE_TRANSLATION: "SET_TRANSLATION",
    OpCode.UPDATE_BOUNDS: "RESIZE",
    OpCode.MERGE_SPEAKERS: "MERGE_SPEAKERS",
    OpCode.REGISTER_SPEAKER: "CREATE_SPEAKER",
    OpCode.UPDATE_SPEAKER: "RENAME_SPEAKER",
    OpCode.LOCK_SPEAKER: "LOCK_SPEAKER",
}


def _parse_ts(v) -> float:
    """兼容 epoch 秒与 ISO 字符串 (旧 TimelinePatch 用 ISO 格式)。"""
    if v is None or v == "":
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    try:
        return float(s)
    except ValueError:
        pass
    from datetime import datetime
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        raise ValueError(f"无法解析 patch 时间戳: {v}")


def legacy_to_core(d: dict) -> Patch:
    """旧前端 patch dict → core Patch。未知 opcode/speaker 编码 op 响亮报错。"""
    op_raw = str(d.get("opcode") or "").upper()
    op = _LEGACY_TO_OP.get(op_raw)
    if op is None:
        raise UnsupportedPatchError(
            f"不支持的 opcode '{d.get('opcode')}' (合法: {sorted(_LEGACY_TO_OP)})"
        )
    targets = list(d.get("targets") or [])
    target_id = targets[0] if targets else str(d.get("target_id") or "")
    payload = d.get("payload") or {}

    if op_raw == "ANNOTATE":
        key = payload.get("key", "")
        if key == "deleted":
            value = payload.get("value")
            flags = ["deleted"] if value else []
            value = {"review": {"flags": flags}}
        else:
            value = payload
    elif op_raw == "MERGE":
        value = {"target_ids": targets}
    elif op_raw == "SPLIT":
        value = {"at": float(payload.get("split_point", 0.0))}
    elif op_raw == "RETAG_SPEAKER" or op_raw == "ASSIGN_SPEAKER":
        value = {"speaker_id": str(payload.get("new_speaker") or "")}
    elif op_raw in ("MOVE_EVENT", "TRIM_START", "TRIM_END"):
        value = {
            "start": float(payload["start"]) if "start" in payload else None,
            "end": float(payload["end"]) if "end" in payload else None,
        }
    elif op_raw == "SPLIT_EVENT":
        value = {"at": float(payload.get("splitTime", 0.0))}
    elif op_raw in ("MERGE_PREV", "MERGE_NEXT"):
        merge_with = str(payload.get("mergeTarget") or "")
        if not merge_with:
            raise UnsupportedPatchError(f"{op_raw} 缺合并目标 (payload.mergeTarget)")
        ids = [target_id, merge_with]
        targets = ids
        value = {"target_ids": ids}
    elif op_raw == "APPLY_AI_SUGGESTION":
        value = {"translation": payload.get("translation", "")}
    elif op_raw == "RETRIGGER":
        value = {"review": {"flags": ["needs_retranslate"], "needs_human_review": True}}
    elif op_raw == "SET_TRANSLATION":
        value = {"translation": payload.get("translation", payload.get("text", ""))}
    elif op_raw == "RESIZE":
        value = {
            "start": float(payload["new_start"]) if "new_start" in payload else None,
            "end": float(payload["new_end"]) if "new_end" in payload else None,
        }
    elif op_raw == "MERGE_SPEAKERS":
        into = str(payload.get("target") or payload.get("new_speaker") or "")
        if not into:
            raise UnsupportedPatchError("MERGE_SPEAKERS 缺合并目标 (payload.target)")
        value = {
            "from_ids": [str(payload.get("source") or target_id)],
            "into_id": into,
        }
    elif op_raw == "CREATE_SPEAKER":
        # 前端 create 用伪 eventId 作占位 — 这里落注册表 speaker_id
        value = {
            "speaker_id": target_id,
            "display_name": payload.get("display_name", payload.get("name", "")),
        }
    elif op_raw == "RENAME_SPEAKER":
        value = {
            "speaker_id": target_id,
            "name": payload.get("newName", payload.get("name", "")),
            "color": payload.get("color"),
        }
    elif op_raw == "BIND_VOICE":
        # 声线绑定/解绑 — UPDATE_SPEAKER 写注册表 voice_id (此前仅本地 lanes, 刷新即丢)
        value = {
            "speaker_id": target_id,
            "voice_id": payload.get("voice_id", ""),
        }
    elif op_raw == "LOCK_SPEAKER":
        value = {
            "speaker_id": target_id,
            "locked": bool(payload.get("locked", True)),
        }
    else:
        value = payload

    return Patch(
        id=str(d.get("patch_id") or d.get("id") or "patch_legacy"),
        target_id=target_id,
        op=op,
        value=value,
        timestamp=_parse_ts(d.get("timestamp")),
        author=str(d.get("author") or "user"),
        targets=targets or None,
        reason=list(d.get("reason") or []),
        score=float(d.get("score", 1.0)),
        confidence=float(d.get("confidence", 1.0)),
        parent_version=str(d.get("parent_version") or ""),
        idempotency_key=str(d.get("idempotency_key") or ""),
    )


def core_to_legacy(p: Patch) -> dict:
    """core Patch → 前端 log 显示格式 (旧词表映射保持 pass_trace 兼容)。"""
    op_label = _OP_TO_LEGACY.get(p.op, p.op.value)
    return {
        "patch_id": p.id,
        "opcode": op_label,
        "targets": p.targets or [p.target_id],
        "payload": p.value,
        "reason": list(p.reason or []),
        "score": p.score,
        "confidence": p.confidence,
        "parent_version": p.parent_version or "",
        "idempotency_key": p.idempotency_key or "",
        "author": p.author,
        "timestamp": p.timestamp,
    }


def load_chain(path: str) -> list[Patch]:
    """读 patch 链 (timeline_patches.json) — 新格式 (core to_dict) + 旧格式混合归一。

    旧链是历史数据, 经 legacy_to_core 归一; 单条解析失败响亮报错 (禁止兜底)。
    """
    if not path or not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, list):
        raise ValueError(f"patch 链格式错误 (应为 list): {path}")
    out: list[Patch] = []
    for item in raw:
        try:
            out.append(Patch.from_dict(item))
        except (KeyError, ValueError, TypeError):
            out.append(legacy_to_core(item))
    return out


def save_chain(patches: list[Patch], path: str) -> None:
    """以 core 序列化格式落盘 patch 链。"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([p.to_dict() for p in patches], f, ensure_ascii=False, indent=2)
