"""
TextGate + EmotionGate 单元测试全覆盖 (批次9)
"""
import pytest
from core.gates.text_gate import TextGate
from core.gates.emotion_gate import EmotionGate
from core.emotion.emotion_space import EmotionVector


@pytest.mark.unit
class TestTextGateA:

    def test_pass_high_sim(self):
        r = TextGate(semantic_threshold=0.70).decide(0.85, 0.88, 1.2, 0.9)
        assert r.accepted

    def test_fail_low_sim(self):
        r = TextGate(semantic_threshold=0.70).decide(0.85, 0.60, 1.0, 1.0)
        assert not r.accepted
        assert r.reason == "semantic_drift"

    def test_boundary_exact(self):
        r = TextGate(semantic_threshold=0.70).decide(0.70, 0.70, 1.2, 0.9)
        assert r.accepted

    def test_near_zero(self):
        r = TextGate(semantic_threshold=0.70).decide(0.01, 0.01, 1.0, 1.0)
        assert not r.accepted


@pytest.mark.unit
class TestTextGateB:

    def test_ppl_improved(self):
        r = TextGate(mode="logic_gate").decide(0.88, 0.87, 1.5, 0.9)
        assert r.accepted

    def test_ppl_degraded(self):
        r = TextGate(mode="logic_gate").decide(0.88, 0.87, 0.8, 1.5)
        assert not r.accepted

    def test_equal_ppl(self):
        r = TextGate(mode="logic_gate").decide(0.88, 0.87, 1.2, 0.8)
        assert r.accepted


@pytest.mark.unit
class TestTextGateC:

    def test_small_sim_drop(self):
        r = TextGate(sim_drop_limit=0.05).decide(0.90, 0.87, 1.0, 1.0)
        assert r is not None

    def test_large_sim_drop(self):
        r = TextGate(sim_drop_limit=0.05).decide(0.90, 0.82, 1.0, 1.0)
        assert not r.accepted


@pytest.mark.unit
class TestTextGateJoint:

    def test_balanced(self):
        r = TextGate(mode="joint_formula", beta=0.6, gamma=0.4).decide(0.8, 0.85, 1.0, 0.5)
        assert r.accepted

    def test_low_score(self):
        r = TextGate(mode="joint_formula", beta=0.6, gamma=0.4).decide(0.4, 0.45, 1.0, 0.8)
        assert not r.accepted


@pytest.mark.unit
class TestEmotionGate:

    def test_e2_pass(self):
        cur = EmotionVector(emotion=0.5, valence=0.5, arousal=0.5, dominance=0.5, confidence=0.8, intensity=0.4)
        assert EmotionGate(max_break=1.5, min_confidence=0.3, max_conflict=1.0).decide(cur).accepted

    def test_e2_fail(self):
        cur = EmotionVector(emotion=0.5, valence=0.5, arousal=0.5, dominance=0.5, confidence=0.1, intensity=0.4)
        assert not EmotionGate(max_break=1.5, min_confidence=0.3, max_conflict=1.0).decide(cur).accepted
