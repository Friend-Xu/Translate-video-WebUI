"""
Quick E2E test: translate first 20 source SRT entries.
Errors written to tests/_e2e_errors.log
"""
import os, sys, time, traceback

PROJECT_ROOT = r"D:\Workspace\Translate_video"
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "SRT"))

OUTPUT_DIR = os.path.join(PROJECT_ROOT, "tests", "e2e_naturalness_20")
ERR_LOG = os.path.join(PROJECT_ROOT, "tests", "_e2e_errors.log")

def log(msg):
    print(msg)
    try:
        with open(os.path.join(OUTPUT_DIR, "run.log"), "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass

try:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    log("=== START ===")

    import pysrt
    log("[OK] pysrt imported")

    SOURCE_SRT = os.path.join(
        PROJECT_ROOT, "source_file", "新建文件夹",
        "This Minecraft Dragon Mod Just Got BETTER_project",
        "01_extract", "source.srt",
    )
    log(f"[INFO] source_srt: {SOURCE_SRT}")
    log(f"[INFO] source exists: {os.path.exists(SOURCE_SRT)}")

    # Create 20-entry subset
    subs = pysrt.open(SOURCE_SRT, encoding="utf-8")
    test_srt = os.path.join(OUTPUT_DIR, "source_20.srt")
    subs[:20].save(test_srt, encoding="utf-8")
    log(f"[OK] Created {test_srt} ({len(subs[:20])} entries)")

    # Import translator (heavy imports happen here)
    from SRT.SRT_Translator import SRTTranslator
    log("[OK] SRTTranslator imported")

    # Translate
    config_path = os.path.join(PROJECT_ROOT, "config", "translate.yaml")
    log(f"[INFO] config: {config_path}, exists: {os.path.exists(config_path)}")
    translator = SRTTranslator(config_path)
    log(f"[INFO] Translator created, naturalness_check={translator.naturalness_check}")
    log("[RUN] Starting translate()...")

    t0 = time.time()
    translator.translate(test_srt)
    elapsed = time.time() - t0

    log(f"[DONE] Translation completed in {elapsed:.1f}s")
    for f in sorted(os.listdir(OUTPUT_DIR)):
        log(f"  {f}")

except Exception:
    with open(ERR_LOG, "w", encoding="utf-8") as f:
        f.write(traceback.format_exc())
    print("ERROR - see tests/_e2e_errors.log")
