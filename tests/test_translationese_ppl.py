"""Quick test: Qwen2-0.5B perplexity for translationese detection.

Compares sentence-level perplexity between natural Chinese
and translationese (word-for-word literal translation) sentences.

Usage:
    .venv/Scripts/python tests/test_translationese_ppl.py
"""

import os
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(PROJECT_ROOT, "models")
os.environ["HF_HOME"] = os.path.join(MODELS_DIR, "hf_cache")
os.environ["HF_HUB_CACHE"] = os.path.join(MODELS_DIR, "hub")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

TEST_PAIRS = [
    (
        "So, let's just jump straight into it.",
        "那我们直接开始吧。",
        "那么，我们就直线跳跃进去吧。",
    ),
    (
        "Let's call it a day.",
        "今天就到这里吧。",
        "让我们称之为一天吧。",
    ),
    (
        "What's up, everyone?",
        "大家好啊。",
        "向上的是什么，每个人？",
    ),
    (
        "I'll show you the ropes.",
        "我来教你怎么玩。",
        "我会给你展示绳索。",
    ),
    (
        "That makes sense.",
        "有道理。",
        "那制造了感觉。",
    ),
    (
        "Hang in there!",
        "坚持住！",
        "挂在那里！",
    ),
    (
        "See you next time.",
        "下次见。",
        "在下次看到你。",
    ),
]

MODEL_ID = "Qwen/Qwen2-0.5B"
LOCAL_PATH = os.path.join(MODELS_DIR, "Qwen", "Qwen2-0.5B")


def load_model(local_path=None):
    path = local_path or LOCAL_PATH
    print(f"[load] model={path}")
    t0 = time.time()
    tokenizer = AutoTokenizer.from_pretrained(
        path, trust_remote_code=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        path,
        torch_dtype=torch.float16,
        device_map="auto",
        trust_remote_code=True,
    )
    model.eval()
    print(f"[load] done in {time.time() - t0:.1f}s")
    return model, tokenizer


def sentence_ppl(model, tokenizer, text: str) -> dict:
    inputs = tokenizer(text, return_tensors="pt").to(model.device)
    input_ids = inputs["input_ids"]
    num_tokens = input_ids.shape[1]
    if num_tokens < 2:
        return {"nll": 0.0, "ppl": 0.0, "num_tokens": 0}
    with torch.no_grad():
        outputs = model(**inputs, labels=input_ids)
        total_nll = outputs.loss.item() * num_tokens
    avg_nll = total_nll / num_tokens
    ppl = torch.exp(torch.tensor(avg_nll)).item()
    return {"nll": round(avg_nll, 4), "ppl": round(ppl, 2), "num_tokens": num_tokens}


def main():
    print("=" * 65)
    print("Qwen2-0.5B 翻译腔困惑度测试")
    print("=" * 65)

    model, tokenizer = load_model()

    results = []
    for source, natural, bad in TEST_PAIRS:
        nat = sentence_ppl(model, tokenizer, natural)
        bad_r = sentence_ppl(model, tokenizer, bad)
        delta = round(bad_r["ppl"] - nat["ppl"], 2)
        winner = (
            "✅ 自然" if nat["ppl"] < bad_r["ppl"]
            else ("❌ 翻译腔更低" if nat["ppl"] > bad_r["ppl"] else "➖ 持平")
        )
        results.append({
            "source": source, "natural": natural, "bad": bad,
            "nat_ppl": nat["ppl"], "bad_ppl": bad_r["ppl"],
            "delta": delta, "winner": winner,
        })

    print(f"\n{'原文':<44} delta")
    print(f"{'自然中文  vs  翻译腔中文':<44} (越低越好)")
    print("-" * 65)
    for r in results:
        print(f"\n源: {r['source'][:60]}")
        print(f"  ✅ 自然  [{r['nat_ppl']:.2f}]  {r['natural']}")
        print(f"  ⚠ 翻译腔 [{r['bad_ppl']:.2f}]  {r['bad']}")
        print(f"  → delta={r['delta']:+.1f} → {r['winner']}")

    print("\n" + "=" * 65)
    wins = sum(1 for r in results if "✅" in r["winner"])
    losses = sum(1 for r in results if "❌" in r["winner"])
    ties = sum(1 for r in results if "➖" in r["winner"])
    avg_delta = sum(r["delta"] for r in results) / len(results)
    print(f"Summary: {wins} win / {losses} loss / {ties} tie | avg delta = {avg_delta:+.1f}")
    if wins > len(results) * 0.7:
        print("✅ 信号足够强，困惑度可以用于翻译腔检测")
    else:
        print("⚠ 信号偏弱，需要进一步验证或换模型")


if __name__ == "__main__":
    main()
