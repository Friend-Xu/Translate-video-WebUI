"""
Timeline 模块 — AI Assisted Timeline Editing System (Phase 4 收敛后精简版)

写路径 (apply/undo/log) 已迁移到 core PatchEngine + timeline_io。
仅剩只读 AI 建议链 (api/rules/scorer/patch) 存活, 等待迁移 core/suggestion。
ir/io/fusion (v1 提取格式) 已随 extract_subtitles.py 退役 (架构收束 P2)。
"""

__all__ = []
