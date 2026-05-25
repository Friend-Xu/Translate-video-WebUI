"""
PatchStore — 三层 Patch 存储 (Chapter 12 §12.9)

Layer 1: Hot (in-memory)    Layer 2: Persistent (JSON)    Layer 3: Compressed
"""
from __future__ import annotations
import json, os
from core.runtime.patch import Patch, OpCode


class PatchStore:

    def __init__(self, persist_dir: str = ""):
        self.hot: list[Patch] = []
        self.persist_dir = persist_dir

    def append(self, patch: Patch) -> None:
        self.hot.append(patch)

    def flush(self) -> str:
        if not self.persist_dir:
            return ""
        os.makedirs(self.persist_dir, exist_ok=True)
        fp = os.path.join(self.persist_dir, "patches.json")
        data = [{
            "id": p.id, "target_id": p.target_id, "op": p.op.value,
            "value": p.value, "timestamp": p.timestamp, "author": p.author,
            "confidence": p.confidence, "score": p.score, "reason": p.reason,
            "parent_version": p.parent_version, "idempotency_key": p.idempotency_key,
        } for p in self.hot]
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return fp

    def load(self, file_path: str) -> list[Patch]:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [Patch(
            id=d["id"], target_id=d["target_id"], op=OpCode(d["op"]),
            value=d.get("value", {}), timestamp=d.get("timestamp", 0.0),
            author=d.get("author", "system"), confidence=d.get("confidence", 1.0),
            score=d.get("score", 1.0), reason=d.get("reason"),
            parent_version=d.get("parent_version", ""),
            idempotency_key=d.get("idempotency_key", ""),
        ) for d in data]

    def compress(self, patches: list[Patch], strategy: str = "merge_adjacent") -> list[Patch]:
        if strategy == "keep_latest":
            return self._keep_latest(patches)
        if strategy == "keep_checkpoints":
            return self._keep_checkpoints(patches)
        return self._merge_adjacent(patches)

    def _merge_adjacent(self, patches: list[Patch]) -> list[Patch]:
        if len(patches) <= 1:
            return patches
        result = [patches[0]]
        for p in patches[1:]:
            prev = result[-1]
            if prev.target_id == p.target_id and prev.op == p.op and prev.author == p.author:
                mv = dict(prev.value); mv.update(p.value)
                result[-1] = Patch(
                    id=prev.id, target_id=prev.target_id, op=prev.op, value=mv,
                    timestamp=prev.timestamp, author=prev.author,
                    confidence=max(prev.confidence, p.confidence),
                    reason=(prev.reason or []) + (p.reason or []),
                )
            else:
                result.append(p)
        return result

    def _keep_latest(self, patches: list[Patch]) -> list[Patch]:
        latest: dict[str, Patch] = {}
        for p in sorted(patches, key=lambda x: x.timestamp):
            latest[p.target_id] = p
        return list(latest.values())

    def _keep_checkpoints(self, patches: list[Patch]) -> list[Patch]:
        key = {OpCode.SEGMENT_INSERT, OpCode.SEGMENT_SPLIT, OpCode.SEGMENT_MERGE,
               OpCode.ASSIGN_SPEAKER, OpCode.MERGE_SPEAKERS}
        result = []
        for p in patches:
            if p.op in key or p.author == "user":
                result.append(p)
            elif result and result[-1].target_id == p.target_id:
                result[-1] = p
            else:
                result.append(p)
        return result

    def get_history(self, segment_id: str) -> list[Patch]:
        return [p for p in self.hot if p.target_id == segment_id]
