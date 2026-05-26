"""
GateValidator — Patch 预应用校验 (Chapter 12 §)

OpCode 合法性, target 存在性, confidence 范围, 幂等性, value 结构,
v3.0: JSON Schema config 校验 + 跨槽位约束规则表 (定稿 §10.6, §10.6.1)
"""
from __future__ import annotations
from dataclasses import dataclass
import os
from core.runtime.patch import Patch, OpCode
from core.runtime.project_state import TimelineProjectState
from core.config.schema_loader import SchemaLoader


@dataclass
class GateRejection:
    patch_id: str
    reason: str
    detail: str
    suggestion: str = ""


_REQUIRED: dict[OpCode, list[str]] = {
    OpCode.SEGMENT_INSERT: ["start", "end"],
    OpCode.SEGMENT_SPLIT: ["at"],
    OpCode.SEGMENT_MERGE: ["target_ids"],
    OpCode.ASSIGN_SPEAKER: ["speaker_id"],
    OpCode.MERGE_SPEAKERS: ["from_ids", "into_id"],
    OpCode.SPLIT_SEGMENT_BY_SPEAKER: ["boundaries"],
    # v3.0: 配置 OpCode (定稿 §10.5)
    OpCode.SET_CONFIG: ["slot", "config_block"],
    OpCode.OVERRIDE_CONFIG: ["slot", "partial_config"],
    OpCode.RESET_CONFIG: ["slot"],
    OpCode.BATCH_SET_CONFIG: ["slot", "config_block"],
}

_NO_TARGET = {OpCode.SEGMENT_INSERT}

# ── 跨槽位约束规则表 (定稿 §10.6.1) ────────────────────────────
# (constraint_id, check_fn, level) — level="ERROR" 拒绝, "WARN" 允许但记录
_CROSS_SLOT_RULES: list[tuple[str, callable, str]] = []


def _rule(cid: str, level: str = "ERROR"):
    """注册跨槽位约束的装饰器工厂。"""
    def decorator(fn):
        _CROSS_SLOT_RULES.append((cid, fn, level))
        return fn
    return decorator


@_rule("ASR-C01", "WARN")
def _check_asr_large_on_cpu(patch, state):
    v = patch.value
    cfg = v.get("partial_config") or v.get("config_block") or {}
    if cfg.get("model") in ("medium", "large-v2", "large-v3") and cfg.get("device") == "cpu":
        return False, "large model on CPU will be very slow"
    return True, ""


@_rule("TR-C02", "ERROR")
def _check_contextual_glossary_local(patch, state):
    v = patch.value
    cfg = v.get("partial_config") or v.get("config_block") or {}
    glossary = cfg.get("glossary") or {}
    backend = cfg.get("backend", "")
    if glossary.get("mode") == "CONTEXTUAL" and backend == "local_dict":
        return False, "CONTEXTUAL glossary requires LLM backend (deepseek/openai), not local_dict"
    return True, ""


@_rule("GATE-C03", "ERROR")
def _check_gate_thresholds(patch, state):
    v = patch.value
    cfg = v.get("partial_config") or v.get("config_block") or {}
    gate = cfg.get("gate") or {}
    accept = gate.get("threshold_accept")
    reject = gate.get("threshold_reject")
    if accept is not None and reject is not None and accept <= reject:
        return False, "threshold_accept must be > threshold_reject"
    return True, ""


@_rule("TTS-C01", "WARN")
def _check_cosyvoice_needs_clone(patch, state):
    v = patch.value
    cfg = v.get("partial_config") or v.get("config_block") or {}
    if cfg.get("engine") == "cosyvoice":
        return False, "CosyVoice zero-shot cloning works best with a speaker clone_ref"
    return True, ""


@_rule("EMO-C01", "WARN")
def _check_emotion_without_demucs(patch, state):
    v = patch.value
    cfg = v.get("partial_config") or v.get("config_block") or {}
    if cfg.get("enabled") is True:
        return False, "emotion recognition may be affected without Demucs separation"
    return True, ""


@_rule("ENG-C02", "ERROR")
def _check_cosyvoice_lang(patch, state):
    v = patch.value
    cfg = v.get("partial_config") or v.get("config_block") or {}
    lang = cfg.get("lang", "")
    engine = cfg.get("engine", "")
    if lang and lang not in ("zh", "en", "ja", "ko", "yue") and engine == "cosyvoice":
        return False, "CosyVoice only supports zh/en/ja/ko/yue language tags"
    return True, ""


class GateValidator:

    def __init__(self, schema_dir: str | None = None):
        if schema_dir is None:
            schema_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "schemas", "ir_v2",
            )
        self._schema_loader = SchemaLoader(schema_dir)

    def validate(self, patch: Patch, state: TimelineProjectState) -> list[GateRejection]:
        r: list[GateRejection] = []

        if not isinstance(patch.op, OpCode):
            r.append(GateRejection(patch.id, "invalid_opcode",
                     f"unknown: {patch.op}", "use valid OpCode"))
            return r

        if patch.op not in _NO_TARGET and state.get_event(patch.target_id) is None:
            r.append(GateRejection(patch.id, "target_not_found",
                     f"id={patch.target_id}", "create segment first"))

        if not (0.0 <= patch.confidence <= 1.0):
            r.append(GateRejection(patch.id, "invalid_confidence",
                     f"conf={patch.confidence}", "must be [0,1]"))

        if patch.idempotency_key:
            for es in state.event_states.values():
                if any(e.idempotency_key == patch.idempotency_key for e in es.patches):
                    r.append(GateRejection(patch.id, "duplicate_idempotency",
                             f"key={patch.idempotency_key}", "skip or new key"))
                    return r

        for field in _REQUIRED.get(patch.op, []):
            if field not in patch.value:
                r.append(GateRejection(patch.id, "missing_field",
                         f"op={patch.op.value} needs '{field}'",
                         f"add '{field}' to value"))
                return r

        # v3.0: JSON Schema 校验配置内容 (定稿 §10.6, Step 1)
        if patch.op in (OpCode.SET_CONFIG, OpCode.OVERRIDE_CONFIG):
            slot = patch.value.get("slot", "")
            config = patch.value.get("config_block") or patch.value.get("partial_config") or {}
            ok, err = self._schema_loader.validate(slot, config)
            if not ok:
                r.append(GateRejection(patch.id, "schema_validation_failed",
                         f"slot={slot}: {err}", "fix config values to match schema"))

        # v3.0: 跨槽位约束校验 (定稿 §10.6.1, Step 3)
        for cid, check_fn, level in _CROSS_SLOT_RULES:
            passed, msg = check_fn(patch, state)
            if not passed:
                if level == "ERROR":
                    r.append(GateRejection(patch.id, f"constraint_{cid}",
                             msg, "resolve constraint violation"))
                # WARN level constraints are logged but not rejected

        return r

    def validate_config(self, slot: str, config: dict) -> tuple[bool, str | None]:
        """仅执行 Schema 校验，不检查 Patch 结构。"""
        return self._schema_loader.validate(slot, config)

    def validate_many(self, patches: list[Patch],
                      state: TimelineProjectState) -> dict[str, list[GateRejection]]:
        result: dict[str, list[GateRejection]] = {}
        for p in patches:
            rejections = self.validate(p, state)
            if rejections:
                result[p.id] = rejections
        return result
