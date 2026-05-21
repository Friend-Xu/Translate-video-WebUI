"""Debug: test _get_ppl_evaluator() directly from SRT_Translator context."""
import os, sys, time, traceback
PROJECT_ROOT = r"D:\Workspace\Translate_video"
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "SRT"))

OUT = os.path.join(PROJECT_ROOT, "tests", "_ppl_diag2.txt")
lines = []

try:
    from SRT.SRT_Translator import SRTTranslator
    config_path = os.path.join(PROJECT_ROOT, "config", "translate.yaml")
    translator = SRTTranslator(config_path)
    lines.append(f"translator created, naturalness_check={translator.naturalness_check}")

    t0 = time.time()
    ppl_eval = translator._get_ppl_evaluator()
    elapsed = time.time() - t0
    lines.append(f"_get_ppl_evaluator() -> {type(ppl_eval).__name__} in {elapsed:.1f}s")

    if ppl_eval:
        lines.append(f"  device_str: {ppl_eval._device_str}")
        t0 = time.time()
        ppl = ppl_eval.perplexity("测试一下自然度。")
        lines.append(f"  perplexity -> {ppl:.1f} in {time.time()-t0:.1f}s")
    else:
        lines.append(f"  FAILED: _ppl_evaluator attr = {translator._ppl_evaluator}")

except Exception:
    lines.append(traceback.format_exc())

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("Done -> tests/_ppl_diag2.txt")
