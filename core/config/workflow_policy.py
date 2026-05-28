"""
WorkflowPolicy — 四层对象域的第四层（定稿 §2.3, §17）

四层域模型:
  ProjectPolicy   (What)    — 项目级默认配置: 语言选择、质量阈值、引擎偏好
  WorkflowPolicy  (How)     — 工作流定义: 阶段顺序、Pass 注册、Gate 配置  ← 本模块
  EnginePolicy    (Engine)  — 引擎能力默认: GPU/CPU、VRAM、并发上限
  SegmentRuntimeState       — 段级运行时状态: 9 槽位 + config + patches

WorkflowPolicy 填补了当前架构中"编排层"的缺失。
它定义了从视频加载到成品输出的完整管线: 哪些 Stage、各 Stage 注册哪些 Pass、
Gate 判定后如何路由、是否启用人工审核节点。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


class WorkflowStage(Enum):
    """工作流五阶段（定稿 §1.3 五模式工作台 → 五阶段管线）。"""
    LOAD = "load"
    EXTRACT = "extract"
    TRANSLATE = "translate"
    TTS = "tts"
    EXPORT = "export"

    @property
    def display_name(self) -> str:
        names = {
            "load": "视频加载",
            "extract": "字幕提取",
            "translate": "翻译与审校",
            "tts": "语音合成",
            "export": "导出交付",
        }
        return names.get(self.value, self.value)

    @property
    def index(self) -> int:
        return _STAGE_ORDER[self]


_STAGE_ORDER = {
    WorkflowStage.LOAD: 0,
    WorkflowStage.EXTRACT: 1,
    WorkflowStage.TRANSLATE: 2,
    WorkflowStage.TTS: 3,
    WorkflowStage.EXPORT: 4,
}


@dataclass
class StageConfig:
    """单个阶段的配置。

    Attributes:
        stage: 阶段标识
        passes: 要在本阶段注册的 Pass 名称列表（按依赖序）
        auto_advance: True = 完成后自动进入下一阶段
        gate: 阶段完成后的 Gate 名称（"" = 无门控）
        gate_routing: Gate 判定后的路由规则 {A: next_stage, B: action, C: action}
        allow_pause: 是否允许在此阶段暂停（B 级事件需人工审核）
        max_retries: Gate C 判定时的最大重试次数
        timeout_seconds: 阶段超时（0 = 无限制）
    """
    stage: WorkflowStage
    passes: list[str] = field(default_factory=list)
    auto_advance: bool = True
    gate: str = ""
    gate_routing: dict[str, str] = field(default_factory=dict)
    allow_pause: bool = False
    max_retries: int = 1
    timeout_seconds: int = 0


@dataclass
class WorkflowPolicy:
    """工作流策略 — 定义整条管线的阶段构成与路由规则。

    这是四层对象域中最关键的"编排层"。它将 ProjectPolicy 的"做什么"
    翻译为 WorkflowPolicy 的"怎么做"。

    Usage:
        policy = WorkflowPolicy.default_preset("zh")
        policy.stages[WorkflowStage.TRANSLATE].gate = "text_gate"
        orchestrator = WorkflowOrchestrator(policy)
        state = orchestrator.run(video_path)
    """
    name: str = "default"
    version: str = "1.0"
    stages: dict[WorkflowStage, StageConfig] = field(default_factory=dict)
    global_passes: list[str] = field(default_factory=list)

    @classmethod
    def default_preset(cls, target_lang: str = "zh") -> "WorkflowPolicy":
        """创建默认五阶段管线预设（定稿 Ch17 一键智能模式）。

        高级用户可通过 WorkflowPolicy 编辑器自定义各阶段参数。
        """
        policy = cls(
            name=f"preset_{target_lang}",
            version="1.0",
        )
        policy.stages = {
            WorkflowStage.LOAD: StageConfig(
                stage=WorkflowStage.LOAD,
                passes=["media_validate"],
                auto_advance=True,
            ),
            WorkflowStage.EXTRACT: StageConfig(
                stage=WorkflowStage.EXTRACT,
                passes=["asr", "asr_to_ir", "speaker", "semantic_merge"],
                auto_advance=True,
            ),
            WorkflowStage.TRANSLATE: StageConfig(
                stage=WorkflowStage.TRANSLATE,
                passes=["translate", "quality_check"],
                auto_advance=False,
                gate="text_gate",
                gate_routing={
                    "A": "tts",
                    "B": "pause",
                    "C": "retry",
                },
                allow_pause=True,
                max_retries=1,
            ),
            WorkflowStage.TTS: StageConfig(
                stage=WorkflowStage.TTS,
                passes=["tts", "emotion"],
                auto_advance=True,
                gate="emotion_gate",
                gate_routing={
                    "E1": "export",
                    "E2": "export",
                    "E3": "pause",
                },
                allow_pause=True,
            ),
            WorkflowStage.EXPORT: StageConfig(
                stage=WorkflowStage.EXPORT,
                passes=["srt_export"],
                auto_advance=True,
            ),
        }
        return policy

    @classmethod
    def quick_preset(cls, target_lang: str = "zh") -> "WorkflowPolicy":
        """最小化预设 — 跳过所有 Gate，直接跑通全流程。用于测试。"""
        policy = cls(name=f"quick_{target_lang}", version="1.0")
        policy.stages = {
            WorkflowStage.LOAD: StageConfig(
                stage=WorkflowStage.LOAD,
                passes=["media_validate"],
            ),
            WorkflowStage.EXTRACT: StageConfig(
                stage=WorkflowStage.EXTRACT,
                passes=["asr", "asr_to_ir", "speaker", "semantic_merge"],
            ),
            WorkflowStage.TRANSLATE: StageConfig(
                stage=WorkflowStage.TRANSLATE,
                passes=["translate"],
            ),
            WorkflowStage.TTS: StageConfig(
                stage=WorkflowStage.TTS,
                passes=["tts"],
            ),
            WorkflowStage.EXPORT: StageConfig(
                stage=WorkflowStage.EXPORT,
                passes=["srt_export"],
            ),
        }
        return policy

    def get_stage(self, stage: WorkflowStage) -> StageConfig | None:
        return self.stages.get(stage)

    def stage_order(self) -> list[WorkflowStage]:
        return sorted(self.stages.keys(), key=lambda s: s.index)
