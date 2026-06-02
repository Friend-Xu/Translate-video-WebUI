"""
Chapter 14 — Translation + MiniLM/PPL + TextGate 测试

覆盖: TranslationScore, TranslationScorer, TextGate (logic_gate + joint_formula)
"""
import pytest
from core.scoring.translation_scorer import TranslationScorer, TranslationScore
from core.gates.text_gate import TextGate, TextGateResult


class TestTranslationScore:

    def test_defaults(self):
        s = TranslationScore()
        assert s.semantic_similarity == 0.0
        assert s.accepted is False
        assert s.composite == 0.0

    def test_accepted_sets_decision(self):
        s = TranslationScore(accepted=True)
        assert s.gate_decision == "accept"

    def test_hard_fail_stored(self):
        s = TranslationScore(hard_fail_reason="semantic too low: 0.30")
        assert "0.30" in s.hard_fail_reason

    def test_all_fields(self):
        s = TranslationScore(semantic_similarity=0.85, fluency_score=0.75,
                             faithfulness_score=0.90, length_ratio=1.1,
                             temporal_fit=0.95, accepted=True, composite=0.82)
        assert s.semantic_similarity == 0.85
        assert s.composite == 0.82


class TestTranslationScorer:

    @pytest.fixture
    def scorer(self):
        return TranslationScorer()

    def test_perfect(self, scorer):
        s = scorer.score(semantic_similarity=0.95, ppl_ratio=0.5,
                         faithfulness=0.80, source_len=10, target_len=10)
        assert s.accepted
        assert s.gate_decision == "accept"
        assert s.composite > 0.7

    def test_low_semantic_rejected(self, scorer):
        s = scorer.score(semantic_similarity=0.30, ppl_ratio=1.0)
        assert not s.accepted
        assert s.hard_fail_reason

    def test_high_ppl_rejected(self, scorer):
        s = scorer.score(semantic_similarity=0.80, ppl_ratio=6.0)
        assert not s.accepted

    def test_length_extreme(self, scorer):
        s = scorer.score(semantic_similarity=0.80, ppl_ratio=1.0,
                         source_len=10, target_len=50)
        assert s.hard_fail_reason or not s.accepted

    def test_custom_weights(self, scorer):
        scorer.weights = {"semantic": 0.50, "fluency": 0.50,
                          "faithfulness": 0.0, "temporal_fit": 0.0, "length_ratio": 0.0}
        s = scorer.score(semantic_similarity=0.90, ppl_ratio=0.5)
        assert s.composite > 0.7

    def test_empty_text(self, scorer):
        s = scorer.score(semantic_similarity=0.70)
        assert s.length_ratio == 1.0

    def test_batch(self, scorer):
        results = scorer.score_batch([
            {"semantic_similarity": 0.90, "ppl_ratio": 1.0, "source_len": 10, "target_len": 10},
            {"semantic_similarity": 0.30, "ppl_ratio": 1.0},
        ])
        assert len(results) == 2
        assert results[0].accepted
        assert not results[1].accepted


class TestTextGate:

    @pytest.fixture
    def gate(self):
        return TextGate(semantic_threshold=0.70, sim_drop_limit=0.05, mode="logic_gate")

    def test_all_pass(self, gate):
        r = gate.decide(0.80, 0.85, 3.0, 2.0)
        assert r.accepted
        assert r.kept_version == "retry"

    def test_gate_A_drift(self, gate):
        r = gate.decide(0.85, 0.65, 3.0, 1.0)
        assert not r.accepted
        assert r.reason == "semantic_drift"

    def test_gate_A_boundary(self, gate):
        r = gate.decide(0.75, 0.70, 3.0, 1.0)
        assert r.accepted

    def test_gate_C_degraded(self, gate):
        r = gate.decide(0.90, 0.82, 3.0, 1.0)
        assert not r.accepted
        assert r.reason == "content_degraded"

    def test_gate_C_boundary(self, gate):
        r = gate.decide(0.90, 0.85, 3.0, 1.0)
        assert r.accepted

    def test_gate_B_no_gain(self, gate):
        r = gate.decide(0.80, 0.85, 2.0, 2.5)
        assert not r.accepted
        assert r.reason == "no_naturalness_gain"

    def test_gate_B_same(self, gate):
        r = gate.decide(0.80, 0.85, 2.0, 2.0)
        assert not r.accepted

    def test_sim_drop_zero_skips_C_fail_A(self, gate):
        gate.sim_drop_limit = 0.0
        r = gate.decide(0.90, 0.60, 3.0, 1.0)
        assert not r.accepted
        assert r.reason == "semantic_drift"

    def test_sim_drop_zero_passes(self, gate):
        gate.sim_drop_limit = 0.0
        r = gate.decide(0.80, 0.75, 3.0, 1.0)
        assert r.accepted


class TestTextGateLengthGuards:
    """批次12 §3.2: Gate C 膨胀/收缩守卫 + Gate B 收缩守卫"""

    @pytest.fixture
    def gate(self):
        return TextGate(semantic_threshold=0.70, sim_drop_limit=0.05,
                        max_len_ratio=2.0, min_len_ratio=0.4, min_shrink_ratio=0.5)

    # ── Gate C: 膨胀守卫 ────────────────────────────────

    def test_C_inflated_rejected(self, gate):
        """译文膨胀 > 200% 应被拒绝"""
        r = gate.decide(0.85, 0.82, 3.0, 2.0,
                        source_len=10, old_len=10, new_len=25)
        assert not r.accepted
        assert r.reason == "content_inflated"

    def test_C_inflated_boundary_pass(self, gate):
        """膨胀在 200% 以内应通过"""
        r = gate.decide(0.85, 0.82, 3.0, 2.0,
                        source_len=10, old_len=10, new_len=19)
        assert r.accepted

    def test_C_inflated_exact_double(self, gate):
        """膨胀正好 200% 应通过"""
        r = gate.decide(0.85, 0.82, 3.0, 2.0,
                        source_len=10, old_len=10, new_len=20)
        assert r.accepted

    def test_C_inflated_no_source_len_skips(self, gate):
        """无 source_len 时跳过长度守卫"""
        r = gate.decide(0.85, 0.82, 3.0, 2.0,
                        source_len=0, old_len=10, new_len=25)
        assert r.accepted

    # ── Gate C: 收缩守卫 ────────────────────────────────

    def test_C_deflated_rejected(self, gate):
        """译文收缩 < 40% 应被拒绝"""
        r = gate.decide(0.85, 0.82, 3.0, 2.0,
                        source_len=10, old_len=10, new_len=3)
        assert not r.accepted
        assert r.reason == "content_deflated"

    def test_C_deflated_boundary_pass(self, gate):
        """收缩在 40% 以上应通过"""
        r = gate.decide(0.85, 0.82, 3.0, 2.0,
                        source_len=10, old_len=10, new_len=5)
        assert r.accepted

    def test_C_deflated_no_source_len_skips(self, gate):
        """无 source_len 时跳过收缩守卫"""
        r = gate.decide(0.85, 0.82, 3.0, 2.0,
                        source_len=0, old_len=10, new_len=1)
        assert r.accepted

    # ── Gate B: 收缩守卫 ────────────────────────────────

    def test_B_shrunk_rejected(self, gate):
        """PPL 改善但长度收缩 >50% 应被拒绝"""
        r = gate.decide(0.85, 0.82, 3.0, 2.0,
                        source_len=10, old_len=10, new_len=4)
        assert not r.accepted
        assert r.reason == "content_shrunk"

    def test_B_shrunk_boundary_pass(self, gate):
        """PPL 改善，收缩在 50% 以内应通过"""
        r = gate.decide(0.85, 0.82, 3.0, 2.0,
                        source_len=10, old_len=10, new_len=6)
        assert r.accepted

    def test_B_shrunk_no_source_len_skips(self, gate):
        """无 source_len 时跳过 B 收缩守卫"""
        r = gate.decide(0.85, 0.82, 3.0, 2.0,
                        source_len=0, old_len=10, new_len=2)
        assert r.accepted

    def test_B_shrunk_no_gain_still_works(self, gate):
        """PPL 无改善 + source_len=0 仍被 B 拒绝"""
        r = gate.decide(0.85, 0.82, 2.0, 2.5)
        assert not r.accepted
        assert r.reason == "no_naturalness_gain"

    # ── 组合场景 ────────────────────────────────────────

    def test_C_inflated_before_B_shrink(self, gate):
        """Gate C 膨胀先于 Gate B 收缩被检查"""
        r = gate.decide(0.85, 0.82, 3.0, 2.0,
                        source_len=10, old_len=10, new_len=30)
        assert not r.accepted
        assert r.reason == "content_inflated"

    def test_gate_A_rejects_before_length_checks(self, gate):
        """Gate A 语义漂移先被拦截，跳过长度守卫"""
        r = gate.decide(0.85, 0.60, 3.0, 1.0,
                        source_len=10, old_len=10, new_len=30)
        assert not r.accepted
        assert r.reason == "semantic_drift"

    def test_sim_drop_rejects_before_length_checks(self, gate):
        """Gate C sim drop 先被拦截，跳过长度守卫"""
        r = gate.decide(0.90, 0.82, 3.0, 1.0,
                        source_len=10, old_len=10, new_len=30)
        assert not r.accepted
        assert r.reason == "content_degraded"


class TestTextGateJointFormula:

    @pytest.fixture
    def gate(self):
        return TextGate(semantic_threshold=0.70, mode="joint_formula")

    def test_improved(self, gate):
        r = gate.decide(0.80, 0.85, 0.3, 0.2)
        assert r.accepted
        assert r.reason == "joint_improved"

    def test_not_improved(self, gate):
        r = gate.decide(0.90, 0.85, 0.2, 0.3)
        assert not r.accepted

    def test_gate_A_still(self, gate):
        r = gate.decide(0.85, 0.65, 3.0, 0.1)
        assert not r.accepted
        assert r.reason == "semantic_drift"


class TestTextGateResult:

    def test_fields(self):
        r = TextGateResult(True, "accept", "retry", "ok",
                           {"old_sim": 0.8}, {"gates_checked": ["A", "C", "B"]})
        assert r.accepted
        assert r.scores["old_sim"] == 0.8
        assert "A" in r.gate_trace["gates_checked"]

    def test_defaults(self):
        r = TextGateResult(True, "accept", "retry", "ok")
        assert r.scores == {}
