"""
End-to-end test: translate 20 subtitles through SRT_Translator
and exercise PPL + naturalness re-translation flow.

Generates a 20-segment SRT from source.srt, runs the full translator,
then saves results alongside the test SRT for manual inspection.

Usage:
    .venv/Scripts/python tests/test_20_naturalness_e2e.py
"""

import os
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "SRT"))

from SRT.SRT_Translator import SRTTranslator

SOURCE_SRT = os.path.join(
    PROJECT_ROOT, "source_file", "新建文件夹",
    "This Minecraft Dragon Mod Just Got BETTER_project",
    "01_extract", "source.srt",
)
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "tests", "e2e_naturalness_20")
os.makedirs(OUTPUT_DIR, exist_ok=True)
TEST_SRT = os.path.join(OUTPUT_DIR, "source_20.srt")


def create_20_entry_srt():
    """Extract first 20 entries from source SRT."""
    import pysrt
    subs = pysrt.open(SOURCE_SRT, encoding="utf-8")
    subset = subs[:20]
    subset.save(TEST_SRT, encoding="utf-8")
    print(f"[setup] Created {TEST_SRT} ({len(subset)} entries)")
    return TEST_SRT


def main():
    import logging
    logging.basicConfig(level=logging.INFO)

    # Also tee main script output to a log file
    log_path = os.path.join(OUTPUT_DIR, "run.log")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    class TeeWriter:
        def __init__(self, *files):
            self.files = files
        def write(self, s):
            for f in self.files:
                f.write(s)
                f.flush()
        def flush(self):
            for f in self.files:
                f.flush()

    log_fh = open(log_path, "w", encoding="utf-8")
    sys.stdout = TeeWriter(sys.stdout, log_fh)

    t0 = time.time()
    print("=" * 72)
    print("E2E Test: 20-segment translation + naturalness check")
    print("=" * 72)

    # Step 1: Create test file
    srt_path = create_20_entry_srt()

    # Step 2: Translate
    print("\n[translate] Starting SRTTranslator...")
    config_path = os.path.join(PROJECT_ROOT, "config", "translate.yaml")

    translator = SRTTranslator(config_path)
    translator.translate(srt_path)

    # Step 3: Report
    elapsed = time.time() - t0
    print(f"\n[done] Translation completed in {elapsed:.1f}s")
    print(f"[output] Check {OUTPUT_DIR}/ for results:")
    for f in sorted(os.listdir(OUTPUT_DIR)):
        print(f"  {f}")


if __name__ == "__main__":
    main()
