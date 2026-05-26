"""
WordLevelRefiner — 5-step probabilistic sequence refinement

1. temporal_smooth — 前后邻域概率混合
2. local_majority  — 滑窗多数 speaker 加权
3. short_correct   — 短词降低自身信号权重
4. boundary_adjust — 靠近 pyannote 边界降置信度
5. finalize        — argmax + confidence + entropy
"""
from __future__ import annotations
import math
import logging
from core.refiner.prob_builder import build_initial_probs

logger = logging.getLogger("core.refiner")


class WordLevelRefiner:
    """Word-level Speaker Probabilistic Refinement Engine"""

    def __init__(self, short_threshold: float = 0.25, window_size: int = 7):
        self.short_threshold = short_threshold
        self.window_size = window_size

    def refine(
        self, words: list[dict], speaker_timeline: list[tuple]
    ) -> dict:
        """完整精修流程。返回 {"words": [...], "stats": {...}}"""
        n = len(words)
        words = build_initial_probs(words, speaker_timeline)
        words = _temporal_smooth(words)
        words = _local_majority(words, self.window_size)
        words = _short_word_correct(words, self.short_threshold)
        words = _boundary_adjust(words, speaker_timeline)
        words = _finalize(words)

        refined = sum(1 for w in words if w.get("_refined"))
        logger.info(
            "WordRefiner: %d/%d words adjusted (%.1f%%)",
            refined, n, refined / max(n, 1) * 100,
        )
        return {"words": words, "stats": self._compute_stats(words)}

    def _compute_stats(self, words: list[dict]) -> dict:
        refined = sum(1 for w in words if w.get("_refined"))
        entropies = [
            -sum(p * math.log(p + 1e-9)
                 for p in w.get("speaker_probs", {}).values() if p > 0)
            for w in words
        ]
        return {
            "total": len(words),
            "refined_count": refined,
            "refined_pct": round(refined / max(len(words), 1) * 100, 1),
            "avg_entropy": round(sum(entropies) / max(len(entropies), 1), 4),
        }


# ── Step 1: Temporal Smoothing ──

def _temporal_smooth(words: list[dict], alpha: float = 0.3) -> list[dict]:
    """前后邻域概率混合。"""
    n = len(words)
    if n < 2:
        return words
    for i in range(1, n - 1):
        probs = words[i].get("speaker_probs", {})
        prev = words[i - 1].get("speaker_probs", {})
        nxt = words[i + 1].get("speaker_probs", {})
        if not probs:
            continue
        blended: dict[str, float] = {}
        all_spk = set(probs) | set(prev) | set(nxt)
        for spk in all_spk:
            own = probs.get(spk, 0)
            blended[spk] = own * (1 - 2 * alpha) + prev.get(spk, 0) * alpha + nxt.get(spk, 0) * alpha
        s = sum(blended.values())
        if s > 0:
            words[i]["speaker_probs"] = {k: v / s for k, v in blended.items()}
    return words


# ── Step 2: Local Window Majority ──

def _local_majority(words: list[dict], window: int = 7) -> list[dict]:
    """滑窗聚合 speaker 概率，与当前混合 (40% own + 60% window)。"""
    n = len(words)
    half = window // 2
    for i in range(n):
        probs = words[i].get("speaker_probs", {})
        if not probs:
            continue
        agg: dict[str, float] = {}
        for j in range(max(0, i - half), min(n, i + half + 1)):
            for spk, p in words[j].get("speaker_probs", {}).items():
                agg[spk] = agg.get(spk, 0) + p
        s = sum(agg.values())
        if s > 0:
            agg = {k: v / s for k, v in agg.items()}
        blended: dict[str, float] = {}
        all_spk = set(probs) | set(agg)
        for spk in all_spk:
            blended[spk] = probs.get(spk, 0) * 0.4 + agg.get(spk, 0) * 0.6
        s2 = sum(blended.values())
        if s2 > 0:
            words[i]["speaker_probs"] = {k: v / s2 for k, v in blended.items()}
    return words


# ── Step 3: Short Word Correction ──

def _short_word_correct(words: list[dict], threshold: float = 0.25) -> list[dict]:
    """短词不信任自身信号，偏向邻域。"""
    n = len(words)
    for i in range(n):
        w = words[i]
        dur = w.get("end", 0) - w.get("start", 0)
        if dur >= threshold:
            continue
        probs = w.get("speaker_probs", {})
        if not probs:
            continue
        neighbor: dict[str, float] = {}
        if i > 0:
            for spk, p in words[i - 1].get("speaker_probs", {}).items():
                neighbor[spk] = neighbor.get(spk, 0) + p
        if i < n - 1:
            for spk, p in words[i + 1].get("speaker_probs", {}).items():
                neighbor[spk] = neighbor.get(spk, 0) + p
        s_nb = sum(neighbor.values())
        if s_nb > 0:
            neighbor = {k: v / s_nb for k, v in neighbor.items()}
        blended: dict[str, float] = {}
        all_spk = set(probs) | set(neighbor)
        for spk in all_spk:
            blended[spk] = probs.get(spk, 0) * 0.2 + neighbor.get(spk, 0) * 0.8
        s2 = sum(blended.values())
        if s2 > 0:
            w["speaker_probs"] = {k: v / s2 for k, v in blended.items()}
    return words


# ── Step 4: Boundary Adjustment ──

def _boundary_adjust(
    words: list[dict], speaker_timeline: list[tuple], margin: float = 0.15
) -> list[dict]:
    """靠近 pyannote speaker 切换点的词 → 概率乘以衰减因子。"""
    if not speaker_timeline or len(speaker_timeline) < 2:
        return words
    switch_times: list[float] = []
    for i in range(1, len(speaker_timeline)):
        if speaker_timeline[i][0] != speaker_timeline[i - 1][0]:
            switch_times.append(speaker_timeline[i][1])
    if not switch_times:
        return words
    for w in words:
        w_mid = w.get("start", 0) + (w.get("end", 0) - w.get("start", 0)) / 2
        near = any(abs(w_mid - st) < margin for st in switch_times)
        if near:
            w["_near_boundary"] = True
            probs = w.get("speaker_probs", {})
            if probs:
                decayed = {k: v * 0.6 for k, v in probs.items()}
                s = sum(decayed.values())
                if s > 0:
                    w["speaker_probs"] = {k: v / s for k, v in decayed.items()}
    return words


# ── Step 5: Finalize ──

def _finalize(words: list[dict]) -> list[dict]:
    """argmax + confidence + entropy。"""
    for w in words:
        probs = w.get("speaker_probs", {})
        if not probs:
            continue
        old_spk = w.get("speaker")
        new_spk = max(probs, key=probs.get)
        w["speaker"] = new_spk
        w["speaker_confidence"] = probs[new_spk]
        entropy = -sum(
            p * math.log(p + 1e-9) for p in probs.values() if p > 0
        )
        w["speaker_entropy"] = round(entropy, 4)
        if old_spk and old_spk != new_spk:
            w["_refined"] = True
    return words
