"""
TimelineIR — Timeline 中间层容器 (Chapter 2 §2.2)

负责组织 segment 拓扑关系、patch 历史索引、快照列表。
位于 Project 和 Segment 之间，是全局可视化和调度的主要对象。
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TimelineIR:
    """Timeline 级状态 — 轨道组织、拓扑关系、patch 历史索引。

    不直接包含所有模型结果的细节，负责组织和索引。
    """
    id: str                              # timeline 唯一标识
    project_ref: str = ""                # → TimelineProjectIR
    tracks: tuple[str, ...] = ()         # 轨道 ID 列表（多轨支持）
    segment_order: tuple[str, ...] = ()  # segment ID 拓扑顺序
    patch_history_ref: str | None = None # → patch log 路径
    snapshot_list: tuple[str, ...] = ()  # 快照 ID 列表
    quality_summary: dict | None = None  # 质量评分摘要
    repair_queue: tuple[str, ...] = ()   # 待修复 segment ID 列表
    schema_version: str = "2.1"          # Schema 版本
