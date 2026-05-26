"""
prob_builder — overlap → probability vector

替代 assign_word_speakers 的 hard argmax。
每个 word 计算所有 speaker 的重叠比例，归一化为概率分布。
"""
from __future__ import annotations
import math
import numpy as np


def build_initial_probs(
    words: list[dict],
    speaker_timeline: list[tuple],
) -> list[dict]:
    """为每个 word 构建 speaker 概率向量。

    word 增加:
    - speaker_probs: {SPK_A: 0.65, SPK_B: 0.35, ...}
    - speaker_init: 原始 hard label
    - speaker_confidence: 基于分布熵的初始置信度
    """
    if not speaker_timeline:
        return words

    spk_labels = [s[0] for s in speaker_timeline]
    spk_starts = np.array([s[1] for s in speaker_timeline])
    spk_ends = np.array([s[2] for s in speaker_timeline])

    for w in words:
        w_start = w.get("start", 0)
        w_end = w.get("end", 0)

        w["speaker_init"] = w.get("speaker")

        intersections = np.maximum(
            0, np.minimum(spk_ends, w_end) - np.maximum(spk_starts, w_start)
        )
        probs: dict[str, float] = {}
        for i, label in enumerate(spk_labels):
            probs[label] = probs.get(label, 0) + float(intersections[i])

        s = sum(probs.values())
        if s > 0:
            probs = {k: v / s for k, v in probs.items()}
        w["speaker_probs"] = probs

        entropy = -sum(
            p * math.log(p + 1e-9) for p in probs.values() if p > 0
        )
        max_entropy = math.log(len(probs)) if len(probs) > 1 else 1.0
        w["speaker_confidence"] = max(0.0, 1.0 - entropy / max_entropy)

    return words
