"""
契约测试 — 逐句翻译引擎 (翻译引擎重构 Step 1)

锁定新翻译链的行为契约:
  - 每个有 text 的 event 必须得到译文, 否则 flag 人工 (完整性, 禁静默缺失)
  - 邻居上下文窗口: 跨 speaker, 当前句 [待译] 标注, 边界不补占位
  - system prompt 跨调用字节一致 (DeepSeek 前缀缓存前提)
  - 逐句失败 → 该句 flag, 其他句不受影响, apply 不抛异常
  - translation slot 为 dict {text, engine} (Phase 1 契约)
  - bible 渲染器确定性 + 转录预算截断响亮标记
  - LLM 客户端: JSON 提取/重试/无 key 响亮报错
"""
from __future__ import annotations

import pytest

from core.passes.llm_translation_pass import LLMTranslationPass, build_user_message
from core.ir.timeline_event import TimelineEventIR
from core.ir.project import TimelineProjectIR
from core.runtime.project_state import TimelineProjectState
from pipeline.translation_bible import (
    TranslationBible, render_system_prompt, render_transcript,
)
from pipeline.translation_llm import (
    SentenceTranslator, TranslationError, _extract_dst,
)


# ── 构造工具 ─────────────────────────────────────────────────

def _make_state(specs):
    """specs: [(text, speaker), ...] → state (事件 evt_001..N)。"""
    events = {}
    for i, (text, spk) in enumerate(specs, 1):
        eid = f"evt_{i:03d}"
        events[eid] = TimelineEventIR(
            id=eid, start=float(i - 1), end=float(i),
            speaker_ref=spk, text_ref=text, source="asr",
        )
    proj = TimelineProjectIR(events=events, speakers={})
    return TimelineProjectState(proj)


class _Recorder:
    """记录全部 (user, system) 调用的假翻译函数。"""

    def __init__(self, fail_on: str | None = None):
        self.calls: list[tuple[str, str]] = []
        self.fail_on = fail_on

    def __call__(self, user: str, system: str) -> str:
        self.calls.append((user, system))
        current = next((l for l in user.split("\n") if l.startswith("[待译]")), "")
        if self.fail_on and self.fail_on in current:
            raise TranslationError("模拟翻译失败")
        return "译文:" + current


# ── Pass: 完整性 + slot 契约 ────────────────────────────────

def test_all_events_translated_and_slot_shape():
    state = _make_state([
        ("Hello everyone.", "SPEAKER_00"),
        ("How are you?", "SPEAKER_01"),
        ("I am fine.", "SPEAKER_00"),
    ])
    rec = _Recorder()
    LLMTranslationPass(translate_fn=rec, concurrency=1).apply(state)

    assert len(rec.calls) == 3
    for es in state.sorted_events():
        assert es.translation.text.startswith("译文:")
        assert es.translation.engine == "llm"
        assert not es.review.needs_human_review


def test_events_without_text_are_skipped():
    state = _make_state([("Hello.", "A"), ("", "A"), ("World.", "B")])
    rec = _Recorder()
    LLMTranslationPass(translate_fn=rec, concurrency=1).apply(state)
    assert len(rec.calls) == 2
    assert state.get_event("evt_002").translation.text == ""


def test_failure_flags_only_failed_sentence():
    state = _make_state([
        ("Good morning.", "A"),
        ("FAIL_ME please.", "B"),
        ("Goodbye.", "A"),
    ])
    rec = _Recorder(fail_on="FAIL_ME")
    # apply 不得抛异常
    LLMTranslationPass(translate_fn=rec, concurrency=1).apply(state)

    assert state.get_event("evt_001").translation.text.startswith("译文:")
    bad = state.get_event("evt_002")
    assert bad.translation.text == ""
    assert "translation_failed" in bad.review.flags
    assert bad.review.needs_human_review is True
    assert state.get_event("evt_003").translation.text.startswith("译文:")


# ── 邻居窗口 ────────────────────────────────────────────────

def test_user_message_neighbor_window_crosses_speakers():
    items = [
        {"id": "e1", "text": "What do you think?", "speaker": "A"},
        {"id": "e2", "text": "It is overpriced.", "speaker": "B"},
        {"id": "e3", "text": "Only five percent faster.", "speaker": "B"},
    ]
    msg = build_user_message(items, 1, window=1)
    lines = msg.split("\n")
    assert len(lines) == 3
    assert lines[0].startswith("[上下文·勿译] [A] What do you think?")
    assert lines[1] == "[待译] [B] It is overpriced."
    assert lines[2].startswith("[上下文·勿译] [B]")


def test_user_message_boundary_no_placeholder():
    items = [
        {"id": "e1", "text": "First.", "speaker": None},
        {"id": "e2", "text": "Second.", "speaker": None},
    ]
    msg = build_user_message(items, 0, window=1)
    lines = msg.split("\n")
    assert lines[0] == "[待译] First."   # 首句无前邻居, 不补占位
    assert len(lines) == 2


# ── system prompt 稳定性 (前缀缓存前提) ─────────────────────

def test_system_prompt_byte_identical_across_calls():
    state = _make_state([
        ("One.", "A"), ("Two.", "B"), ("Three.", "A"), ("Four.", "B"),
    ])
    rec = _Recorder()
    LLMTranslationPass(translate_fn=rec, concurrency=1).apply(state)
    systems = {s for _, s in rec.calls}
    assert len(systems) == 1          # 全部调用共享同一 system prompt


def test_render_system_prompt_deterministic():
    bible = TranslationBible(
        summary="一个评测视频",
        hotwords=[{"src": "GPU", "dst": "显卡"}],
    )
    a = render_system_prompt(bible, "en", "zh", transcript="[evt_001][A] hi")
    b = render_system_prompt(bible, "en", "zh", transcript="[evt_001][A] hi")
    assert a == b
    assert "GPU -> 显卡" in a
    assert "一个评测视频" in a
    assert "json" in a                  # json_object 模式要求 prompt 含 json


def test_speaker_section_goes_last():
    bible = TranslationBible(speakers={
        "A": {"role": "host", "register": "casual", "notes": ""},
    })
    p1 = render_system_prompt(bible, "en", "zh", transcript="T", current_speaker="A")
    p2 = render_system_prompt(bible, "en", "zh", transcript="T", current_speaker=None)
    assert p1.endswith("casual")
    assert p1.startswith(p2[:200])      # 共享前缀一致


# ── 转录渲染预算 ─────────────────────────────────────────────

def test_transcript_over_budget_marks_omission():
    events = [
        {"id": f"evt_{i:03d}", "speaker": "A", "text": "x" * 200}
        for i in range(1, 201)
    ]
    out = render_transcript(events, budget_tokens=1000)
    assert "省略" in out
    assert "evt_001" in out and "evt_200" in out   # 头尾保留


def test_transcript_under_budget_intact():
    events = [{"id": "evt_001", "speaker": "A", "text": "hello"}]
    assert render_transcript(events) == "[evt_001][A] hello"


# ── LLM 客户端 ───────────────────────────────────────────────

def test_extract_dst_strict():
    assert _extract_dst('{"dst": "你好"}') == "你好"
    assert _extract_dst('前缀{"dst": "你好"}后缀') == "你好"
    with pytest.raises(TranslationError):
        _extract_dst('{"wrong": "你好"}')
    with pytest.raises(TranslationError):
        _extract_dst("not json at all")
    with pytest.raises(TranslationError):
        _extract_dst('{"dst": "  "}')


def test_no_api_key_fails_loud():
    with pytest.raises(TranslationError, match="api_key|API key"):
        SentenceTranslator(api_key="")


def test_retry_then_raise(monkeypatch):
    calls = {"n": 0}

    class _FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "garbage"}}], "usage": {}}

    import requests
    monkeypatch.setattr(requests, "post", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1) or _FakeResp())
    t = SentenceTranslator(api_key="k", max_retries=2)
    with pytest.raises(TranslationError, match="重试"):
        t.translate("user", "system")
    assert calls["n"] == 2


def test_success_parses_dst(monkeypatch):
    class _FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [{"message": {"content": '{"dst": "你好"}'}}],
                "usage": {"prompt_cache_hit_tokens": 90, "prompt_cache_miss_tokens": 10},
            }

    import requests
    monkeypatch.setattr(requests, "post", lambda *a, **k: _FakeResp())
    t = SentenceTranslator(api_key="k")
    assert t.translate("user", "system") == "你好"
