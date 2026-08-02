"""
suggestion.scorer — 加权评分 (迁移自 timeline/scorer/scorer)

final = semantic*0.4 + speaker*0.2 + timing*0.2 + subtitle*0.2
"""
from __future__ import annotations


def score_signals(pair_signals: dict, seg_a_signals: dict | None = None,
                  seg_b_signals: dict | None = None) -> float:
    semantic = _semantic_score(pair_signals)
    speaker = _speaker_score(pair_signals)
    timing = _timing_score(pair_signals)
    subtitle = _subtitle_score(pair_signals)
    return round(semantic * 0.4 + speaker * 0.2 + timing * 0.2 + subtitle * 0.2, 2)


def score_all(pair_signals_list: list[dict],
              seg_signals_list: list[dict] | None = None) -> list[float]:
    scores = []
    for i, ps in enumerate(pair_signals_list):
        seg_a = seg_signals_list[i] if seg_signals_list and i < len(seg_signals_list) else None
        seg_b = seg_signals_list[i + 1] if seg_signals_list and i + 1 < len(seg_signals_list) else None
        scores.append(score_signals(ps, seg_a, seg_b))
    return scores


def confidence_label(score: float) -> str:
    if score > 0.9:
        return "high"
    elif score >= 0.7:
        return "medium"
    return "low"


def _semantic_score(pair: dict) -> float:
    score = 0.5
    if pair.get("semantic_continuation"):
        score += 0.3
    if pair.get("incomplete_ending"):
        score += 0.2
    if pair.get("semantic_continuation") and pair.get("incomplete_ending"):
        score += 0.1
    return min(score, 1.0)


def _speaker_score(pair: dict) -> float:
    return 0.9 if pair.get("same_speaker") else 0.0


def _timing_score(pair: dict) -> float:
    gap = pair.get("gap", 999.0)
    if gap < 0.3:
        return 0.95
    elif gap < 0.5:
        return 0.8
    elif gap < 0.8:
        return 0.6
    elif gap < 1.5:
        return 0.3
    return 0.1


def _subtitle_score(pair: dict) -> float:
    merged_dur = pair.get("merged_duration", 999.0)
    if merged_dur > 12:
        return 0.0
    elif merged_dur > 8:
        return 0.3
    elif merged_dur > 5:
        return 0.6
    return 0.8
