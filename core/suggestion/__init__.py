"""
core/suggestion — AI Patch 建议 (只读, 架构收束 P5)

从 timeline/ 旧系统迁移 (timeline-first AI Assisted Editing)。
输出契约与 TimelinePatch.to_dict 字段形状一致, GUI/patch_adapter 的
_LEGACY_TO_OP 承接大写 opcode (MERGE/SPLIT) — 前端零改动。

只读不写: 建议只消费 timeline.json, 写路径仍在 core PatchEngine。
"""
from core.suggestion.api import generate_candidate_patches

__all__ = ["generate_candidate_patches"]
