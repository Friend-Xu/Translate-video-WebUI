"""
suggestion.signal — 相邻段特征信号提取 (迁移自 timeline/rules/extractor)

只输出特征 dict, 不产生决策。
"""
from __future__ import annotations

SENTENCE_ENDERS = {"。", "！", "？", "!", "?", ".", "…", "」", "）", ")", "\"", "'"}
CONTINUATION_STARTS = {"だが", "でも", "しかし", "けど", "だけど", "それに", "そして",
                       "だから", "なので", "そこで", "すると", "また", "まだ", "あと",
                       "じゃ", "じゃあ", "それじゃ", "で", "あの", "えっと", "あー",
                       "and", "but", "so", "then", "also", "because", "however"}


def extract_signals(segments: list[dict]) -> list[dict]:
    """Extract per-adjacent-pair feature signals.
    Returns list of dicts (len = len(segments) - 1). No decisions, no patches.
    """
    if len(segments) < 2:
        return []
    signals_list = []
    for i in range(len(segments) - 1):
        a, b = segments[i], segments[i + 1]
        signals_list.append(_extract_pair_signals(a, b))
    return signals_list


def extract_segment_signals(seg: dict) -> dict:
    """Extract per-segment signals (for split decisions)."""
    dur = seg.get("end", 0) - seg.get("start", 0)
    text = seg.get("text", "")
    words = seg.get("words", [])
    char_count = len(text)
    cps = char_count / dur if dur > 0 else 0
    ender_count = sum(1 for c in text if c in SENTENCE_ENDERS)
    max_word_gap = 0.0
    for j in range(len(words) - 1):
        wj, wj1 = words[j], words[j + 1]
        gap = (wj1.get("start", 0) if isinstance(wj1, dict) else 0) - (wj.get("end", 0) if isinstance(wj, dict) else 0)
        if gap > max_word_gap:
            max_word_gap = gap
    return {
        "duration": dur, "char_count": char_count, "cps": cps,
        "word_count": len(words), "sentence_enders": ender_count,
        "max_word_gap": max_word_gap,
        "too_long": dur > 15, "exceeds_cps": cps > 25,
        "multi_sentence": ender_count >= 2,
        "has_word_gap": max_word_gap > 0.6,
        "speaker": seg.get("speaker"),
    }


def _extract_pair_signals(a: dict, b: dict) -> dict:
    text_a = a.get("text", "").strip()
    text_b = b.get("text", "").strip()
    gap = b.get("start", 0) - a.get("end", 0)
    same_speaker = (
        a.get("speaker") is not None and
        b.get("speaker") is not None and
        a["speaker"] == b["speaker"]
    )
    incomplete_ending = len(text_a) > 0 and text_a[-1] not in SENTENCE_ENDERS
    semantic_cont = False
    if text_b:
        for cw in CONTINUATION_STARTS:
            if text_b.startswith(cw):
                semantic_cont = True
                break
        if text_b[0].islower() if (text_b and text_b[0].isalpha()) else False:
            semantic_cont = True
    merged_dur = b.get("end", 0) - a.get("start", 0)
    return {
        "gap": round(gap, 2), "same_speaker": same_speaker,
        "incomplete_ending": incomplete_ending,
        "semantic_continuation": semantic_cont,
        "duration_safe": merged_dur < 12.0,
        "merged_duration": round(merged_dur, 2),
    }
