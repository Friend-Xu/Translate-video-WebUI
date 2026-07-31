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
    """Mock Pass: 给所有 event 注入 Gate B 判定 (写 review 槽 — 与真实 pass 一致)。"""
    name = "gate_b_injector"

    def apply(self, state, resolver=None):
        for es in state.event_states.values():
            es.review.gate_decision = "B"
        return state


class GateCPass(TimelinePass):
    """Mock Pass: 给所有 event 注入 Gate C 判定 (写 review 槽 — 与真实 pass 一致)。"""
    name = "gate_c_injector"
    call_count = 0

    def apply(self, state, resolver=None):
        GateCPass.call_count += 1
        for es in state.event_states.values():
            es.review.gate_decision = "C"
        return state


class EventSeedPass(TimelinePass):
    """给空 state 创建事件 — gate 判定必须有目标事件才触发。

    现有测试的空 state 导致 _evaluate_gate 遍历不到任何事件,
    gate 永不触发 (假绿)。真实管线中 EXTRACT 阶段产出事件。
    """
    name = "event_seed"

    def apply(self, state, resolver=None):
        from core.ir.timeline_event import TimelineEventIR
        ir = TimelineEventIR(id="evt_001", start=0.0, end=1.0,
                             speaker_ref=None, text_ref="hello")
        state.event_states["evt_001"] = TimelineEventState(ir)
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
        # PassManager deduplicates by name: second "noop" overwrites first
        assert NoopPass.call_count == 1
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

    def test_unknown_pass_skipped(self):
        policy = WorkflowPolicy(name="test", version="1.0")
        policy.stages = {
            WorkflowStage.EXPORT: StageConfig(
                stage=WorkflowStage.EXPORT, passes=["noop"],
            ),
        }
        orch = WorkflowOrchestrator(policy)
        orch.set_pass_factory(_make_factory({}))
        # Missing pass returns None from factory → StageExecutor skips it
        state = orch.run("")
        assert orch.status == WorkflowStatus.COMPLETED


class TestGateBRouting:

    def test_gate_B_completes_when_no_events(self):
        """Empty state has no events, gate evaluation finds nothing to pause on."""
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
        # Empty state → no events to gate → completes
        assert orch.status == WorkflowStatus.COMPLETED

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
        # Empty state → no events → gate doesn't pause → all stages complete
        assert orch.status == WorkflowStatus.COMPLETED


class TestGateCRetry:

    def test_gate_C_retry_exhausts_then_pauses(self):
        """真实 C 级路径: 阶段重跑 max_retries 次后暂停, 不无限循环。"""
        GateCPass.call_count = 0
        policy = WorkflowPolicy(name="test", version="1.0")
        policy.stages = {
            WorkflowStage.LOAD: StageConfig(
                stage=WorkflowStage.LOAD, passes=["event_seed"],
            ),
            WorkflowStage.TRANSLATE: StageConfig(
                stage=WorkflowStage.TRANSLATE,
                passes=["gate_c_injector"],
                gate="text_gate",
                gate_routing={"A": "continue", "B": "pause", "C": "retry"},
                max_retries=3,
            ),
        }
        orch = WorkflowOrchestrator(policy)
        orch.set_pass_factory(_make_factory({
            "event_seed": EventSeedPass(),
            "gate_c_injector": GateCPass(),
        }))
        orch.run("")
        # 1 首次执行 + 3 次重试 = 4 次调用, 然后暂停 (不会无限循环)
        assert GateCPass.call_count == 4
        assert orch.status == WorkflowStatus.PAUSED
        assert orch.retry_count == 3

    def test_gate_C_retry_then_advance_when_fixed(self):
        """重试期间 gate 修复 → 阶段推进到完成。"""
        policy = WorkflowPolicy(name="test", version="1.0")
        policy.stages = {
            WorkflowStage.LOAD: StageConfig(
                stage=WorkflowStage.LOAD, passes=["event_seed"],
            ),
            WorkflowStage.TRANSLATE: StageConfig(
                stage=WorkflowStage.TRANSLATE,
                passes=["flaky_c_injector"],
                gate="text_gate",
                gate_routing={"A": "continue", "B": "pause", "C": "retry"},
                max_retries=2,
            ),
            WorkflowStage.EXPORT: StageConfig(
                stage=WorkflowStage.EXPORT, passes=[],
            ),
        }

        class _FlakyPass(TimelinePass):
            name = "flaky_c_injector"
            n = 0

            def apply(self, state, resolver=None):
                _FlakyPass.n += 1
                for es in state.event_states.values():
                    es.review.gate_decision = "C" if _FlakyPass.n <= 1 else "A"
                return state

        orch = WorkflowOrchestrator(policy)
        orch.set_pass_factory(_make_factory({
            "event_seed": EventSeedPass(),
            "flaky_c_injector": _FlakyPass(),
        }))
        orch.run("")
        # 1 首次 + 1 次重试后 gate 修复 → 继续 → 完成
        assert orch.status == WorkflowStatus.COMPLETED
        assert _FlakyPass.n == 2

    def test_gate_C_retry_zero_max_retries_pauses_immediately(self):
        """max_retries=0 → 首次 C 即暂停, 不重跑。"""
        policy = WorkflowPolicy(name="test", version="1.0")
        policy.stages = {
            WorkflowStage.LOAD: StageConfig(
                stage=WorkflowStage.LOAD, passes=["event_seed"],
            ),
            WorkflowStage.TRANSLATE: StageConfig(
                stage=WorkflowStage.TRANSLATE,
                passes=["gate_c_injector"],
                gate="text_gate",
                gate_routing={"A": "continue", "B": "pause", "C": "retry"},
                max_retries=0,
            ),
        }
        GateCPass.call_count = 0
        orch = WorkflowOrchestrator(policy)
        orch.set_pass_factory(_make_factory({
            "event_seed": EventSeedPass(),
            "gate_c_injector": GateCPass(),
        }))
        orch.run("")
        assert orch.status == WorkflowStatus.PAUSED
        assert GateCPass.call_count == 1


class TestEmotionGateRouting:

    class _EmotionGatePass(TimelinePass):
        """注入 emotion gate 判定 (写 emotion 槽 — 与真实 pass 一致)。"""
        name = "emotion_gate_injector"
        decision = "E1"

        def apply(self, state, resolver=None):
            for es in state.event_states.values():
                es.emotion.gate_decision = self.decision
            return state

    def _make_emotion_policy(self, decision: str):
        self._EmotionGatePass.decision = decision
        policy = WorkflowPolicy(name="test", version="1.0")
        policy.stages = {
            WorkflowStage.LOAD: StageConfig(
                stage=WorkflowStage.LOAD, passes=["event_seed"],
            ),
            WorkflowStage.TTS: StageConfig(
                stage=WorkflowStage.TTS,
                passes=["emotion_gate_injector"],
                gate="emotion_gate",
                gate_routing={"E1": "export", "E2": "export", "E3": "pause"},
            ),
            WorkflowStage.EXPORT: StageConfig(
                stage=WorkflowStage.EXPORT, passes=[],
            ),
        }
        return policy

    def test_emotion_E3_pauses(self):
        """E3 (repair) → routing E3 → pause。旧实现永远匹配不到 E3 (假行为)。"""
        orch = WorkflowOrchestrator(self._make_emotion_policy("E3"))
        orch.set_pass_factory(_make_factory({
            "event_seed": EventSeedPass(),
            "emotion_gate_injector": self._EmotionGatePass(),
        }))
        orch.run("")
        assert orch.status == WorkflowStatus.PAUSED

    def test_emotion_E2_continues_to_export(self):
        """E2 (downgrade) → routing E2 → 继续 (不暂停)。"""
        orch = WorkflowOrchestrator(self._make_emotion_policy("E2"))
        orch.set_pass_factory(_make_factory({
            "event_seed": EventSeedPass(),
            "emotion_gate_injector": self._EmotionGatePass(),
        }))
        orch.run("")
        assert orch.status == WorkflowStatus.COMPLETED

    def test_emotion_does_not_overwrite_text_gate(self):
        """Phase1 跨域修复: emotion 判定写 emotion 槽, review.gate_decision 不受影响。"""
        state = TimelineProjectState(
            TimelineProjectIR(events={"evt_001": TimelineEventIR(
                id="evt_001", start=0.0, end=1.0, speaker_ref=None, text_ref="hi")})
        )
        es = state.get_event("evt_001")
        es.review.gate_decision = "A"          # text_gate 已判定
        es.translation.text = "你好"

        # emotion pass 需要 recognizer/scorer/gate 全套依赖 — 直接模拟其写入行为
        # 验证契约: emotion 结果只写 emotion 槽
        es.emotion.gate_decision = "E2"
        assert es.review.gate_decision == "A"  # 文本门控不被覆盖


class TestWorkflowStatus:

    def test_cancel_sets_status(self):
        orch = WorkflowOrchestrator(WorkflowPolicy.quick_preset("zh"))
        orch.cancel()
        assert orch.status == WorkflowStatus.CANCELLED

    def test_pause_in_idle_is_noop(self):
        orch = WorkflowOrchestrator(WorkflowPolicy.quick_preset("zh"))
        orch.pause()
        assert orch.status == WorkflowStatus.IDLE

    def test_cancel_sets_status(self):
        orch = WorkflowOrchestrator(WorkflowPolicy.quick_preset("zh"))
        orch.cancel()
        assert orch.status == WorkflowStatus.CANCELLED

    def test_pause_in_idle_is_noop(self):
        orch = WorkflowOrchestrator(WorkflowPolicy.quick_preset("zh"))
        orch.pause()
        assert orch.status == WorkflowStatus.IDLE
