"""
Unified checkpoint/resume manager for Translate_video pipeline.

Design borrows from proven patterns:
  - fairseq:       state_dict() canonical serialization + extra_state for resume data
  - Bazel/Skyframe: content-hash change detection (not timestamps)
  - Dagster:        verify_files() scans disk for actual completed outputs
  - Airflow AIP-96: distinguish INFRASTRUCTURE vs USER vs APPLICATION failures
  - Atomic writes:  tempfile + flush + fsync + os.replace

Always active — no opt-in flag needed.  Backward compatible: absent
checkpoint falls back to file-existence checks (existing behaviour).
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = 1


def _now_iso() -> str:
    return datetime.datetime.now().isoformat()


def _file_sha256(path: str) -> str:
    if not os.path.isfile(path):
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _video_fingerprint(video_path: str) -> str:
    """SHA-256 of first 1 MiB + last 1 MiB + file size (fast change detection)."""
    if not os.path.isfile(video_path):
        return ""
    size = os.path.getsize(video_path)
    h = hashlib.sha256()
    with open(video_path, "rb") as f:
        h.update(f.read(1 << 20))
        if size > (2 << 20):
            f.seek(-(1 << 20), 2)
            h.update(f.read(1 << 20))
    h.update(str(size).encode())
    return h.hexdigest()


def _params_fingerprint(params: dict) -> str:
    raw = json.dumps(params, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def atomic_write_json(target_path: str, data: dict) -> None:
    target_dir = os.path.dirname(target_path)
    os.makedirs(target_dir, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=target_dir, prefix=".checkpoint.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, target_path)
    except BaseException:
        if os.path.isfile(tmp_name):
            os.remove(tmp_name)
        raise


# ── state records ───────────────────────────────────────────────────


@dataclass
class NodeState:
    status: str = "pending"
    started_at: str = ""
    completed_at: str = ""
    error: str = ""
    output_hashes: dict[str, str] = field(default_factory=dict)


@dataclass
class StepState:
    status: str = "pending"
    started_at: str = ""
    completed_at: str = ""
    error: str = ""
    error_type: str = ""
    input_hashes: dict[str, str] = field(default_factory=dict)
    output_hashes: dict[str, str] = field(default_factory=dict)
    nodes: dict[str, NodeState] = field(default_factory=dict)
    extra_state: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "error_type": self.error_type,
            "input_hashes": self.input_hashes,
            "output_hashes": self.output_hashes,
            "nodes": {k: v.__dict__ for k, v in self.nodes.items()},
            "extra_state": self.extra_state,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "StepState":
        nodes = {}
        for k, v in d.get("nodes", {}).items():
            nodes[k] = NodeState(
                status=v.get("status", "pending"),
                started_at=v.get("started_at", ""),
                completed_at=v.get("completed_at", ""),
                error=v.get("error", ""),
                output_hashes=v.get("output_hashes", {}),
            )
        return cls(
            status=d.get("status", "pending"),
            started_at=d.get("started_at", ""),
            completed_at=d.get("completed_at", ""),
            error=d.get("error", ""),
            error_type=d.get("error_type", ""),
            input_hashes=d.get("input_hashes", {}),
            output_hashes=d.get("output_hashes", {}),
            nodes=nodes,
            extra_state=d.get("extra_state", {}),
        )


# ── main checkpoint class ───────────────────────────────────────────


class PipelineCheckpoint:
    """Single source of truth for pipeline resume state.

    Usage::

        ck = PipelineCheckpoint.load(workspace_dir)
        if ck.is_step_done("extract"):
            print("extract already completed, skipping")
        ck.start_step("translate")
        ...
        ck.complete_step("translate", output_hashes={"machine_srt": hash})
        ck.save()
    """

    def __init__(self, path: str):
        self._path = path
        self.version: int = SCHEMA_VERSION
        self.video_path: str = ""
        self.video_hash: str = ""
        self.config_hash: str = ""
        self.created_at: str = _now_iso()
        self.updated_at: str = _now_iso()
        self.steps: dict[str, StepState] = {
            "extract": StepState(),
            "translate": StepState(),
            "tts": StepState(),
        }

    # ── serialization ──────────────────────────────────────────

    def state_dict(self) -> dict:
        return {
            "version": self.version,
            "video_path": self.video_path,
            "video_hash": self.video_hash,
            "config_hash": self.config_hash,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "steps": {k: v.to_dict() for k, v in self.steps.items()},
        }

    def save(self) -> None:
        self.updated_at = _now_iso()
        atomic_write_json(self._path, self.state_dict())

    @classmethod
    def load(cls, workspace_dir: str) -> "PipelineCheckpoint":
        path = os.path.join(workspace_dir, "checkpoint.json")
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                data = {}
            return cls._from_dict(data, path)
        return cls(path)

    @classmethod
    def _from_dict(cls, data: dict, path: str) -> "PipelineCheckpoint":
        ck = cls(path)
        ck.version = data.get("version", 1)
        ck.video_path = data.get("video_path", "")
        ck.video_hash = data.get("video_hash", "")
        ck.config_hash = data.get("config_hash", "")
        ck.created_at = data.get("created_at", _now_iso())
        ck.updated_at = data.get("updated_at", _now_iso())
        steps_data = data.get("steps", {})
        for step_name in ("extract", "translate", "tts"):
            if step_name in steps_data:
                ck.steps[step_name] = StepState.from_dict(steps_data[step_name])
        return ck

    # ── initialisation ─────────────────────────────────────────

    def init_from_video(self, video_path: str, params: dict | None = None) -> None:
        self.video_path = video_path.replace("\\", "/")
        self.video_hash = _video_fingerprint(video_path)
        if params:
            self.config_hash = _params_fingerprint(params)

    def check_video_changed(self, video_path: str) -> bool:
        current = _video_fingerprint(video_path)
        return self.video_hash and current and current != self.video_hash

    # ── per-step helpers ───────────────────────────────────────

    def _get_step(self, name: str) -> StepState:
        return self.steps[name]

    def is_step_done(self, name: str) -> bool:
        return self._get_step(name).status == "completed"

    def is_step_running(self, name: str) -> bool:
        return self._get_step(name).status == "running"

    def start_step(self, name: str, input_hashes: dict[str, str] | None = None,
                   params: dict | None = None) -> None:
        s = self._get_step(name)
        s.status = "running"
        s.started_at = _now_iso()
        s.error = ""
        s.error_type = ""
        if input_hashes:
            s.input_hashes = dict(input_hashes)
        if params and not self.config_hash:
            self.config_hash = _params_fingerprint(params)
        self._invalidate_downstream(name)

    def complete_step(self, name: str,
                      output_hashes: dict[str, str] | None = None) -> None:
        s = self._get_step(name)
        s.status = "completed"
        s.completed_at = _now_iso()
        s.error = ""
        if output_hashes:
            s.output_hashes = dict(output_hashes)

    def fail_step(self, name: str, error: str,
                  error_type: str = "APPLICATION") -> None:
        s = self._get_step(name)
        s.status = "failed"
        s.error = error
        s.error_type = error_type
        if error_type == "APPLICATION":
            s.extra_state = {}
        s.completed_at = ""

    # ── node-level (extract step) ──────────────────────────────

    def start_node(self, node_id: str) -> None:
        s = self.steps["extract"]
        if node_id not in s.nodes:
            s.nodes[node_id] = NodeState()
        n = s.nodes[node_id]
        n.status = "running"
        n.started_at = _now_iso()
        n.error = ""

    def complete_node(self, node_id: str,
                      output_hashes: dict[str, str] | None = None) -> None:
        s = self.steps["extract"]
        if node_id not in s.nodes:
            s.nodes[node_id] = NodeState()
        n = s.nodes[node_id]
        n.status = "completed"
        n.completed_at = _now_iso()
        if output_hashes:
            n.output_hashes = dict(output_hashes)

    def fail_node(self, node_id: str, error: str) -> None:
        s = self.steps["extract"]
        if node_id not in s.nodes:
            s.nodes[node_id] = NodeState()
        n = s.nodes[node_id]
        n.status = "failed"
        n.error = error

    def is_node_done(self, step: str, node_id: str) -> bool:
        s = self._get_step(step)
        return s.nodes.get(node_id, NodeState()).status == "completed"

    # ── extra_state ────────────────────────────────────────────

    def get_extra(self, step: str, key: str, default: Any = None) -> Any:
        return self._get_step(step).extra_state.get(key, default)

    def set_extra(self, step: str, key: str, value: Any) -> None:
        self._get_step(step).extra_state[key] = value

    def update_extra(self, step: str, **kwargs: Any) -> None:
        self._get_step(step).extra_state.update(kwargs)

    # ── disk verification ─────────────────────────────────────

    def verify_files(self, file_map: dict[str, str]) -> list[tuple[str, str, str]]:
        step_outputs: dict[str, dict[str, str]] = {
            "extract": {}, "translate": {}, "tts": {},
        }
        for key, path in file_map.items():
            if key in ("source_srt", "transcript_json", "audio_wav", "vocals_wav",
                        "instrumental_wav", "vad_segments"):
                step_outputs["extract"][key] = path
            elif key in ("machine_srt", "reviewed_srt", "translate_log"):
                step_outputs["translate"][key] = path
            elif key in ("dubbed_mp4",):
                step_outputs["tts"][key] = path

        issues: list[tuple[str, str, str]] = []
        for step_name, outputs in step_outputs.items():
            s = self._get_step(step_name)
            if s.status != "completed":
                continue
            for fkey, fpath in outputs.items():
                if not fpath:
                    continue
                current = _file_sha256(fpath)
                recorded = s.output_hashes.get(fkey, "")
                if not current:
                    issues.append((step_name, fkey, "missing"))
                    s.status = "failed"
                    s.error = f"output file missing: {fkey}"
                elif recorded and current != recorded:
                    issues.append((step_name, fkey, "hash_mismatch"))
                    s.status = "failed"
                    s.error = f"output hash mismatch: {fkey}"
        return issues

    @staticmethod
    def clean_tmp_files(directory: str) -> int:
        import glob
        removed = 0
        for pattern in ("*.tmp", ".*.tmp"):
            for f in glob.glob(os.path.join(directory, pattern)):
                try:
                    os.remove(f)
                    removed += 1
                except OSError:
                    pass
        return removed

    # ── progress ───────────────────────────────────────────────

    def progress(self) -> dict[str, Any]:
        total_nodes = 0
        done_nodes = 0
        current = "idle"
        detail = ""

        step_order = ("extract", "translate", "tts")
        for name in step_order:
            s = self._get_step(name)
            if s.status == "completed":
                total_nodes += 1
                done_nodes += 1
                continue
            if s.status == "running":
                current = name
                if s.nodes:
                    total_nodes += len(s.nodes)
                    for n in s.nodes.values():
                        if n.status == "completed":
                            done_nodes += 1
                        elif n.status == "running":
                            detail = f"{name}/{n.status}"
                groups_done = s.extra_state.get("groups_done", 0)
                groups_total = s.extra_state.get("groups_total", 1)
                if groups_total > 0:
                    total_nodes += groups_total
                    done_nodes += groups_done
                    detail = f"translation {groups_done}/{groups_total} groups"
                segs_done = s.extra_state.get("segs_done", 0)
                segs_total = s.extra_state.get("segs_total", 1)
                if segs_total > 0 and not detail:
                    total_nodes += segs_total
                    done_nodes += segs_done
                    detail = f"TTS {segs_done}/{segs_total} segments"
                break
            break

        if done_nodes == total_nodes and total_nodes > 0:
            current = "completed"

        pct = (done_nodes / max(total_nodes, 1)) * 100
        return {
            "done": done_nodes,
            "total": total_nodes,
            "pct": round(pct, 1),
            "current_step": current,
            "detail": detail,
        }

    # ── crash recovery ─────────────────────────────────────────

    def recover_from_crash(self) -> list[str]:
        retry_steps: list[str] = []
        for name, s in self.steps.items():
            if s.status == "running":
                s.status = "failed"
                s.error = "previous run interrupted (crash or kill)"
                s.error_type = "INFRASTRUCTURE"
                s.completed_at = ""
                retry_steps.append(name)
        return retry_steps

    # ── internal ───────────────────────────────────────────────

    def _invalidate_downstream(self, from_step: str) -> None:
        step_order = ("extract", "translate", "tts")
        clear = False
        for name in step_order:
            if clear:
                s = self._get_step(name)
                s.status = "pending"
                s.started_at = ""
                s.completed_at = ""
                s.error = ""
                s.error_type = ""
                s.input_hashes = {}
                s.output_hashes = {}
                s.nodes = {}
                s.extra_state = {}
            if name == from_step:
                clear = True
