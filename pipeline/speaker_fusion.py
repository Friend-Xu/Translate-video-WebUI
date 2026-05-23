"""
Speaker Fusion — 词级说话人分配 + 段边界切分

将 pyannote 说话人分离结果与 wav2vec2 词级对齐结果融合。
纯时间戳数学运算，零显存，不加载音频。

核心算法来自 WhisperX 的 assign_word_speakers()。

用法:
    from pipeline.speaker_fusion import assign_word_speakers, split_at_speaker_boundaries

    words = assign_word_speakers(words, speaker_timeline)
    segments = split_at_speaker_boundaries(segments)
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np


def assign_word_speakers(
    words: List[dict],
    speaker_timeline: List[Tuple[str, float, float, float]],
    fill_nearest: bool = False,
) -> List[dict]:
    """为每个词分配说话人标签（词级时间交集法）。

    对每个词，计算它与所有 diarization 段的时间交集。
    取交集时长最大的 speaker 作为该词的说话人。

    Args:
        words: [{word, start, end}, ...] (来自 wav2vec2 对齐)
        speaker_timeline: [(speaker_id, start, end, confidence), ...]
        fill_nearest: True=没有交集时用最近的 speaker

    Returns:
        words with 'speaker' key added to each entry
    """
    if not speaker_timeline:
        return words

    spk_labels = [s[0] for s in speaker_timeline]
    spk_starts = np.array([s[1] for s in speaker_timeline])
    spk_ends = np.array([s[2] for s in speaker_timeline])

    for w in words:
        w_start = w.get("start", 0)
        w_end = w.get("end", 0)
        intersections = np.maximum(
            0, np.minimum(spk_ends, w_end) - np.maximum(spk_starts, w_start)
        )
        if fill_nearest or intersections.sum() > 0:
            best_idx = 0
            best_sum = 0
            for i, label in enumerate(spk_labels):
                total = intersections[i]
                for j in range(i + 1, len(spk_labels)):
                    if spk_labels[j] == label:
                        total += intersections[j]
                if total > best_sum:
                    best_sum = total
                    best_idx = i
            w["speaker"] = spk_labels[best_idx]
            w["speaker_confidence"] = float(
                intersections[best_idx] / max(w_end - w_start, 0.01)
            )
    return words


def split_at_speaker_boundaries(
    segments: List[dict], min_duration_s: float = 0.3
) -> List[dict]:
    """检测段内说话人切换点，在边界处切开。

    单说话人段直接通过，多说话人段在切换点切成多个单说话人段。
    """
    result = []
    for seg in segments:
        result.extend(_split_one(seg, min_duration_s))
    return result


def _majority_speaker(words: List[dict]) -> Optional[str]:
    counts: Dict[str, float] = {}
    for w in words:
        spk = w.get("speaker")
        if spk:
            dur = w.get("end", 0) - w.get("start", 0)
            counts[spk] = counts.get(spk, 0) + max(dur, 0)
    return max(counts, key=counts.get) if counts else None


def _find_boundaries(words: List[dict], min_dur: float) -> List[int]:
    """找词序列中的说话人切换点。"""
    if len(words) < 2:
        return []
    boundaries = []
    cur = words[0].get("speaker")
    for i in range(1, len(words)):
        nxt = words[i].get("speaker")
        if nxt and cur and nxt != cur:
            prev_dur = words[i - 1].get("end", 0) - words[0].get("start", 0)
            next_dur = words[-1].get("end", 0) - words[i].get("start", 0)
            if prev_dur >= min_dur and next_dur >= min_dur:
                boundaries.append(i)
                cur = nxt
    return boundaries


def _split_one(seg: dict, min_dur: float) -> List[dict]:
    words = seg.get("words", [])
    if not words:
        seg_copy = dict(seg)
        return [seg_copy]
    boundaries = _find_boundaries(words, min_dur)
    if not boundaries:
        seg_copy = dict(seg)
        seg_copy["speaker"] = _majority_speaker(words)
        return [seg_copy]
    sub_segs = []
    prev = 0
    for bi in boundaries:
        sw = words[prev:bi]
        if sw:
            sub = {
                "start": sw[0].get("start", seg.get("start", 0)),
                "end": sw[-1].get("end", seg.get("end", 0)),
                "text": " ".join(w.get("word", "") for w in sw),
                "speaker": _majority_speaker(sw),
                "words": sw,
            }
            if sub["end"] - sub["start"] >= min_dur:
                sub_segs.append(sub)
        prev = bi
    sw = words[prev:]
    if sw:
        sub = {
            "start": sw[0].get("start", seg.get("start", 0)),
            "end": sw[-1].get("end", seg.get("end", 0)),
            "text": " ".join(w.get("word", "") for w in sw),
            "speaker": _majority_speaker(sw),
            "words": sw,
        }
        if sub["end"] - sub["start"] >= min_dur:
            sub_segs.append(sub)
    return sub_segs if sub_segs else [dict(seg)]


def detect_overlaps(
    speaker_timeline: List[Tuple[str, float, float, float]],
    min_overlap_s: float = 0.5,
) -> List[dict]:
    """检测时间线中的重叠说话区域。Returns: [{start, end, speakers[], duration}]"""
    if len(speaker_timeline) < 2:
        return []
    overlaps = []
    turns = sorted(speaker_timeline, key=lambda x: x[1])
    for i in range(len(turns) - 1):
        si, ei = turns[i][1], turns[i][2]
        for j in range(i + 1, len(turns)):
            sj, ej = turns[j][1], turns[j][2]
            if sj > ei:
                break
            ov_s = max(si, sj)
            ov_e = min(ei, ej)
            dur = ov_e - ov_s
            if dur >= min_overlap_s:
                overlaps.append({
                    "start": ov_s, "end": ov_e,
                    "speakers": [turns[i][0], turns[j][0]],
                    "duration": dur,
                })
    return overlaps
