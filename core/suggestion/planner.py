"""
suggestion.planner — 唯一决策点 (迁移自 timeline/patch/planner)

Input: signals + scores; Output: SuggestionPatch 列表。
确定性: 相同输入 → 相同输出; 无外部状态变更。
"""
from __future__ import annotations

from core.suggestion.model import SuggestionPatch
from core.suggestion.opcode import SuggestionOpCode as OpCode


def plan(
    segments: list[dict],
    signals_list: list[dict],
    scores: list[float],
    min_confidence: float = 0.7,
) -> list[SuggestionPatch]:
    """Generate patches from scored signals. Deterministic."""
    patches: list[SuggestionPatch] = []

    if len(signals_list) != len(segments) - 1:
        return patches

    for i, signals in enumerate(signals_list):
        if i >= len(segments) - 1:
            break
        seg_a, seg_b = segments[i], segments[i + 1]
        score = scores[i] if i < len(scores) else 0.0

        if score < min_confidence:
            continue

        patch = _signals_to_patch(seg_a, seg_b, signals, score, i)
        if patch:
            patches.append(patch)

    patches.sort(key=lambda p: p.confidence, reverse=True)
    return patches


def _signals_to_patch(
    seg_a: dict, seg_b: dict, signals: dict, score: float, idx: int,
) -> SuggestionPatch | None:
    """Convert scored signals to a single patch candidate."""
    same_spk = signals.get("same_speaker", False)
    gap = signals.get("gap", 999.0)
    semantic_cont = signals.get("semantic_continuation", False)

    # MERGE
    if same_spk and gap < 0.8 and semantic_cont:
        reasons = ["same_speaker"]
        if gap < 0.8:
            reasons.append("short_gap")
        if semantic_cont:
            reasons.append("semantic_continuation")
        if signals.get("incomplete_ending"):
            reasons.append("incomplete_ending")
        return SuggestionPatch(
            patch_id=f"patch_merge_{idx:04d}",
            opcode=OpCode.MERGE,
            targets=[seg_a["id"], seg_b["id"]],
            reason=reasons,
            confidence=score,
            author="system",
        )

    # SPLIT
    if signals.get("too_long", False):
        seg_dur = seg_a.get("end", 0) - seg_a.get("start", 0)
        mid = seg_a.get("start", 0) + seg_dur / 2
        words = seg_a.get("words", [])
        if len(words) >= 2:
            mid = words[len(words) // 2].get("start", mid) if isinstance(words[len(words) // 2], dict) else mid
        return SuggestionPatch(
            patch_id=f"patch_split_{idx:04d}",
            opcode=OpCode.SPLIT,
            targets=[seg_a["id"]],
            payload={"split_point": mid},
            reason=["segment_too_long"],
            confidence=score,
            author="system",
        )

    return None
