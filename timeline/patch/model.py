"""
TASK 03 — Patch Model

Patch is the ONLY mutation mechanism for Timeline.
All patches are: replayable, idempotent, serializable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from .opcode import OpCode
import hashlib


def _hash_timeline(timeline_data: dict) -> str:
    """SHA-256 of serialized timeline for parent_version tracking."""
    import json
    raw = json.dumps(timeline_data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


@dataclass
class TimelinePatch:
    """Patch — the only mutation primitive in the system."""
    patch_id: str
    opcode: OpCode
    targets: list[str]                          # segment ids
    payload: dict = field(default_factory=dict)
    reason: list[str] = field(default_factory=list)
    score: float = 0.0
    confidence: float = 0.0                     # 0.0-1.0
    parent_version: str = ""                    # hash of timeline before patch
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

    @classmethod
    def from_dict(cls, d: dict) -> "TimelinePatch":
        opcode = OpCode(d["opcode"]) if isinstance(d["opcode"], str) else d["opcode"]
        return cls(
            patch_id=d["patch_id"],
            opcode=opcode,
            targets=d.get("targets", []),
            payload=d.get("payload", {}),
            reason=d.get("reason", []),
            score=d.get("score", 0.0),
            confidence=d.get("confidence", 0.0),
            parent_version=d.get("parent_version", ""),
            idempotency_key=d.get("idempotency_key", ""),
            author=d.get("author", "system"),
            timestamp=d.get("timestamp", ""),
        )
