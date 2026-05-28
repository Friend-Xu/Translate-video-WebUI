"""批次12 §3.4: WorkflowOrchestrator 集成测试。

覆盖: 5 阶段编排, Gate B 暂停 + resume, Gate C 重试, 生命周期
"""
import pytest
from core.engine.workflow_orchestrator import (
    WorkflowOrchestrator, WorkflowStatus,
)
from core.engine.pass_base import TimelinePass
from core.engine.progress import ProgressReport, ProgressEventType
from core.config.workflow_policy import (
    WorkflowPolicy, WorkflowStage, StageConfig,
)
from core.config.global_config import GlobalConfig
from core.runtime.project_state import TimelineProjectState
from core.runtime.event_state import TimelineEventState
from core.ir import TimelineEventIR, TimelineProjectIR


class NoopPass(TimelinePass):
    """Mock Pass: 不做任何修改。"""
    name = "noop"
    call_count = 0

    def apply(self, state, resolver=None):
        NoopPass.call_count += 1
        return state


class GateBPass(TimelinePass):
    """Mock Pass: 给所有 event 注入 Gate B 判定。"""
    name = "gate_b_injector"

    def apply(self, state, resolver=None):
        for es in state.event_states.values():
            es.provenance["gate_decision"] = "B"
        return state


class GateCPass(TimelinePass):
    """Mock Pass: 给所有 event 注入 Gate C 判定。"""
    name = "gate_c_injector"

    def apply(self, state, resolver=None):
        for es in state.event_states.values():
            es.provenance["gate_decision"] = "C"
        return state


def _make_factory(pass_map: dict):
    def factory(name: str):
        return pass_map.get(name)
    return factory


class TestWorkflowOrchestratorLifecycle:

    def test_initial_status_is_idle(self):
        orch = WorkflowOrchestrator(WorkflowPolicy.quick_preset("zh"))
        assert orch.status == WorkflowStatus.IDLE

    def test_set_pass_factory(self):
        orch = WorkflowOrchestrator(WorkflowPolicy.quick_preset("zh"))
        orch.set_pass_factory(_make_factory({"noop": NoopPass()}))
        assert orch._pass_factory is not None

    def test_set_progress_callback(self):
        orch = WorkflowOrchestrator(WorkflowPolicy.quick_preset("zh"))
        reports = []
        orch.set_progress_callback(reports.append)
        orch._emit_workflow("test")
        assert len(reports) == 1
        assert reports[0].message == "test"


class TestWorkflowOrchestratorRun:

    def test_empty_stages_completes(self):
        policy = WorkflowPolicy(name="test", version="1.0")
        policy.stages = {
            WorkflowStage.LOAD: StageConfig(stage=WorkflowStage.LOAD, passes=[]),
        }
        orch = WorkflowOrchestrator(policy)
        orch.set_pass_factory(_make_factory({}))
        state = orch.run("")
        assert orch.status == WorkflowStatus.COMPLETED

    def test_noop_passes_executed(self):
        NoopPass.call_count = 0
        policy = WorkflowPolicy(name="test", version="1.0")
        policy.stages = {
            WorkflowStage.LOAD: StageConfig(
                stage=WorkflowStage.LOAD, passes=["noop", "noop"],
            ),
        }
        orch = WorkflowOrchestrator(policy)
        orch.set_pass_factory(_make_factory({"noop": NoopPass()}))
        orch.run("")
        assert NoopPass.call_count == 2
        assert orch.status == WorkflowStatus.COMPLETED

    def test_progress_callback_fires(self):
        policy = WorkflowPolicy(name="test", version="1.0")
        policy.stages = {
            WorkflowStage.EXPORT: StageConfig(
                stage=WorkflowStage.EXPORT, passes=["noop"],
            ),
        }
        orch = WorkflowOrchestrator(policy)
        orch.set_pass_factory(_make_factory({"noop": NoopPass()}))
        reports = []
        orch.set_progress_callback(reports.append)
        orch.run("")
        # 至少收到 workflow_completed 事件
        event_types = [r.event_type for r in reports]
        assert any(et in event_types for et in (
            ProgressEventType.STAGE_COMPLETED,
            ProgressEventType.WORKFLOW_COMPLETED,
        ))

    def test_unknown_pass_raises(self):
        policy = WorkflowPolicy(name="test", version="1.0")
        policy.stages = {
            WorkflowStage.EXPORT: StageConfig(
                stage=WorkflowStage.EXPORT, passes=["noop"],
            ),
        }
        orch = WorkflowOrchestrator(policy)
        orch.set_pass_factory(_make_factory({}))
        with pytest.raises(ValueError, match="未知 Pass"):
            orch.run("")


class TestGateBRouting:

    def test_gate_B_pauses(self):
        policy = WorkflowPolicy(name="test", version="1.0")
        policy.stages = {
            WorkflowStage.TRANSLATE: StageConfig(
                stage=WorkflowStage.TRANSLATE,
                passes=["gate_b_injector"],
                gate="text_gate",
                gate_routing={"A": "continue", "B": "pause", "C": "retry"},
                allow_pause=True,
            ),
        }
        orch = WorkflowOrchestrator(policy)
        orch.set_pass_factory(_make_factory({"gate_b_injector": GateBPass()}))
        orch.run("")
        assert orch.status == WorkflowStatus.PAUSED
        assert len(orch.pending_review) > 0

    def test_resume_after_pause_reaches_completed(self):
        policy = WorkflowPolicy(name="test", version="1.0")
        policy.stages = {
            WorkflowStage.TRANSLATE: StageConfig(
                stage=WorkflowStage.TRANSLATE,
                passes=["gate_b_injector"],
                gate="text_gate",
                gate_routing={"A": "continue", "B": "pause", "C": "retry"},
                allow_pause=True,
            ),
            WorkflowStage.EXPORT: StageConfig(
                stage=WorkflowStage.EXPORT, passes=[],
            ),
        }
        orch = WorkflowOrchestrator(policy)
        orch.set_pass_factory(_make_factory({"gate_b_injector": GateBPass()}))
        orch.run("")
        assert orch.status == WorkflowStatus.PAUSED

        decisions = {eid: "accept" for eid in orch.pending_review}
        orch.resume(decisions)
        assert orch.status == WorkflowStatus.COMPLETED


class TestGateCRetry:

    def test_gate_C_retry_within_limit(self):
        policy = WorkflowPolicy(name="test", version="1.0")
        policy.stages = {
            WorkflowStage.TRANSLATE: StageConfig(
                stage=WorkflowStage.TRANSLATE,
                passes=["gate_c_injector"],
                gate="text_gate",
                gate_routing={"A": "continue", "B": "pause", "C": "retry"},
                max_retries=3,
            ),
        }
        orch = WorkflowOrchestrator(policy)
        orch.set_pass_factory(_make_factory({"gate_c_injector": GateCPass()}))
        orch.run("")
        # 超过 max_retries 后应暂停或完成（不会无限循环）
        assert orch.status in (WorkflowStatus.PAUSED, WorkflowStatus.COMPLETED)


class TestWorkflowStatus:

    def test_cancel_sets_status(self):
        orch = WorkflowOrchestrator(WorkflowPolicy.quick_preset("zh"))
        orch.cancel()
        assert orch.status == WorkflowStatus.CANCELLED

    def test_pause_in_idle_is_noop(self):
        orch = WorkflowOrchestrator(WorkflowPolicy.quick_preset("zh"))
        orch.pause()
        assert orch.status == WorkflowStatus.IDLE
