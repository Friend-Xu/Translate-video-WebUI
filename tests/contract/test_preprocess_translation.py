"""
契约测试 — 翻译预处理 bible (翻译引擎重构 Step 2)

锁定预处理链的行为契约:
  - PreprocessTranslationPass 产出 bible 写 state.ir.translation_bible
  - 幂等: 已有 bible 跳过; force 重生成
  - 证据校验门: src/wrong 不在原文 → 丢弃; count 按原文重算
  - L0 人工词典: 冲突人工赢 + 置前 + origin 溯源
  - persist/load 往返: translation_bible 完整保留 (Phase 2 互逆原则)
  - 下游: LLMTranslationPass 的 system prompt 含 bible 术语
  - 禁止兜底: 预处理 LLM 失败 → TranslationError 上抛, 不静默空 bible
"""
from __future__ import annotations

import pytest

from core.passes.preprocess_translation_pass import PreprocessTranslationPass
from core.passes.llm_translation_pass import LLMTranslationPass
from core.ir.timeline_event import TimelineEventIR
from core.ir.project import TimelineProjectIR
from core.runtime.project_state import TimelineProjectState
from core.runtime import timeline_io
from pipeline.translation_bible import (
    TranslationBible, parse_bible_response, merge_manual_glossary,
)
from pipeline.translation_llm import TranslationError


# ── 构造工具 ─────────────────────────────────────────────────

def _make_state(specs):
    events = {}
    for i, (text, spk) in enumerate(specs, 1):
        eid = f"evt_{i:03d}"
        events[eid] = TimelineEventIR(
            id=eid, start=float(i - 1), end=float(i),
            speaker_ref=spk, text_ref=text, source="asr",
        )
    proj = TimelineProjectIR(events=events, speakers={})
    return TimelineProjectState(proj)


_TRANSCRIPT_TEXTS = [
    ("Today we review the LEGO set and the GPU performance.", "A"),
    ("The Transformer model inside is impressive.", "A"),
    ("You can run java script on it too.", "B"),
]

_LLM_OUTPUT = {
    "domain": "tech_review",
    "summary": "一个硬件评测视频。",
    "style_guide": "口语化, 面向爱好者。",
    "hotwords": [
        {"src": "LEGO", "dst": "乐高"},
        {"src": "GPU", "dst": "GPU"},
        {"src": "Hallucinated", "dst": "幻觉词"},     # 不在原文 → 必须被丢
    ],
    "corrections": [
        {"wrong": "java script", "correct": "JavaScript"},
        {"wrong": "not in text", "correct": "x"},      # 不在原文 → 必须被丢
    ],
}


class _PreprocessFn:
    def __init__(self, output=None, fail=False):
        self.calls = 0
        self.output = output if output is not None else _LLM_OUTPUT
        self.fail = fail

    def __call__(self, prompt: str) -> dict:
        self.calls += 1
        if self.fail:
            raise TranslationError("模拟预处理失败")
        return self.output


# ── Pass: 生成 + 幂等 ───────────────────────────────────────

def test_preprocess_writes_bible_to_state():
    state = _make_state(_TRANSCRIPT_TEXTS)
    fn = _PreprocessFn()
    PreprocessTranslationPass(preprocess_fn=fn, manual_terms={}).apply(state)

    bible = TranslationBible.from_dict(state.ir.translation_bible)
    assert bible.domain == "tech_review"
    assert bible.summary == "一个硬件评测视频。"
    srcs = [h["src"] for h in bible.hotwords]
    assert "LEGO" in srcs and "GPU" in srcs


def test_preprocess_idempotent_and_force():
    state = _make_state(_TRANSCRIPT_TEXTS)
    fn = _PreprocessFn()
    p = PreprocessTranslationPass(preprocess_fn=fn, manual_terms={},
                                  enable_profiles=False)
    p.apply(state)
    p.apply(state)                       # 第二次应跳过
    assert fn.calls == 1

    PreprocessTranslationPass(preprocess_fn=fn, manual_terms={}, force=True,
                              enable_profiles=False).apply(state)
    assert fn.calls == 2


def test_preprocess_failure_raises_loud():
    state = _make_state(_TRANSCRIPT_TEXTS)
    with pytest.raises(TranslationError):
        PreprocessTranslationPass(preprocess_fn=_PreprocessFn(fail=True),
                                  manual_terms={}).apply(state)


# ── 证据校验门 ───────────────────────────────────────────────

def test_evidence_gate_drops_hallucinations():
    state = _make_state(_TRANSCRIPT_TEXTS)
    PreprocessTranslationPass(preprocess_fn=_PreprocessFn(), manual_terms={}).apply(state)
    bible = TranslationBible.from_dict(state.ir.translation_bible)

    srcs = [h["src"] for h in bible.hotwords]
    assert "Hallucinated" not in srcs          # 无原文证据被丢
    wrongs = [c["wrong"] for c in bible.corrections]
    assert "java script" in wrongs
    assert "not in text" not in wrongs


def test_count_recomputed_from_transcript():
    data = {"hotwords": [{"src": "GPU", "dst": "显卡"}]}
    bible = parse_bible_response(data, "GPU and GPU and GPU", engine="test")
    assert bible.hotwords[0]["count"] == 3     # 不信 LLM, 按原文重算


# ── L0 人工词典 ─────────────────────────────────────────────

def test_manual_glossary_wins_conflict_and_prepends():
    bible = TranslationBible(hotwords=[
        {"src": "GPU", "dst": "图形处理器", "count": 5},
        {"src": "LEGO", "dst": "乐高", "count": 2},
    ])
    merged = merge_manual_glossary(bible, {"GPU": "显卡"})
    assert merged.hotwords[0] == {
        "src": "GPU", "dst": "显卡", "count": 0, "origin": "manual",
    }
    dsts = {h["src"]: h["dst"] for h in merged.hotwords}
    assert dsts["GPU"] == "显卡"               # 人工赢
    assert dsts["LEGO"] == "乐高"              # 无冲突保留
    assert sum(1 for h in merged.hotwords if h["src"] == "GPU") == 1


# ── persist/load 往返 ───────────────────────────────────────

def test_bible_persist_load_roundtrip(tmp_path):
    state = _make_state(_TRANSCRIPT_TEXTS)
    PreprocessTranslationPass(preprocess_fn=_PreprocessFn(), manual_terms={}).apply(state)
    before = state.ir.translation_bible
    assert before

    path = timeline_io.persist_state(state, str(tmp_path), "fake.mp4", "en")
    loaded = timeline_io.load_state(path)
    assert loaded.ir.translation_bible == before


# ── 下游集成: 翻译 prompt 含 bible 术语 ──────────────────────

def test_translate_prompt_contains_bible_terms():
    state = _make_state(_TRANSCRIPT_TEXTS)
    PreprocessTranslationPass(preprocess_fn=_PreprocessFn(), manual_terms={}).apply(state)

    calls = []
    LLMTranslationPass(
        translate_fn=lambda u, s: calls.append((u, s)) or "译文",
        concurrency=1,
    ).apply(state)
    assert calls
    system = calls[0][1]
    assert "LEGO -> 乐高" in system
    assert "java script -> JavaScript" in system
    assert "一个硬件评测视频" in system


# ── 说话人画像 (Step 3) ─────────────────────────────────────

_PROFILE_OUTPUT = {
    "speakers": {
        "A": {"role": "主持人", "register": "随意口语", "notes": "爱开玩笑"},
        "B": {"role": "嘉宾", "register": "正式讲解", "notes": "技术背景"},
        "GHOST": {"role": "幻觉", "register": "x", "notes": "x"},  # 不存在 → 丢
    },
}


def test_speaker_profiles_generated():
    state = _make_state(_TRANSCRIPT_TEXTS)
    fn = _PreprocessFn()

    def _profile_fn(prompt: str) -> dict:
        assert "[A]" in prompt and "[B]" in prompt   # 分 speaker 聚合样本
        return _PROFILE_OUTPUT

    PreprocessTranslationPass(preprocess_fn=fn, profile_fn=_profile_fn,
                              manual_terms={}).apply(state)
    bible = TranslationBible.from_dict(state.ir.translation_bible)
    assert bible.speakers["A"]["role"] == "主持人"
    assert bible.speakers["B"]["register"] == "正式讲解"
    assert "GHOST" not in bible.speakers            # 画像门: 幻觉 id 丢弃


def test_profile_failure_degrades_loud():
    state = _make_state(_TRANSCRIPT_TEXTS)

    def _bad_profile(prompt: str) -> dict:
        raise TranslationError("画像调用失败")

    # 不得抛异常; bible 主体仍在, 仅无画像
    PreprocessTranslationPass(preprocess_fn=_PreprocessFn(),
                              profile_fn=_bad_profile, manual_terms={}).apply(state)
    bible = TranslationBible.from_dict(state.ir.translation_bible)
    assert bible.domain == "tech_review"
    assert bible.speakers == {}


def test_translate_system_has_per_speaker_tail():
    state = _make_state(_TRANSCRIPT_TEXTS)

    def _profile_fn(prompt: str) -> dict:
        return _PROFILE_OUTPUT

    PreprocessTranslationPass(preprocess_fn=_PreprocessFn(),
                              profile_fn=_profile_fn, manual_terms={}).apply(state)

    calls = []
    LLMTranslationPass(
        translate_fn=lambda u, s: calls.append((u, s)) or "译文",
        concurrency=1,
    ).apply(state)
    systems = {s for _, s in calls}
    assert len(systems) == 2                         # A/B 各一份
    # 名册在双方 prompt 里都有, 区分只看尾部"当前句说话人"
    sys_a = next(s for s in systems if "当前句说话人: A" in s)
    sys_b = next(s for s in systems if "当前句说话人: B" in s)
    assert "主持人, 随意口语" in sys_a.split("当前句说话人")[-1]
    assert "嘉宾, 正式讲解" in sys_b.split("当前句说话人")[-1]
    # 共享前缀: 两份 prompt 前 60% 逐字节一致 (缓存命中段)
    common = 0
    for ca, cb in zip(sys_a, sys_b):
        if ca != cb:
            break
        common += 1
    assert common > len(sys_a) * 0.6
