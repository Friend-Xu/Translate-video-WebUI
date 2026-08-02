"""
xCOMET 阈值校准工具 — 用真实 xCOMET-lite 对工作区翻译重新打分, 输出分布 + 建议阈值

用法:
    python tools/calibrate_xcomet.py [timeline.json ...]
    不传参数则自动扫描 test_trail/**/timeline.json 与各 *_project 工作区

输出:
    每工作区统计 + 总体分位数 + 建议 accept/review 阈值
    (建议: accept = P75, review = P15 — 保留 25% 复审余量, 15% 重翻)
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import glob
import statistics


def collect_pairs(paths: list[str]) -> list[dict]:
    pairs = []
    for p in paths:
        if not os.path.isfile(p):
            continue
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception as e:
            print(f"[skip] {p}: {e}")
            continue
        for e in d.get("events", []):
            tr = e.get("translation")
            if not isinstance(tr, dict):
                continue
            src = (e.get("text") or e.get("text_ref") or "").strip()
            mt = (tr.get("text") or "").strip()
            if src and mt:
                pairs.append({"file": p, "src": src, "mt": mt})
    return pairs


def score_pairs(pairs: list[dict]) -> list[float]:
    from core.quality.xcomet_strategy import XCometStrategy

    strategy = XCometStrategy()
    strategy.warmup()
    if strategy._model is None:
        raise RuntimeError("xCOMET-lite 加载失败 — 检查 models/XCOMET-lite 与 mdeberta-v3-base")
    out = strategy._model.predict(
        [{"src": p["src"], "mt": p["mt"]} for p in pairs],
        batch_size=8,
        gpus=1 if __import__("torch").cuda.is_available() else 0,
    )
    return list(out.scores)


def percentile(vals: list[float], q: float) -> float:
    """q in [0,1] — 线性插值分位数"""
    vals = sorted(vals)
    if not vals:
        return 0.0
    k = (len(vals) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(vals) - 1)
    return vals[lo] + (vals[hi] - vals[lo]) * (k - lo)


def main() -> None:
    paths = sys.argv[1:]
    if not paths:
        paths = sorted(glob.glob("test_trail/**/timeline.json", recursive=True))
    pairs = collect_pairs(paths)
    if not pairs:
        print("没有可评分的 (源, 译文) 对")
        sys.exit(1)

    print(f"评分 {len(pairs)} 对 (batch=8, {'GPU' if __import__('torch').cuda.is_available() else 'CPU'})...")
    scores = score_pairs(pairs)

    from collections import defaultdict
    by_file = defaultdict(list)
    for p, s in zip(pairs, scores):
        by_file[p["file"]].append(s)

    for f, ss in sorted(by_file.items()):
        print(f"  {os.path.basename(os.path.dirname(f)) or f}: n={len(ss)} "
              f"min={min(ss):.3f} median={statistics.median(ss):.3f} max={max(ss):.3f}")

    accept = percentile(scores, 0.75)
    review = percentile(scores, 0.15)
    print("\n── 总体分布 (n=%d) ──" % len(scores))
    print("  min   P15   P25   median P75   max")
    print(f"  {min(scores):.3f} {percentile(scores, 0.15):.3f} {percentile(scores, 0.25):.3f} "
          f"{statistics.median(scores):.3f} {percentile(scores, 0.75):.3f} {max(scores):.3f}")
    print("\n建议阈值 (accept=P75, review=P15):")
    print(f"  threshold_accept = {accept:.2f}")
    print(f"  threshold_reject = {review:.2f}")

    # 最低分样例 (复核坏译文是否真的坏)
    worst = sorted(zip(scores, pairs), key=lambda x: x[0])[:3]
    print("\n最低分 3 条 (人工复核):")
    for s, p in worst:
        print(f"  {s:.3f}  {p['src'][:30]!r} => {p['mt'][:30]!r}")


if __name__ == "__main__":
    main()
