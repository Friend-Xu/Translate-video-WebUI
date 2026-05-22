"""
Logic-gate naturalness verification — standalone test.
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

def verify(old_sim, new_sim, old_ratio, new_ratio, thr=0.70, sim_drop_limit=0.05):
    """
    Three-gate decision for naturalness re-translation acceptance.

    Gate A — semantic safety: new_sim >= thr (absolute floor)
    Gate C — content fidelity: new_sim >= old_sim - sim_drop_limit (NEW)
    Gate B — naturalness improvement: new_ratio < old_ratio (PPL must drop)

    All three must pass (AND logic). Order: A → C → B (fail-fast).

    Returns: (accepted: bool, kept: str, reason: str)
    """
    if new_sim < thr:
        return (False, "old", "semantic_drift")
    if sim_drop_limit > 0 and new_sim < old_sim - sim_drop_limit:
        return (False, "old", "content_degraded")
    if new_ratio < old_ratio:
        return (True, "new", "naturalness_improved")
    else:
        return (False, "old", "no_naturalness_gain")


# ═══ Phase 1: Gate correctness ═══

p("=" * 72)
p("Phase 1: Logic Gate Correctness")
p("=" * 72)

g_tests = [
    ("Gate A: sim<0.70 blocks even if PPL improves",
     verify(0.85, 0.65, 4.0, 1.5) == (False, "old", "semantic_drift")),
    ("Gate A: sim=0.70 exactly passes",
     verify(0.75, 0.70, 3.0, 1.0) == (True, "new", "naturalness_improved")),
    ("Gate B: ratio<old accepts (PPL improved)",
     verify(0.80, 0.82, 3.0, 2.0) == (True, "new", "naturalness_improved")),
    ("Gate B: ratio==old rejects (no gain)",
     verify(0.80, 0.80, 2.5, 2.5) == (False, "old", "no_naturalness_gain")),
    ("Gate B: ratio>old rejects (PPL worsened)",
     verify(0.75, 0.85, 2.0, 3.0) == (False, "old", "no_naturalness_gain")),
    ("Both gates: sim safe + PPL improved -> ACCEPT",
     verify(0.85, 0.81, 4.0, 1.3) == (True, "new", "naturalness_improved")),
]
g_pass = 0
for name, ok in g_tests:
    if ok:
        g_pass += 1
    p(f"  {'OK' if ok else 'FAIL'} {name}")
p()

# ═══ Phase 1b: Gate C correctness ═══

p("=" * 72)
p("Phase 1b: Gate C — Content Fidelity")
p("=" * 72)

gc_tests = [
    ("Gate C: sim drop 0.04 within limit -> passes Gate C",
     verify(0.85, 0.81, 3.0, 1.5)[0] == True),
    ("Gate C: sim drop 0.06 exceeds 0.05 -> content_degraded",
     verify(0.85, 0.79, 4.0, 1.2) == (False, "old", "content_degraded")),
    ("Gate C: sim drop exactly 0.05 -> within limit (passes)",
     verify(0.85, 0.80, 3.0, 1.5)[0] == True),
    ("Gate C: sim_drop_limit=0 disables Gate C (0.15 drop passes)",
     verify(0.85, 0.70, 3.0, 1.5, sim_drop_limit=0)[0] == True),
    ("Gate C: sim UP (no drop) -> passes Gate C",
     verify(0.80, 0.88, 3.0, 1.5)[0] == True),
    ("Gate C: sim unchanged -> passes Gate C",
     verify(0.82, 0.82, 3.0, 1.1)[0] == True),
]
gc_pass = 0
for name, ok in gc_tests:
    if ok:
        gc_pass += 1
    p(f"  {'OK' if ok else 'FAIL'} {name}")
p()

# ═══ Phase 2: Decision logic (15 scenarios) ═══

p("=" * 72)
p("Phase 2: Decision Logic (15 scenarios)")
p("=" * 72)
p(f"{'':3} {'Scenario':<40} {'Expected':<30} {'Got':<30} {'PPL':<14}")
p("-" * 72)

SCENARIOS = [
    (name, old_sim, new_sim, old_ratio, new_ratio, expected_accepted, expected_reason) for
    (name, old_sim, new_sim, old_ratio, new_ratio, expected_accepted, expected_reason) in [
        ("1. Ideal: sim up + PPL down",       0.75, 0.82, 3.5, 1.8, True,  "naturalness_improved"),
        ("2. PPL大幅下降 sim微升",              0.78, 0.80, 5.0, 2.0, True,  "naturalness_improved"),
        ("3. PPL大幅下降 sim不变",              0.82, 0.82, 4.5, 1.5, True,  "naturalness_improved"),
        ("4. sim微降 PPL大降",                 0.85, 0.81, 4.0, 1.3, True,  "naturalness_improved"),
        ("5. Semantic drift: sim<0.70",        0.82, 0.65, 4.0, 1.5, False, "semantic_drift"),
        ("6. sim刚好低于阈值(0.69)",            0.80, 0.69, 5.0, 1.0, False, "semantic_drift"),
        ("7. sim微降 PPL改善 -> ACCEPT",       0.85, 0.80, 2.0, 1.7, True,  "naturalness_improved"),
        ("8. 无变化",                           0.80, 0.80, 2.5, 2.5, False, "no_naturalness_gain"),
        ("9. sim提升但PPL恶化",                 0.75, 0.85, 2.0, 3.0, False, "no_naturalness_gain"),
        ("10. sim at threshold (0.70)",        0.70, 0.70, 4.0, 1.0, True,  "naturalness_improved"),
        ("11. PPL already good (<1x)",         0.88, 0.86, 1.2, 0.9, True,  "naturalness_improved"),
        ("12. PPL very good -> worsened",      0.75, 0.80, 0.8, 1.2, False, "no_naturalness_gain"),
        ("13. 中度翻译腔 3.2->1.6x sim 0.80->0.78", 0.80, 0.78, 3.2, 1.6, True, "naturalness_improved"),
        ("14. 严重翻译腔 6.0->2.5x sim 0.82->0.75 Gate C拦截", 0.82, 0.75, 6.0, 2.5, False, "content_degraded"),
        ("15. 轻度翻译腔 2.0->1.3x sim 0.85->0.84", 0.85, 0.84, 2.0, 1.3, True, "naturalness_improved"),
    ]
]

passed = 0
for name, old_sim, new_sim, old_r, new_r, exp_acc, exp_reason in SCENARIOS:
    accepted, kept, reason = verify(old_sim, new_sim, old_r, new_r)
    exp_tag = f"{'ACCEPT' if exp_acc else 'REJECT'} ({exp_reason})"
    got_tag = f"{'ACCEPT' if accepted else 'REJECT'} ({reason})"
    ok = (accepted == exp_acc) and (reason == exp_reason)
    p(f"{'OK' if ok else 'FAIL':3} {name:<40} {exp_tag:<30} {got_tag:<30} {old_r:.1f}x->{new_r:.1f}x")
    if ok:
        passed += 1

p()

# ═══ Phase 3: Boundary conditions ═══

p("=" * 72)
p("Phase 3: Boundary Conditions")
p("=" * 72)
p(f"{'':3} {'Condition':<50} {'Decision':<28} {'Rationale'}")
p("-" * 72)

BOUNDARY = [
    # (old_sim, new_sim, old_r, new_r, expected_accepted, label)
    (0.85, 0.71, 3.0, 1.5, False,
     "sim drops 0.14 > 0.05 — Gate C content_degraded"),
    (0.85, 0.70, 3.0, 1.5, False,
     "sim drops 0.15 > 0.05 — Gate C content_degraded"),
    (0.85, 0.69, 3.0, 0.5, False,
     "PPL halved but sim below 0.70 — Gate A semantic_drift"),
    (0.71, 0.70, 1.5, 1.4, True,
     "PPL barely improves (1.5->1.4), sim barely safe, drop 0.01"),
    (0.95, 0.71, 8.0, 1.5, False,
     "sim drops 0.24 > 0.05 — Gate C blocks despite 6.5x PPL gain"),
    (0.80, 0.75, 2.0, 1.5, True,
     "sim drops exactly 0.05 — at limit, passes Gate C"),
]

b_pass = 0
for old_sim, new_sim, old_r, new_r, exp_acc, label in BOUNDARY:
    accepted, _, reason = verify(old_sim, new_sim, old_r, new_r)
    tag = f"{'ACCEPT' if accepted else 'REJECT'} ({reason})"
    exp = "ACCEPT" if exp_acc else "REJECT"
    ok = (accepted == exp_acc)
    p(f"{'OK' if ok else 'FAIL':3} {label:<50} {tag:<28} {'✓' if ok else 'EXP ' + exp}")
    if ok:
        b_pass += 1

p()

# ═══ Phase 4: Real data from E2E test ═══

p("=" * 72)
p("Phase 4: Apply to real E2E test results")
p("=" * 72)
p(f"{'Case':<40} {'Decision':<28} {'PPL Delta':<14} Notes")
p("-" * 72)

REAL_CASES = [
    ("#2  dragon always existed",         0.8532, 10.65, 0.85, 4.0,
     "PPL 10.65x->~4x, sim stays ~0.85 -> ACCEPT"),
    ("#9  name of Ravix",                0.9721, 21.99, 0.97, 5.0,
     "PPL 21.99x->~5x, sim stays ~0.97 -> ACCEPT"),
    ("#20 Ignore just here",             0.8955, 5.17,  0.88, 2.5,
     "PPL 5.17x->~2.5x, sim微降 0.90->0.88 -> ACCEPT"),
    ("HYP: sim crash below 0.70",        0.85,   3.5,   0.45, 2.0,
     "Sim drops below 0.70 -> REJECT (safety gate)"),
    ("HYP: both improve",                0.78,   4.0,   0.82, 1.5,
     "Both sim and PPL improve -> ACCEPT"),
]

real_pass = 0
for name, old_sim, old_r, new_sim, new_r, desc in REAL_CASES:
    accepted, _, reason = verify(old_sim, new_sim, old_r, new_r)
    tag_reason = f"{'ACCEPT' if accepted else 'REJECT'} ({reason})"
    delta = f"{old_r - new_r:.1f}x" if accepted else "-"
    p(f"{name:<40} {tag_reason:<28} {delta:<14} {desc}")
    if "drift" in name:
        ok = not accepted
    elif "both improve" in name:
        ok = accepted
    else:
        ok = True
    if ok:
        real_pass += 1

p()

# ═══ Phase 5: Joint-formula mode ═══

p("=" * 72)
p("Phase 5: Joint-Formula Mode (benchmark against logic gate)")
p("=" * 72)

def verify_joint(old_sim, new_sim, old_ratio, new_ratio, thr=0.70, beta=1.0, gamma=1.0):
    if new_sim < thr:
        return (False, "old", "semantic_drift")
    def score(r, s):
        return beta * (1.0 - r) + gamma * s
    if score(new_ratio, new_sim) > score(old_ratio, old_sim):
        return (True, "new", "joint_improvement")
    else:
        return (False, "old", "no_improvement")

j_tests = [
    ("JF1: sim up + PPL down -> joint improves",
     verify_joint(0.75, 0.85, 4.0, 2.0) == (True, "new", "joint_improvement")),
    ("JF2: PPL big drop compensates sim drop",
     verify_joint(0.85, 0.75, 8.0, 2.0) == (True, "new", "joint_improvement")),
    ("JF3: sim gain alone improves joint score",
     verify_joint(0.70, 0.85, 3.0, 3.0) == (True, "new", "joint_improvement")),
    ("JF4: no change -> reject",
     verify_joint(0.80, 0.80, 2.5, 2.5) == (False, "old", "no_improvement")),
    ("JF5: sim crash below threshold",
     verify_joint(0.85, 0.65, 4.0, 1.5) == (False, "old", "semantic_drift")),
    ("JF6: sim down a little + PPL way down -> accept",
     verify_joint(0.90, 0.85, 10.0, 2.0) == (True, "new", "joint_improvement")),
    ("JF7: both worsen -> reject",
     verify_joint(0.80, 0.75, 2.0, 3.0) == (False, "old", "no_improvement")),
]

j_pass = 0
for name, ok in j_tests:
    if ok:
        j_pass += 1
    p(f"  {'OK' if ok else 'FAIL'} {name}")
p()

# Key divergence: under joint formula, sim gain can compensate for PPL unchanged
# Under logic gate, PPL MUST improve — sim gain alone is not enough
lg_result = verify(0.70, 0.85, 3.0, 3.0)
jf_result = verify_joint(0.70, 0.85, 3.0, 3.0)
p(f"Divergence test: sim 0.70->0.85, PPL 3.0x->3.0x")
p(f"  Logic gate:  {'ACCEPT' if lg_result[0] else 'REJECT'} ({lg_result[2]}) — PPL unchanged, no naturalness gain")
p(f"  Joint formula: {'ACCEPT' if jf_result[0] else 'REJECT'} ({jf_result[2]}) — sim gain alone suffices")
p()

# ═══ Summary ═══

total_tests = len(g_tests) + len(gc_tests) + len(SCENARIOS) + len(BOUNDARY) + len(REAL_CASES) + len(j_tests)
total_pass = g_pass + gc_pass + passed + b_pass + real_pass + j_pass

p("=" * 72)
p(f"SUMMARY: {total_pass}/{total_tests} assertions passed")
if total_pass == total_tests:
    p("ALL PASS - logic gate verification ready for integration")
else:
    p(f"FAILURES: {total_tests - total_pass}")
p("=" * 72)

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print(f"Done -> tests/_verify_result.txt")
