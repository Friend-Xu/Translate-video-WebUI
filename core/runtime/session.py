"""
Runtime Session — 工作区会话生命周期管理 (计划书 §2 + §3)

SessionState 枚举定义一次视频处理从创建到完成/失败的全部状态。
SessionStore 是 workspace 中 session.json 的读写入口。

v2: 新增 StageProgress 步骤追踪 + 崩溃恢复。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import json as _json
import time


class SessionState(str, Enum):
    DRAFT = "draft"
    BOOTSTRAPPING = "bootstrapping"
    REVIEWABLE = "reviewable"
    VALIDATED = "validated"
    EXPORTING = "exporting"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class StageProgress:
    """单个步骤的进度追踪。"""
    status: str = "pending"  # "pending" | "running" | "completed" | "failed"
    started_at: float = 0.0
    completed_at: float = 0.0
    events_count: int = 0

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "events_count": self.events_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "StageProgress":
        return cls(
            status=d.get("status", "pending"),
            started_at=d.get("started_at", 0.0),
            completed_at=d.get("completed_at", 0.0),
            events_count=d.get("events_count", 0),
        )


@dataclass
class SessionEnvelope:
    workspace_id: str
    video_path: str = ""
    session_state: SessionState = SessionState.DRAFT
    current_stage: str = ""
    checkpoint_id: str = ""
    patch_head: str = ""
    validation_status: str = ""
    export_status: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    stages: dict[str, StageProgress] = field(default_factory=dict)


class SessionStore:
    FILENAME = "session.json"

    @classmethod
    def path(cls, workspace_dir: str) -> Path:
        return Path(workspace_dir) / cls.FILENAME

    @classmethod
    def load(cls, workspace_dir: str) -> SessionEnvelope | None:
        p = cls.path(workspace_dir)
        if not p.is_file():
            return None
        try:
            data = _json.loads(p.read_text(encoding="utf-8"))
            stages_raw = data.get("stages", {})
            return SessionEnvelope(
                workspace_id=data.get("workspace_id", ""),
                video_path=data.get("video_path", ""),
                session_state=SessionState(data.get("session_state", "draft")),
                current_stage=data.get("current_stage", ""),
                checkpoint_id=data.get("checkpoint_id", ""),
                patch_head=data.get("patch_head", ""),
                validation_status=data.get("validation_status", ""),
                export_status=data.get("export_status", ""),
                created_at=data.get("created_at", time.time()),
                updated_at=data.get("updated_at", time.time()),
                stages={k: StageProgress.from_dict(v) for k, v in stages_raw.items()},
            )
        except Exception:
            return None

    @classmethod
    def save(cls, workspace_dir: str, envelope: SessionEnvelope) -> None:
        p = cls.path(workspace_dir)
        p.parent.mkdir(parents=True, exist_ok=True)
        envelope.updated_at = time.time()
        p.write_text(_json.dumps({
            "workspace_id": envelope.workspace_id,
            "video_path": envelope.video_path,
            "session_state": envelope.session_state.value,
            "current_stage": envelope.current_stage,
            "checkpoint_id": envelope.checkpoint_id,
            "patch_head": envelope.patch_head,
            "validation_status": envelope.validation_status,
            "export_status": envelope.export_status,
            "stages": {k: v.as_dict() for k, v in envelope.stages.items()},
            "created_at": envelope.created_at,
            "updated_at": envelope.updated_at,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def transition(cls, workspace_dir: str, new_state: SessionState) -> SessionEnvelope:
        env = cls.load(workspace_dir)
        if env is None:
            ws_id = Path(workspace_dir).name
            env = SessionEnvelope(workspace_id=ws_id, session_state=new_state)
        env.session_state = new_state
        env.updated_at = time.time()
        cls.save(workspace_dir, env)
        return env

    # ── 步骤追踪 ────────────────────────────────────────

    @classmethod
    def mark_stage_started(cls, workspace_dir: str, stage: str) -> None:
        env = cls.load(workspace_dir)
        if env is None:
            env = SessionEnvelope(workspace_id=Path(workspace_dir).name)
        env.stages[stage] = StageProgress(status="running", started_at=time.time())
        cls.save(workspace_dir, env)

    @classmethod
    def mark_stage_completed(cls, workspace_dir: str, stage: str,
                             events_count: int = 0) -> None:
        env = cls.load(workspace_dir)
        if env is None:
            return
        env.stages[stage] = StageProgress(
            status="completed",
            started_at=env.stages.get(stage, StageProgress()).started_at,
            completed_at=time.time(),
            events_count=events_count,
        )
        cls.save(workspace_dir, env)

    @classmethod
    def mark_stage_failed(cls, workspace_dir: str, stage: str) -> None:
        env = cls.load(workspace_dir)
        if env is None:
            return
        env.stages[stage] = StageProgress(
            status="failed",
            started_at=env.stages.get(stage, StageProgress()).started_at,
            completed_at=time.time(),
        )
        cls.save(workspace_dir, env)

    @classmethod
    def is_stage_done(cls, workspace_dir: str, stage: str) -> bool:
        env = cls.load(workspace_dir)
        if env is None:
            return False
        return env.stages.get(stage, StageProgress()).status == "completed"

    @classmethod
    def recover_crashed_stage(cls, workspace_dir: str) -> str | None:
        """检测崩溃的 running 状态步骤，返回需要重跑的 stage 名。"""
        env = cls.load(workspace_dir)
        if env is None:
            return None
        for name, prog in env.stages.items():
            if prog.status == "running":
                return name
        return None
