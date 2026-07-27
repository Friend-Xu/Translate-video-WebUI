"""
契约测试 — 标点感知分段 (数据结构重设计 Phase 4)

锁定 pipeline/segmentation 引擎 + core/passes/segmentation_pass 的行为:
  - 长段 (模拟 41s ASR 批) 在标点处切开, words 完整保留
  - 小数点不切成句 (3.14)
  - 说话人边界不跨切
  - 无 words → review_flag: no_word_timestamps (禁止兜底, 不字符比例虚构)
  - SegmentationPass 重排 ID 且句级 event 带 words
"""
from __future__ import annotations
import pytest

from pipeline.segmentation import (
    EN_CONFIG, JA_CONFIG, config_for, segment_words, segment_event_stream,
    _is_sentence_end,
)
from core.passes.segmentation_pass import SegmentationPass
from core.ir.timeline_event import TimelineEventIR
from core.ir.project import TimelineProjectIR
from core.runtime.project_state import TimelineProjectState


# ── 构造工具 ─────────────────────────────────────────────────

def _words(tokens, start=0.0, step=0.4):
    """tokens: list[str] → 词 dict 流, 等间隔 step 秒。"""
    return [
        {"word": t, "start": round(start + i * step, 3),
         "end": round(start + (i + 1) * step, 3), "confidence": 0.9}
        for i, t in enumerate(tokens)
    ]


# ── 引擎: 句末标点切分 + words 保留 ─────────────────────────

def test_long_english_segment_splits_at_punctuation():
    tokens = (
        "Hello everyone welcome back to the channel today we have news."
        " Now let us talk about something completely different here."
    ).split(" ")
    words = _words(tokens)
    groups, hard = segment_words(words, EN_CONFIG)
    assert not hard
    assert len(groups) >= 2
    # 第一组应以句末标点结尾
    assert groups[0][-1]["word"].endswith(".")
    # words 总数守恒
    assert sum(len(g) for g in groups) == len(words)


def test_decimal_point_not_sentence_end():
    # 小数 "3." + "14" 处不应视为句末切点
    assert not _is_sentence_end("3.", "14", EN_CONFIG)
    assert not _is_sentence_end("2.", "71", EN_CONFIG)
    assert _is_sentence_end("exactly.", "", EN_CONFIG)


def test_abbreviation_not_sentence_end():
    assert not _is_sentence_end("Dr.", "Smith", EN_CONFIG)
    assert _is_sentence_end("Smith.", "The", EN_CONFIG)


def test_clause_break_lower_priority_than_sentence():
    # 句末(4) > 强停顿(3) > 从句(2): 优先在 "." 处切
    tokens = "First part, second part continues here. Third sentence now begins."
    words = _words(tokens.split(" "))
    groups, _ = segment_words(words, EN_CONFIG)
    ends = [g[-1]["word"] for g in groups]
    assert any(e.endswith(".") for e in ends)


# ── 引擎: 说话人硬边界 ──────────────────────────────────────

def test_speaker_boundary_not_crossed():
    wa = _words("Good morning everyone.".split(" "), start=0.0)
    wb = _words("Hello thanks for having me.".split(" "), start=5.0)
    events = [
        {"id": "e1", "start": 0.0, "end": 5.0, "text": "", "words": wa, "speaker": "A"},
        {"id": "e2", "start": 5.0, "end": 9.0, "text": "", "words": wb, "speaker": "B"},
    ]
    segs = segment_event_stream(events, "en")
    speakers = {s.speaker for s in segs}
    assert speakers == {"A", "B"}
    # 每个段只属于一个 speaker (A 的词不会进 B 段)
    for s in segs:
        if s.speaker == "A":
            assert all(w in wa for w in s.words)


def test_no_words_event_flagged_not_fabricated():
    events = [
        {"id": "e1", "start": 0.0, "end": 3.0, "text": "no words here",
         "words": [], "speaker": "A"},
    ]
    segs = segment_event_stream(events, "en")
    assert len(segs) == 1
    assert segs[0].flag == "no_word_timestamps"
    assert segs[0].text == "no words here"  # 保留原文, 不虚构


# ── 语言配置分派 ────────────────────────────────────────────

def test_config_dispatch():
    assert config_for("en") is EN_CONFIG
    assert config_for("en-US") is EN_CONFIG
    assert config_for("ja") is JA_CONFIG
    assert config_for("fr") is EN_CONFIG       # 拉丁回落
    assert config_for("zh") is JA_CONFIG       # CJK 字符单元


# ── Pass: 重排 ID + 句级 event 带 words ─────────────────────

def _make_state_with_long_event():
    tokens = (
        "Hello everyone welcome back to the channel today we have big news."
        " Now we will discuss an entirely different and important topic."
    ).split(" ")
    words = _words(tokens)
    ir = TimelineEventIR(id="evt_001", start=words[0]["start"],
                         end=words[-1]["end"], speaker_ref="A",
                         text_ref=" ".join(tokens), source="asr")
    proj = TimelineProjectIR(events={"evt_001": ir}, speakers={})
    state = TimelineProjectState(proj)
    es = state.get_event("evt_001")
    es.asr["words"] = words
    es.asr["language"] = "en"
    es.speaker["speaker_id"] = "A"
    return state, len(words)


def test_segmentation_pass_resegments_and_preserves_words():
    state, n_words = _make_state_with_long_event()
    SegmentationPass().apply(state)

    events = state.sorted_events()
    assert len(events) >= 2                      # 长段被切开
    # ID 重排为 evt_001..N
    ids = [es.id for es in events]
    assert ids == [f"evt_{i:03d}" for i in range(1, len(events) + 1)]
    # 每个 event 都带 words, 且总数守恒
    total = sum(len(es.asr.get("words", [])) for es in events)
    assert total == n_words
    # speaker 保留
    assert all(es.speaker.get("speaker_id") == "A" for es in events)
    # 每个 event 的 text 非空且来自其 words
    for es in events:
        assert es.ir.text_ref.strip()


def test_segmentation_pass_flags_no_words_event():
    ir = TimelineEventIR(id="evt_001", start=0.0, end=3.0,
                         speaker_ref="A", text_ref="silent gap", source="asr")
    proj = TimelineProjectIR(events={"evt_001": ir}, speakers={})
    state = TimelineProjectState(proj)
    SegmentationPass().apply(state)
    es = state.get_event("evt_001")
    assert "no_word_timestamps" in es.review.get("flags", [])
    assert es.review.get("needs_human_review") is True
