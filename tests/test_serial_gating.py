"""Test: serial gating logic — MiniLM gate → PPL gate → naturalness retry"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.ppl_evaluator import PPLEvaluator

e = PPLEvaluator()

bad = "那么，我们就直线跳跃进去吧。"
good = "那我们直接开始吧。"
source = "So, let's just jump straight into it."
baseline = 63.0

ppl_bad = e.perplexity(bad)
ppl_good = e.perplexity(good)

print(f"源文: {source}")
print()
print("=== 串行门控模拟 ===")
print(f"MiniLM gate: 0.75 ≥ 0.70 → PASS to PPL gate")

ratio_bad = ppl_bad / baseline
flagged = ratio_bad > 3.0
print(f"PPL gate: PPL={ppl_bad:.0f} / baseline({baseline}) = {ratio_bad:.1f}x > 3.0 → flagged={flagged}")
if flagged:
    print(f"  → trigger naturalness retry (RefineContrast prompt)")
    print(f"  → expect output like: '{good}'")

ratio_good = ppl_good / baseline
flagged2 = ratio_good > 3.0
print()
print(f"自然版: PPL={ppl_good:.0f} / baseline({baseline}) = {ratio_good:.1f}x → flagged={flagged2}")
print(f"  → {'retry' if flagged2 else 'PASS ✓'}")

print()
if flagged and not flagged2:
    print("✅ 串行门控正确: 翻译腔被拦截, 自然翻译放行")
else:
    print(" FAIL")
