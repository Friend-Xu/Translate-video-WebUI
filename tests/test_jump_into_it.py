"""Test: would the quality system catch '直线跳跃进去吧'?"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.ppl_evaluator import PPLEvaluator
from pipeline.quality_assessor import naturalness_score, semantic_score, structural_score, QualityScores, assign_tier

e = PPLEvaluator()

bad = "那么，我们就直线跳跃进去吧。"
good = "那我们直接开始吧。"
source = "So, let's just jump straight into it."
baseline = 63.0

ppl_bad = e.perplexity(bad)
ppl_good = e.perplexity(good)

print(f"源文: {source}")
print()
print(f'翻译腔: "{bad}"')
print(f"  PPL={ppl_bad:.1f}, ratio={ppl_bad/baseline:.1f}x (baseline={baseline})")
nat_bad = naturalness_score(ppl_bad, baseline, 3.0)
print(f"  自然度评分: value={nat_bad.value}, flagged={nat_bad.flagged}")
print()
print(f'自然: "{good}"')
print(f"  PPL={ppl_good:.1f}, ratio={ppl_good/baseline:.1f}x")
nat_good = naturalness_score(ppl_good, baseline, 3.0)
print(f"  自然度评分: value={nat_good.value}, flagged={nat_good.flagged}")
print()

sem_bad = semantic_score(0.75, 0.70)
sem_good = semantic_score(0.85, 0.70)
st = structural_score(0, 2000, bad)

print("=== QualityScores 对比 ===")
s_bad = QualityScores(1, sem_bad, nat_bad, st)
t_bad, r_bad = assign_tier(s_bad)
print(f"翻译腔版: sem=0.75(OK) nat=FLAGGED(PPL={ppl_bad:.0f}) → tier={t_bad.value} ({r_bad})")

s_good = QualityScores(1, sem_good, nat_good, st)
t_good, r_good = assign_tier(s_good)
print(f"自然版:   sem=0.85(OK) nat=OK(PPL={ppl_good:.0f})     → tier={t_good.value} ({r_good})")

print()
if nat_bad.flagged and not nat_good.flagged:
    print("✅ 质量系统可以区分翻译腔和自然翻译")
    print(f"   '直线跳跃进去吧' 会被标记为 {t_bad.value.upper()} — 自然度 PPL 是基线的 {ppl_bad/baseline:.1f} 倍")
else:
    print("❌ 未区分出")
