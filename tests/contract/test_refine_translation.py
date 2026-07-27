"""
契约测试 — 质量闭环 (翻译引擎重构 Step 4)

锁定:
  - xCOMET 未加载 → 诚实降级 (全 B + 人工), 禁止虚假满分 A
  - 重翻改善 → 采纳 (新译/新分/gate 更新, 无其他 flag 时解除人工标记)
  - 重翻退化 → 回退初译 + refine_rejected + 人工审核
  - Gate A 句子不被重翻 (零浪费)
  - 无 strategy → 响亮跳过, 状态不变
  - 重翻调用失败 → 保留初译
"""
from __future__ import annotations

import pytest

from core.passes.refine_translation_pass import RefineTranslationPass
from core.ir.timeline_event import TimelineEventIR
from core.ir.project import TimelineProjectIR
from core.runtime.project_state import TimelineProjectState
from core.quality.protocol import QualityStrategy, QualityVerdict, ThresholdConfig
from core.quality.xcomet_strategy import XCometStrategy


# ── 构造工具 ─────────────────────────────────────────────────

def _make_state(specs):
    """specs: [(text, translation, gate, score), ...]"""
    events = {}
    for i, (text, trans, gate, score) in enumerate(specs, 1):
        eid = f"evt_{i:03d}"
        events[eid] = TimelineEventIR(
            id=eid, start=float(i - 1), end=float(i),
            speaker_ref="A", text_ref=text, source="asr",
        )
    proj = TimelineProjectIR(events=events, speakers={})
    state = TimelineProjectState(proj)
    for i, (text, trans, gate, score) in enumerate(specs, 1):
        es = state.get_event(f"evt_{i:03d}")
        if trans:
            es.translation["text"] = trans
            es.translation["quality_score"] = score
        es.review["gate_decision"] = gate
        if gate in ("B", "C"):
            es.review["needs_human_review"] = True
    return state


class _TextBasedStrategy(QualityStrategy):
    """按译文内容打分的假策略: 含 'good' → 0.9, 否则 0.3。"""
    name = "fake"

    @property
    def thresholds(self) -> ThresholdConfig:
        return ThresholdConfig(accept=0.7, review=0.4)

    def score_batch(self, state) -> dict:
        out = {}
        for es in state.sorted_events():
            t = es.translation.get("text", "")
            if not t:
                continue
            score = 0.9 if "good" in t else 0.3
            out[es.id] = QualityVerdict.from_score(score, self.thresholds, self.name)
        return out


# ── xCOMET 诚实降级 ─────────────────────────────────────────

def test_xcomet_not_loaded_honest_degradation():
    state = _make_state([("Hello.", "你好", "A", 0.9)])
    strategy = XCometStrategy()          # 不 warmup → _model None
    verdicts = strategy.score_batch(state)
    v = verdicts["evt_001"]
    assert v.gate_decision == "B"        # 不是虚假 A
    assert v.score == 0.0
    assert v.needs_human is True
    assert v.reason == "xcomet_not_loaded"


# ── 重翻闭环 ─────────────────────────────────────────────────

def test_refine_accepted_when_improved():
    state = _make_state([("Hello.", "烂译", "C", 0.3)])
    fn_calls = []

    def _fn(user, system):
        fn_calls.append(user)
        assert "烂译" in user             # 对比提示含初译
        assert "Hello." in user
        return "good translation"

    RefineTranslationPass(
        translate_fn=_fn, quality_strategy=_TextBasedStrategy(),
        concurrency=1,
    ).apply(state)

    es = state.get_event("evt_001")
    assert es.translation["text"] == "good translation"
    assert es.translation["quality_score"] == 0.9
    assert es.review["gate_decision"] == "A"
    assert es.review["needs_human_review"] is False
    assert len(fn_calls) == 1


def test_refine_rejected_when_not_improved():
    state = _make_state([("Hello.", "初译", "B", 0.3)])

    def _fn(user, system):
        return "still bad"               # 不含 good → 0.3, 未改善

    RefineTranslationPass(
        translate_fn=_fn, quality_strategy=_TextBasedStrategy(),
        concurrency=1,
    ).apply(state)

    es = state.get_event("evt_001")
    assert es.translation["text"] == "初译"          # 回退
    assert es.translation["quality_score"] == 0.3
    assert "refine_rejected" in es.review["flags"]
    assert es.review["needs_human_review"] is True


def test_gate_a_events_not_refined():
    state = _make_state([
        ("One.", "好译文 good", "A", 0.9),
        ("Two.", "烂译", "C", 0.3),
    ])
    fn_calls = []
    RefineTranslationPass(
        translate_fn=lambda u, s: fn_calls.append(u) or "good x",
        quality_strategy=_TextBasedStrategy(), concurrency=1,
    ).apply(state)
    assert len(fn_calls) == 1            # 只重翻 C 那句
    assert "Two." in fn_calls[0]


def test_no_strategy_skips_loud():
    state = _make_state([("Hello.", "烂译", "C", 0.3)])
    RefineTranslationPass(translate_fn=lambda u, s: "good x",
                          quality_strategy=None).apply(state)
    es = state.get_event("evt_001")
    assert es.translation["text"] == "烂译"          # 状态不变


def test_refine_fn_failure_keeps_original():
    state = _make_state([("Hello.", "初译", "B", 0.3)])
    from pipeline.translation_llm import TranslationError

    def _fn(user, system):
        raise TranslationError("模拟重翻失败")

    RefineTranslationPass(
        translate_fn=_fn, quality_strategy=_TextBasedStrategy(),
        concurrency=1,
    ).apply(state)
    es = state.get_event("evt_001")
    assert es.translation["text"] == "初译"
    assert "refine_rejected" not in es.review.get("flags", [])
