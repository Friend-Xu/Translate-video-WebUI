"""
suggestion.model — 建议 patch 数据模型 (迁移自 timeline/patch/model)

to_dict 字段形状 = 旧 TimelinePatch 契约, 前端/适配层零改动。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from core.suggestion.opcode import SuggestionOpCode as OpCode
import hashlib


@dataclass
class SuggestionPatch:
    """Patch 建议 — 只读候选, 不直接修改任何状态。"""
    patch_id: str
    opcode: OpCode
    targets: list[str]
    payload: dict = field(default_factory=dict)
    reason: list[str] = field(default_factory=list)
    score: float = 0.0
    confidence: float = 0.0
    parent_version: str = ""
    idempotency_key: str = ""
    author: str = "system"
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if not self.idempotency_key:
            import json
            raw = f"{self.opcode.value}:{','.join(sorted(self.targets))}:{json.dumps(self.payload, sort_keys=True)}"
            self.idempotency_key = hashlib.sha256(raw.encode()).hexdigest()[:16]

    @property
    def confidence_label(self) -> str:
        if self.confidence > 0.9:
            return "high"
        elif self.confidence >= 0.7:
            return "medium"
        return "low"

    def to_dict(self) -> dict:
        return {
            "patch_id": self.patch_id,
            "opcode": self.opcode.value,
            "targets": self.targets,
            "payload": self.payload,
            "reason": self.reason,
            "score": self.score,
            "confidence": self.confidence,
            "parent_version": self.parent_version,
            "idempotency_key": self.idempotency_key,
            "author": self.author,
            "timestamp": self.timestamp,
        }
