"""core/config — 全局配置与 Schema 校验模块

提供:
  - GlobalConfig / ProjectPolicy / EnginePolicy — 三层配置数据模型
  - SchemaLoader — JSON Schema 加载与校验
"""
from core.config.global_config import GlobalConfig, ProjectPolicy, EnginePolicy
from core.config.schema_loader import SchemaLoader
from core.config.engine_policy import derive_engine_policy

__all__ = [
    "GlobalConfig",
    "ProjectPolicy",
    "EnginePolicy",
    "SchemaLoader",
    "derive_engine_policy",
]
