"""
集成测试 — core/pipeline.py API + CLI (批次11)
"""
import pytest
from core.pipeline import build_policy, load_transcript_data
from core.config.workflow_policy import WorkflowStage
from core.runtime.context import RuntimeContext


@pytest.mark.integration
class TestPipelineAPI:

    def test_build_policy_bootstrap(self):
        policy = build_policy("zh")
        assert WorkflowStage.TTS not in policy.stages
        assert WorkflowStage.VALIDATE in policy.stages
        assert WorkflowStage.LOAD in policy.stages

    def test_build_policy_all(self):
        policy = build_policy("zh", stages=["all"])
        assert WorkflowStage.TTS in policy.stages
        assert WorkflowStage.EXPORT in policy.stages

    def test_build_policy_custom(self):
        policy = build_policy("zh", stages=["load", "extract"])
        assert WorkflowStage.LOAD in policy.stages
        assert WorkflowStage.EXTRACT in policy.stages
        assert WorkflowStage.TRANSLATE not in policy.stages

    def test_runtime_context_workspace(self):
        ctx = RuntimeContext(video_path="C:/videos/test.mp4")
        assert ctx.workspace_dir.endswith("test_project")

    def test_load_transcript_empty(self):
        segs, st = load_transcript_data("/nonexistent/path")
        assert segs is None
        assert st is None
