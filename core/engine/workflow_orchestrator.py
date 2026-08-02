"""
WorkflowOrchestrator — 工作流编排器 (定稿 §17, 批次 A 核心交付件)

将 Pass 原子编排为完整生产管线: LOAD → EXTRACT → TRANSLATE → TTS → EXPORT。
实现 Gate 条件分支（A→继续, B→暂停, C→重试）、进度回调、暂停/恢复。

这是从"能力原子堆叠"到"可运行工作流"的关键桥梁。
"""
from __future__ import annotations
import time
from typing import Callable
from enum import Enum

from core.engine.pass_base import TimelinePass
from core.engine.stage_executor import StageExecutor
from core.engine.progress import (
    ProgressEventType, ProgressReport, StageProgress,
)
from core.config.workflow_policy import (
    WorkflowPolicy, WorkflowStage, StageConfig,
)
from core.config.global_config import GlobalConfig
from core.runtime.project_state import TimelineProjectState
from core.runtime.config_resolver import ConfigResolver
from core.ir.project import TimelineProjectIR
from core.engine.event_bus import EventBus
from core.engine.runtime_event import RuntimeEvent, RuntimeEventType as RET


class WorkflowStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowOrchestrator:
    """工作流编排器 — 将 Stage 串联为完整生产线。

    生命周期:
      orchestrator = WorkflowOrchestrator(policy)
      orchestrator.on_progress = my_handler
      state = orchestrator.run(video_path)

      orchestrator.pause()                 # 暂停（Gate B 级）
      orchestrator.resume(decisions)       # 恢复（携带审核决策）

    Gate 路由逻辑（定稿 §14.3, §15.4）:
      TextGate:  A→auto_advance, B→pause, C→retry
      EmotionGate: E1→continue, E2→continue(降级), E3→pause
    """

    def __init__(
        self,
        policy: WorkflowPolicy,
        global_config: GlobalConfig | None = None,
        pass_factory: Callable[[str], TimelinePass | None] | None = None,
    ):
        self._policy = policy
        self._global_config = global_config or GlobalConfig()
        self._pass_factory = pass_factory or (lambda _: None)
        self._status = WorkflowStatus.IDLE
        self._current_stage: WorkflowStage | None = None
        self._state: TimelineProjectState | None = None
        self._stage_executors: dict[WorkflowStage, StageExecutor] = {}
        self._stage_progress: dict[str, StageProgress] = {}
        self._on_progress: Callable[[ProgressReport], None] | None = None
        self._pending_review: list[str] = []
        self._retry_count: int = 0   # Gate C 重试计数 (执行期状态, run/resume 重置)
        self._video_path: str = ""
        self._started_at: float = 0.0
        self._completed_at: float = 0.0

    @property
    def status(self) -> WorkflowStatus:
        return self._status

    @property
    def current_stage(self) -> WorkflowStage | None:
        return self._current_stage

    @property
    def state(self) -> TimelineProjectState | None:
        return self._state

    @property
    def pending_review(self) -> list[str]:
        return list(self._pending_review)

    @property
    def retry_count(self) -> int:
        return self._retry_count

    @property
    def elapsed(self) -> float:
        if self._started_at == 0:
            return 0.0
        end = self._completed_at or time.time()
        return end - self._started_at

    def set_progress_callback(self, cb: Callable[[ProgressReport], None]) -> None:
        self._on_progress = cb

    def set_pass_factory(self, factory: Callable[[str], TimelinePass | None]) -> None:
        """设置 Pass 工厂 — 将 Pass 名称映射为实例。

        外部（tvw.py 或 GUI/server.py）负责理解 Pass 名称
        并返回配置好的实例。这保持核心引擎的依赖反转。
        """
        self._pass_factory = factory

    # ── 主要 API ──────────────────────────────────────────────

    def run(self, video_path: str) -> TimelineProjectState:
        """同步执行完整工作流（阻塞直到完成或暂停）。"""
        self._video_path = video_path
        self._status = WorkflowStatus.RUNNING
        self._started_at = time.time()
        self._pending_review = []
        self._retry_count = 0

        self._emit_workflow("开始执行工作流", {"video": video_path})
        EventBus().emit_now(RuntimeEvent(
            event_type=RET.WORKFLOW_STARTED,
            payload={"video": video_path},
        ))

        try:
            # 尝试从 workspace 加载已有 timeline 状态（用于 dub-after-review / export 等续跑场景）
            # 数据结构重设计 Phase 2: 统一走 timeline_io.load_state, 全字段回填
            # (translation/words/speaker), 修复 reload 丢译文导致 export 产出英文的 bug。
            import os as _os
            from core.runtime.timeline_io import load_state
            ws = _os.path.join(_os.path.dirname(video_path),
                               _os.path.basename(video_path).rsplit(".", 1)[0] + "_project")
            tl_path = _os.path.join(ws, "01_extract", "timeline.json")
            state = None
            if _os.path.isfile(tl_path):
                try:
                    # 禁止兜底: 文件损坏/缺字段时 load_state 显式 raise,
                    # 由外层 except 标记 FAILED, 不再 except:pass 静默产出错误输出。
                    state = load_state(tl_path)
                except ValueError as e:
                    # v1 提取格式 (timeline.ir) 无译文可复用: 显式跳过加载,
                    # 由注入的 ASR 产物 (segments) 重建事件 (CLI 翻译路径)。
                    self._emit_workflow(
                        f"跳过 v1 timeline 加载: {e}",
                        {"reason": "v1_format", "path": tl_path},
                    )
                    state = None

            if state is not None:
                self._state = state
            else:
                empty_ir = TimelineProjectIR(events={}, speakers={})
                self._state = TimelineProjectState(empty_ir)
            stage_order = self._policy.stage_order()
            idx = 0
            while idx < len(stage_order):
                stage = stage_order[idx]
                stage_config = self._policy.get_stage(stage)
                if stage_config is None:
                    idx += 1
                    continue

                self._current_stage = stage
                executor = self._get_executor(stage_config)
                executor.set_progress_callback(self._on_stage_progress)
                self._state = executor.execute(self._state, self._get_resolver())

                route = self._evaluate_gate(stage_config, self._state)
                if route == "pause":
                    self._status = WorkflowStatus.PAUSED
                    self._emit_workflow(
                        f"工作流暂停于 {stage_config.stage.display_name}",
                        {"reason": "gate_pause", "pending_review": self._pending_review},
                    )
                    return self._state
                elif route == "retry":
                    if self._handle_retry(stage_config) == "pause":
                        self._emit_workflow(
                            f"工作流暂停于 {stage_config.stage.display_name}",
                            {"reason": "retry_exhausted", "retry_count": self._retry_count},
                        )
                        return self._state
                    # 未超限: 重跑当前 stage (idx 不变)
                    continue
                idx += 1

            self._status = WorkflowStatus.COMPLETED
            self._completed_at = time.time()
            self._emit_workflow(
                f"工作流完成 (总耗时 {self.elapsed:.1f}s)",
                {"total_events": len(self._state.event_states)},
            )
            return self._state

        except Exception as exc:
            self._status = WorkflowStatus.FAILED
            self._completed_at = time.time()
            self._emit_workflow(
                f"工作流失败: {exc}",
                {"error": str(exc)},
                event_type=ProgressEventType.WORKFLOW_FAILED,
            )
            raise RuntimeError(
                f"Workflow failed at stage '{self._current_stage}': {exc}"
            ) from exc

    def resume(self, decisions: dict[str, str]) -> TimelineProjectState:
        """从暂停状态恢复。

        Args:
            decisions: {event_id: "accept" | "reject" | "retry"}
        """
        if self._status != WorkflowStatus.PAUSED:
            raise RuntimeError("只能在 PAUSED 状态调用 resume()")
        if self._state is None or self._current_stage is None:
            raise RuntimeError("无可用状态")

        self._status = WorkflowStatus.RUNNING
        self._retry_count = 0  # 用户介入后重新计数
        self._emit_workflow("恢复执行", {"decisions": decisions})

        for event_id, decision in decisions.items():
            event = self._state.get_event(event_id)
            if event is not None:
                event.review.gate_decision = decision
                if decision == "reject":
                    event.review.flags = event.review.flags + ["rejected"]
                    self._pending_review.remove(event_id)

        remaining = [
            s for s in self._policy.stage_order()
            if s.index >= self._current_stage.index
        ]
        try:
            idx = 0
            while idx < len(remaining):
                stage = remaining[idx]
                stage_config = self._policy.get_stage(stage)
                if stage_config is None:
                    idx += 1
                    continue
                self._current_stage = stage
                executor = self._get_executor(stage_config)
                executor.set_progress_callback(self._on_stage_progress)
                self._state = executor.execute(self._state, self._get_resolver())

                route = self._evaluate_gate(stage_config, self._state)
                if route == "pause":
                    self._status = WorkflowStatus.PAUSED
                    return self._state
                elif route == "retry":
                    if self._handle_retry(stage_config) == "pause":
                        self._status = WorkflowStatus.PAUSED
                        return self._state
                    continue  # 重跑当前 stage
                idx += 1

            self._status = WorkflowStatus.COMPLETED
            self._completed_at = time.time()
            return self._state

        except Exception as exc:
            self._status = WorkflowStatus.FAILED
            self._completed_at = time.time()
            raise

    def pause(self) -> None:
        if self._status == WorkflowStatus.RUNNING:
            self._status = WorkflowStatus.PAUSED
            self._emit_workflow("收到暂停请求")

    def cancel(self) -> None:
        self._status = WorkflowStatus.CANCELLED
        self._completed_at = time.time()
        self._emit_workflow("工作流已取消")

    # ── 内部方法 ──────────────────────────────────────────────

    def _get_executor(self, config: StageConfig) -> StageExecutor:
        if config.stage not in self._stage_executors:
            self._stage_executors[config.stage] = StageExecutor(
                config, self._pass_factory,
            )
        return self._stage_executors[config.stage]

    def _get_resolver(self) -> ConfigResolver | None:
        if self._global_config is not None:
            return ConfigResolver(self._global_config)
        return None

    def _evaluate_gate(
        self, stage_config: StageConfig, state: TimelineProjectState,
    ) -> str:
        """评估 Gate 结果并返回路由指令。

        读取源按 gate 类型区分 (Phase1 跨域修复):
          text_gate/validate_gate → review 槽 (A/B/C)
          emotion_gate            → emotion 槽 (E1/E2/E3)
        旧实现一律读 review.gate_decision, emotion pass 写 E1/E2/E3 到同键
        覆盖文本门控结果; 且 routing 的 E3 key 永远匹配不到 (检查只认 C/B)。

        Returns: "continue" | "pause" | "retry" (routing 中的动作值)
        """
        if not stage_config.gate:
            return "continue"

        routing = stage_config.gate_routing or {}
        gate = stage_config.gate
        any_b = False
        any_c = False

        for es in state.event_states.values():
            if gate == "emotion_gate":
                gate_result = es.emotion.gate_decision
            else:
                gate_result = es.review.gate_decision

            if gate_result in ("C", "E3"):
                any_c = True
                es.review.needs_human_review = True
            elif gate_result in ("B", "E2"):
                any_b = True
                es.review.needs_human_review = True
                if es.id not in self._pending_review:
                    self._pending_review.append(es.id)

        if any_c:
            for key in ("C", "E3"):
                if key in routing:
                    return routing[key]
        if any_b:
            for key in ("B", "E2"):
                if key in routing:
                    return routing[key]
        return routing.get("A", "continue")

    def _handle_retry(self, stage_config: StageConfig) -> str:
        """Gate C 重试 — 计数在 orchestrator 实例上 (执行期状态, run/resume 重置)。

        修复: 旧实现读 state.global_config (恒 None) 且 isinstance(gc, dict)
        对 GlobalConfig 实例恒 False → retry_count 恒 0 → 无限重试。
        返回 "retry" (未超限, 调用方重跑当前 stage) 或 "pause" (超限, 需人工)。
        """
        if self._retry_count < stage_config.max_retries:
            self._retry_count += 1
            self._emit_workflow(
                f"触发重试 ({self._retry_count}/{stage_config.max_retries})",
                {"retry_count": self._retry_count},
            )
            return "retry"
        self._emit_workflow("超过最大重试次数，标记为需人工审核")
        self._status = WorkflowStatus.PAUSED
        return "pause"

    def _on_stage_progress(self, report: ProgressReport) -> None:
        self._stage_progress[report.stage] = StageProgress(
            stage=report.stage,
            total=report.total_items,
            current=report.current_item,
        )
        if self._on_progress:
            self._on_progress(report)

    def _emit_workflow(
        self,
        message: str,
        payload: dict | None = None,
        event_type: ProgressEventType = ProgressEventType.STAGE_COMPLETED,
    ) -> None:
        # 向后兼容：旧的 ProgressReport 回调
        if self._on_progress is not None:
            stage = self._current_stage.value if self._current_stage else ""
            label = self._current_stage.display_name if self._current_stage else ""
            self._on_progress(ProgressReport(
                event_type=event_type,
                stage=stage,
                stage_label=label,
                message=message,
                payload=payload or {},
            ))
        # EventBus — 统一事件流
        _type_map: dict[ProgressEventType, RET] = {
            ProgressEventType.WORKFLOW_FAILED: RET.WORKFLOW_FAILED,
            ProgressEventType.WORKFLOW_CANCELLED: RET.WORKFLOW_CANCELLED,
        }
        re_type = _type_map.get(event_type, RET.STAGE_COMPLETED)
        stage_val = self._current_stage.value if self._current_stage else ""
        stage_lbl = self._current_stage.display_name if self._current_stage else ""
        EventBus().emit_now(RuntimeEvent(
            event_type=re_type,
            stage=stage_val,
            stage_label=stage_lbl,
            message=message,
            payload=payload or {},
        ))
