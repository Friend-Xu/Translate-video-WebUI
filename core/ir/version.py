"""
版本常量与兼容性检查 (Chapter 2 §2.5)

三类版本独立管理:
  Schema Version — 数据结构定义版本 (字段增删、类型变化)
  IR Version     — Timeline IR 语义版本 (segment 逻辑定义变化)
  Patch Version  — Patch 协议版本 (OpCode 变更、payload 格式变更)

MAJOR 不同 = 不兼容, MINOR 不同 = 向前兼容。
"""
from __future__ import annotations

SCHEMA_VERSION = "3.0"  # v3.0: 槽位新增 config 子字段 (定稿 §10.3)
IR_VERSION = "3.0"      # v3.0: 配置注入 + 三级继承
PATCH_VERSION = "2.0"   # Patch 协议未变


def check_schema_compatible(data_version: str) -> bool:
    """检查数据文件 schema 版本是否与当前代码兼容。

    MAJOR.MINOR 格式: MAJOR 变化 = 不兼容, MINOR 变化 = 向前兼容。
    """
    if not data_version:
        return False
    try:
        parts = data_version.split(".")
        cur = SCHEMA_VERSION.split(".")
        return parts[0] == cur[0]  # MAJOR 必须一致
    except (IndexError, ValueError):
        return False


def migrate_if_needed(data: dict, target_version: str = SCHEMA_VERSION) -> dict:
    """根据版本号自动执行迁移。当前无迁移路径，直接返回。"""
    src = data.get("schema_version", "1.0")
    if src == target_version:
        return data
    if not check_schema_compatible(src):
        raise ValueError(f"Schema version {src} is incompatible with {target_version}")
    data["schema_version"] = target_version
    return data
