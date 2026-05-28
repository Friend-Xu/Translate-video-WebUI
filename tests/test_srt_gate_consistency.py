"""批次12 §4: SRT 门控委托一致性回归测试。

验证 SRT_Translator._verify_naturalness_result() 委托到 TextGate.decide()
后，对固定输入矩阵产生一致结果。
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.gates.text_gate import TextGate, TextGateResult


# 20 个代表性 case，覆盖所有 Gate 判定路径
# (old_sim, new_sim, old_ppl_ratio, new_ppl_ratio, source_len, old_len, new_len,
#  expected_accepted, expected_reason)
GATE_CONSISTENCY_CASES = [
    # ── Gate A: 语义漂移 ──
    (0.85, 0.60, 3.0, 1.0, 10, 10, 10, False, "semantic_drift"),
    (0.90, 0.65, 2.0, 1.0, 10, 10, 10, False, "semantic_drift"),
    (0.75, 0.72, 3.0, 2.0, 10, 10, 10, True, None),

    # ── Gate C: 内容退化 ──
    (0.90, 0.82, 3.0, 1.0, 0, 0, 0, False, "content_degraded"),
    (0.88, 0.80, 2.0, 1.5, 0, 0, 0, False, "content_degraded"),
    (0.90, 0.86, 3.0, 1.0, 0, 0, 0, True, None),

    # ── Gate C: 长度膨胀 ──
    (0.85, 0.82, 3.0, 2.0, 10, 10, 30, False, "content_inflated"),
    (0.85, 0.82, 3.0, 2.0, 10, 10, 15, True, None),

    # ── Gate C: 长度收缩 ──
    (0.85, 0.82, 3.0, 2.0, 10, 10, 2, False, "content_deflated"),
    (0.85, 0.82, 3.0, 2.0, 10, 10, 5, True, None),

    # ── Gate B: 自然度改善 ──
    (0.85, 0.85, 3.0, 2.0, 0, 0, 0, True, None),

    # ── Gate B: 无自然度改善 ──
    (0.85, 0.85, 2.0, 2.5, 0, 0, 0, False, "no_naturalness_gain"),
    (0.80, 0.85, 2.0, 2.0, 0, 0, 0, False, "no_naturalness_gain"),

    # ── Gate B: 收缩守卫 ──
    (0.85, 0.82, 3.0, 2.0, 10, 10, 4, False, "content_shrunk"),
    (0.85, 0.82, 3.0, 2.0, 10, 10, 6, True, None),

    # ── 边界值 ──
    (0.70, 0.70, 1.0, 1.0, 0, 0, 0, True, None),
    (0.85, 0.85, 2.0, 2.1, 0, 0, 0, False, "no_naturalness_gain"),

    # ── 极端值 ──
    (0.95, 0.93, 1.0, 0.5, 5, 5, 8, True, None),
    (0.60, 0.40, 5.0, 0.5, 8, 8, 20, False, "semantic_drift"),
    (0.90, 0.83, 4.0, 1.0, 12, 12, 3, False, "content_degraded"),
]


def _run_gate(gate, old_sim, new_sim, old_ratio, new_ratio,
              src_len, old_len, new_len):
    return gate.decide(old_sim, new_sim, old_ratio, new_ratio,
                       source_len=src_len, old_len=old_len, new_len=new_len)


class TestSRTTextGateConsistency:
    """验证 core/ TextGate 判定逻辑与 batch 05 规范一致。"""

    @pytest.fixture
    def gate(self):
        return TextGate(
            semantic_threshold=0.70,
            sim_drop_limit=0.05,
            mode="logic_gate",
            max_len_ratio=2.0,
            min_len_ratio=0.4,
            min_shrink_ratio=0.5,
        )

    @pytest.mark.parametrize(
        "old_sim, new_sim, old_ratio, new_ratio, src_len, old_len, new_len, "
        "expected_ok, expected_reason",
        GATE_CONSISTENCY_CASES,
    )
    def test_case(self, gate, old_sim, new_sim, old_ratio, new_ratio,
                  src_len, old_len, new_len, expected_ok, expected_reason):
        r = _run_gate(gate, old_sim, new_sim, old_ratio, new_ratio,
                      src_len, old_len, new_len)
        assert r.accepted == expected_ok, \
            f"accepted mismatch: expected={expected_ok}, got={r.accepted}, reason={r.reason}"
        if expected_reason is not None:
            assert r.reason == expected_reason, \
                f"reason mismatch: expected={expected_reason}, got={r.reason}"

    def test_joint_formula_respects_gate_A(self):
        """joint_formula 模式仍遵守 Gate A 阈值"""
        gate = TextGate(semantic_threshold=0.70, mode="joint_formula")
        r = gate.decide(0.85, 0.60, 3.0, 1.0,
                        source_len=10, old_len=10, new_len=25)
        assert not r.accepted
        assert r.reason == "semantic_drift"

    def test_custom_thresholds(self):
        """自定义阈值生效"""
        gate = TextGate(
            semantic_threshold=0.50, sim_drop_limit=0.20,
            max_len_ratio=3.0, min_len_ratio=0.2, min_shrink_ratio=0.3,
        )
        r = gate.decide(0.80, 0.55, 3.0, 2.0,
                        source_len=10, old_len=10, new_len=25)
        assert r.accepted

    def test_strict_thresholds(self):
        """严格阈值增加拒绝率"""
        gate = TextGate(
            semantic_threshold=0.90, sim_drop_limit=0.01,
            max_len_ratio=1.2, min_len_ratio=0.8, min_shrink_ratio=0.9,
        )
        r = gate.decide(0.80, 0.85, 3.0, 2.0,
                        source_len=10, old_len=10, new_len=15)
        assert not r.accepted


class TestTextGateDeterminism:
    """确保 TextGate 对相同输入始终返回相同结果。"""

    def test_repeated_calls_same_result(self):
        gate = TextGate()
        params = (0.85, 0.82, 3.0, 2.0, 10, 10, 25)
        results = [gate.decide(*params) for _ in range(10)]
        assert all(r.accepted == results[0].accepted for r in results)
        assert all(r.reason == results[0].reason for r in results)
        assert all(r.kept_version == results[0].kept_version for r in results)
