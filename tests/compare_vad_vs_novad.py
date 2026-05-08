"""
Compare whisper word timestamps with vs without external VAD segmentation.

Purpose: determine if Silero VAD's aggressive merging (min_silence_gap=3.0s)
is causing whisper to produce compressed word timestamps for segment 7
("Make sure you guys watch all the way through").

Usage:
    python tests/compare_vad_vs_novad.py
"""

from __future__ import annotations

import os
import sys
import time
import numpy as np
import soundfile as sf

AUDIO_PATH = "source_file/test_out/test.wav"
MODEL_NAME = "turbo"
DEVICE = "cuda"
COMPUTE_TYPE = "float16"
MODEL_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "models", "whisper",
)
TARGET_TEXT = "Make sure you guys watch all the way through"
TARGET_WORDS = TARGET_TEXT.lower().split()


def load_model():
    from faster_whisper import WhisperModel
    local_path = os.path.join(MODEL_ROOT, MODEL_NAME)
    if os.path.isdir(local_path) and os.path.isfile(
        os.path.join(local_path, "model.bin")
    ):
        path = local_path
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
    else:
        path = MODEL_NAME
    print(f"Loading model: {path}")
    return WhisperModel(
        path, device=DEVICE, compute_type=COMPUTE_TYPE,
        cpu_threads=0, num_workers=1,
    )


def find_target(words: list[dict]) -> list[dict] | None:
    for i in range(len(words) - len(TARGET_WORDS) + 1):
        window = words[i:i + len(TARGET_WORDS)]
        if all(
            w["word"].strip().lower() == t
            for w, t in zip(window, TARGET_WORDS)
        ):
            return window
    return None


def print_words(label: str, words: list[dict] | None):
    print(f"\n  {label}:")
    if not words:
        print("    (not found)")
        return
    first_start = words[0]["start"]
    last_end = words[-1]["end"]
    duration = last_end - first_start
    print(f"    [{first_start:.3f}s - {last_end:.3f}s] = {duration:.3f}s")
    for w in words:
        s = w.get("start", "?")
        e = w.get("end", "?")
        print(f"      {w['word']:<15} [{s}, {e}]")


def main():
    print("=" * 70)
    print("  Whisper: VAD vs No-VAD comparison")
    print(f'  Target: "{TARGET_TEXT}"')
    print("=" * 70)

    print("\nLoading audio...")
    audio, sr = sf.read(AUDIO_PATH)
    audio = audio.astype(np.float32)
    duration = len(audio) / sr
    print(f"  {duration:.3f}s, {sr}Hz")

    print("\nLoading model...")
    t0 = time.time()
    model = load_model()
    print(f"  loaded in {time.time() - t0:.1f}s")

    # ═══════════════════════════════════════════════════════════════
    # A: No external VAD — whisper uses built-in Silero VAD
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "-" * 70)
    print("  A: No external VAD (vad_filter=True)")
    print("-" * 70)

    t0 = time.time()
    segs_a, info_a = model.transcribe(
        audio, language="en", word_timestamps=True,
        beam_size=2, vad_filter=True,
        vad_parameters=dict(
            threshold=0.5, min_speech_duration_ms=250,
            min_silence_duration_ms=2000,
        ),
    )
    all_a = []
    n_seg_a = 0
    for seg in segs_a:
        n_seg_a += 1
        if seg.words:
            for w in seg.words:
                all_a.append({
                    "word": w.word.strip(),
                    "start": round(w.start, 3),
                    "end": round(w.end, 3),
                })
    print(f"  Whisper segments: {n_seg_a}, words: {len(all_a)}, time: {time.time()-t0:.1f}s")
    target_a = find_target(all_a)
    print_words("Target", target_a)

    # ═══════════════════════════════════════════════════════════════
    # B: External VAD single segment — current pipeline (vad_filter=False)
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "-" * 70)
    print("  B: External VAD single segment (vad_filter=False, current pipeline)")
    print("-" * 70)

    seg_start, seg_end = 0.0, duration
    t0 = time.time()
    segs_b, info_b = model.transcribe(
        audio, language="en", word_timestamps=True,
        beam_size=2, vad_filter=False,
    )
    all_b = []
    n_seg_b = 0
    for seg in segs_b:
        n_seg_b += 1
        if seg.words:
            for w in seg.words:
                all_b.append({
                    "word": w.word.strip(),
                    "start": round(w.start + seg_start, 3),
                    "end": round(w.end + seg_start, 3),
                })
    print(f"  Whisper segments: {n_seg_b}, words: {len(all_b)}, time: {time.time()-t0:.1f}s")
    target_b = find_target(all_b)
    print_words("Target", target_b)

    # ═══════════════════════════════════════════════════════════════
    # Comparison
    # ═══════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("  Comparison")
    print("=" * 70)

    if not target_a or not target_b:
        print("  [ERROR] Target sentence not found!")
        return

    dur_a = target_a[-1]["end"] - target_a[0]["start"]
    dur_b = target_b[-1]["end"] - target_b[0]["start"]
    diff_pct = (dur_b - dur_a) / dur_a * 100 if dur_a > 0 else 0

    print(f"\n  Duration:")
    print(f"    A (no VAD):  {dur_a:.3f}s [{target_a[0]['start']:.3f} - {target_a[-1]['end']:.3f}]")
    print(f"    B (VAD):     {dur_b:.3f}s [{target_b[0]['start']:.3f} - {target_b[-1]['end']:.3f}]")
    print(f"    Difference:  {diff_pct:+.1f}%")

    print(f"\n  Word-by-word:")
    print(f"    {'Word':<15} {'A start':>8} {'A end':>8} {'B start':>8} {'B end':>8} {'dStart':>8} {'dEnd':>8}")
    print(f"    {'-'*70}")
    for wa, wb in zip(target_a, target_b):
        ds = wb["start"] - wa["start"]
        de = wb["end"] - wa["end"]
        print(f"    {wa['word']:<15} {wa['start']:>8.3f} {wa['end']:>8.3f} "
              f"{wb['start']:>8.3f} {wb['end']:>8.3f} {ds:>+8.3f} {de:>+8.3f}")

    print(f"\n  Conclusion:")
    if abs(diff_pct) < 5:
        print(f"    Both methods agree (difference {diff_pct:.1f}%).")
        print(f"    VAD is NOT the cause — the issue is whisper/wav2vec2")
        print(f"    timestamp allocation for these specific words.")
    else:
        print(f"    Significant difference ({diff_pct:+.1f}%). VAD may contribute.")


if __name__ == "__main__":
    main()
