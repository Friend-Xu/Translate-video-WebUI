"""
Runtime Structured Logging (CLI Runtime 计划书 §11)

JSON Lines 格式结构化日志，携带 trace_id / workspace_id。
CLI 和 WebUI 共享同一日志基础设施。

设计原则:
  - 不引入外部日志框架，只做最小扩展
  - JSON Lines 格式，一行一条
  - trace_id 贯穿一次完整执行
"""
from __future__ import annotations
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class RuntimeLog:
    """单条结构化日志。"""
    timestamp: str = ""
    trace_id: str = ""
    workspace_id: str = ""
    stage: str = ""
    event: str = ""           # stage_started / pass_completed / adapter_error
    duration_ms: float = 0.0
    message: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class StructuredLogger:
    """结构化日志器 — JSON Lines 输出到 stdout。

    Usage:
        slog = StructuredLogger(workspace_id="project_001")
        slog.stage_started("extract", "开始字幕提取")
        slog.pass_completed("asr_composite", duration_ms=1234, payload={"events": 152})
        slog.adapter_error("whisper", "CUDA OOM", {"vram_free": "500MB"})
    """

    def __init__(self, workspace_id: str = "", json_mode: bool = False):
        self.workspace_id = workspace_id
        self.json_mode = json_mode
        self._trace_id = uuid.uuid4().hex[:12]
        self._stage_timers: dict[str, float] = {}

    @property
    def trace_id(self) -> str:
        return self._trace_id

    def _emit(self, event: str, stage: str = "", message: str = "",
              duration_ms: float = 0.0, payload: dict | None = None) -> None:
        entry = RuntimeLog(
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
            trace_id=self._trace_id,
            workspace_id=self.workspace_id,
            stage=stage,
            event=event,
            duration_ms=round(duration_ms, 1),
            message=message,
            payload=payload or {},
        )
        if self.json_mode:
            print(entry.to_json(), flush=True)
        else:
            prefix = f"[{entry.stage}]" if entry.stage else "[core]"
            print(f"{prefix} {message}")

    def stage_started(self, stage: str, message: str = "") -> None:
        self._stage_timers[stage] = time.time()
        self._emit("stage_started", stage=stage, message=message)

    def stage_completed(self, stage: str, message: str = "", payload: dict | None = None) -> None:
        start = self._stage_timers.pop(stage, time.time())
        self._emit("stage_completed", stage=stage, message=message,
                   duration_ms=(time.time() - start) * 1000, payload=payload)

    def stage_failed(self, stage: str, message: str = "", payload: dict | None = None) -> None:
        start = self._stage_timers.pop(stage, time.time())
        self._emit("stage_failed", stage=stage, message=message,
                   duration_ms=(time.time() - start) * 1000, payload=payload)

    def pass_completed(self, pass_name: str, stage: str = "",
                       duration_ms: float = 0.0, payload: dict | None = None) -> None:
        self._emit("pass_completed", stage=stage, message=pass_name,
                   duration_ms=duration_ms, payload=payload)

    def adapter_error(self, adapter_id: str, error: str,
                      error_type: str = "", payload: dict | None = None) -> None:
        p = payload or {}
        p["error_type"] = error_type
        self._emit("adapter_error", stage=adapter_id, message=error, payload=p)

    def info(self, message: str, stage: str = "") -> None:
        self._emit("info", stage=stage, message=message)

    def warn(self, message: str, stage: str = "") -> None:
        self._emit("warn", stage=stage, message=message)
