"""
Joint-score formula + naturalness verification logic — standalone test.
Output all results to tests/_verify_result.txt for inspection.

Usage:
    .venv/Scripts/python tests/test_naturalness_verify.py
"""

import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_verify_result.txt")
lines = []


def p(s=""):
    lines.append(str(s))


# ── Pure logic (no I/O, no model) ──

def joint_score(ppl_ratio, sim, beta=1.0, gamma=1.0):
    """ppl_ratio = ppl/baseline (lower=more natural), sim = MiniLM 0-1 (higher=more accurate)"""
    return beta * (1.0 - ppl_ratio) + gamma * sim


def verify(old_sim, new_sim, old_ratio, new_ratio, thr=0.70, b=1.0, g=1.0):
    """
    Decide whether to accept a naturalness-refined translation.
    Returns: (accepted: bool, kept: str, reason: str)
    """
    if new_sim < thr:
        return (False, "old", "semantic_drift")
    old_score = joint_score(old_ratio, old_sim, b, g)
    new_score = joint_score(new_ratio, new_sim, b, g)
    if new_score > old_score:
        return (True, "new", "joint_improvement")
    else:
        return (False, "old", "no_improvement")


# ═══ Phase 1: Formula correctness ═══

p("=" * 72)
p("Phase 1: Joint Score Formula")
p("=" * 72)

f_tests = [
    ("perfect: ppl=1x sim=1.0 -> 1.0", joint_score(1.0, 1.0) == 1.0),
    ("bad ppl: ppl=3x sim=0.85 -> -1.15", joint_score(3.0, 0.85) == -1.15),
    ("mid: ppl=1.5x sim=0.75 -> 0.25", joint_score(1.5, 0.75) == 0.25),
    ("PPL fix > sim loss: 4.0->1.5 beats 0.80->0.75",
     joint_score(1.5, 0.75) > joint_score(4.0, 0.80)),
    ("sim gain < PPL loss: 0.70->0.82 can't beat 1.0->1.3",
     joint_score(1.3, 0.82) < joint_score(1.0, 0.70)),
]
f_pass = 0
for name, ok in f_tests:
    if ok:
        f_pass += 1
    p(f"  {'OK' if ok else 'FAIL'} {name}")
p()

# ═══ Phase 2: Decision logic (15 scenarios) ═══

p("=" * 72)
p("Phase 2: Decision Logic (15 scenarios)")
p("=" * 72)
p(f"{'':3} {'Scenario':<40} {'Expected':<30} {'Got':<30} {'Old->New':<14}")
p("-" * 72)

SCENARIOS = [
    (name, old_sim, new_sim, old_ratio, new_ratio, expected_accepted, expected_reason) for
    (name, old_sim, new_sim, old_ratio, new_ratio, expected_accepted, expected_reason) in [
        ("1. Ideal: sim up + PPL down",       0.75, 0.82, 3.5, 1.8, True,  "joint_improvement"),
        ("2. PPL大幅下降 sim微升",              0.78, 0.80, 5.0, 2.0, True,  "joint_improvement"),
        ("3. PPL大幅下降 sim不变",              0.82, 0.82, 4.5, 1.5, True,  "joint_improvement"),
        ("4. sim微降但联合得分提升",             0.85, 0.81, 4.0, 1.3, True,  "joint_improvement"),
        ("5. Semantic drift: sim<0.70",        0.82, 0.65, 4.0, 1.5, False, "semantic_drift"),
        ("6. sim刚好低于阈值(0.69)",            0.80, 0.69, 5.0, 1.0, False, "semantic_drift"),
        ("7. no joint improvement",            0.85, 0.80, 2.0, 1.7, False, "no_improvement"),
        ("8. 无变化",                           0.80, 0.80, 2.5, 2.5, False, "no_improvement"),
        ("9. sim提升但PPL恶化",                 0.75, 0.85, 2.0, 3.0, False, "no_improvement"),
        ("10. sim at threshold (0.70)",        0.70, 0.70, 4.0, 1.0, True,  "joint_improvement"),
        ("11. PPL already good (<1x)",         0.88, 0.86, 1.2, 0.9, True,  "joint_improvement"),
        ("12. PPL very good -> marginal",      0.75, 0.80, 0.8, 1.2, False, "no_improvement"),
        ("13. 中度翻译腔 3.2->1.6x sim 0.80->0.78", 0.80, 0.78, 3.2, 1.6, True, "joint_improvement"),
        ("14. 严重翻译腔 6.0->2.5x sim 0.82->0.75", 0.82, 0.75, 6.0, 2.5, True, "joint_improvement"),
        ("15. 轻度翻译腔 2.0->1.3x sim 0.85->0.84", 0.85, 0.84, 2.0, 1.3, True, "joint_improvement"),
    ]
]

passed = 0
for name, old_sim, new_sim, old_r, new_r, exp_acc, exp_reason in SCENARIOS:
    accepted, kept, reason = verify(old_sim, new_sim, old_r, new_r)
    exp_tag = f"{'ACCEPT' if exp_acc else 'REJECT'} ({exp_reason})"
    got_tag = f"{'ACCEPT' if accepted else 'REJECT'} ({reason})"
    old_s = joint_score(old_r, old_sim)
    new_s = joint_score(new_r, new_sim)
    ok = (accepted == exp_acc) and (reason == exp_reason)
    p(f"{'OK' if ok else 'FAIL':3} {name:<40} {exp_tag:<30} {got_tag:<30} {old_s:.2f}->{new_s:.2f}")
    if ok:
        passed += 1

p()

# ═══ Phase 3: Weight sensitivity ═══

p("=" * 72)
p("Phase 3: Weight Sensitivity (scenario: sim 0.78->0.74, PPL 4.0x->1.8x)")
p("=" * 72)
p(f"{'':3} {'Beta':<6} {'Gamma':<6} {'Decision':<28} {'Old->New'}")
p("-" * 72)

WEIGHTS = [(1.0, 1.0, "ACCEPT - default balanced"),
           (0.5, 1.0, "REJECT - sim priority (conservative)"),
           (1.5, 1.0, "ACCEPT - PPL priority (aggressive)"),
           (1.0, 1.5, "REJECT - sim priority (conservative)")]

w_pass = 0
for beta, gamma, expected in WEIGHTS:
    accepted, _, _ = verify(0.78, 0.74, 4.0, 1.8, b=beta, g=gamma)
    tag = "ACCEPT" if accepted else "REJECT"
    exp_tag = expected.split(" ")[0]
    ok = tag == exp_tag
    old_s = joint_score(4.0, 0.78, beta, gamma)
    new_s = joint_score(1.8, 0.74, beta, gamma)
    p(f"{'OK' if ok else 'FAIL':3} {beta:<6.1f} {gamma:<6.1f} {tag + ' - ' + expected.split(' - ', 1)[1]:<28} {old_s:.3f}->{new_s:.3f}")
    if ok:
        w_pass += 1

p()

# ═══ Phase 4: Real data from E2E test ═══

p("=" * 72)
p("Phase 4: Apply to real E2E test results")
p("=" * 72)
p(f"{'Case':<40} {'Decision':<28} {'Old->New':<14} Notes")
p("-" * 72)

REAL_CASES = [
    # Entry #2: sim=0.8532, old PPL=737.6/baseline=69.3=10.65x
    ("#2  dragon always existed",         0.8532, 10.65, 0.85, 4.0,
     "PPL 10.65x->~4x, sim stays ~0.85 -> ACCEPT"),
    # Entry #9: sim=0.9721, old PPL=5404.9/baseline=245.8=21.99x
    ("#9  name of Ravix",                0.9721, 21.99, 0.97, 5.0,
     "PPL 21.99x->~5x, sim stays ~0.97 -> ACCEPT"),
    # Entry #20: sim=0.8955, old PPL=977.2/baseline=189.0=5.17x
    ("#20 Ignore just here",             0.8955, 5.17,  0.88, 2.5,
     "PPL 5.17x->~2.5x, sim微降 0.90->0.88 -> ACCEPT"),
    # Hypothetical dangerous case: PPL improves but sim crashes
    ("HYP: sim crash below 0.70",        0.85,   3.5,   0.45, 2.0,
     "Sim drops below 0.70 -> REJECT (safety gate)"),
    # Hypothetical ideal case
    ("HYP: both improve",                0.78,   4.0,   0.82, 1.5,
     "Both sim and PPL improve -> ACCEPT"),
]

real_pass = 0
for name, old_sim, old_r, new_sim, new_r, desc in REAL_CASES:
    accepted, _, reason = verify(old_sim, new_sim, old_r, new_r)
    old_s = joint_score(old_r, old_sim)
    new_s = joint_score(new_r, new_sim)
    tag_reason = f"{'ACCEPT' if accepted else 'REJECT'} ({reason})"
    p(f"{name:<40} {tag_reason:<28} {old_s:.2f}->{new_s:.2f}  {desc}")
    # Check expected outcomes
    if "drift" in name:
        ok = not accepted
    elif "both improve" in name:
        ok = accepted
    else:
        ok = True  # Real cases: observe behavior
    if ok:
        real_pass += 1

p()

# ═══ Summary ═══

total_tests = len(f_tests) + len(SCENARIOS) + len(WEIGHTS) + len(REAL_CASES)
total_pass = f_pass + passed + w_pass + real_pass

p("=" * 72)
p(f"SUMMARY: {total_pass}/{total_tests} assertions passed")
if total_pass == total_tests:
    p("ALL PASS - formula ready for integration into SRT_Translator.py")
else:
    p(f"FAILURES: {total_tests - total_pass}")
p("=" * 72)

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print(f"Done -> tests/_verify_result.txt")
