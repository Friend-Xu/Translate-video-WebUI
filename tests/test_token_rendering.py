"""Verify ChatTTS renders [uv_break]/[lbreak]/[laugh] tokens in actual audio.

Synthesizes text with and without pause tokens, compares audio duration.
If tokens are rendered, [lbreak] should produce measurably longer audio.
"""
import os, sys, time

PROJ_ROOT = r"D:\Workspace\Translate_video"
sys.path.insert(0, PROJ_ROOT)

OUT_DIR = os.path.join(PROJ_ROOT, r"tests\pause_verify_output")
os.makedirs(OUT_DIR, exist_ok=True)

from pipeline.tts_chattts import ChatTTSEngine


def test(label: str, text: str, engine) -> float:
    out_path = os.path.join(OUT_DIR, f"{label}.wav")
    if os.path.exists(out_path):
        os.remove(out_path)
    t0 = time.time()
    dur = engine.synthesize(text, out_path)
    elapsed = time.time() - t0
    print(f"  [{label}] dur={dur:.2f}s, wall={elapsed:.1f}s, text={repr(text[:40])}")
    return dur


def main():
    print("ChatTTS Token Rendering Verification")
    print("=" * 50)

    engine = ChatTTSEngine(
        speaker_seed=2,
        model_source="local",
    )
    print("Warming up...")
    engine.warmup()

    baseline_text = "今天天气真好，我们出去散步吧"
    print(f"\nBaseline: {repr(baseline_text)}")
    dur_baseline = test("baseline", baseline_text, engine)

    uv_text = "今天天气真好[uv_break]我们出去散步吧"
    dur_uv = test("uv_break", uv_text, engine)

    lb_text = "今天天气真好[lbreak]我们出去散步吧"
    dur_lb = test("lbreak", lb_text, engine)

    laugh_text = "今天天气真好[laugh]我们出去散步吧"
    dur_laugh = test("laugh", laugh_text, engine)

    print(f"\n--- Results ---")
    print(f"  baseline:       {dur_baseline:.2f}s")
    print(f"  with [uv_break]: {dur_uv:.2f}s (delta={dur_uv-dur_baseline:+.2f}s)")
    print(f"  with [lbreak]:  {dur_lb:.2f}s (delta={dur_lb-dur_baseline:+.2f}s)")
    print(f"  with [laugh]:   {dur_laugh:.2f}s (delta={dur_laugh-dur_baseline:+.2f}s)")

    if dur_lb > dur_baseline + 0.3:
        print("\nVERDICT: [lbreak] RENDERED — duration increased significantly")
    elif dur_uv > dur_baseline + 0.1:
        print("\nVERDICT: [uv_break] RENDERED — slight duration increase detected")
    elif abs(dur_uv - dur_baseline) < 0.1:
        print("\nVERDICT: TOKENS LIKELY STRIPPED — no significant duration change")
    else:
        print(f"\nVERDICT: UNCLEAR — need manual listening ({OUT_DIR})")

    engine.cleanup()
    print(f"\nAudio files: {OUT_DIR}")


if __name__ == "__main__":
    main()
