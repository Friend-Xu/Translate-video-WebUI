"""core/config — 全局配置与 Schema 校验模块

提供:
  - GlobalConfig / ProjectPolicy / EnginePolicy — 三层配置数据模型
  - WorkflowPolicy / WorkflowStage / StageConfig — 工作流编排策略（四层对象域）
  - SLOT_DEFAULTS — 槽位默认值字典（ConfigResolver Layer 1）
  - SchemaLoader — JSON Schema 加载与校验
"""
from core.config.global_config import GlobalConfig, ProjectPolicy, EnginePolicy
from core.config.schema_loader import SchemaLoader
from core.config.engine_policy import derive_engine_policy
from core.config.workflow_policy import WorkflowPolicy, WorkflowStage, StageConfig
from core.config.defaults import SLOT_DEFAULTS

__all__ = [
    "GlobalConfig",
    "ProjectPolicy",
    "EnginePolicy",
    "WorkflowPolicy",
    "WorkflowStage",
    "StageConfig",
    "SLOT_DEFAULTS",
    "SchemaLoader",
    "derive_engine_policy",
]
