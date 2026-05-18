"""
测试三级翻译管道对中英混合输出的可行性：
  批量翻译 → 语义检查(MiniLM) → 自然度检查(PPL/Qwen2)

模拟：LLM 保留 Minecraft 模组名不翻译，验证语义分和 PPL 分是否仍通过。

用法：
    .venv/Scripts/python tests/test_mixed_lang_quality.py
"""
from __future__ import annotations

import time
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── 样本数据 ──────────────────────────────────
# 格式: (英文原文, 纯中文翻译, 中英混合翻译)
SAMPLES = [
    (
        "Royal variations has been around for a while now, the idea of the mod was to add captain variations of the hostile vanilla maps.",
        "皇家变种已经存在了一段时间，这个模组的想法是为敌对的原版生物添加队长变种，它们更强大、更耐久。",
        "Royal Variations 已经存在了一段时间，这个模组的想法是为敌对的原版生物添加队长变种，它们更强大、更耐久。",
    ),
    (
        "Fingiz has been known for his cursed and entertaining Minecraft mods.",
        "Fingiz 因其古怪而有趣的 Minecraft 模组而闻名。",
        "Fingiz 因其古怪而有趣的 Minecraft 模组而闻名。",
    ),
    (
        "Decocraft Nature is a mod all about gardening.",
        "装饰工艺自然是一个关于园艺的模组。",
        "Decocraft Nature 是一个关于园艺的模组。",
    ),
    (
        "Next up we have Dodo's mobs, this is a mod that adds a skeleton dinosaur to fight under the jungle temple.",
        "接下来是渡渡鸟生物，这是一个在丛林神庙下添加骷髅恐龙战斗的模组。",
        "接下来是 Dodo's Mobs，这是一个在丛林神庙下添加骷髅恐龙战斗的模组。",
    ),
    (
        "The last journey is a mod that adds a few dinosaurs to the game.",
        "最后的旅程是一个为游戏添加几种恐龙的模组。",
        "The Last Journey 是一个为游戏添加几种恐龙的模组。",
    ),
    (
        "Nekto is an excellent RPG mod.",
        "Nekto 是一个优秀的 RPG 模组。",
        "Nekto 是一个优秀的 RPG 模组。",
    ),
    (
        "Holdable Frogs is a simple yet surprisingly important mod on the list.",
        "可持有的青蛙是一个简单但出人意料重要的模组。",
        "Holdable Frogs 是一个简单但出人意料重要的模组。",
    ),
    (
        "Wondrous is an immensely gratifying magic mod.",
        "奇妙是一个极其令人满意的魔法模组。",
        "Wondrous 是一个极其令人满意的魔法模组。",
    ),
    (
        "The mod is quite sophisticated, as you will need to fill up the car with fuel and use keys server up, after which you will enjoy a fast and fun drive around the world.",
        "这个模组相当复杂，因为你需要给车加油并使用钥匙启动，之后你将享受快速有趣的环球驾驶。",
        "这个模组相当复杂，因为你需要给车加油并使用钥匙启动，之后你将享受快速有趣的环球驾驶。",
    ),
    (
        "The Megascent is a deadly robot constructed by scientists from the evil organization of the Elegers.",
        "巨型机器人是由邪恶组织 Elegers 的科学家建造的致命机器人。",
        "The Megascent 是由邪恶组织 Elegers 的科学家建造的致命机器人。",
    ),
]


def test_semantic():
    """Phase 1: MiniLM 跨语言语义相似度"""
    print("\n" + "=" * 70)
    print("Phase 1: 语义检查 (MiniLM cross-lingual, threshold=0.65)")
    print("=" * 70)

    from SRT.TranslationVerifier import CrossLingualScorer
    scorer = CrossLingualScorer()

    results = []
    for en, _zh_pure, zh_mixed in SAMPLES:
        sim_pure = scorer.similarity(en, _zh_pure)
        sim_mixed = scorer.similarity(en, zh_mixed)
        diff = sim_mixed - sim_pure
        flag = "⚠" if sim_mixed < 0.65 else "✓"
        results.append((en[:60], sim_pure, sim_mixed, diff, flag))
        print(f"  {flag} pure={sim_pure:.3f}  mixed={sim_mixed:.3f}  Δ={diff:+.3f}  | {en[:55]}...")

    avg_diff = sum(r[3] for r in results) / len(results)
    failed = sum(1 for r in results if r[3] < 0.65)
    print(f"\n  平均 Δ: {avg_diff:+.3f}  未通过数: {failed}/{len(results)}")
    return results


def test_ppl():
    """Phase 2: Qwen2-0.5B PPL 自然度"""
    print("\n" + "=" * 70)
    print("Phase 2: PPL 自然度检查 (Qwen2-0.5B, threshold=3.0x baseline)")
    print("=" * 70)

    from pipeline.ppl_evaluator import PPLEvaluator
    import re

    ppl_eval = PPLEvaluator()
    _ASCII_WORD = re.compile(r'\b[A-Za-z][\w\']*\b')

    all_texts = []
    for _, _zh_pure, zh_mixed in SAMPLES:
        all_texts.append(_zh_pure)
        all_texts.append(zh_mixed)

    print("  计算 PPL (纯中文 vs 中英混合)...")
    t0 = time.time()
    ppls = ppl_eval.batch_perplexity(all_texts)
    print(f"  耗时: {time.time() - t0:.1f}s")

    # Baseline from pure Chinese
    pure_ppls = [ppls[i * 2] for i in range(len(SAMPLES))]
    mixed_ppls = [ppls[i * 2 + 1] for i in range(len(SAMPLES))]

    valid = [p for p in pure_ppls if p > 0]
    baseline = sorted(valid)[len(valid) // 2] if valid else 60.0
    threshold = baseline * 3.0

    print(f"  自适应基线 (纯中文 PPL 中位数): {baseline:.1f}")
    print(f"  自然度阈值 (3.0x): {threshold:.1f}")
    print()

    failed = 0
    for i, (en, _zh_pure, zh_mixed) in enumerate(SAMPLES):
        p_pure = pure_ppls[i]
        p_mixed = mixed_ppls[i]
        ratio = p_mixed / baseline if baseline > 0 else 0
        flag = "✓" if ratio <= 3.0 else "✗ (会触发重翻)"
        if ratio > 3.0:
            failed += 1
        print(f"  {flag} pure_ppl={p_pure:4.0f}  mixed_ppl={p_mixed:4.0f}  "
              f"ratio={ratio:.1f}x  | {en[:50]}...")

    print(f"\n  会触发自然度重翻: {failed}/{len(SAMPLES)}")


if __name__ == "__main__":
    test_semantic()
    test_ppl()
    print("\n" + "=" * 70)
    print("结论：如果语义 ≥ 0.65 且 PPL ratio ≤ 3.0x，则中英混合翻译可以通过三级管道")
    print("=" * 70)
