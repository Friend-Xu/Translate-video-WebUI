"""
契约测试 — 质量策略 (logic_gate | xcomet) 选择接线 + 诚实降级

锁死 E2E 集成结论:
  1. gate.mode 配置决定策略 (GlobalConfig translation.gate.mode)
  2. xCOMET-lite 用本地模型 (XCOMETLite 加载器), 非 transformers 直载
  3. 模型缺失 → 诚实降级 B + 人工审核, 不给虚假满分
"""
import pytest
from core.ir import TimelineEventIR, TimelineProjectIR
from core.runtime import TimelineProjectState
from core.passes.translation_quality_pass import TranslationQualityPass


def _state_with_translation() -> TimelineProjectState:
    evts = {
        "e1": TimelineEventIR(id="e1", start=0.0, end=1.0,
                              speaker_ref=None, text_ref="こんにちは"),
    }
    state = TimelineProjectState(TimelineProjectIR(events=evts, speakers={}))
    state.get_event("e1").translation.text = "你好"
    return state


@pytest.mark.contract
class TestStrategySelection:
    def _fake_factory(self, monkeypatch, calls):
        """monkeypatch create_strategy → 记录调用 + 返回无害策略。"""
        from core.quality import protocol
        from types import SimpleNamespace

        def fake_create(name, config=None):
            calls.append(name)
            return SimpleNamespace(
                name=name, warmup=lambda: None,
                score_batch=lambda state: {},
            )

        monkeypatch.setattr(protocol, "create_strategy", fake_create)

    def test_gate_mode_drives_strategy(self, monkeypatch):
        """gate.mode=xcomet → create_strategy('xcomet') (E2E 集成接线)。"""
        calls = []
        self._fake_factory(monkeypatch, calls)
        p = TranslationQualityPass()
        p.configure({"translation": {"gate": {"mode": "xcomet"}}})
        p.apply(_state_with_translation())
        assert calls == ["xcomet"]

    def test_unconfigured_fallback_is_xcomet(self, monkeypatch):
        """无 gate.mode 配置 → 默认 xcomet (2026-08-01 起 xcomet 为默认策略)。"""
        calls = []
        self._fake_factory(monkeypatch, calls)
        p = TranslationQualityPass()
        p.configure({"translation": {"gate": {}}})
        p.apply(_state_with_translation())
        assert calls == ["xcomet"]


@pytest.mark.contract
class TestXCometHonestDegrade:
    def test_missing_model_degrades_to_gate_b(self, monkeypatch):
        """xCOMET-lite 模型缺失 → 全部 Gate B + 人工审核 (禁止兜底: 不给假满分)。"""
        import core.quality.xcomet_strategy as xs
        monkeypatch.setattr(xs, "_WT_PATH",
                            "models/XCOMET-lite/definitely_missing.bin")
        from core.quality.protocol import create_strategy
        s = create_strategy("xcomet")
        s.warmup()  # 加载尝试 (路径缺失 → 失败)
        assert s._model is None
        state = _state_with_translation()
        verdicts = s.score_batch(state)
        v = verdicts["e1"]
        assert v.gate_decision == "B"
        assert v.needs_human is True
        assert v.score == 0.0
        assert v.reason == "xcomet_not_loaded"

    def test_register_strategy_available(self):
        """xcomet 策略注册可用 (create_strategy 懒加载后)。"""
        from core.quality.protocol import create_strategy
        s = create_strategy("xcomet")
        assert s.name == "xcomet"
