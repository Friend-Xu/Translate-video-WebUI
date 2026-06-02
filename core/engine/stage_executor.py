"""
StageExecutor — 单阶段执行器 (定稿 §17.2)

每个 WorkflowStage 对应一个 StageExecutor 实例。
管理该阶段的 PassManager 生命周期、配置注入、进度追踪和错误处理。

设计原则:
  - 阶段原子性: 完整执行产出有效 state，或失败留下可诊断错误
  - 配置注入: Pass.apply() 前通过 ConfigResolver 解析每事件配置
  - 进度透明: 每 Pass 执行前后发出 ProgressReport
"""
from __future__ import annotations
import time
from typing import Callable

from core.engine.pass_base import TimelinePass
from core.engine.pass_manager import PassManager
from core.engine.progress import (
    ProgressEventType, ProgressReport, StageProgress,
)
from core.config.workflow_policy import StageConfig, WorkflowStage
from core.runtime.project_state import TimelineProjectState
from core.runtime.config_resolver import ConfigResolver
from core.engine.event_bus import EventBus
from core.engine.runtime_event import RuntimeEvent, RuntimeEventType as RET


class StageExecutor:
    """单阶段执行器 — 管理一个 WorkflowStage 的完整生命周期。

    Usage:
        executor = StageExecutor(stage_config, pass_factory)
        executor.set_progress_callback(lambda r: print(r.message))
        state = executor.execute(state, config_resolver)
    """

    def __init__(
        self,
        config: StageConfig,
        pass_factory: Callable[[str], TimelinePass | None],
    ):
        self._config = config
        self._pass_factory = pass_factory
        self._progress = StageProgress(stage=config.stage.value)
        self._on_progress: Callable[[ProgressReport], None] | None = None

    @property
    def stage(self) -> WorkflowStage:
        return self._config.stage

    @property
    def stage_progress(self) -> StageProgress:
        return self._progress

    def set_progress_callback(self, cb: Callable[[ProgressReport], None]) -> None:
        self._on_progress = cb

    def execute(
        self,
        state: TimelineProjectState,
        config_resolver: ConfigResolver | None = None,
    ) -> TimelineProjectState:
        """执行本阶段所有 Pass，返回更新后的 state。

        Raises:
            RuntimeError: 阶段执行失败
        """
        self._progress.started_at = time.time()
        self._emit(ProgressEventType.STAGE_STARTED, "开始执行")

        try:
            pm = PassManager()
            registered = 0
            for pass_name in self._config.passes:
                p = self._pass_factory(pass_name)
                if p is not None:
                    pm.register(p)
                    registered += 1

            if registered == 0:
                self._emit(
                    ProgressEventType.STAGE_COMPLETED,
                    "无 Pass（已跳过）",
                )
                self._progress.completed_at = time.time()
                return state

            self._progress.total = registered
            self._progress.current = 0

            if config_resolver is not None:
                pm.set_config_resolver(config_resolver)

            state, diffs = pm.run_with_diff(state)

            for i, diff in enumerate(diffs):
                self._progress.advance()
                self._emit(
                    ProgressEventType.STAGE_PROGRESS,
                    f"完成: {diff['pass']} ({diff['events_before']}→{diff['events_after']} events)",
                    total=registered,
                    current=i + 1,
                    payload=diff,
                )
                # For translate/tts stages: emit item-level progress
                if self._config.stage.value in ("translate", "tts"):
                    total_items = diff.get("events_after", 0)
                    if total_items > 0:
                        for ei in range(total_items):
                            self._emit(
                                ProgressEventType.STAGE_PROGRESS,
                                f"{diff['pass']}: event {ei + 1}/{total_items}",
                                total=total_items,
                                current=ei + 1,
                                payload={"pass": diff["pass"], "item": ei + 1, "total": total_items},
                            )

            self._progress.completed_at = time.time()
            elapsed = self._progress.elapsed
            self._emit(
                ProgressEventType.STAGE_COMPLETED,
                f"阶段完成 ({len(state.event_states)} 事件, {elapsed:.1f}s)",
                total=registered,
                current=registered,
                payload={"elapsed": elapsed, "event_count": len(state.event_states)},
            )
            return state

        except Exception as exc:
            self._progress.completed_at = time.time()
            self._emit(
                ProgressEventType.STAGE_FAILED,
                f"阶段失败: {exc}",
                payload={"error": str(exc), "error_type": type(exc).__name__},
            )
            raise RuntimeError(
                f"Stage '{self._config.stage.value}' failed: {exc}"
            ) from exc

    def _emit(
        self,
        event_type: ProgressEventType,
        message: str,
        total: int = 0,
        current: int = 0,
        payload: dict | None = None,
    ) -> None:
        # 向后兼容：旧的 ProgressReport 回调
        if self._on_progress is not None:
            self._on_progress(ProgressReport(
                event_type=event_type,
                stage=self._config.stage.value,
                stage_label=self._config.stage.display_name,
                total_items=total,
                current_item=current,
                message=message,
                payload=payload or {},
            ))
        # EventBus — 统一事件流
        _type_map = {
            ProgressEventType.STAGE_STARTED: RET.STAGE_STARTED,
            ProgressEventType.STAGE_PROGRESS: RET.STAGE_PROGRESS,
            ProgressEventType.STAGE_COMPLETED: RET.STAGE_COMPLETED,
            ProgressEventType.STAGE_FAILED: RET.ERROR,
        }
        re_type = _type_map.get(event_type, RET.LOG)
        EventBus().emit_now(RuntimeEvent(
            event_type=re_type,
            stage=self._config.stage.value,
            stage_label=self._config.stage.display_name,
            node=payload.get("pass", "") if payload else "",
            message=message,
            total_items=total,
            current_item=current,
            payload=payload or {},
        ))
