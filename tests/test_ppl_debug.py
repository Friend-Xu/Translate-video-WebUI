"""Debug: test PPL evaluation on 20 translated subtitles directly."""
import os, sys, time, json, traceback

PROJECT_ROOT = r"D:\Workspace\Translate_video"
sys.path.insert(0, PROJECT_ROOT)

ERR_FILE = os.path.join(PROJECT_ROOT, "tests", "_ppl_debug.txt")

try:
    import pysrt
    AUTO_SRT = os.path.join(PROJECT_ROOT, "tests", "e2e_naturalness_20", "source_20-auto.srt")
    subs = pysrt.open(AUTO_SRT, encoding="utf-8")

    texts = [s.text for s in subs]
    log_lines = [f"Loaded {len(texts)} texts from {AUTO_SRT}"]

    from pipeline.ppl_evaluator import PPLEvaluator
    import torch
    log_lines.append(f"CUDA: {torch.cuda.is_available()}, device: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'cpu'}")

    t0 = time.time()
    evaluator = PPLEvaluator()
    log_lines.append(f"PPLEvaluator init: {time.time()-t0:.1f}s, device={evaluator._device_str}")

    t0 = time.time()
    ppls = evaluator.batch_perplexity(texts)
    elapsed = time.time() - t0
    log_lines.append(f"PPL batch done: {elapsed:.1f}s, valid: {sum(1 for p in ppls if p>0)}/{len(ppls)}")

    valid = sorted([p for p in ppls if p > 0])
    baseline = valid[len(valid)//3] if len(valid) >= 3 else (valid[0] if valid else 60.0)
    log_lines.append(f"Baseline: {baseline:.1f}")
    log_lines.append("")
    log_lines.append(f"{'Idx':>4} {'PPL':>8} {'Ratio':>7} {'Flag':>6} {'Text'}")
    log_lines.append("-" * 72)
    for s, ppl in zip(subs, ppls):
        ratio = ppl / baseline if baseline > 0 and ppl > 0 else 0
        flag = "WARN" if ratio > 3.0 else ""
        txt = s.text[:55].replace('\n',' ')
        log_lines.append(f"{s.index:>4} {ppl:>8.1f} {ratio:>7.2f}x {flag:>6} {txt}")

    with open(ERR_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))
    print("OK -> tests/_ppl_debug.txt")

except Exception:
    with open(ERR_FILE, "w", encoding="utf-8") as f:
        f.write(traceback.format_exc())
    print("FAIL -> tests/_ppl_debug.txt")
