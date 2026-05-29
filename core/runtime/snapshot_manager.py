"""SnapshotManager — auto-snapshot + crash recovery (定稿 §12.5)."""
from __future__ import annotations
import json, os, time
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from core.runtime.project_state import TimelineProjectState
    from core.runtime.patch import Patch

DEFAULT_INTERVAL = 50

class SnapshotManager:
    def __init__(self, snapshot_dir="", auto_interval=DEFAULT_INTERVAL):
        if not snapshot_dir:
            snapshot_dir = ".snapshots"
        self._dir = snapshot_dir; self._interval = auto_interval
        self._count = 0; self._last_snap = 0
        os.makedirs(snapshot_dir, exist_ok=True)

    def on_patch_applied(self, state, patch):
        self._count += 1
        if self._count - self._last_snap >= self._interval:
            self.create_snapshot(state); return True
        return False

    def create_snapshot(self, state, label=""):
        idx = self._count; ts = time.strftime("%Y%m%d_%H%M%S")
        name = label or "snap_%s_%04d" % (ts, idx)
        path = os.path.join(self._dir, "%s.json" % name)
        data = {"label": name, "timestamp": time.time(), "patch_index": idx,
                "events": {}, "speakers": {}}
        for eid, es in state.event_states.items():
            data["events"][eid] = {"id": es.id, "derivatives": dict(es.derivatives)}
        for sid, spk in state.ir.speakers.items():
            data["speakers"][sid] = {"id": spk.id, "name": spk.name, "config": spk.config}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        self._last_snap = idx; return path

    def restore_from_latest(self, state):
        snaps = sorted([f for f in os.listdir(self._dir) if f.endswith(".json")]) if os.path.exists(self._dir) else []
        if not snaps: return -1
        with open(os.path.join(self._dir, snaps[-1]), "r", encoding="utf-8") as f:
            data = json.load(f)
        for eid, edata in data.get("events", {}).items():
            es = state.get_event(eid)
            if es and "derivatives" in edata:
                es.derivatives.clear(); es.derivatives.update(edata["derivatives"])
        return data.get("patch_index", 0)

def generate_undo_patch(original, previous_state):
    from core.runtime.patch import Patch, OpCode
    slot = original.value.get("slot", "")
    if original.op == OpCode.OVERRIDE_CONFIG:
        return Patch(id="undo_%s" % original.id, target_id=original.target_id, op=OpCode.OVERRIDE_CONFIG, value={"slot": slot, "partial_config": previous_state}, author="undo")
    elif original.op == OpCode.SET_CONFIG:
        return Patch(id="undo_%s" % original.id, target_id=original.target_id, op=OpCode.SET_CONFIG, value={"slot": slot, "config_block": previous_state.get("_full_config", {})}, author="undo")
    elif original.op == OpCode.RESET_CONFIG:
        if "_full_config" in previous_state:
            return Patch(id="undo_%s" % original.id, target_id=original.target_id, op=OpCode.SET_CONFIG, value={"slot": slot, "config_block": previous_state["_full_config"]}, author="undo")
        return Patch(id="undo_%s" % original.id, target_id=original.target_id, op=OpCode.OVERRIDE_CONFIG, value={"slot": slot, "partial_config": previous_state}, author="undo")
    raise ValueError("Unsupported op: %s" % original.op)
