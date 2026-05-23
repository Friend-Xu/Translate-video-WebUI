"""
E2E test: Emotion extraction → ChatTTS dynamic prompt synthesis.

Full pipeline proof-of-concept:
  1. Parse SRT → segment time ranges + text
  2. emotion2vec → per-segment emotion labels + 1024-dim embeddings
  3. Emotion → ChatTTS prompt mapping (weighted blending)
  4. ChatTTS worker warmup
  5. Synthesize 3 segments — each with BOTH fixed and dynamic prompts
  6. Compare audio durations

ZERO modifications to pipeline code. Uses only public APIs:
  - pipeline.tts_chattts.ChatTTSEngine
  - funasr.AutoModel (emotion2vec)
  - pipeline.tts_config.parse_srt

Usage:
    tests\_run_e2e_emotion.bat
"""

import json
import os
import subprocess
import sys
import time
import numpy as np

PROJ_ROOT = r"D:\Workspace\Translate_video"
sys.path.insert(0, PROJ_ROOT)

AUDIO_PATH = os.path.join(PROJ_ROOT, r"source_file\test_project\01_extract\vocals.wav")
SRT_PATH = os.path.join(PROJ_ROOT, r"source_file\test_project\02_translate\machine.srt")
OUT_DIR = os.path.join(PROJ_ROOT, r"tests\e2e_emotion_output")
LOG_PATH = os.path.join(PROJ_ROOT, r"tests\_e2e_emotion.log")

os.makedirs(OUT_DIR, exist_ok=True)

_LOG_FH = open(LOG_PATH, "w", encoding="utf-8", buffering=1)


def _log(*args):
    msg = " ".join(str(a) for a in args)
    _LOG_FH.write(msg + "\n")
    _LOG_FH.flush()
    print(msg, flush=True)


# ── Emotion → ChatTTS prompt mapping (from Phase 2 research) ──

EMOTION_PROMPT_MAP = {
    "生气/angry":     (3, 0, 2),
    "厌恶/disgusted":  (1, 0, 4),
    "恐惧/fearful":   (2, 0, 4),
    "开心/happy":     (6, 1, 4),
    "中立/neutral":   (2, 0, 5),
    "其他/other":     (2, 0, 5),
    "难过/sad":       (1, 0, 6),
    "吃惊/surprised": (4, 0, 3),
    "<unk>":          (2, 0, 5),
}

LABEL_ORDER = [
    "生气/angry", "厌恶/disgusted", "恐惧/fearful", "开心/happy",
    "中立/neutral", "其他/other", "难过/sad", "吃惊/surprised", "<unk>",
]

FIXED_PROMPT = "[oral_0][break_5]"  # current default


def scores_to_prompt(scores: list) -> str:
    """Weighted-blend emotion scores into ChatTTS prompt."""
    oral = sum(
        EMOTION_PROMPT_MAP[label][0] * score
        for label, score in zip(LABEL_ORDER, scores)
        if label in EMOTION_PROMPT_MAP
    )
    laugh = sum(
        EMOTION_PROMPT_MAP[label][1] * score
        for label, score in zip(LABEL_ORDER, scores)
        if label in EMOTION_PROMPT_MAP
    )
    break_ = sum(
        EMOTION_PROMPT_MAP[label][2] * score
        for label, score in zip(LABEL_ORDER, scores)
        if label in EMOTION_PROMPT_MAP
    )
    return f"[oral_{max(0, min(9, int(round(oral))))}][laugh_{max(0, min(2, int(round(laugh))))}][break_{max(0, min(7, int(round(break_))))}]"


# ── Main ──────────────────────────────────────────────────────

def main():
    _log("=" * 60)
    _log("E2E: Emotion Extraction -> ChatTTS Dynamic Prompt Synthesis")
    _log("=" * 60)
    _log(f"Audio: {AUDIO_PATH}")
    _log(f"SRT:   {SRT_PATH}")
    _log(f"Output: {OUT_DIR}")

    # Step 1: Parse SRT
    _log("\n[Step 1] Parsing SRT...")
    from pipeline.tts_config import parse_srt
    segments = parse_srt(SRT_PATH)
    _log(f"  Parsed {len(segments)} segments")
    for i, (start, end, text) in enumerate(segments[:3]):
        _log(f"  [{i}] {start/1000:.1f}s-{end/1000:.1f}s: {text[:50]}...")

    # Step 2: emotion2vec per segment
    _log("\n[Step 2] Loading emotion2vec + extracting per segment...")
    from funasr import AutoModel
    model = AutoModel(model="iic/emotion2vec_plus_large", hub="ms", disable_update=True)

    seg_emotions = []
    for idx, (start_ms, end_ms, text) in enumerate(segments):
        if idx >= 5:
            break
        start_s = start_ms / 1000.0
        end_s = end_ms / 1000.0
        dur = end_s - start_s
        if dur < 1.0:
            seg_emotions.append({"index": idx, "scores": None, "prompt": FIXED_PROMPT,
                                 "warning": f"too short ({dur:.1f}s)"})
            continue
        seg_wav = os.path.join(OUT_DIR, f"seg_{idx:02d}.wav")
        subprocess.run([
            "ffmpeg", "-y", "-v", "quiet", "-i", AUDIO_PATH,
            "-ss", str(start_s), "-t", str(dur + 0.1),
            "-ac", "1", "-ar", "16000", seg_wav
        ], check=True)
        result = model.generate(input=seg_wav, output_dir=None, granularity="utterance")
        if result and len(result) > 0:
            scores = result[0]["scores"]
            labels = result[0]["labels"]
            prompt = scores_to_prompt(scores)
            top = sorted(zip(labels, scores), key=lambda x: x[1], reverse=True)
            seg_emotions.append({
                "index": idx, "scores": scores,
                "top_emotion": top[0][0], "top_score": round(top[0][1], 3),
                "prompt": prompt, "text": text,
            })
            _log(f"  [{idx}] {top[0][0]} ({top[0][1]:.3f}) -> {prompt}")
        else:
            seg_emotions.append({"index": idx, "scores": None, "prompt": FIXED_PROMPT,
                                 "error": "emotion2vec failed"})

    # Step 3: Select diverse test segments
    _log("\n[Step 3] Selecting test segments (different emotions)...")
    neutral_seg = None
    happy_seg = None
    for se in seg_emotions:
        if se["scores"] is None:
            continue
        top, score = se["top_emotion"], se["top_score"]
        if "中立" in top and score > 0.8 and neutral_seg is None:
            neutral_seg = se
        if "开心" in top and score > 0.5 and happy_seg is None:
            happy_seg = se
        if neutral_seg and happy_seg:
            break
    # Fallback: add a third if available
    others = [s for s in seg_emotions if s["scores"] is not None
              and s is not neutral_seg and s is not happy_seg]
    extra_seg = others[0] if others else None
    test_segs = [s for s in [neutral_seg, happy_seg, extra_seg] if s is not None]
    _log(f"  Selected {len(test_segs)} segments:")
    for s in test_segs:
        _log(f"    [{s['index']}] {s.get('top_emotion','?')} -> {s['prompt']} | {s['text'][:40]}")

    # Step 4: ChatTTS warmup
    _log("\n[Step 4] Starting ChatTTS worker...")
    from pipeline.tts_chattts import ChatTTSEngine
    engine = ChatTTSEngine(speaker_seed=2, model_source="local")
    engine.warmup()

    # Step 5: Synthesize
    _log("\n[Step 5] Synthesizing (fixed vs dynamic prompt)...")
    results = []
    for seg in test_segs:
        text = seg["text"]
        dynamic_prompt = seg["prompt"]

        fixed_path = os.path.join(OUT_DIR, f"seg{seg['index']:02d}_fixed.wav")
        t0 = time.time()
        dur_fixed = engine.synthesize(text, fixed_path)
        t_fixed = time.time() - t0

        dyn_path = os.path.join(OUT_DIR, f"seg{seg['index']:02d}_dynamic.wav")
        t0 = time.time()
        dur_dynamic = engine.synthesize(text, dyn_path, emotion=dynamic_prompt)
        t_dynamic = time.time() - t0

        results.append({
            "index": seg["index"],
            "top_emotion": seg.get("top_emotion", "?"),
            "text": text[:40],
            "fixed_prompt": FIXED_PROMPT,
            "dynamic_prompt": dynamic_prompt,
            "fixed_dur": round(dur_fixed, 2),
            "dynamic_dur": round(dur_dynamic, 2),
        })
        _log(f"  [{seg['index']}] fixed={dur_fixed:.2f}s | dynamic={dur_dynamic:.2f}s"
             f" | prompt={dynamic_prompt}")

    # Step 6: Summary
    _log("\n[Step 6] Summary")
    _log("=" * 60)
    _log(f"{'Idx':>4s} {'Emotion':<14s} {'Fixed':>8s} {'Dynamic':>8s}  Prompt")
    _log("-" * 60)
    for r in results:
        _log(f"  {r['index']:2d}  {r['top_emotion']:<14s} {r['fixed_dur']:7.2f}s {r['dynamic_dur']:7.2f}s  {r['dynamic_prompt']}")

    with open(os.path.join(OUT_DIR, "e2e_results.json"), "w", encoding="utf-8") as f:
        json.dump({"segments": seg_emotions, "synthesis": results}, f, indent=2, ensure_ascii=False)

    _log(f"\nOutput: {OUT_DIR}")
    _log("NOTE: Fixed prompt = [oral_0][break_5], Dynamic = emotion2vec-generated.")
    _log("      Listen and compare: *_fixed.wav vs *_dynamic.wav")

    engine.cleanup()
    _log("Done.")


if __name__ == "__main__":
    main()
