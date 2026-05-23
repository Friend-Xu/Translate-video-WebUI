"""
Test CosyVoice2 paralinguistic inline tokens.

Directly uses the project's CosyVoiceTTSEngine class (subprocess isolation).
Tests whether [laughter] [breath] [cough] [sigh] tokens produce audible effects.

Independent — no pipeline modifications.

Usage:
    tests\_run_cosyvoice_para.bat
"""

import os
import sys
import time

PROJ_ROOT = r"D:\Workspace\Translate_video"
sys.path.insert(0, PROJ_ROOT)

OUTPUT_DIR = os.path.join(PROJ_ROOT, r"tests\cosyvoice_para_output")
LOG_PATH = os.path.join(PROJ_ROOT, r"tests\_cosyvoice_para.log")
PROMPT_AUDIO = os.path.join(PROJ_ROOT, r"models\CosyVoice\asset\zero_shot_prompt.wav")
PROMPT_TEXT = "希望你以后能够做得比我还好哟"

os.makedirs(OUTPUT_DIR, exist_ok=True)

_LOG_FH = open(LOG_PATH, "w", encoding="utf-8", buffering=1)


def _log(*args):
    msg = " ".join(str(a) for a in args)
    _LOG_FH.write(msg + "\n")
    _LOG_FH.flush()
    print(msg, flush=True)


def test_basic_tts(engine, text: str, label: str) -> str:
    """Synthesize and return output path."""
    out_path = os.path.join(OUTPUT_DIR, f"{label}.wav")
    if os.path.exists(out_path):
        os.remove(out_path)
    t0 = time.time()
    duration = engine.synthesize(text, out_path)
    elapsed = time.time() - t0
    size_kb = os.path.getsize(out_path) / 1024 if os.path.exists(out_path) else 0
    _log(f"  [{label}] {elapsed:.1f}s, dur={duration:.1f}s, size={size_kb:.0f}KB -> {out_path}")
    return out_path


def main():
    _log("CosyVoice2 Paralinguistic Token Test")
    _log(f"Prompt audio: {PROMPT_AUDIO}")
    _log(f"Output dir: {OUTPUT_DIR}")
    _log("")

    from pipeline.tts_cosyvoice import CosyVoiceTTSEngine

    # Warmup
    _log("Starting CosyVoice worker (v2, fp16=True)...")
    engine = CosyVoiceTTSEngine(
        model_version="v2",
        prompt_audio=PROMPT_AUDIO,
        prompt_text=PROMPT_TEXT,
        fp16=True,
        default_speed=1.0,
        tts_mode="cross_lingual",
        lang="zh",
    )

    t0 = time.time()
    engine.warmup()
    _log(f"Warmup done in {time.time() - t0:.1f}s")

    # Test cases
    test_cases = [
        ("baseline", "今天天气真好，我们出去散步吧"),
        ("laughter", "我喜欢这个[laughter]真的很有趣"),
        ("breath", "让我深吸一口气[breath]然后开始"),
        ("cough", "今天嗓子有点不舒服[cough]不过没关系"),
        ("sigh", "唉[sigh]今天真是累坏了"),
    ]

    _log("\nSynthesizing test cases...")
    for label, text in test_cases:
        test_basic_tts(engine, text, label)

    # Cleanup
    _log("\nShutting down worker...")
    engine.cleanup()
    _log(f"\nDone. Output files in: {OUTPUT_DIR}")
    _log("Listen and compare each .wav with baseline.wav")


if __name__ == "__main__":
    main()
